from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8080
DEFAULT_THREADS = 2
DEFAULT_MAX_TOKENS = 64
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9


def read_gradle_local_properties() -> dict[str, str]:
    properties_path = REPO_ROOT / "gradle-local.properties"
    if not properties_path.exists():
        return {}

    properties: dict[str, str] = {}
    for raw_line in properties_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def windows_to_wsl_path(path: str | Path) -> str:
    text = str(path)
    if text.startswith("/"):
        return text

    try:
        windows_path = PureWindowsPath(text)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported path: {text}") from exc

    drive = windows_path.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"Expected an absolute Windows path, got: {text}")

    tail = "/".join(part for part in windows_path.parts[1:] if part not in ("\\", "/"))
    return f"/mnt/{drive}/{tail}"


def default_model_path() -> Path | None:
    candidate = REPO_ROOT / "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    return candidate if candidate.exists() else None


def default_llama_cli_path() -> str | None:
    properties = read_gradle_local_properties()
    llama_cpp_dir = properties.get("llamaCppSourceDir")
    if not llama_cpp_dir:
        return None
    return f"{windows_to_wsl_path(llama_cpp_dir)}/build-wsl-cli/bin/llama-cli"


def default_ld_library_path(cli_path: str | None) -> str | None:
    if not cli_path:
        return None
    cli_dir = cli_path.rsplit("/", 1)[0]
    parts = [
        cli_dir,
        f"{cli_dir.rsplit('/', 1)[0]}/lib",
        "/tmp/cmake-root/usr/lib/x86_64-linux-gnu",
        "/tmp/cmake-root/lib/x86_64-linux-gnu",
    ]
    return ":".join(parts)


def build_prompt(system_prompt: str, user_prompt: str) -> str:
    system_prompt = system_prompt.strip()
    user_prompt = user_prompt.strip()
    if not user_prompt:
        raise ValueError("userPrompt must not be blank.")

    if not system_prompt:
        return user_prompt

    return (
        f"System: {system_prompt}\n"
        f"User: {user_prompt}\n"
        "Assistant:"
    )


def extract_response_text(stdout_text: str, user_prompt: str) -> str:
    text = stdout_text.replace("\r\n", "\n")

    marker = f"> {user_prompt.strip()}"
    if marker in text:
        text = text.split(marker, 1)[1]

    for tail_marker in ("\n[ Prompt:", "\nExiting...", "\nllama_"):
        if tail_marker in text:
            text = text.split(tail_marker, 1)[0]

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "Loading model...":
            continue
        if line.startswith("build      :"):
            continue
        if line.startswith("model      :"):
            continue
        if line.startswith("modalities :"):
            continue
        if line.startswith("using custom system prompt"):
            continue
        if line.startswith("available commands:"):
            continue
        if line.startswith("/"):
            continue
        if set(line) <= {"в", "–", "„", "€", "Ђ"}:
            continue
        lines.append(line)

    return "\n".join(lines).strip()


@dataclass
class ServiceConfig:
    host: str
    port: int
    model_path: Path
    llama_cli_wsl_path: str
    ld_library_path: str
    threads: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a minimal desktop llama.cpp HTTP inference endpoint via WSL llama-cli."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind.")
    parser.add_argument(
        "--model-path",
        type=Path,
        default=default_model_path(),
        help="Windows path to the GGUF model file.",
    )
    parser.add_argument(
        "--llama-cli-wsl-path",
        default=default_llama_cli_path(),
        help="WSL path to llama-cli.",
    )
    parser.add_argument(
        "--ld-library-path",
        default=None,
        help="Optional WSL LD_LIBRARY_PATH override for llama-cli.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help="Desktop llama-cli thread count.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate local configuration and exit without starting the server.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> ServiceConfig:
    if args.model_path is None:
        raise ValueError("A model path is required. Provide --model-path.")
    if not args.model_path.exists():
        raise ValueError(f"Model file not found: {args.model_path}")
    if not args.llama_cli_wsl_path:
        raise ValueError(
            "A llama-cli WSL path is required. Provide --llama-cli-wsl-path or set llamaCppSourceDir in gradle-local.properties."
        )

    ld_library_path = args.ld_library_path or default_ld_library_path(args.llama_cli_wsl_path)
    if not ld_library_path:
        raise ValueError("Could not determine LD_LIBRARY_PATH for llama-cli.")

    return ServiceConfig(
        host=args.host,
        port=args.port,
        model_path=args.model_path.resolve(),
        llama_cli_wsl_path=args.llama_cli_wsl_path,
        ld_library_path=ld_library_path,
        threads=max(1, int(args.threads)),
    )


def run_configuration_check(config: ServiceConfig) -> int:
    print(f"model_path={config.model_path}")
    print(f"llama_cli_wsl_path={config.llama_cli_wsl_path}")
    print(f"ld_library_path={config.ld_library_path}")
    print(f"threads={config.threads}")

    check_command = (
        "test -f {model} && test -x {cli} && echo OK || echo MISSING"
    ).format(
        model=shlex.quote(windows_to_wsl_path(config.model_path)),
        cli=shlex.quote(config.llama_cli_wsl_path),
    )

    result = subprocess.run(
        ["wsl.exe", "bash", "-lc", check_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.stdout.strip() != "OK":
        print(result.stdout.strip(), file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        return 1

    print("configuration_check=OK")
    return 0


def run_generation(config: ServiceConfig, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("requestId") or uuid.uuid4())
    system_prompt = str(payload.get("systemPrompt") or "")
    user_prompt = str(payload.get("userPrompt") or "")
    model = str(payload.get("model") or config.model_path.name)
    max_tokens = int(payload.get("maxTokens") or DEFAULT_MAX_TOKENS)
    temperature = float(payload.get("temperature") or DEFAULT_TEMPERATURE)
    top_p = float(payload.get("topP") or DEFAULT_TOP_P)

    model_path = config.model_path
    if model and Path(model).is_absolute():
        model_path = Path(model)

    model_wsl_path = windows_to_wsl_path(model_path)
    cli_command = [
        shlex.quote(config.llama_cli_wsl_path),
        "-m",
        shlex.quote(model_wsl_path),
        "-sys",
        shlex.quote(system_prompt),
        "-p",
        shlex.quote(user_prompt),
        "-n",
        str(max(1, max_tokens)),
        "--no-warmup",
        "--simple-io",
        "--no-display-prompt",
        "-st",
        "-t",
        str(config.threads),
        "--temp",
        str(temperature),
        "--top-p",
        str(top_p),
        "--log-disable",
        "--no-perf",
    ]
    bash_command = (
        f"export LD_LIBRARY_PATH={shlex.quote(config.ld_library_path)};"
        f" {' '.join(cli_command)}"
    )

    started = time.perf_counter()
    result = subprocess.run(
        ["wsl.exe", "bash", "-lc", bash_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    output_text = extract_response_text(result.stdout, user_prompt)
    stderr_text = result.stderr.strip()

    if result.returncode != 0:
        return {
            "requestId": request_id,
            "outputText": "",
            "finishReason": "error",
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "backendLabel": "desktop-llama.cpp-wsl-cli",
            "timings": {
                "generationMs": elapsed_ms,
            },
            "error": stderr_text or f"llama-cli failed with exit code {result.returncode}",
        }

    completion_tokens = len(output_text.split())
    prompt_tokens = len(user_prompt.split()) + len(system_prompt.split())
    return {
        "requestId": request_id,
        "outputText": output_text,
        "finishReason": "stop",
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": prompt_tokens + completion_tokens,
        "backendLabel": "desktop-llama.cpp-wsl-cli",
        "timings": {
            "generationMs": elapsed_ms,
        },
        "error": "",
        "debug": {
            "stderr": stderr_text,
            "model": model_path.name,
        },
    }


class InferenceRequestHandler(BaseHTTPRequestHandler):
    server: "InferenceServer"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
            return

        self._write_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "backendLabel": "desktop-llama.cpp-wsl-cli",
                "modelPath": str(self.server.config.model_path),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/generate":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))
            response = run_generation(self.server.config, payload)
            status = HTTPStatus.OK if not response["error"] else HTTPStatus.BAD_GATEWAY
            self._write_json(status, response)
        except ValueError as exc:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": str(exc),
                },
            )
        except json.JSONDecodeError as exc:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": f"Invalid JSON body: {exc.msg}",
                },
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": f"Unexpected server error: {exc}",
                },
            )

    def log_message(self, fmt: str, *args: object) -> None:
        message = fmt % args
        sys.stderr.write(f"[desktop-inference-service] {message}\n")

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class InferenceServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: ServiceConfig) -> None:
        super().__init__(server_address, InferenceRequestHandler)
        self.config = config


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = validate_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.check:
        return run_configuration_check(config)

    server = InferenceServer((config.host, config.port), config)
    print(
        f"desktop_inference_service listening on http://{config.host}:{config.port} "
        f"using model {config.model_path.name}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down desktop inference service...", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

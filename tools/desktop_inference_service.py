from __future__ import annotations

import argparse
import json
import shlex
import socket
import subprocess
import sys
import threading
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
PROTOCOL_VERSION = 1


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
    request_log_path: Path


@dataclass
class SpeculativeSession:
    session_id: str
    request_id: str
    protocol_version: int
    draft_model: str
    target_model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    top_p: float
    status: str
    draft_step: int
    accepted_token_ids: list[int]
    accepted_token_count: int
    mismatch_count: int
    correction_token_ids: list[int]
    target_token_ids: list[int]
    last_finish_reason: str
    created_at_ms: int
    updated_at_ms: int


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
    parser.add_argument(
        "--request-log-path",
        type=Path,
        default=REPO_ROOT / "logs" / "desktop-inference-service.log",
        help="Path to the local request log file.",
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
        request_log_path=args.request_log_path.resolve(),
    )


def detect_ipv4_addresses() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        host_entries = socket.gethostbyname_ex(socket.gethostname())[2]
        addresses.update(ip for ip in host_entries if "." in ip)
    except OSError:
        pass
    return sorted(addresses)


def append_request_log(config: ServiceConfig, event: dict[str, Any]) -> None:
    config.request_log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestampMs": int(time.time() * 1000),
        **event,
    }
    with config.request_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True))
        handle.write("\n")


def run_configuration_check(config: ServiceConfig) -> int:
    print(f"model_path={config.model_path}")
    print(f"llama_cli_wsl_path={config.llama_cli_wsl_path}")
    print(f"ld_library_path={config.ld_library_path}")
    print(f"threads={config.threads}")
    print(f"request_log_path={config.request_log_path}")

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


def parse_int_list(name: str, value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array of integers.")

    parsed: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{name} must contain only integers.")
        parsed.append(int(item))
    return parsed


def build_stub_target_token_ids(system_prompt: str, user_prompt: str) -> list[int]:
    source = user_prompt.strip() or build_prompt(system_prompt, user_prompt)
    token_ids = [ord(char) for char in source][:256]
    return token_ids or [0]


def token_ids_to_debug_text(token_ids: list[int]) -> str:
    chars: list[str] = []
    for token_id in token_ids:
        if 32 <= token_id <= 126:
            chars.append(chr(token_id))
        else:
            chars.append(f"<{token_id}>")
    return "".join(chars)


def build_speculative_session(payload: dict[str, Any], config: ServiceConfig) -> SpeculativeSession:
    session_id = str(payload.get("sessionId") or uuid.uuid4())
    request_id = str(payload.get("requestId") or uuid.uuid4())
    protocol_version = int(payload.get("protocolVersion") or PROTOCOL_VERSION)
    sampling = payload.get("sampling") if isinstance(payload.get("sampling"), dict) else {}
    temperature = float(sampling.get("temperature") or payload.get("temperature") or DEFAULT_TEMPERATURE)
    top_p = float(sampling.get("topP") or payload.get("topP") or DEFAULT_TOP_P)
    target_model = str(payload.get("targetModel") or config.model_path.name)
    draft_model = str(payload.get("draftModel") or "")
    system_prompt = str(payload.get("systemPrompt") or "")
    user_prompt = str(payload.get("userPrompt") or "")
    if not user_prompt.strip():
        raise ValueError("userPrompt must not be blank.")

    now_ms = int(time.time() * 1000)
    return SpeculativeSession(
        session_id=session_id,
        request_id=request_id,
        protocol_version=protocol_version,
        draft_model=draft_model,
        target_model=target_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        top_p=top_p,
        status="ready",
        draft_step=0,
        accepted_token_ids=[],
        accepted_token_count=0,
        mismatch_count=0,
        correction_token_ids=[],
        target_token_ids=build_stub_target_token_ids(system_prompt, user_prompt),
        last_finish_reason="",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )


def start_speculative_session(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session = build_speculative_session(payload, server.config)
    with server.sessions_lock:
        server.sessions[session.session_id] = session

    return {
        "protocolVersion": session.protocol_version,
        "type": "startSessionResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "status": session.status,
        "targetModel": session.target_model,
        "draftModel": session.draft_model,
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "fallbackAvailable": True,
        "error": "",
    }


def propose_speculative_tokens(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId is required.")

    with server.sessions_lock:
        session = server.sessions.get(session_id)
    if session is None:
        raise ValueError(f"Unknown speculative session: {session_id}")

    draft_step = int(payload.get("draftStep") or 0)
    proposed_token_ids = parse_int_list("proposedTokenIds", payload.get("proposedTokenIds"))
    max_correction_tokens = max(1, int(payload.get("maxCorrectionTokens") or 1))
    if not proposed_token_ids:
        raise ValueError("proposedTokenIds must not be empty.")

    target_index = session.accepted_token_count
    target_remaining = session.target_token_ids[target_index:]

    accepted_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    rejected_from_index = -1

    for index, proposed_token_id in enumerate(proposed_token_ids):
        current_target_index = target_index + index
        if current_target_index >= len(session.target_token_ids):
            rejected_from_index = index
            break

        expected_token_id = session.target_token_ids[current_target_index]
        if proposed_token_id == expected_token_id:
            accepted_token_ids.append(proposed_token_id)
            continue

        rejected_from_index = index
        correction_token_ids = session.target_token_ids[
            current_target_index:current_target_index + max_correction_tokens
        ]
        session.mismatch_count += 1
        break

    if rejected_from_index == -1 and len(accepted_token_ids) < len(proposed_token_ids):
        correction_token_ids = session.target_token_ids[
            target_index + len(accepted_token_ids):target_index + len(accepted_token_ids) + max_correction_tokens
        ]

    committed_token_ids = accepted_token_ids + correction_token_ids
    accepted_count = len(accepted_token_ids)
    finish_reason = ""
    if target_index + len(committed_token_ids) >= len(session.target_token_ids):
        finish_reason = "stub_target_complete"

    session.draft_step = draft_step
    session.accepted_token_ids.extend(committed_token_ids)
    session.accepted_token_count = len(session.accepted_token_ids)
    session.correction_token_ids = correction_token_ids[:max_correction_tokens]
    session.last_finish_reason = finish_reason
    session.status = "verifying"
    session.updated_at_ms = int(time.time() * 1000)

    status = (
        "accepted_by_prompt_stub"
        if not correction_token_ids and rejected_from_index == -1
        else "corrected_by_prompt_stub"
    )
    session.status = status

    return {
        "protocolVersion": session.protocol_version,
        "type": "verifyDraftResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "draftStep": draft_step,
        "acceptedCount": accepted_count,
        "acceptedTokenIds": accepted_token_ids,
        "rejectedFromIndex": rejected_from_index,
        "correctionTokenIds": correction_token_ids,
        "targetTextDelta": token_ids_to_debug_text(committed_token_ids),
        "finishReason": finish_reason,
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "status": status,
        "warning": (
            "Desktop speculative verification is currently a deterministic prompt-derived stub. "
            "It now computes accepted prefixes and correction tokens, but it still does not run target-model token verification yet."
        ),
        "error": "",
        "debug": {
            "targetIndexBeforeStep": target_index,
            "targetRemainingCount": len(target_remaining),
            "targetPreview": token_ids_to_debug_text(target_remaining[:16]),
        },
    }


def fallback_speculative_session(
    server: "InferenceServer",
    payload: dict[str, Any],
) -> tuple[HTTPStatus, dict[str, Any]]:
    session_id = str(payload.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId is required.")

    with server.sessions_lock:
        session = server.sessions.get(session_id)
    if session is None:
        raise ValueError(f"Unknown speculative session: {session_id}")

    reason = str(payload.get("reason") or "manual_fallback")
    remaining_max_tokens = int(payload.get("remainingMaxTokens") or DEFAULT_MAX_TOKENS)
    request_payload = {
        "requestId": str(payload.get("requestId") or session.request_id),
        "model": payload.get("targetModel") or session.target_model,
        "systemPrompt": payload.get("systemPrompt") or session.system_prompt,
        "userPrompt": payload.get("userPrompt") or session.user_prompt,
        "maxTokens": remaining_max_tokens,
        "temperature": payload.get("temperature") or session.temperature,
        "topP": payload.get("topP") or session.top_p,
    }
    response = run_generation(server.config, request_payload)
    session.status = "fallback_completed" if not response["error"] else "fallback_error"
    session.last_finish_reason = response.get("finishReason") or ""
    session.updated_at_ms = int(time.time() * 1000)

    wrapped = {
        "protocolVersion": session.protocol_version,
        "type": "fallbackGenerateResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "reason": reason,
        "fallbackMode": "ordinary_remote_resume",
        "status": session.status,
        "generation": response,
        "error": response.get("error", ""),
    }
    status = HTTPStatus.OK if not response["error"] else HTTPStatus.BAD_GATEWAY
    return status, wrapped


def close_speculative_session(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId is required.")

    reason = str(payload.get("reason") or "completed")
    with server.sessions_lock:
        session = server.sessions.pop(session_id, None)
    if session is None:
        raise ValueError(f"Unknown speculative session: {session_id}")

    return {
        "protocolVersion": session.protocol_version,
        "type": "closeSessionResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "status": "closed",
        "reason": reason,
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "lastFinishReason": session.last_finish_reason,
        "error": "",
    }


class InferenceRequestHandler(BaseHTTPRequestHandler):
    server: "InferenceServer"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = {
                "status": "ok",
                "backendLabel": "desktop-llama.cpp-wsl-cli",
                "modelPath": str(self.server.config.model_path),
                "requestLogPath": str(self.server.config.request_log_path),
                "ipv4Addresses": detect_ipv4_addresses(),
                "speculativeSessionCount": self.server.session_count(),
                "speculativeProtocolVersion": PROTOCOL_VERSION,
            }
            self._write_json(HTTPStatus.OK, payload)
            self._record_request(HTTPStatus.OK, payload)
            return

        if self.path == "/probe":
            payload = {
                "status": "reachable",
                "message": "desktop inference service probe reached successfully",
                "clientAddress": self.client_address[0],
                "serverHost": self.server.config.host,
                "serverPort": self.server.config.port,
                "requestLogPath": str(self.server.config.request_log_path),
                "ipv4Addresses": detect_ipv4_addresses(),
                "speculativeSessionCount": self.server.session_count(),
            }
            self._write_json(HTTPStatus.OK, payload)
            self._record_request(HTTPStatus.OK, payload)
            return

        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
            return

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {
            "/v1/generate",
            "/v1/speculative/start",
            "/v1/speculative/propose",
            "/v1/speculative/fallback",
            "/v1/speculative/close",
        }:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))
            if self.path == "/v1/generate":
                response = run_generation(self.server.config, payload)
                status = HTTPStatus.OK if not response["error"] else HTTPStatus.BAD_GATEWAY
            elif self.path == "/v1/speculative/start":
                response = start_speculative_session(self.server, payload)
                status = HTTPStatus.OK
            elif self.path == "/v1/speculative/propose":
                response = propose_speculative_tokens(self.server, payload)
                status = HTTPStatus.OK
            elif self.path == "/v1/speculative/fallback":
                status, response = fallback_speculative_session(self.server, payload)
            else:
                response = close_speculative_session(self.server, payload)
                status = HTTPStatus.OK
            self._write_json(status, response)
            self._record_request(status, response, payload)
        except ValueError as exc:
            payload = {
                "error": str(exc),
            }
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                payload,
            )
            self._record_request(HTTPStatus.BAD_REQUEST, payload)
        except json.JSONDecodeError as exc:
            payload = {
                "error": f"Invalid JSON body: {exc.msg}",
            }
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                payload,
            )
            self._record_request(HTTPStatus.BAD_REQUEST, payload)
        except Exception as exc:  # pragma: no cover - runtime safety
            payload = {
                "error": f"Unexpected server error: {exc}",
            }
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                payload,
            )
            self._record_request(HTTPStatus.INTERNAL_SERVER_ERROR, payload)

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

    def _record_request(
        self,
        status: HTTPStatus,
        response: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
    ) -> None:
        append_request_log(
            self.server.config,
            {
                "clientAddress": self.client_address[0],
                "method": self.command,
                "path": self.path,
                "status": int(status),
                "request": request_payload or {},
                "responsePreview": {
                    key: response.get(key)
                    for key in ("status", "message", "requestId", "finishReason", "error")
                },
            },
        )


class InferenceServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: ServiceConfig) -> None:
        super().__init__(server_address, InferenceRequestHandler)
        self.config = config
        self.sessions: dict[str, SpeculativeSession] = {}
        self.sessions_lock = threading.Lock()

    def session_count(self) -> int:
        with self.sessions_lock:
            return len(self.sessions)


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

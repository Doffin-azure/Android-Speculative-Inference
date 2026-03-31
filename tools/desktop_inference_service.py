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
import urllib.error
import urllib.parse
import urllib.request
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
DEFAULT_SPECULATIVE_VERIFIER_MODE = "prompt_stub"
DEFAULT_LLAMA_PREVIEW_MAX_TOKENS = 8
DEFAULT_LLAMA_REPLAY_MAX_TOKENS = 8
DEFAULT_TRUE_VERIFY_MAX_TOKENS = 8
DEFAULT_TRUE_TREE_BRANCH_FACTOR = 3


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


def default_llama_server_wsl_path() -> str | None:
    properties = read_gradle_local_properties()
    llama_cpp_dir = properties.get("llamaCppSourceDir")
    if not llama_cpp_dir:
        return None
    return f"{windows_to_wsl_path(llama_cpp_dir)}/build-wsl-server/bin/llama-server"


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
        if line.startswith("> User:"):
            continue
        if line == "Assistant:":
            continue
        if not any(ch.isalnum() for ch in line):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def build_replay_prompt(system_prompt: str, user_prompt: str, assistant_prefix: str) -> str:
    system_prompt = system_prompt.strip()
    user_prompt = user_prompt.strip()
    assistant_prefix = assistant_prefix or ""
    if not user_prompt:
        raise ValueError("userPrompt must not be blank.")

    lines: list[str] = []
    if system_prompt:
        lines.append(f"System: {system_prompt}")
    lines.append(f"User: {user_prompt}")
    lines.append(f"Assistant: {assistant_prefix}")
    return "\n".join(lines)


def extract_response_text_without_marker(stdout_text: str) -> str:
    text = stdout_text.replace("\r\n", "\n")

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
        if all((not ch.isalnum()) and (not ch.isspace()) and ord(ch) > 127 for ch in line):
            continue
        if line.startswith("> User:"):
            continue
        if line == "Assistant:":
            continue
        if not any(ch.isalnum() for ch in line):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


@dataclass
class ServiceConfig:
    host: str
    port: int
    model_path: Path
    llama_cli_wsl_path: str
    llama_server_base_url: str
    llama_server_wsl_path: str
    ld_library_path: str
    threads: int
    request_log_path: Path
    speculative_verifier_mode: str


@dataclass
class SpeculativeSession:
    session_id: str
    request_id: str
    protocol_version: int
    draft_model: str
    target_model: str
    system_prompt: str
    user_prompt: str
    verifier_mode: str
    temperature: float
    top_p: float
    status: str
    draft_step: int
    accepted_token_ids: list[int]
    accepted_token_count: int
    mismatch_count: int
    correction_token_ids: list[int]
    target_token_ids: list[int]
    target_preview_text: str
    accepted_text: str
    last_replay_prompt: str
    last_target_text_delta: str
    last_finish_reason: str
    target_session_id: str
    created_at_ms: int
    updated_at_ms: int


@dataclass
class TargetSessionState:
    target_session_id: str
    speculative_session_id: str
    request_id: str
    verifier_mode: str
    verifier_stage: str
    target_model: str
    system_prompt: str
    user_prompt: str
    accepted_text: str
    target_preview_text: str
    last_replay_prompt: str
    last_target_text_delta: str
    target_token_ids: list[int]
    accepted_token_count: int
    mismatch_count: int
    true_verifier_call_count: int
    last_true_expected_token_id: int
    last_true_expected_token_text: str
    true_prefix_cache: dict[str, str]
    true_runtime_backend: str
    llama_server_slot_id: int
    last_true_chunk_start: int
    last_true_chunk_consumed: int
    true_cache_hit_streak: int
    true_fetch_streak: int
    created_at_ms: int
    updated_at_ms: int


@dataclass
class VerifyComputation:
    accepted_token_ids: list[int]
    correction_token_ids: list[int]
    rejected_from_index: int
    target_text_delta: str
    finish_reason: str
    target_index_before_step: int
    target_remaining_count: int
    target_preview_debug: str
    tree_candidate_count: int = 0
    tree_best_path_token_ids: list[int] | None = None
    tree_branch_factor: int = 0
    tree_depth_evaluated: int = 0
    tree_debug_summary: str = ""


@dataclass
class TreeCandidateNode:
    token_id: int
    depth: int
    parent_index: int
    prefix_text: str
    score: float
    token_text: str
    draft_selected_prob: float | None = None


@dataclass
class TreeVerifyComputation:
    accepted_token_ids: list[int]
    correction_token_ids: list[int]
    rejected_from_index: int
    target_text_delta: str
    candidate_count: int
    best_path_token_ids: list[int]
    tree_debug_summary: str
    tree_branch_factor: int
    tree_depth_evaluated: int


def infer_verifier_stage(verifier_mode: str) -> str:
    if verifier_mode == "prompt_stub":
        return "prompt_stub"
    if verifier_mode in {"llama_true_step", "llama_true_tree"}:
        return "true_target"
    if verifier_mode in {"llama_preview", "llama_step_proxy", "llama_replay_proxy"}:
        return "proxy_target"
    return "unknown"


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
        "--llama-server-base-url",
        default="",
        help="Optional base URL for a running llama-server, for example http://127.0.0.1:8091.",
    )
    parser.add_argument(
        "--llama-server-wsl-path",
        default=default_llama_server_wsl_path(),
        help="Optional WSL path to llama-server for documentation and diagnostics.",
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
    parser.add_argument(
        "--speculative-verifier-mode",
        choices=("prompt_stub", "llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree"),
        default=DEFAULT_SPECULATIVE_VERIFIER_MODE,
        help="Verifier mode for speculative propose handling.",
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
        llama_server_base_url=str(args.llama_server_base_url or "").rstrip("/"),
        llama_server_wsl_path=str(args.llama_server_wsl_path or ""),
        ld_library_path=ld_library_path,
        threads=max(1, int(args.threads)),
        request_log_path=args.request_log_path.resolve(),
        speculative_verifier_mode=args.speculative_verifier_mode,
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
    print(f"llama_server_base_url={config.llama_server_base_url}")
    print(f"llama_server_wsl_path={config.llama_server_wsl_path}")
    print(f"ld_library_path={config.ld_library_path}")
    print(f"threads={config.threads}")
    print(f"request_log_path={config.request_log_path}")
    print(f"speculative_verifier_mode={config.speculative_verifier_mode}")

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

    if config.llama_server_base_url:
        try:
            server_health = request_json(
                "GET",
                f"{config.llama_server_base_url}/health",
                timeout_seconds=10.0,
            )
            print(f"llama_server_health={server_health.get('status', 'unknown')}")
        except RuntimeError as exc:
            print(f"llama_server_health_error={exc}", file=sys.stderr)
            return 1

    print("configuration_check=OK")
    return 0


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc

    if not raw.strip():
        return {}
    return json.loads(raw)


def choose_llama_server_slot(base_url: str) -> int:
    slots = request_json("GET", f"{base_url}/slots", timeout_seconds=10.0)
    if not isinstance(slots, list) or not slots:
        return 0

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if not bool(slot.get("is_processing")):
            return int(slot.get("id", 0))

    first_slot = slots[0]
    if isinstance(first_slot, dict):
        return int(first_slot.get("id", 0))
    return 0


def erase_llama_server_slot(base_url: str, slot_id: int) -> None:
    request_json(
        "POST",
        f"{base_url}/slots/{slot_id}?action=erase",
        {"id_slot": slot_id},
        timeout_seconds=10.0,
    )


def run_generation_from_server_completion(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    full_prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    slot_id: int,
    cache_prompt: bool,
    n_probs: int = 0,
    post_sampling_probs: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    request_payload = {
        "prompt": full_prompt,
        "n_predict": max(1, max_tokens),
        "temperature": temperature,
        "top_p": top_p,
        "cache_prompt": cache_prompt,
        "id_slot": slot_id,
        "return_tokens": True,
        "stream": False,
        "n_keep": -1,
    }
    if n_probs > 0:
        request_payload["n_probs"] = int(n_probs)
    if post_sampling_probs:
        request_payload["post_sampling_probs"] = True

    response = request_json(
        "POST",
        f"{config.llama_server_base_url}/completion",
        request_payload,
        timeout_seconds=120.0,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    output_text = str(response.get("content") or "")
    completion_tokens = len(response.get("tokens") or [])
    prompt_text = str(response.get("prompt") or full_prompt)
    prompt_tokens = len(prompt_text.split())

    return {
        "requestId": request_id,
        "outputText": output_text,
        "finishReason": "stop" if not bool(response.get("stop")) else "stop",
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": prompt_tokens + completion_tokens,
        "backendLabel": "desktop-llama.cpp-server",
        "timings": {
            "generationMs": elapsed_ms,
        },
        "error": "",
        "debug": {
            "model": model,
            "slotId": slot_id,
            "serverBaseUrl": config.llama_server_base_url,
            "stop": response.get("stop"),
            "tokensPredicted": completion_tokens,
            "completionProbabilities": response.get("completion_probabilities") or [],
        },
    }


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


def run_generation_from_full_prompt(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    full_prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
) -> dict[str, Any]:
    model_path = config.model_path
    if model and Path(model).is_absolute():
        model_path = Path(model)

    model_wsl_path = windows_to_wsl_path(model_path)
    cli_command = [
        shlex.quote(config.llama_cli_wsl_path),
        "-m",
        shlex.quote(model_wsl_path),
        "-p",
        shlex.quote(full_prompt),
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

    output_text = extract_response_text_without_marker(result.stdout)
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
    prompt_tokens = len(full_prompt.split())
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


def run_true_target_chunk_text(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    accepted_text: str,
    max_tokens: int,
    target_session: TargetSessionState | None = None,
) -> dict[str, Any]:
    replay_prompt = build_replay_prompt(system_prompt, user_prompt, accepted_text)
    if config.llama_server_base_url and target_session is not None and target_session.llama_server_slot_id >= 0:
        response = run_generation_from_server_completion(
            config,
            request_id=request_id,
            model=model,
            full_prompt=replay_prompt,
            max_tokens=max(1, max_tokens),
            temperature=0.0,
            top_p=1.0,
            slot_id=target_session.llama_server_slot_id,
            cache_prompt=True,
        )
        response.setdefault("debug", {})
        response["debug"]["replayPrompt"] = replay_prompt
        response["debug"]["runtimeBackend"] = "llama_server_slot"
        return response

    response = run_generation_from_full_prompt(
        config,
        request_id=request_id,
        model=model,
        full_prompt=replay_prompt,
        max_tokens=max(1, max_tokens),
        temperature=0.0,
        top_p=1.0,
    )
    response.setdefault("debug", {})
    response["debug"]["replayPrompt"] = replay_prompt
    response["debug"]["runtimeBackend"] = "llama_cli_replay"
    return response


def run_true_target_next_text(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    accepted_text: str,
) -> dict[str, Any]:
    return run_true_target_chunk_text(
        config,
        request_id=request_id,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        accepted_text=accepted_text,
        max_tokens=1,
        target_session=None,
    )


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


def token_ids_from_text(text: str) -> list[int]:
    token_ids = [ord(char) for char in text][:256]
    return token_ids or [0]


def first_wire_token_id_from_text(text: str) -> int:
    token_ids = token_ids_from_text(text)
    return token_ids[0] if token_ids else -1


def build_target_preview_text(
    config: ServiceConfig,
    *,
    verifier_mode: str,
    request_id: str,
    target_model: str,
    system_prompt: str,
    user_prompt: str,
    accepted_text: str,
    temperature: float,
    top_p: float,
) -> tuple[str, str]:
    if verifier_mode not in {"llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree"}:
        return "", ""

    if verifier_mode in {"llama_true_step", "llama_true_tree"}:
        response = run_true_target_chunk_text(
            config,
            request_id=f"{request_id}-true-preview",
            model=target_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            accepted_text=accepted_text,
            max_tokens=DEFAULT_TRUE_VERIFY_MAX_TOKENS,
            target_session=None,
        )
        return str(response.get("outputText") or "").strip(), str(
            response.get("debug", {}).get("replayPrompt") or ""
        )

    if verifier_mode == "llama_replay_proxy":
        replay_prompt = build_replay_prompt(system_prompt, user_prompt, accepted_text)
        preview_response = run_generation_from_full_prompt(
            config,
            request_id=f"{request_id}-replay-preview",
            model=target_model,
            full_prompt=replay_prompt,
            max_tokens=DEFAULT_LLAMA_REPLAY_MAX_TOKENS,
            temperature=temperature,
            top_p=top_p,
        )
        if preview_response.get("error"):
            return "", replay_prompt
        return str(preview_response.get("outputText") or "").strip(), replay_prompt

    preview_response = run_generation(
        config,
        {
            "requestId": f"{request_id}-preview",
            "model": target_model,
            "systemPrompt": system_prompt,
            "userPrompt": user_prompt,
            "maxTokens": DEFAULT_LLAMA_PREVIEW_MAX_TOKENS,
            "temperature": temperature,
            "topP": top_p,
        },
    )
    if preview_response.get("error"):
        return "", ""
    return str(preview_response.get("outputText") or "").strip(), ""


def resolve_target_token_ids(
    *,
    verifier_mode: str,
    system_prompt: str,
    user_prompt: str,
    accepted_token_ids: list[int],
    target_preview_text: str,
) -> list[int]:
    if verifier_mode == "llama_replay_proxy":
        prefix_token_ids = accepted_token_ids[:]
        if target_preview_text.strip():
            return prefix_token_ids + token_ids_from_text(target_preview_text)
        return prefix_token_ids or [0]
    if verifier_mode in {"llama_true_step", "llama_true_tree"}:
        return accepted_token_ids[:] if accepted_token_ids else [0]
    if verifier_mode in {"llama_preview", "llama_step_proxy"} and target_preview_text.strip():
        return token_ids_from_text(target_preview_text)
    return build_stub_target_token_ids(system_prompt, user_prompt)


def resolve_session_target_token_ids(session: SpeculativeSession) -> list[int]:
    return resolve_target_token_ids(
        verifier_mode=session.verifier_mode,
        system_prompt=session.system_prompt,
        user_prompt=session.user_prompt,
        accepted_token_ids=session.accepted_token_ids,
        target_preview_text=session.target_preview_text,
    )


def resolve_target_session_token_ids(
    target_session: TargetSessionState,
    accepted_token_ids: list[int],
) -> list[int]:
    return resolve_target_token_ids(
        verifier_mode=target_session.verifier_mode,
        system_prompt=target_session.system_prompt,
        user_prompt=target_session.user_prompt,
        accepted_token_ids=accepted_token_ids,
        target_preview_text=target_session.target_preview_text,
    )


def refresh_llama_proxy_preview_for_target_session(
    config: ServiceConfig,
    target_session: TargetSessionState,
    accepted_token_ids: list[int],
    min_target_chars: int,
) -> None:
    if target_session.verifier_mode not in {"llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree"}:
        return

    if target_session.verifier_mode in {"llama_true_step", "llama_true_tree"}:
        return

    current_chars = max(0, len(target_session.target_token_ids) - target_session.accepted_token_count)
    if current_chars >= min_target_chars:
        return

    if target_session.verifier_mode == "llama_replay_proxy":
        desired_tokens = max(DEFAULT_LLAMA_REPLAY_MAX_TOKENS, min_target_chars + 8, current_chars + 8)
        replay_prompt = build_replay_prompt(
            target_session.system_prompt,
            target_session.user_prompt,
            target_session.accepted_text,
        )
        target_session.last_replay_prompt = replay_prompt
        replay_response = run_generation_from_full_prompt(
            config,
            request_id=f"{target_session.request_id}-replay-refresh-{desired_tokens}",
            model=target_session.target_model,
            full_prompt=replay_prompt,
            max_tokens=desired_tokens,
            temperature=DEFAULT_TEMPERATURE,
            top_p=DEFAULT_TOP_P,
        )
        refreshed_text = str(replay_response.get("outputText") or "").strip()
        if refreshed_text:
            target_session.target_preview_text = refreshed_text
            target_session.target_token_ids = accepted_token_ids[:] + token_ids_from_text(refreshed_text)
        return

    desired_tokens = max(DEFAULT_LLAMA_PREVIEW_MAX_TOKENS, min_target_chars + 8, current_chars + 8)
    preview_response = run_generation(
        config,
        {
            "requestId": f"{target_session.request_id}-preview-refresh-{desired_tokens}",
            "model": target_session.target_model,
            "systemPrompt": target_session.system_prompt,
            "userPrompt": target_session.user_prompt,
            "maxTokens": desired_tokens,
            "temperature": DEFAULT_TEMPERATURE,
            "topP": DEFAULT_TOP_P,
        },
    )
    refreshed_text = str(preview_response.get("outputText") or "").strip()
    if refreshed_text:
        target_session.target_preview_text = refreshed_text
        target_session.target_token_ids = resolve_target_session_token_ids(target_session, accepted_token_ids)


def token_ids_to_debug_text(token_ids: list[int]) -> str:
    chars: list[str] = []
    for token_id in token_ids:
        if 32 <= token_id <= 126:
            chars.append(chr(token_id))
        else:
            chars.append(f"<{token_id}>")
    return "".join(chars)


def current_assistant_prefix_text(session: SpeculativeSession) -> str:
    if session.accepted_text:
        return session.accepted_text
    if session.accepted_token_ids:
        return token_ids_to_debug_text(session.accepted_token_ids)
    return ""


def build_target_session_state(session: SpeculativeSession) -> TargetSessionState:
    return TargetSessionState(
        target_session_id=str(uuid.uuid4()),
        speculative_session_id=session.session_id,
        request_id=session.request_id,
        verifier_mode=session.verifier_mode,
        verifier_stage=infer_verifier_stage(session.verifier_mode),
        target_model=session.target_model,
        system_prompt=session.system_prompt,
        user_prompt=session.user_prompt,
        accepted_text=session.accepted_text,
        target_preview_text=session.target_preview_text,
        last_replay_prompt=session.last_replay_prompt,
        last_target_text_delta=session.last_target_text_delta,
        target_token_ids=session.target_token_ids[:],
        accepted_token_count=session.accepted_token_count,
        mismatch_count=session.mismatch_count,
        true_verifier_call_count=0,
        last_true_expected_token_id=-1,
        last_true_expected_token_text="",
        true_prefix_cache={},
        true_runtime_backend="llama_server_slot" if session.verifier_mode in {"llama_true_step", "llama_true_tree"} else "proxy_target",
        llama_server_slot_id=-1,
        last_true_chunk_start=0,
        last_true_chunk_consumed=0,
        true_cache_hit_streak=0,
        true_fetch_streak=0,
        created_at_ms=session.created_at_ms,
        updated_at_ms=session.updated_at_ms,
    )


def sync_target_session_state(target_session: TargetSessionState, session: SpeculativeSession) -> None:
    target_session.verifier_mode = session.verifier_mode
    target_session.verifier_stage = infer_verifier_stage(session.verifier_mode)
    target_session.target_model = session.target_model
    target_session.system_prompt = session.system_prompt
    target_session.user_prompt = session.user_prompt
    target_session.accepted_text = session.accepted_text
    target_session.target_preview_text = session.target_preview_text
    target_session.last_replay_prompt = session.last_replay_prompt
    target_session.last_target_text_delta = session.last_target_text_delta
    target_session.target_token_ids = session.target_token_ids[:]
    target_session.accepted_token_count = session.accepted_token_count
    target_session.mismatch_count = session.mismatch_count
    target_session.updated_at_ms = session.updated_at_ms


def apply_target_session_state_to_session(
    session: SpeculativeSession,
    target_session: TargetSessionState,
) -> None:
    session.target_preview_text = target_session.target_preview_text
    session.last_replay_prompt = target_session.last_replay_prompt
    session.last_target_text_delta = target_session.last_target_text_delta
    session.target_token_ids = target_session.target_token_ids[:]
    session.accepted_text = target_session.accepted_text


def latest_true_cache_entry(target_session: TargetSessionState) -> tuple[str, str]:
    if not target_session.true_prefix_cache:
        return "", ""
    latest_prefix = next(reversed(target_session.true_prefix_cache))
    return latest_prefix, target_session.true_prefix_cache.get(latest_prefix, "")


def refresh_target_session_driver_state(
    config: ServiceConfig,
    target_session: TargetSessionState,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    requested_token_span: int,
) -> None:
    refresh_llama_proxy_preview_for_target_session(
        config,
        target_session,
        accepted_token_ids,
        accepted_token_count + requested_token_span,
    )


def compute_proxy_verifier_result(
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
) -> VerifyComputation:
    target_index = accepted_token_count
    target_token_ids = target_session.target_token_ids
    target_remaining = target_token_ids[target_index:]

    accepted_step_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    rejected_from_index = -1

    for index, proposed_token_id in enumerate(proposed_token_ids):
        current_target_index = target_index + index
        if current_target_index >= len(target_token_ids):
            rejected_from_index = index
            break

        expected_token_id = target_token_ids[current_target_index]
        if proposed_token_id == expected_token_id:
            accepted_step_token_ids.append(proposed_token_id)
            continue

        rejected_from_index = index
        correction_token_ids = target_token_ids[
            current_target_index:current_target_index + max_correction_tokens
        ]
        break

    if rejected_from_index == -1 and len(accepted_step_token_ids) < len(proposed_token_ids):
        correction_token_ids = target_token_ids[
            target_index + len(accepted_step_token_ids):target_index + len(accepted_step_token_ids) + max_correction_tokens
        ]

    committed_token_ids = accepted_step_token_ids + correction_token_ids
    target_text_delta = token_ids_to_debug_text(committed_token_ids)
    finish_reason = ""
    if target_index + len(committed_token_ids) >= len(target_token_ids):
        finish_reason = "stub_target_complete"

    return VerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids,
        rejected_from_index=rejected_from_index,
        target_text_delta=target_text_delta,
        finish_reason=finish_reason,
        target_index_before_step=target_index,
        target_remaining_count=len(target_remaining),
        target_preview_debug=token_ids_to_debug_text(target_remaining[:16]),
    )


def compute_true_verifier_result(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
) -> VerifyComputation:
    accepted_step_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    rejected_from_index = -1
    target_index = accepted_token_count
    working_prefix = target_session.accepted_text
    preview_debug_parts: list[str] = []
    desired_tokens = len(proposed_token_ids) + max_correction_tokens
    chunk_response = get_or_fetch_true_target_chunk_text(
        config,
        target_session,
        prefix_text=working_prefix,
        step_index=target_index,
        desired_tokens=desired_tokens,
    )
    if chunk_response.get("error"):
        return VerifyComputation(
            accepted_token_ids=[],
            correction_token_ids=[],
            rejected_from_index=0,
            target_text_delta="",
            finish_reason="",
            target_index_before_step=target_index,
            target_remaining_count=0,
            target_preview_debug="",
        )

    next_text = str(chunk_response.get("outputText") or "")
    target_session.true_runtime_backend = str(
        chunk_response.get("debug", {}).get("runtimeBackend") or target_session.true_runtime_backend
    )
    target_session.last_replay_prompt = str(chunk_response.get("debug", {}).get("replayPrompt") or "")
    target_session.target_preview_text = next_text
    target_session.last_true_chunk_start = target_index
    if not bool(chunk_response.get("debug", {}).get("cacheHit")):
        record_true_verifier_observation(target_session, prefix_text=working_prefix, next_text=next_text)

    expected_token_ids = token_ids_from_text(next_text) if next_text else []
    preview_debug_parts.extend(list(next_text[: min(len(next_text), 16)]))

    for index, proposed_token_id in enumerate(proposed_token_ids):
        if index >= len(expected_token_ids):
            rejected_from_index = index
            break

        expected_token_id = expected_token_ids[index]
        if proposed_token_id == expected_token_id:
            accepted_step_token_ids.append(proposed_token_id)
            continue

        rejected_from_index = index
        correction_token_ids = expected_token_ids[index:index + max_correction_tokens]
        break

    if rejected_from_index == -1 and len(accepted_step_token_ids) < len(proposed_token_ids):
        correction_token_ids = expected_token_ids[
            len(accepted_step_token_ids):len(accepted_step_token_ids) + max_correction_tokens
        ]

    committed_token_ids = accepted_step_token_ids + correction_token_ids
    target_session.last_true_chunk_consumed = len(committed_token_ids)
    target_text_delta = token_ids_to_debug_text(committed_token_ids)
    finish_reason = ""
    if correction_token_ids:
        finish_reason = ""

    return VerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids,
        rejected_from_index=rejected_from_index,
        target_text_delta=target_text_delta,
        finish_reason=finish_reason,
        target_index_before_step=target_index,
        target_remaining_count=len(preview_debug_parts),
        target_preview_debug="".join(preview_debug_parts) or target_session.target_preview_text[:16],
    )


def compute_true_tree_verifier_result(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
) -> VerifyComputation:
    target_index = accepted_token_count
    tree = build_true_tree_computation(
        config,
        target_session,
        target_index=target_index,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
    target_session.last_true_chunk_start = target_index
    target_session.last_true_chunk_consumed = len(tree.accepted_token_ids) + len(tree.correction_token_ids)
    if tree.best_path_token_ids:
        target_session.last_true_expected_token_id = tree.best_path_token_ids[0]
        target_session.last_true_expected_token_text = token_ids_to_debug_text([tree.best_path_token_ids[0]])
    target_session.true_verifier_call_count += 1
    return VerifyComputation(
        accepted_token_ids=tree.accepted_token_ids,
        correction_token_ids=tree.correction_token_ids,
        rejected_from_index=tree.rejected_from_index,
        target_text_delta=tree.target_text_delta,
        finish_reason="",
        target_index_before_step=target_index,
        target_remaining_count=tree.tree_depth_evaluated,
        target_preview_debug=token_ids_to_debug_text(tree.best_path_token_ids[:16]),
        tree_candidate_count=tree.candidate_count,
        tree_best_path_token_ids=tree.best_path_token_ids,
        tree_branch_factor=tree.tree_branch_factor,
        tree_depth_evaluated=tree.tree_depth_evaluated,
        tree_debug_summary=tree.tree_debug_summary,
    )


def apply_verify_computation_to_sessions(
    session: SpeculativeSession,
    target_session: TargetSessionState,
    *,
    draft_step: int,
    computation: VerifyComputation,
    max_correction_tokens: int,
) -> None:
    committed_token_ids = computation.accepted_token_ids + computation.correction_token_ids
    if computation.correction_token_ids:
        session.mismatch_count += 1

    session.draft_step = draft_step
    session.accepted_token_ids.extend(committed_token_ids)
    session.accepted_token_count = len(session.accepted_token_ids)
    session.correction_token_ids = computation.correction_token_ids[:max_correction_tokens]
    session.accepted_text = token_ids_to_debug_text(session.accepted_token_ids)
    session.last_target_text_delta = computation.target_text_delta
    session.last_finish_reason = computation.finish_reason
    session.status = "verifying"
    session.updated_at_ms = int(time.time() * 1000)

    target_session.accepted_text = session.accepted_text
    target_session.accepted_token_count = session.accepted_token_count
    target_session.mismatch_count = session.mismatch_count
    target_session.last_target_text_delta = computation.target_text_delta
    target_session.target_token_ids = session.accepted_token_ids[:]
    target_session.updated_at_ms = session.updated_at_ms
    sync_target_session_state(target_session, session)


def record_true_verifier_observation(
    target_session: TargetSessionState,
    *,
    prefix_text: str,
    next_text: str,
) -> None:
    target_session.true_verifier_call_count += 1
    target_session.last_true_expected_token_text = next_text[:1]
    target_session.last_true_expected_token_id = ord(next_text[0]) if next_text else -1
    target_session.true_prefix_cache[prefix_text] = next_text
    target_session.true_cache_hit_streak = 0
    target_session.true_fetch_streak += 1


def get_or_fetch_true_target_chunk_text(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    prefix_text: str,
    step_index: int,
    desired_tokens: int,
) -> dict[str, Any]:
    cached_next_text = target_session.true_prefix_cache.get(prefix_text, "")
    if len(cached_next_text) >= max(1, desired_tokens):
        target_session.true_cache_hit_streak += 1
        target_session.true_fetch_streak = 0
        return {
            "outputText": cached_next_text,
            "error": "",
            "debug": {
                "replayPrompt": target_session.last_replay_prompt,
                "cacheHit": True,
                "runtimeBackend": target_session.true_runtime_backend,
            },
        }

    response = run_true_target_chunk_text(
        config,
        request_id=f"{target_session.request_id}-true-step-{step_index}",
        model=target_session.target_model,
        system_prompt=target_session.system_prompt,
        user_prompt=target_session.user_prompt,
        accepted_text=prefix_text,
        max_tokens=max(DEFAULT_TRUE_VERIFY_MAX_TOKENS, desired_tokens),
        target_session=target_session,
    )
    response.setdefault("debug", {})
    response["debug"]["cacheHit"] = False
    return response


def fetch_target_top_candidates(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    prefix_text: str,
    step_index: int,
    branch_factor: int,
) -> dict[str, Any]:
    if config.llama_server_base_url and target_session.llama_server_slot_id >= 0:
        replay_prompt = build_replay_prompt(
            target_session.system_prompt,
            target_session.user_prompt,
            prefix_text,
        )
        response = run_generation_from_server_completion(
            config,
            request_id=f"{target_session.request_id}-true-tree-{step_index}",
            model=target_session.target_model,
            full_prompt=replay_prompt,
            max_tokens=1,
            temperature=0.0,
            top_p=1.0,
            slot_id=target_session.llama_server_slot_id,
            cache_prompt=True,
            n_probs=max(1, branch_factor),
            post_sampling_probs=True,
        )
        completion_probabilities = response.get("debug", {}).get("completionProbabilities") or []
        first_entry = completion_probabilities[0] if completion_probabilities else {}
        top_probs = []
        if isinstance(first_entry, dict):
            top_probs = first_entry.get("top_probs") or first_entry.get("top_logprobs") or []
        candidates: list[dict[str, Any]] = []
        for item in top_probs[: max(1, branch_factor)]:
            if not isinstance(item, dict):
                continue
            token_text = str(item.get("token") or "")
            token_id = first_wire_token_id_from_text(token_text) if token_text else -1
            prob = float(item.get("prob", 0.0) or 0.0)
            logprob = float(item.get("logprob", 0.0) or 0.0)
            score = prob if prob > 0.0 else logprob
            candidates.append(
                {
                    "tokenId": token_id,
                    "tokenText": token_text,
                    "score": score,
                    "prob": prob,
                    "logprob": logprob,
                }
            )
        if candidates:
            return {
                "selectedContent": str(first_entry.get("content") or response.get("outputText") or ""),
                "candidates": candidates,
                "runtimeBackend": "llama_server_slot",
                "replayPrompt": replay_prompt,
            }

    chunk_response = get_or_fetch_true_target_chunk_text(
        config,
        target_session,
        prefix_text=prefix_text,
        step_index=step_index,
        desired_tokens=1,
    )
    next_text = str(chunk_response.get("outputText") or "")
    next_token_ids = token_ids_from_text(next_text) if next_text else []
    selected_token_id = next_token_ids[0] if next_token_ids else -1
    return {
        "selectedContent": next_text[:1],
        "candidates": [
            {
                "tokenId": selected_token_id,
                "tokenText": next_text[:1],
                "score": 1.0 if selected_token_id >= 0 else 0.0,
                "prob": 1.0 if selected_token_id >= 0 else 0.0,
                "logprob": 0.0,
            }
        ] if selected_token_id >= 0 else [],
        "runtimeBackend": str(chunk_response.get("debug", {}).get("runtimeBackend") or target_session.true_runtime_backend),
        "replayPrompt": str(chunk_response.get("debug", {}).get("replayPrompt") or target_session.last_replay_prompt),
    }


def build_true_tree_computation(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    target_index: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
    branch_factor: int = DEFAULT_TRUE_TREE_BRANCH_FACTOR,
) -> TreeVerifyComputation:
    accepted_step_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    best_path_token_ids: list[int] = []
    tree_nodes: list[TreeCandidateNode] = []
    debug_lines: list[str] = []
    rejected_from_index = -1
    working_prefix = target_session.accepted_text
    parent_index = -1

    total_depth = len(proposed_token_ids) + max(0, max_correction_tokens)
    for depth in range(total_depth):
        top_result = fetch_target_top_candidates(
            config,
            target_session,
            prefix_text=working_prefix,
            step_index=target_index + depth,
            branch_factor=branch_factor,
        )
        target_session.true_runtime_backend = str(top_result.get("runtimeBackend") or target_session.true_runtime_backend)
        target_session.last_replay_prompt = str(top_result.get("replayPrompt") or target_session.last_replay_prompt)
        candidates = list(top_result.get("candidates") or [])
        if not candidates:
            if depth < len(proposed_token_ids):
                rejected_from_index = depth
            break

        current_parent_index = parent_index
        for candidate in candidates:
            tree_nodes.append(
                TreeCandidateNode(
                    token_id=int(candidate.get("tokenId", -1)),
                    depth=depth,
                    parent_index=current_parent_index,
                    prefix_text=working_prefix,
                    score=float(candidate.get("score", 0.0) or 0.0),
                    token_text=str(candidate.get("tokenText") or ""),
                )
            )

        best_candidate = candidates[0]
        best_token_id = int(best_candidate.get("tokenId", -1))
        best_path_token_ids.append(best_token_id)
        proposed_token_id = proposed_token_ids[depth] if depth < len(proposed_token_ids) else None
        proposal_in_topk = proposed_token_id in {int(item.get("tokenId", -1)) for item in candidates}
        debug_lines.append(
            f"d{depth}:best={best_token_id} proposal={proposed_token_id if proposed_token_id is not None else '-'} inTopK={proposal_in_topk}"
        )

        if depth < len(proposed_token_ids):
            if proposed_token_id == best_token_id:
                accepted_step_token_ids.append(best_token_id)
                working_prefix += chr(best_token_id) if best_token_id >= 0 else ""
                parent_index = len(tree_nodes) - len(candidates)
                continue

            rejected_from_index = depth
            correction_token_ids = [best_token_id] if best_token_id >= 0 else []
            working_prefix += chr(best_token_id) if best_token_id >= 0 else ""
            parent_index = len(tree_nodes) - len(candidates)
            continue

        if len(correction_token_ids) < max_correction_tokens and best_token_id >= 0:
            correction_token_ids.append(best_token_id)
            working_prefix += chr(best_token_id)
            parent_index = len(tree_nodes) - len(candidates)
            if len(correction_token_ids) >= max_correction_tokens:
                break

    target_text_delta = token_ids_to_debug_text(accepted_step_token_ids + correction_token_ids)
    return TreeVerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids[:max_correction_tokens],
        rejected_from_index=rejected_from_index,
        target_text_delta=target_text_delta,
        candidate_count=len(tree_nodes),
        best_path_token_ids=best_path_token_ids,
        tree_debug_summary="; ".join(debug_lines),
        tree_branch_factor=branch_factor,
        tree_depth_evaluated=len(best_path_token_ids),
    )


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
        verifier_mode=config.speculative_verifier_mode,
        temperature=temperature,
        top_p=top_p,
        status="ready",
        draft_step=0,
        accepted_token_ids=[],
        accepted_token_count=0,
        mismatch_count=0,
        correction_token_ids=[],
        target_token_ids=build_stub_target_token_ids(system_prompt, user_prompt),
        target_preview_text="",
        accepted_text="",
        last_replay_prompt="",
        last_target_text_delta="",
        last_finish_reason="",
        target_session_id="",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )


def start_speculative_session(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session = build_speculative_session(payload, server.config)
    target_session = build_target_session_state(session)
    if session.verifier_mode in {"llama_true_step", "llama_true_tree"} and server.config.llama_server_base_url:
        target_session.true_runtime_backend = "llama_server_slot"
        target_session.llama_server_slot_id = choose_llama_server_slot(server.config.llama_server_base_url)
        true_preview = get_or_fetch_true_target_chunk_text(
            server.config,
            target_session,
            prefix_text=target_session.accepted_text,
            step_index=0,
            desired_tokens=DEFAULT_TRUE_VERIFY_MAX_TOKENS,
        )
        target_session.target_preview_text = str(true_preview.get("outputText") or "").strip()
        target_session.last_replay_prompt = str(true_preview.get("debug", {}).get("replayPrompt") or "")
        if target_session.target_preview_text and not bool(true_preview.get("debug", {}).get("cacheHit")):
            record_true_verifier_observation(
                target_session,
                prefix_text=target_session.accepted_text,
                next_text=target_session.target_preview_text,
            )
        session.target_preview_text = target_session.target_preview_text
        session.last_replay_prompt = target_session.last_replay_prompt
        session.target_token_ids = resolve_target_session_token_ids(target_session, session.accepted_token_ids)
        sync_target_session_state(target_session, session)
    else:
        session.target_preview_text, session.last_replay_prompt = build_target_preview_text(
            server.config,
            verifier_mode=session.verifier_mode,
            request_id=session.request_id,
            target_model=session.target_model,
            system_prompt=session.system_prompt,
            user_prompt=session.user_prompt,
            accepted_text=current_assistant_prefix_text(session),
            temperature=session.temperature,
            top_p=session.top_p,
        )
        session.target_token_ids = resolve_session_target_token_ids(session)
        sync_target_session_state(target_session, session)
    session.target_session_id = target_session.target_session_id
    with server.sessions_lock:
        server.sessions[session.session_id] = session
        server.target_sessions[target_session.target_session_id] = target_session
    latest_cached_prefix, latest_cached_next = latest_true_cache_entry(target_session)

    return {
        "protocolVersion": session.protocol_version,
        "type": "startSessionResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "status": session.status,
        "targetSessionId": session.target_session_id,
        "targetModel": session.target_model,
        "draftModel": session.draft_model,
        "verifierMode": session.verifier_mode,
        "verifierStage": infer_verifier_stage(session.verifier_mode),
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "fallbackAvailable": True,
        "targetPreviewText": session.target_preview_text,
        "acceptedText": session.accepted_text,
        "debug": {
            "targetSessionId": session.target_session_id,
            "lastReplayPrompt": session.last_replay_prompt,
            "trueVerifierCallCount": target_session.true_verifier_call_count,
            "lastTrueExpectedTokenId": target_session.last_true_expected_token_id,
            "lastTrueExpectedTokenText": target_session.last_true_expected_token_text,
            "truePrefixCacheSize": len(target_session.true_prefix_cache),
            "cachedTruePrefixText": latest_cached_prefix,
            "cachedTrueNextText": latest_cached_next,
            "trueRuntimeBackend": target_session.true_runtime_backend,
            "llamaServerSlotId": target_session.llama_server_slot_id,
        },
        "error": "",
    }


def propose_speculative_tokens(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or "")
    if not session_id:
        raise ValueError("sessionId is required.")

    with server.sessions_lock:
        session = server.sessions.get(session_id)
        target_session = server.target_sessions.get(session.target_session_id) if session is not None else None
    if session is None:
        raise ValueError(f"Unknown speculative session: {session_id}")
    if target_session is None:
        raise ValueError(f"Unknown target session for speculative session: {session_id}")

    draft_step = int(payload.get("draftStep") or 0)
    proposed_token_ids = parse_int_list("proposedTokenIds", payload.get("proposedTokenIds"))
    max_correction_tokens = max(1, int(payload.get("maxCorrectionTokens") or 1))
    if not proposed_token_ids:
        raise ValueError("proposedTokenIds must not be empty.")

    refresh_target_session_driver_state(
        server.config,
        target_session,
        session.accepted_token_ids,
        session.accepted_token_count,
        len(proposed_token_ids) + max_correction_tokens,
    )
    apply_target_session_state_to_session(session, target_session)

    if session.verifier_mode == "llama_true_step":
        computation = compute_true_verifier_result(
            server.config,
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
        )
    elif session.verifier_mode == "llama_true_tree":
        computation = compute_true_tree_verifier_result(
            server.config,
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
        )
    else:
        computation = compute_proxy_verifier_result(
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
        )
    accepted_count = len(computation.accepted_token_ids)
    apply_verify_computation_to_sessions(
        session,
        target_session,
        draft_step=draft_step,
        computation=computation,
        max_correction_tokens=max_correction_tokens,
    )
    with server.sessions_lock:
        target_session = server.target_sessions.get(session.target_session_id)
        if target_session is not None:
            sync_target_session_state(target_session, session)
    latest_cached_prefix, latest_cached_next = latest_true_cache_entry(target_session) if target_session is not None else ("", "")

    base_status = "accepted" if not computation.correction_token_ids and computation.rejected_from_index == -1 else "corrected"
    if session.verifier_mode == "llama_replay_proxy":
        status = f"{base_status}_by_llama_replay"
    elif session.verifier_mode == "llama_true_step":
        status = f"{base_status}_by_llama_true_step"
    elif session.verifier_mode == "llama_true_tree":
        status = f"{base_status}_by_llama_true_tree"
    elif session.verifier_mode in {"llama_preview", "llama_step_proxy"}:
        status = f"{base_status}_by_llama_preview"
    else:
        status = f"{base_status}_by_prompt_stub"
    session.status = status

    warning = (
        "Desktop speculative verification is currently replaying the accepted assistant prefix into llama-cli and using the resulting continuation as a target proxy. "
        "This is closer to true target verification than fixed preview text, but it still does not verify target-model tokens directly inside a persistent model session yet."
        if session.verifier_mode == "llama_replay_proxy"
        else
        "Desktop speculative verification is now using the real target model for next-token checks through llama-cli on each speculative comparison step. "
        "This is the first true-target verifier stage. When llama-server is configured it now runs through a persistent server slot with prompt-cache reuse, "
        "but it still does not directly hold libllama state inside this Python process."
        if session.verifier_mode == "llama_true_step"
        else
        "Desktop speculative verification is now building a shallow target-side tree from llama-server top-k candidates. "
        "This first tree verifier node keeps the wire protocol unchanged and uses target-side top-k expansion to score a best path, "
        "but it is still not a full EAGLE-style posterior/KV-copy implementation."
        if session.verifier_mode == "llama_true_tree"
        else
        "Desktop speculative verification is currently using llama preview text as a target proxy. "
        "It now computes accepted prefixes and correction tokens from the preview text, but it still does not run true target-model token verification yet."
        if session.verifier_mode in {"llama_preview", "llama_step_proxy"}
        else
        "Desktop speculative verification is currently a deterministic prompt-derived stub. "
        "It now computes accepted prefixes and correction tokens, but it still does not run target-model token verification yet."
    )

    return {
        "protocolVersion": session.protocol_version,
        "type": "verifyDraftResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "targetSessionId": session.target_session_id,
        "draftStep": draft_step,
        "acceptedCount": accepted_count,
        "acceptedTokenIds": computation.accepted_token_ids,
        "rejectedFromIndex": computation.rejected_from_index,
        "correctionTokenIds": computation.correction_token_ids,
        "targetTextDelta": computation.target_text_delta,
        "finishReason": computation.finish_reason,
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "status": status,
        "verifierStage": infer_verifier_stage(session.verifier_mode),
        "warning": warning,
        "acceptedText": session.accepted_text,
        "error": "",
        "debug": {
            "targetSessionId": session.target_session_id,
            "verifierMode": session.verifier_mode,
            "targetIndexBeforeStep": computation.target_index_before_step,
            "targetRemainingCount": computation.target_remaining_count,
            "targetPreview": computation.target_preview_debug,
            "llamaPreviewText": session.target_preview_text,
            "acceptedText": session.accepted_text,
            "lastReplayPrompt": session.last_replay_prompt,
            "trueVerifierCallCount": target_session.true_verifier_call_count,
            "lastTrueExpectedTokenId": target_session.last_true_expected_token_id,
            "lastTrueExpectedTokenText": target_session.last_true_expected_token_text,
            "truePrefixCacheSize": len(target_session.true_prefix_cache),
            "cachedTruePrefixText": latest_cached_prefix,
            "cachedTrueNextText": latest_cached_next,
            "trueRuntimeBackend": target_session.true_runtime_backend,
            "llamaServerSlotId": target_session.llama_server_slot_id,
            "lastTrueChunkStart": target_session.last_true_chunk_start,
            "lastTrueChunkConsumed": target_session.last_true_chunk_consumed,
            "trueCacheHitStreak": target_session.true_cache_hit_streak,
            "trueFetchStreak": target_session.true_fetch_streak,
            "treeCandidateCount": computation.tree_candidate_count,
            "treeBestPathTokenIds": computation.tree_best_path_token_ids or [],
            "treeBranchFactor": computation.tree_branch_factor,
            "treeDepthEvaluated": computation.tree_depth_evaluated,
            "treeDebugSummary": computation.tree_debug_summary,
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
    with server.sessions_lock:
        target_session = server.target_sessions.pop(session.target_session_id, None)
    if (
        target_session is not None
        and target_session.verifier_mode in {"llama_true_step", "llama_true_tree"}
        and server.config.llama_server_base_url
        and target_session.llama_server_slot_id >= 0
    ):
        try:
            erase_llama_server_slot(server.config.llama_server_base_url, target_session.llama_server_slot_id)
        except RuntimeError:
            pass
    latest_cached_prefix, latest_cached_next = latest_true_cache_entry(target_session) if target_session is not None else ("", "")

    return {
        "protocolVersion": session.protocol_version,
        "type": "closeSessionResult",
        "sessionId": session.session_id,
        "requestId": session.request_id,
        "targetSessionId": session.target_session_id,
        "status": "closed",
        "reason": reason,
        "verifierMode": session.verifier_mode,
        "verifierStage": infer_verifier_stage(session.verifier_mode),
        "acceptedTokenCount": session.accepted_token_count,
        "mismatchCount": session.mismatch_count,
        "acceptedText": session.accepted_text,
        "lastTargetTextDelta": session.last_target_text_delta,
        "lastFinishReason": session.last_finish_reason,
        "trueVerifierCallCount": target_session.true_verifier_call_count if target_session is not None else 0,
        "lastTrueExpectedTokenId": target_session.last_true_expected_token_id if target_session is not None else -1,
        "lastTrueExpectedTokenText": target_session.last_true_expected_token_text if target_session is not None else "",
        "truePrefixCacheSize": len(target_session.true_prefix_cache) if target_session is not None else 0,
        "cachedTruePrefixText": latest_cached_prefix,
        "cachedTrueNextText": latest_cached_next,
        "trueRuntimeBackend": target_session.true_runtime_backend if target_session is not None else "",
        "llamaServerSlotId": target_session.llama_server_slot_id if target_session is not None else -1,
        "targetSessionClosed": target_session is not None,
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
                "llamaServerBaseUrl": self.server.config.llama_server_base_url,
                "ipv4Addresses": detect_ipv4_addresses(),
                "speculativeSessionCount": self.server.session_count(),
                "targetSessionCount": self.server.target_session_count(),
                "speculativeProtocolVersion": PROTOCOL_VERSION,
                "speculativeVerifierMode": self.server.config.speculative_verifier_mode,
                "speculativeVerifierStage": infer_verifier_stage(self.server.config.speculative_verifier_mode),
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
                "llamaServerBaseUrl": self.server.config.llama_server_base_url,
                "ipv4Addresses": detect_ipv4_addresses(),
                "speculativeSessionCount": self.server.session_count(),
                "targetSessionCount": self.server.target_session_count(),
                "speculativeVerifierMode": self.server.config.speculative_verifier_mode,
                "speculativeVerifierStage": infer_verifier_stage(self.server.config.speculative_verifier_mode),
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
        self.target_sessions: dict[str, TargetSessionState] = {}
        self.sessions_lock = threading.Lock()

    def session_count(self) -> int:
        with self.sessions_lock:
            return len(self.sessions)

    def target_session_count(self) -> int:
        with self.sessions_lock:
            return len(self.target_sessions)


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
        f"using model {config.model_path.name}"
        f"{' with llama-server ' + config.llama_server_base_url if config.llama_server_base_url else ''}",
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

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
DEFAULT_TOKEN_PQ_TARGET_TOPK = 8


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


def default_desktop_target_runtime_path() -> Path | None:
    cmd_candidate = REPO_ROOT / "tools" / "desktop_target_runtime.cmd"
    if cmd_candidate.exists():
        return cmd_candidate
    candidate = REPO_ROOT / "tools" / "desktop_target_runtime.exe"
    if candidate.exists():
        return candidate
    raw_candidate = REPO_ROOT / "tools" / "desktop_target_runtime"
    return raw_candidate if raw_candidate.exists() else None


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
    desktop_target_runtime_path: Path | None


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
    verifier_sampling_seed: int
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
    accepted_text_after_step: str = ""
    timing_prepare_ms: float = 0.0
    timing_decode_ms: float = 0.0
    timing_sample_ms: float = 0.0
    timing_rollback_ms: float = 0.0
    timing_helper_total_ms: float = 0.0
    timing_helper_round_trip_ms: float = 0.0
    timing_service_total_ms: float = 0.0


@dataclass
class TreeCandidateNode:
    token_id: int
    token_ids: list[int]
    depth: int
    parent_index: int
    prefix_text: str
    score: float
    token_text: str
    draft_selected_prob: float | None = None


@dataclass
class DraftTreePayloadNode:
    node_index: int
    token_id: int
    token_text: str
    depth: int
    parent_node_index: int
    probability: float
    log_probability: float
    cumulative_log_probability: float


@dataclass
class DraftPathStepCandidatePayload:
    node_index: int
    token_id: int
    token_text: str
    probability: float
    log_probability: float


@dataclass
class DraftPathStepPayload:
    depth: int
    parent_node_index: int
    accepted_prefix_token_ids: list[int]
    candidates: list[DraftPathStepCandidatePayload]
    best_token_id: int
    best_node_index: int


@dataclass
class DraftTreePayload:
    session_id: str
    token_mode: str
    root_accepted_text: str
    best_path_token_ids: list[int]
    best_path_node_indices: list[int]
    best_path_text: str
    branch_factor: int
    depth_evaluated: int
    node_count: int
    nodes: list[DraftTreePayloadNode]
    draft_path_steps: list[DraftPathStepPayload]


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
    if verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
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
        choices=("prompt_stub", "llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"),
        default=DEFAULT_SPECULATIVE_VERIFIER_MODE,
        help="Verifier mode for speculative propose handling.",
    )
    parser.add_argument(
        "--desktop-target-runtime-path",
        type=Path,
        default=default_desktop_target_runtime_path(),
        help="Optional path to the desktop target runtime helper for native verifier lanes.",
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
        desktop_target_runtime_path=args.desktop_target_runtime_path.resolve() if args.desktop_target_runtime_path else None,
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
    print(f"desktop_target_runtime_path={config.desktop_target_runtime_path}")

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


class DesktopTargetRuntimeClient:
    def __init__(self, helper_path: Path, model_path: Path) -> None:
        self.helper_path = helper_path
        self.model_path = model_path
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.model_loaded = False

    def _ensure_started(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.helper_path.exists():
            raise RuntimeError(
                f"Exact desktop target runtime helper is not available: {self.helper_path}"
            )
        launch_command = [str(self.helper_path)]
        if self.helper_path.suffix.lower() in {".cmd", ".bat"}:
            launch_command = ["cmd.exe", "/c", str(self.helper_path)]
        self.process = subprocess.Popen(
            launch_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.model_loaded = False

    def request(self, command: str, **payload: Any) -> dict[str, Any]:
        with self.lock:
            self._ensure_started()
            assert self.process is not None
            if self.process.stdin is None or self.process.stdout is None:
                raise RuntimeError("Exact desktop target runtime helper pipes are not available.")
            if not self.model_loaded:
                self._write_request({"command": "load_model", "modelPath": str(self.model_path)})
                load_response = self._read_response()
                if not bool(load_response.get("ok")):
                    raise RuntimeError(str(load_response.get("error") or "Failed to load exact desktop target runtime model."))
                self.model_loaded = True
            self._write_request({"command": command, **payload})
            response = self._read_response()
            if not bool(response.get("ok")):
                raise RuntimeError(str(response.get("error") or f"Exact helper command failed: {command}"))
            return response

    def _write_request(self, payload: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, ensure_ascii=True))
        self.process.stdin.write("\n")
        self.process.stdin.flush()

    def _read_response(self) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr_text = ""
            if self.process.stderr is not None:
                try:
                    stderr_text = self.process.stderr.read()
                except Exception:
                    stderr_text = ""
            raise RuntimeError(
                "Exact desktop target runtime helper exited unexpectedly."
                + (f" stderr={stderr_text.strip()}" if stderr_text.strip() else "")
            )
        return json.loads(line)

    def close(self) -> None:
        with self.lock:
            if self.process is None:
                return
            try:
                if self.process.poll() is None and self.process.stdin is not None:
                    self.process.stdin.write(json.dumps({"command": "shutdown"}))
                    self.process.stdin.write("\n")
                    self.process.stdin.flush()
            except Exception:
                pass
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None
            self.model_loaded = False


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


def parse_optional_draft_tree_payload(value: Any) -> DraftTreePayload | None:
    if not isinstance(value, dict):
        return None

    raw_nodes = value.get("nodes")
    nodes: list[DraftTreePayloadNode] = []
    if isinstance(raw_nodes, list):
        for index, item in enumerate(raw_nodes):
            if not isinstance(item, dict):
                continue
            nodes.append(
                DraftTreePayloadNode(
                    node_index=int(item.get("nodeIndex", index)),
                    token_id=int(item.get("tokenId", -1)),
                    token_text=str(item.get("tokenText") or ""),
                    depth=int(item.get("depth", 0)),
                    parent_node_index=int(item.get("parentNodeIndex", -1)),
                    probability=float(item.get("probability", 0.0) or 0.0),
                    log_probability=float(item.get("logProbability", 0.0) or 0.0),
                    cumulative_log_probability=float(item.get("cumulativeLogProbability", 0.0) or 0.0),
                )
            )

    raw_draft_path_steps = value.get("draftPathSteps")
    draft_path_steps: list[DraftPathStepPayload] = []
    if isinstance(raw_draft_path_steps, list):
        for index, item in enumerate(raw_draft_path_steps):
            if not isinstance(item, dict):
                continue
            raw_candidates = item.get("candidates")
            candidates: list[DraftPathStepCandidatePayload] = []
            if isinstance(raw_candidates, list):
                for candidate_index, candidate in enumerate(raw_candidates):
                    if not isinstance(candidate, dict):
                        continue
                    candidates.append(
                        DraftPathStepCandidatePayload(
                            node_index=int(candidate.get("nodeIndex", candidate_index)),
                            token_id=int(candidate.get("tokenId", -1)),
                            token_text=str(candidate.get("tokenText") or ""),
                            probability=float(candidate.get("probability", 0.0) or 0.0),
                            log_probability=float(candidate.get("logProbability", 0.0) or 0.0),
                        )
                    )
            draft_path_steps.append(
                DraftPathStepPayload(
                    depth=int(item.get("depth", index)),
                    parent_node_index=int(item.get("parentNodeIndex", -1)),
                    accepted_prefix_token_ids=parse_int_list(
                        "draftTree.draftPathSteps.acceptedPrefixTokenIds",
                        item.get("acceptedPrefixTokenIds") or [],
                    ),
                    candidates=candidates,
                    best_token_id=int(item.get("bestTokenId", -1)),
                    best_node_index=int(item.get("bestNodeIndex", -1)),
                )
            )

    return DraftTreePayload(
        session_id=str(value.get("sessionId") or ""),
        token_mode=str(value.get("tokenMode") or "codepoint_legacy"),
        root_accepted_text=str(value.get("rootAcceptedText") or ""),
        best_path_token_ids=parse_int_list("draftTree.bestPathTokenIds", value.get("bestPathTokenIds") or []),
        best_path_node_indices=parse_int_list("draftTree.bestPathNodeIndices", value.get("bestPathNodeIndices") or []),
        best_path_text=str(value.get("bestPathText") or ""),
        branch_factor=max(1, int(value.get("branchFactor", 1) or 1)),
        depth_evaluated=max(0, int(value.get("depthEvaluated", 0) or 0)),
        node_count=max(0, int(value.get("nodeCount", len(nodes)) or len(nodes))),
        nodes=nodes,
        draft_path_steps=draft_path_steps,
    )


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


def common_prefix_length(left: list[int], right: list[int]) -> int:
    length = 0
    for left_token_id, right_token_id in zip(left, right):
        if left_token_id != right_token_id:
            break
        length += 1
    return length


def deterministic_probability_draw(*parts: Any) -> float:
    payload = "|".join(str(part) for part in parts).encode("utf-8", errors="replace")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value / float(1 << 64)


def candidate_probability(candidate: dict[str, Any]) -> float:
    prob = float(candidate.get("prob", 0.0) or 0.0)
    if prob > 0.0:
        return prob
    logprob = float(candidate.get("logprob", 0.0) or 0.0)
    if logprob < 0.0:
        try:
            return math.exp(logprob)
        except OverflowError:
            return 0.0
    return 0.0


def is_real_token_verifier_mode(verifier_mode: str) -> bool:
    return verifier_mode in {"llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}


def is_llama_cpp_native_verifier_mode(verifier_mode: str) -> bool:
    return verifier_mode in {"llama_cpp_spec_native", "llama_cpp_spec_split"}


def tokenize_with_server(
    base_url: str,
    content: str,
    *,
    add_special: bool = False,
    parse_special: bool = True,
    with_pieces: bool = False,
) -> list[dict[str, Any]] | list[int]:
    response = request_json(
        "POST",
        f"{base_url}/tokenize",
        {
            "content": content,
            "add_special": add_special,
            "parse_special": parse_special,
            "with_pieces": with_pieces,
        },
        timeout_seconds=10.0,
    )
    tokens = response.get("tokens")
    if isinstance(tokens, list):
        return tokens
    return []


def detokenize_with_server(base_url: str, token_ids: list[int]) -> str:
    if not token_ids:
        return ""
    response = request_json(
        "POST",
        f"{base_url}/detokenize",
        {"tokens": token_ids},
        timeout_seconds=10.0,
    )
    return str(response.get("content") or "")


def render_token_ids_for_verifier(
    config: ServiceConfig,
    target_session: TargetSessionState,
    token_ids: list[int],
) -> str:
    if not token_ids:
        return ""
    if is_real_token_verifier_mode(target_session.verifier_mode) and config.llama_server_base_url:
        try:
            return detokenize_with_server(config.llama_server_base_url, token_ids)
        except Exception:
            pass
    return token_ids_to_debug_text(token_ids)


def tokenize_text_for_verifier(
    config: ServiceConfig,
    target_session: TargetSessionState,
    text: str,
) -> list[int]:
    if not text:
        return []
    if is_real_token_verifier_mode(target_session.verifier_mode) and config.llama_server_base_url:
        try:
            token_entries = tokenize_with_server(
                config.llama_server_base_url,
                text,
                add_special=False,
                parse_special=True,
                with_pieces=True,
            )
            return [
                int(item.get("id", -1))
                for item in token_entries
                if isinstance(item, dict) and int(item.get("id", -1)) >= 0
            ]
        except Exception:
            pass
    return token_ids_from_text(text)


def summed_first_token_probability(candidates: list[dict[str, Any]], token_id: int) -> float:
    total = 0.0
    for candidate in candidates:
        candidate_token_ids = [int(value) for value in candidate.get("tokenIds") or []]
        if candidate_token_ids and candidate_token_ids[0] == token_id:
            total += candidate_probability(candidate)
    return total


def aggregate_first_token_probabilities(candidates: list[dict[str, Any]]) -> dict[int, float]:
    aggregated: dict[int, float] = {}
    for candidate in candidates:
        candidate_token_ids = [int(value) for value in candidate.get("tokenIds") or []]
        if not candidate_token_ids:
            raw_token_id = int(candidate.get("tokenId", -1))
            candidate_token_ids = [raw_token_id] if raw_token_id >= 0 else []
        if not candidate_token_ids:
            continue
        token_id = candidate_token_ids[0]
        aggregated[token_id] = aggregated.get(token_id, 0.0) + candidate_probability(candidate)
    return aggregated


def select_contextual_draft_nodes(
    draft_nodes_by_depth: dict[int, list[DraftTreePayloadNode]],
    *,
    depth: int,
    active_parent_node_index: int,
) -> list[DraftTreePayloadNode]:
    nodes_at_depth = draft_nodes_by_depth.get(depth, [])
    if active_parent_node_index < 0:
        root_nodes = [node for node in nodes_at_depth if node.parent_node_index < 0]
        return root_nodes or nodes_at_depth
    contextual_nodes = [
        node for node in nodes_at_depth
        if node.parent_node_index == active_parent_node_index
    ]
    return contextual_nodes or nodes_at_depth


def choose_contextual_draft_node(
    draft_nodes: list[DraftTreePayloadNode],
    *,
    token_id: int,
) -> DraftTreePayloadNode | None:
    matching_nodes = [node for node in draft_nodes if node.token_id == token_id]
    if not matching_nodes:
        return None
    return max(
        matching_nodes,
        key=lambda node: (
            float(node.probability),
            float(node.cumulative_log_probability),
            -int(node.node_index),
        ),
    )


def select_draft_path_step(
    draft_tree: DraftTreePayload | None,
    *,
    depth: int,
    active_parent_node_index: int,
) -> DraftPathStepPayload | None:
    if draft_tree is None or not draft_tree.draft_path_steps:
        return None
    for step in draft_tree.draft_path_steps:
        if step.depth == depth and step.parent_node_index == active_parent_node_index:
            return step
    for step in draft_tree.draft_path_steps:
        if step.depth == depth:
            return step
    return None


def choose_draft_path_step_candidate(
    step: DraftPathStepPayload | None,
    *,
    token_id: int,
) -> DraftPathStepCandidatePayload | None:
    if step is None:
        return None
    matching_candidates = [candidate for candidate in step.candidates if candidate.token_id == token_id]
    if not matching_candidates:
        return None
    return max(
        matching_candidates,
        key=lambda candidate: (
            float(candidate.probability),
            float(candidate.log_probability),
            -int(candidate.node_index),
        ),
    )


def choose_residual_token_id(
    target_prob_by_token: dict[int, float],
    draft_prob_by_token: dict[int, float],
    *,
    request_id: str,
    target_index: int,
    depth: int,
    working_prefix: str,
) -> tuple[int, float, float]:
    residual_items: list[tuple[int, float]] = []
    for token_id, target_prob in target_prob_by_token.items():
        residual = max(0.0, float(target_prob) - float(draft_prob_by_token.get(token_id, 0.0) or 0.0))
        if residual > 0.0:
            residual_items.append((int(token_id), residual))
    if not residual_items:
        return -1, 0.0, -1.0

    residual_items.sort(key=lambda item: (-item[1], item[0]))
    residual_total = sum(weight for _, weight in residual_items)
    draw = deterministic_probability_draw(request_id, target_index, depth, "residual", working_prefix)
    threshold = draw * residual_total
    running = 0.0
    for token_id, weight in residual_items:
        running += weight
        if running >= threshold:
            return token_id, residual_total, draw
    token_id, _ = residual_items[-1]
    return token_id, residual_total, draw


def choose_sampled_token_id(
    token_prob_by_id: dict[int, float],
    *,
    request_id: str,
    target_index: int,
    depth: int,
    label: str,
    working_prefix: str,
) -> tuple[int, float]:
    items = [
        (int(token_id), float(probability))
        for token_id, probability in token_prob_by_id.items()
        if float(probability) > 0.0
    ]
    if not items:
        return -1, -1.0
    total = sum(probability for _, probability in items)
    if total <= 0.0:
        return -1, -1.0

    draw = deterministic_probability_draw(
        request_id,
        target_index,
        depth,
        label,
        working_prefix,
    )
    threshold = draw * total
    running = 0.0
    ordered_items = sorted(items, key=lambda item: (-item[1], item[0]))
    for token_id, probability in ordered_items:
        running += probability
        if running >= threshold:
            return token_id, draw
    token_id, _ = ordered_items[-1]
    return token_id, draw


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
    if verifier_mode not in {"llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
        return "", ""

    if verifier_mode in {"llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
        return "", ""

    if verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens"}:
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
    if verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
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
    if target_session.verifier_mode not in {"llama_preview", "llama_step_proxy", "llama_replay_proxy", "llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
        return

    if target_session.verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
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
    verifier_sampling_seed = int(
        hashlib.sha256(
            f"{session.request_id}:{session.session_id}:verifier".encode("utf-8")
        ).hexdigest()[:8],
        16,
    )
    return TargetSessionState(
        target_session_id=str(uuid.uuid4()),
        speculative_session_id=session.session_id,
        request_id=session.request_id,
        verifier_sampling_seed=verifier_sampling_seed,
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
        true_runtime_backend=(
            "desktop_target_runtime_exact"
            if session.verifier_mode == "llama_eagle_aligned"
            else "desktop_target_runtime_llama_cpp_spec_split"
            if session.verifier_mode == "llama_cpp_spec_split"
            else "desktop_target_runtime_llama_cpp_spec_native"
            if session.verifier_mode == "llama_cpp_spec_native"
            else "llama_server_slot"
            if session.verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens"}
            else "proxy_target"
        ),
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
        record_true_verifier_observation(
            config,
            target_session,
            prefix_text=working_prefix,
            next_text=next_text,
        )

    expected_token_ids = tokenize_text_for_verifier(config, target_session, next_text)
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
    target_text_delta = render_token_ids_for_verifier(config, target_session, committed_token_ids)
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
        target_preview_debug=(
            render_token_ids_for_verifier(config, target_session, expected_token_ids[:16])
            if expected_token_ids
            else "".join(preview_debug_parts) or target_session.target_preview_text[:16]
        ),
    )


def compute_true_tree_verifier_result(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
    draft_tree: DraftTreePayload | None = None,
) -> VerifyComputation:
    target_index = accepted_token_count
    tree = build_true_tree_computation(
        config,
        target_session,
        target_index=target_index,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
        draft_tree=draft_tree,
    )
    target_session.last_true_chunk_start = target_index
    target_session.last_true_chunk_consumed = len(tree.accepted_token_ids) + len(tree.correction_token_ids)
    if tree.best_path_token_ids:
        target_session.last_true_expected_token_id = tree.best_path_token_ids[0]
        target_session.last_true_expected_token_text = render_token_ids_for_verifier(
            config,
            target_session,
            [tree.best_path_token_ids[0]],
        )
    target_session.true_verifier_call_count += 1
    return VerifyComputation(
        accepted_token_ids=tree.accepted_token_ids,
        correction_token_ids=tree.correction_token_ids,
        rejected_from_index=tree.rejected_from_index,
        target_text_delta=tree.target_text_delta,
        finish_reason="",
        target_index_before_step=target_index,
        target_remaining_count=tree.tree_depth_evaluated,
        target_preview_debug=render_token_ids_for_verifier(config, target_session, tree.best_path_token_ids[:16]),
        tree_candidate_count=tree.candidate_count,
        tree_best_path_token_ids=tree.best_path_token_ids,
        tree_branch_factor=tree.tree_branch_factor,
        tree_depth_evaluated=tree.tree_depth_evaluated,
        tree_debug_summary=tree.tree_debug_summary,
    )


def compute_true_tree_pq_token_verifier_result(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
    draft_tree: DraftTreePayload | None = None,
    branch_factor: int = DEFAULT_TRUE_TREE_BRANCH_FACTOR,
) -> VerifyComputation:
    target_index = accepted_token_count
    working_prefix = target_session.accepted_text
    accepted_step_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    best_path_token_ids: list[int] = []
    debug_lines: list[str] = []
    rejected_from_index = -1
    total_candidate_count = 0
    draft_nodes_by_depth: dict[int, list[DraftTreePayloadNode]] = {}
    active_draft_parent_node_index = -1
    if draft_tree is not None:
        debug_lines.append(
            f"draftTree:mode={draft_tree.token_mode} nodes={draft_tree.node_count} depth={draft_tree.depth_evaluated} bestNodes={','.join(str(index) for index in draft_tree.best_path_node_indices)} draftPathSteps={len(draft_tree.draft_path_steps)}"
        )
        for node in draft_tree.nodes:
            draft_nodes_by_depth.setdefault(node.depth, []).append(node)

    for depth, proposed_token_id in enumerate(proposed_token_ids):
        effective_branch_factor = max(
            branch_factor,
            draft_tree.branch_factor if draft_tree is not None else branch_factor,
            DEFAULT_TOKEN_PQ_TARGET_TOPK,
        )
        top_result = fetch_target_top_candidates(
            config,
            target_session,
            prefix_text=working_prefix,
            step_index=target_index + depth,
            branch_factor=effective_branch_factor,
        )
        target_session.true_runtime_backend = str(top_result.get("runtimeBackend") or target_session.true_runtime_backend)
        target_session.last_replay_prompt = str(top_result.get("replayPrompt") or target_session.last_replay_prompt)
        candidates = list(top_result.get("candidates") or [])
        total_candidate_count += len(candidates)
        if not candidates:
            rejected_from_index = depth
            break

        target_best_candidate = max(candidates, key=candidate_probability)
        target_best_token_ids = [int(token_id) for token_id in target_best_candidate.get("tokenIds") or []]
        if not target_best_token_ids:
            raw_best_token_id = int(target_best_candidate.get("tokenId", -1))
            target_best_token_ids = [raw_best_token_id] if raw_best_token_id >= 0 else []
        target_best_token_id = target_best_token_ids[0] if target_best_token_ids else -1
        if target_best_token_id >= 0:
            best_path_token_ids.append(target_best_token_id)

        draft_path_step = select_draft_path_step(
            draft_tree,
            depth=depth,
            active_parent_node_index=active_draft_parent_node_index,
        )
        draft_nodes_at_depth = select_contextual_draft_nodes(
            draft_nodes_by_depth,
            depth=depth,
            active_parent_node_index=active_draft_parent_node_index,
        )
        if draft_path_step is not None:
            draft_prob_by_token = {
                candidate.token_id: candidate.probability
                for candidate in draft_path_step.candidates
            }
        else:
            draft_prob_by_token = {node.token_id: node.probability for node in draft_nodes_at_depth}
        draft_best_token = (
            draft_path_step.best_token_id
            if draft_path_step is not None and draft_path_step.best_token_id >= 0
            else draft_tree.best_path_token_ids[depth]
            if draft_tree is not None and depth < len(draft_tree.best_path_token_ids)
            else None
        )
        target_prob_by_token = aggregate_first_token_probabilities(candidates)
        selected_target_prob = float(target_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
        selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
        pq_acceptance_prob = -1.0
        pq_draw = -1.0
        pq_accepted = False
        residual_token_id = -1
        residual_total = 0.0
        residual_draw = -1.0
        if selected_draft_prob > 0.0:
            pq_acceptance_prob = min(1.0, selected_target_prob / selected_draft_prob)
            pq_draw = deterministic_probability_draw(
                target_session.request_id,
                target_index,
                depth,
                proposed_token_id,
                working_prefix,
            )
            pq_accepted = pq_draw <= pq_acceptance_prob
        if not pq_accepted:
            residual_token_id, residual_total, residual_draw = choose_residual_token_id(
                target_prob_by_token,
                draft_prob_by_token,
                request_id=target_session.request_id,
                target_index=target_index,
                depth=depth,
                working_prefix=working_prefix,
            )

        proposal_in_topk = proposed_token_id in target_prob_by_token
        overlap_count = len(set(target_prob_by_token.keys()) & set(draft_prob_by_token.keys()))
        debug_lines.append(
            f"d{depth}:topK={effective_branch_factor} best={target_best_token_id} proposal={proposed_token_id} "
            f"inTopK={proposal_in_topk} draftBest={draft_best_token if draft_best_token is not None else '-'} "
            f"draftParent={active_draft_parent_node_index} overlap={overlap_count} p={selected_target_prob:.4f} q={selected_draft_prob:.4f} "
            f"accP={pq_acceptance_prob:.4f} draw={pq_draw:.4f} pqAccepted={pq_accepted} "
            f"residualBest={residual_token_id} residualTotal={residual_total:.4f} residualDraw={residual_draw:.4f}"
        )

        if pq_accepted:
            accepted_step_token_ids.append(proposed_token_id)
            matched_draft_candidate = choose_draft_path_step_candidate(
                draft_path_step,
                token_id=proposed_token_id,
            )
            if matched_draft_candidate is not None:
                active_draft_parent_node_index = matched_draft_candidate.node_index
            else:
                matched_draft_node = choose_contextual_draft_node(
                    draft_nodes_at_depth,
                    token_id=proposed_token_id,
                )
                if matched_draft_node is not None:
                    active_draft_parent_node_index = matched_draft_node.node_index
            working_prefix += render_token_ids_for_verifier(config, target_session, [proposed_token_id])
            continue

        rejected_from_index = depth
        correction_token_id = residual_token_id if residual_token_id >= 0 else target_best_token_id
        if correction_token_id >= 0:
            correction_token_ids = [correction_token_id][:max_correction_tokens]
            working_prefix += render_token_ids_for_verifier(config, target_session, correction_token_ids)
        break

    if rejected_from_index == -1 and max_correction_tokens > 0:
        followup_result = fetch_target_top_candidates(
            config,
            target_session,
            prefix_text=working_prefix,
            step_index=target_index + len(accepted_step_token_ids),
            branch_factor=max(
                branch_factor,
                draft_tree.branch_factor if draft_tree is not None else branch_factor,
                DEFAULT_TOKEN_PQ_TARGET_TOPK,
            ),
        )
        target_session.true_runtime_backend = str(followup_result.get("runtimeBackend") or target_session.true_runtime_backend)
        target_session.last_replay_prompt = str(followup_result.get("replayPrompt") or target_session.last_replay_prompt)
        followup_candidates = list(followup_result.get("candidates") or [])
        total_candidate_count += len(followup_candidates)
        if followup_candidates:
            followup_best = max(followup_candidates, key=candidate_probability)
            followup_token_ids = [int(token_id) for token_id in followup_best.get("tokenIds") or []]
            if not followup_token_ids:
                raw_followup_id = int(followup_best.get("tokenId", -1))
                followup_token_ids = [raw_followup_id] if raw_followup_id >= 0 else []
            if followup_token_ids:
                followup_prob_by_token = aggregate_first_token_probabilities(followup_candidates)
                sampled_followup_token_id, followup_draw = choose_sampled_token_id(
                    followup_prob_by_token,
                    request_id=target_session.request_id,
                    target_index=target_index,
                    depth=len(accepted_step_token_ids),
                    label="followup",
                    working_prefix=working_prefix,
                )
                selected_followup_token_ids = (
                    [sampled_followup_token_id]
                    if sampled_followup_token_id >= 0
                    else followup_token_ids[:1]
                )
                correction_token_ids = selected_followup_token_ids[:max_correction_tokens]
                best_path_token_ids.extend(selected_followup_token_ids[:1])
                working_prefix += render_token_ids_for_verifier(config, target_session, correction_token_ids)
                debug_lines.append(
                    f"followup:best={followup_token_ids[0]} sampled={selected_followup_token_ids[0] if selected_followup_token_ids else -1} draw={followup_draw:.4f} correction={','.join(str(token_id) for token_id in correction_token_ids)}"
                )

    committed_token_ids = accepted_step_token_ids + correction_token_ids
    target_text_delta = render_token_ids_for_verifier(config, target_session, committed_token_ids)
    target_session.last_true_chunk_start = target_index
    target_session.last_true_chunk_consumed = len(committed_token_ids)
    if best_path_token_ids:
        target_session.last_true_expected_token_id = best_path_token_ids[0]
        target_session.last_true_expected_token_text = render_token_ids_for_verifier(
            config,
            target_session,
            [best_path_token_ids[0]],
        )
    target_session.true_verifier_call_count += 1
    return VerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids[:max_correction_tokens],
        rejected_from_index=rejected_from_index,
        target_text_delta=target_text_delta,
        finish_reason="",
        target_index_before_step=target_index,
        target_remaining_count=len(best_path_token_ids),
        target_preview_debug=render_token_ids_for_verifier(config, target_session, best_path_token_ids[:16]),
        tree_candidate_count=total_candidate_count,
        tree_best_path_token_ids=best_path_token_ids,
        tree_branch_factor=max(branch_factor, draft_tree.branch_factor if draft_tree is not None else branch_factor),
        tree_depth_evaluated=len(best_path_token_ids),
        tree_debug_summary="; ".join(debug_lines),
    )


def apply_verify_computation_to_sessions(
    config: ServiceConfig,
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
    if computation.accepted_text_after_step:
        session.accepted_text = computation.accepted_text_after_step
    elif computation.target_text_delta:
        session.accepted_text = f"{session.accepted_text}{computation.target_text_delta}"
    else:
        session.accepted_text = render_token_ids_for_verifier(
            config,
            target_session,
            session.accepted_token_ids,
        )
    session.target_token_ids = session.accepted_token_ids[:]
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
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    prefix_text: str,
    next_text: str,
) -> None:
    target_session.true_verifier_call_count += 1
    next_token_ids = tokenize_text_for_verifier(config, target_session, next_text[:64])
    target_session.last_true_expected_token_id = next_token_ids[0] if next_token_ids else -1
    target_session.last_true_expected_token_text = (
        render_token_ids_for_verifier(config, target_session, next_token_ids[:1])
        if next_token_ids else ""
    )
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
            if is_real_token_verifier_mode(target_session.verifier_mode):
                raw_token_id = item.get("id", -1)
                token_id = int(raw_token_id) if isinstance(raw_token_id, (int, float)) else -1
                token_ids = [token_id] if token_id >= 0 else []
            else:
                token_ids = token_ids_from_text(token_text) if token_text else []
                token_id = token_ids[0] if token_ids else -1
            prob = float(item.get("prob", 0.0) or 0.0)
            logprob = float(item.get("logprob", 0.0) or 0.0)
            effective_prob = prob if prob > 0.0 else (math.exp(logprob) if logprob < 0.0 else 0.0)
            score = effective_prob if effective_prob > 0.0 else logprob
            candidates.append(
                {
                    "tokenId": token_id,
                    "tokenIds": token_ids,
                    "tokenText": token_text,
                    "score": score,
                    "prob": effective_prob,
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
    if is_real_token_verifier_mode(target_session.verifier_mode) and config.llama_server_base_url and next_text:
        try:
            token_entries = tokenize_with_server(
                config.llama_server_base_url,
                next_text,
                add_special=False,
                parse_special=True,
                with_pieces=True,
            )
            next_token_ids = [
                int(item.get("id", -1))
                for item in token_entries
                if isinstance(item, dict) and int(item.get("id", -1)) >= 0
            ]
        except Exception:
            next_token_ids = []
    else:
        next_token_ids = token_ids_from_text(next_text) if next_text else []
    selected_token_id = next_token_ids[0] if next_token_ids else -1
    return {
        "selectedContent": next_text[:1] if next_text else "",
        "candidates": [
            {
                "tokenId": selected_token_id,
                "tokenIds": next_token_ids[:1],
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
    draft_tree: DraftTreePayload | None = None,
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
    proposal_cursor = 0
    draft_nodes_by_depth: dict[int, list[DraftTreePayloadNode]] = {}
    if draft_tree is not None:
        debug_lines.append(
            f"draftTree:mode={draft_tree.token_mode} nodes={draft_tree.node_count} depth={draft_tree.depth_evaluated} bestNodes={','.join(str(index) for index in draft_tree.best_path_node_indices)}"
        )
        for node in draft_tree.nodes:
            draft_nodes_by_depth.setdefault(node.depth, []).append(node)

    total_depth = max(1, len(proposed_token_ids) + max(0, max_correction_tokens))
    for depth in range(total_depth):
        effective_branch_factor = max(
            branch_factor,
            draft_tree.branch_factor if draft_tree is not None else branch_factor,
        )
        top_result = fetch_target_top_candidates(
            config,
            target_session,
            prefix_text=working_prefix,
            step_index=target_index + depth,
            branch_factor=effective_branch_factor,
        )
        target_session.true_runtime_backend = str(top_result.get("runtimeBackend") or target_session.true_runtime_backend)
        target_session.last_replay_prompt = str(top_result.get("replayPrompt") or target_session.last_replay_prompt)
        candidates = list(top_result.get("candidates") or [])
        if not candidates:
            if depth < len(proposed_token_ids):
                rejected_from_index = proposal_cursor
            break

        current_parent_index = parent_index
        draft_nodes_at_depth = draft_nodes_by_depth.get(depth, [])
        draft_prob_by_token = {node.token_id: node.probability for node in draft_nodes_at_depth}
        draft_best_token = (
            draft_tree.best_path_token_ids[depth]
            if draft_tree is not None and depth < len(draft_tree.best_path_token_ids)
            else None
        )
        draft_remaining_token_ids = (
            draft_tree.best_path_token_ids[proposal_cursor:]
            if draft_tree is not None and proposal_cursor < len(draft_tree.best_path_token_ids)
            else []
        )
        for candidate in candidates:
            candidate_token_ids = [int(token_id) for token_id in candidate.get("tokenIds") or []]
            tree_nodes.append(
                TreeCandidateNode(
                    token_id=int(candidate.get("tokenId", -1)),
                    token_ids=candidate_token_ids,
                    depth=depth,
                    parent_index=current_parent_index,
                    prefix_text=working_prefix,
                    score=float(candidate.get("score", 0.0) or 0.0),
                    token_text=str(candidate.get("tokenText") or ""),
                    draft_selected_prob=draft_prob_by_token.get(int(candidate.get("tokenId", -1))),
                )
            )

        target_best_candidate = max(
            candidates,
            key=lambda candidate: (
                candidate_probability(candidate),
                common_prefix_length(
                    [int(token_id) for token_id in candidate.get("tokenIds") or []],
                    draft_remaining_token_ids,
                ),
            ),
        )

        def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, ...]:
            candidate_token_id = int(candidate.get("tokenId", -1))
            candidate_prob = candidate_probability(candidate)
            candidate_token_ids = [int(token_id) for token_id in candidate.get("tokenIds") or []]
            draft_match_length = common_prefix_length(candidate_token_ids, draft_remaining_token_ids)
            proposal_match_length = common_prefix_length(
                candidate_token_ids,
                proposed_token_ids[proposal_cursor:],
            )
            draft_prob = draft_prob_by_token.get(candidate_token_id, 0.0)
            overlap_flag = 1.0 if candidate_token_id in draft_prob_by_token else 0.0
            draft_best_flag = 1.0 if draft_best_token is not None and candidate_token_id == draft_best_token else 0.0
            # Prefer candidates that continue the Android draft best path, then those
            # that overlap with the draft tree at all, then target confidence.
            return (
                float(draft_match_length),
                float(draft_best_flag),
                float(proposal_match_length),
                float(overlap_flag),
                float(candidate_prob + draft_prob),
                float(candidate_prob),
            )

        overlapping_candidates = [
            candidate for candidate in candidates
            if int(candidate.get("tokenId", -1)) in draft_prob_by_token
        ]
        ranked_candidates = sorted(candidates, key=candidate_sort_key, reverse=True)
        best_candidate = ranked_candidates[0]
        proposed_remaining_token_ids = proposed_token_ids[proposal_cursor:]
        proposal_candidate_matches = [
            candidate for candidate in candidates
            if common_prefix_length(
                [int(token_id) for token_id in candidate.get("tokenIds") or []],
                proposed_remaining_token_ids,
            ) > 0
        ]
        proposal_candidate = None
        if proposal_candidate_matches:
            proposal_candidate = max(
                proposal_candidate_matches,
                key=lambda candidate: (
                    common_prefix_length(
                        [int(token_id) for token_id in candidate.get("tokenIds") or []],
                        proposed_remaining_token_ids,
                    ),
                    candidate_probability(candidate),
                ),
            )
        pq_acceptance_prob = -1.0
        pq_draw = -1.0
        pq_accepted = False
        selected_target_prob = 0.0
        selected_draft_prob = 0.0
        proposed_token_id = proposed_token_ids[proposal_cursor] if proposal_cursor < len(proposed_token_ids) else None
        if (
            proposal_candidate is not None
            and proposed_token_id is not None
        ):
            selected_target_prob = summed_first_token_probability(candidates, proposed_token_id)
            selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
            if selected_draft_prob > 0.0:
                pq_acceptance_prob = min(1.0, selected_target_prob / selected_draft_prob)
                pq_draw = deterministic_probability_draw(
                    target_session.request_id,
                    target_index,
                    depth,
                    proposal_cursor,
                    proposed_token_id,
                    working_prefix,
                )
                pq_accepted = pq_draw <= pq_acceptance_prob
        best_candidate_token_ids = [int(token_id) for token_id in best_candidate.get("tokenIds") or []]
        if not best_candidate_token_ids:
            best_token_id = int(best_candidate.get("tokenId", -1))
            best_candidate_token_ids = [best_token_id] if best_token_id >= 0 else []
        else:
            best_token_id = best_candidate_token_ids[0]
        target_best_candidate_token_ids = [int(token_id) for token_id in target_best_candidate.get("tokenIds") or []]
        if not target_best_candidate_token_ids:
            target_best_token_id = int(target_best_candidate.get("tokenId", -1))
            target_best_candidate_token_ids = [target_best_token_id] if target_best_token_id >= 0 else []
        else:
            target_best_token_id = target_best_candidate_token_ids[0]
        best_path_token_ids.append(target_best_token_id)
        proposal_in_topk = proposed_token_id in {int(item.get("tokenId", -1)) for item in candidates}
        overlap_count = len(overlapping_candidates)
        draft_match_count = common_prefix_length(target_best_candidate_token_ids, draft_remaining_token_ids)
        debug_lines.append(
            f"d{depth}:best={target_best_token_id} proposal={proposed_token_id if proposed_token_id is not None else '-'} "
            f"inTopK={proposal_in_topk} draftBest={draft_best_token if draft_best_token is not None else '-'} "
            f"overlap={overlap_count} targetMatch={common_prefix_length(target_best_candidate_token_ids, proposed_remaining_token_ids)}/{len(target_best_candidate_token_ids)} "
            f"draftMatch={draft_match_count}/{len(target_best_candidate_token_ids)} "
            f"p={selected_target_prob:.4f} q={selected_draft_prob:.4f} "
            f"accP={pq_acceptance_prob:.4f} draw={pq_draw:.4f} pqAccepted={pq_accepted}"
        )

        if proposal_cursor < len(proposed_token_ids):
            if pq_accepted and proposed_token_id is not None:
                accepted_step_token_ids.append(proposed_token_id)
                working_prefix += render_token_ids_for_verifier(config, target_session, [proposed_token_id])
                proposal_cursor += 1
                parent_index = len(tree_nodes) - len(candidates)
                if proposal_cursor >= len(proposed_token_ids):
                    correction_source = target_best_candidate_token_ids or best_candidate_token_ids
                    if correction_source and len(correction_token_ids) < max_correction_tokens:
                        correction_token_ids.append(correction_source[0])
                    break
                continue

            rejected_from_index = proposal_cursor
            correction_source = target_best_candidate_token_ids or best_candidate_token_ids
            correction_token_ids = correction_source[:max_correction_tokens]
            working_prefix += render_token_ids_for_verifier(config, target_session, correction_token_ids)
            parent_index = len(tree_nodes) - len(candidates)
            break

        if len(correction_token_ids) < max_correction_tokens and target_best_candidate_token_ids:
            correction_token_ids.extend(
                target_best_candidate_token_ids[: max_correction_tokens - len(correction_token_ids)]
            )
            working_prefix += render_token_ids_for_verifier(config, target_session, correction_token_ids[-1:])
            parent_index = len(tree_nodes) - len(candidates)
            if len(correction_token_ids) >= max_correction_tokens:
                break

    target_text_delta = render_token_ids_for_verifier(
        config,
        target_session,
        accepted_step_token_ids + correction_token_ids,
    )
    return TreeVerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids[:max_correction_tokens],
        rejected_from_index=rejected_from_index,
        target_text_delta=target_text_delta,
        candidate_count=len(tree_nodes),
        best_path_token_ids=best_path_token_ids,
        tree_debug_summary="; ".join(debug_lines),
        tree_branch_factor=max(branch_factor, draft_tree.branch_factor if draft_tree is not None else branch_factor),
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


def serialize_draft_path_steps_for_helper(draft_tree: DraftTreePayload | None) -> list[dict[str, Any]]:
    if draft_tree is None:
        return []
    serialized_steps: list[dict[str, Any]] = []
    for step in draft_tree.draft_path_steps:
        serialized_steps.append(
            {
                "depth": step.depth,
                "parentNodeIndex": step.parent_node_index,
                "acceptedPrefixTokenIds": list(step.accepted_prefix_token_ids),
                "bestTokenId": step.best_token_id,
                "bestNodeIndex": step.best_node_index,
                "candidates": [
                    {
                        "nodeIndex": candidate.node_index,
                        "tokenId": candidate.token_id,
                        "tokenText": candidate.token_text,
                        "probability": candidate.probability,
                        "logProbability": candidate.log_probability,
                    }
                    for candidate in step.candidates
                ],
            }
        )
    return serialized_steps


def start_eagle_aligned_target_session(
    server: "InferenceServer",
    session: SpeculativeSession,
    target_session: TargetSessionState,
) -> None:
    if server.desktop_target_runtime is None:
        raise ValueError(
            "llama_eagle_aligned requires --desktop-target-runtime-path and an exact desktop target runtime helper."
        )
    response = server.desktop_target_runtime.request(
        "start_session",
        sessionId=target_session.target_session_id,
        systemPrompt=session.system_prompt,
        userPrompt=session.user_prompt,
        samplingConfig={
            "temperature": session.temperature,
            "topP": session.top_p,
            "topK": 40,
            "seed": target_session.verifier_sampling_seed,
        },
    )
    target_session.true_runtime_backend = "desktop_target_runtime_exact"
    target_session.target_preview_text = str(response.get("targetPreviewText") or "")
    target_session.last_replay_prompt = str(response.get("replayPrompt") or "")
    session.target_preview_text = target_session.target_preview_text
    session.last_replay_prompt = target_session.last_replay_prompt
    session.target_token_ids = []
    sync_target_session_state(target_session, session)


def start_llama_cpp_native_target_session(
    server: "InferenceServer",
    session: SpeculativeSession,
    target_session: TargetSessionState,
) -> None:
    if server.desktop_target_runtime is None:
        raise ValueError(
            f"{session.verifier_mode} requires --desktop-target-runtime-path and a desktop target runtime helper."
        )
    response = server.desktop_target_runtime.request(
        "start_session",
        sessionId=target_session.target_session_id,
        systemPrompt=session.system_prompt,
        userPrompt=session.user_prompt,
    )
    target_session.true_runtime_backend = (
        "desktop_target_runtime_llama_cpp_spec_split"
        if session.verifier_mode == "llama_cpp_spec_split"
        else "desktop_target_runtime_llama_cpp_spec_native"
    )
    target_session.target_preview_text = str(response.get("targetPreviewText") or "")
    target_session.last_replay_prompt = str(response.get("replayPrompt") or "")
    session.target_preview_text = target_session.target_preview_text
    session.last_replay_prompt = target_session.last_replay_prompt
    session.target_token_ids = []
    sync_target_session_state(target_session, session)


def compute_eagle_aligned_verifier_result(
    server: "InferenceServer",
    target_session: TargetSessionState,
    *,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
    draft_tree: DraftTreePayload | None,
) -> VerifyComputation:
    if server.desktop_target_runtime is None:
        raise ValueError(
            "llama_eagle_aligned requires --desktop-target-runtime-path and an exact desktop target runtime helper."
        )
    if draft_tree is None or draft_tree.token_mode != "real_token":
        raise ValueError("llama_eagle_aligned requires a real_token draftTree payload.")
    if not draft_tree.draft_path_steps:
        raise ValueError("llama_eagle_aligned requires draftPathSteps on the real-token draft payload.")

    response = server.desktop_target_runtime.request(
        "verify_step",
        sessionId=target_session.target_session_id,
        proposedTokenIds=proposed_token_ids,
        draftPathSteps=serialize_draft_path_steps_for_helper(draft_tree),
        maxCorrectionTokens=max_correction_tokens,
        deterministicSeedMaterial=f"{target_session.request_id}:{target_session.accepted_token_count}",
    )
    rejected_from_index_raw = response.get("rejectedFromIndex", -1)
    target_index_before_step_raw = response.get("targetIndexBeforeStep", target_session.accepted_token_count)
    target_remaining_count_raw = response.get("targetRemainingCount", 0)
    tree_candidate_count_raw = response.get("treeCandidateCount", 0)
    tree_branch_factor_raw = response.get("treeBranchFactor", 0)
    tree_depth_evaluated_raw = response.get("treeDepthEvaluated", 0)
    return VerifyComputation(
        accepted_token_ids=parse_int_list("helper.acceptedTokenIds", response.get("acceptedTokenIds") or []),
        correction_token_ids=parse_int_list("helper.correctionTokenIds", response.get("correctionTokenIds") or []),
        rejected_from_index=int(-1 if rejected_from_index_raw is None else rejected_from_index_raw),
        target_text_delta=str(response.get("targetTextDelta") or ""),
        finish_reason=str(response.get("finishReason") or ""),
        target_index_before_step=int(target_session.accepted_token_count if target_index_before_step_raw is None else target_index_before_step_raw),
        target_remaining_count=int(0 if target_remaining_count_raw is None else target_remaining_count_raw),
        target_preview_debug=str(response.get("targetPreviewDebug") or ""),
        tree_candidate_count=int(0 if tree_candidate_count_raw is None else tree_candidate_count_raw),
        tree_best_path_token_ids=parse_int_list("helper.treeBestPathTokenIds", response.get("treeBestPathTokenIds") or []),
        tree_branch_factor=int(0 if tree_branch_factor_raw is None else tree_branch_factor_raw),
        tree_depth_evaluated=int(0 if tree_depth_evaluated_raw is None else tree_depth_evaluated_raw),
        tree_debug_summary=str(response.get("treeDebugSummary") or ""),
        accepted_text_after_step=str(response.get("acceptedTextAfterStep") or ""),
    )


def compute_llama_cpp_native_verifier_result(
    server: "InferenceServer",
    session: SpeculativeSession,
    target_session: TargetSessionState,
    *,
    proposed_token_ids: list[int],
) -> VerifyComputation:
    if server.desktop_target_runtime is None:
        raise ValueError(
            f"{session.verifier_mode} requires --desktop-target-runtime-path and a desktop target runtime helper."
        )

    helper_started_at = time.perf_counter()
    response = server.desktop_target_runtime.request(
        "verify_split_draft_batch" if session.verifier_mode == "llama_cpp_spec_split" else "verify_draft_batch",
        sessionId=target_session.target_session_id,
        draftTokenIds=proposed_token_ids,
        samplingConfig={
            "temperature": session.temperature,
            "topP": session.top_p,
            "topK": 1,
            "minP": 0.0,
            "penaltyRepeat": 1.0,
            "penaltyFreq": 0.0,
            "penaltyPresent": 0.0,
            "seed": target_session.verifier_sampling_seed,
        },
    )
    helper_round_trip_ms = (time.perf_counter() - helper_started_at) * 1000.0
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    rejected_from_index_raw = response.get("rejectedFromIndex", -1)
    target_index_before_step_raw = response.get("targetIndexBeforeStep", target_session.accepted_token_count)
    target_remaining_count_raw = response.get("targetRemainingCount", 0)
    return VerifyComputation(
        accepted_token_ids=parse_int_list("helper.acceptedTokenIds", response.get("acceptedTokenIds") or []),
        correction_token_ids=parse_int_list("helper.correctionTokenIds", response.get("correctionTokenIds") or []),
        rejected_from_index=int(-1 if rejected_from_index_raw is None else rejected_from_index_raw),
        target_text_delta=str(response.get("targetTextDelta") or ""),
        finish_reason=str(response.get("finishReason") or ""),
        target_index_before_step=int(target_session.accepted_token_count if target_index_before_step_raw is None else target_index_before_step_raw),
        target_remaining_count=int(0 if target_remaining_count_raw is None else target_remaining_count_raw),
        target_preview_debug=str(response.get("targetPreviewDebug") or ""),
        tree_debug_summary=(
            f"draftCount={int(debug.get('draftCount', 0) or 0)} "
            f"acceptedDraftCount={int(debug.get('acceptedDraftCount', 0) or 0)} "
            f"rolledBackDraftCount={int(debug.get('rolledBackDraftCount', 0) or 0)} "
            f"usedSpeculative={bool(debug.get('usedSpeculative'))} "
            f"llamaCppStyleMode={bool(debug.get('llamaCppStyleMode'))} "
            f"splitContractMode={bool(debug.get('splitContractMode'))} "
            f"prepareMs={float(debug.get('timingPrepareMs', 0.0) or 0.0):.3f} "
            f"decodeMs={float(debug.get('timingDecodeMs', 0.0) or 0.0):.3f} "
            f"sampleMs={float(debug.get('timingSampleMs', 0.0) or 0.0):.3f} "
            f"rollbackMs={float(debug.get('timingRollbackMs', 0.0) or 0.0):.3f} "
            f"helperTotalMs={float(debug.get('timingHelperTotalMs', 0.0) or 0.0):.3f} "
            f"helperRoundTripMs={helper_round_trip_ms:.3f}"
        ),
        accepted_text_after_step=str(response.get("acceptedTextAfterStep") or ""),
        timing_prepare_ms=float(debug.get("timingPrepareMs", 0.0) or 0.0),
        timing_decode_ms=float(debug.get("timingDecodeMs", 0.0) or 0.0),
        timing_sample_ms=float(debug.get("timingSampleMs", 0.0) or 0.0),
        timing_rollback_ms=float(debug.get("timingRollbackMs", 0.0) or 0.0),
        timing_helper_total_ms=float(debug.get("timingHelperTotalMs", 0.0) or 0.0),
        timing_helper_round_trip_ms=helper_round_trip_ms,
    )


def start_speculative_session(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    session = build_speculative_session(payload, server.config)
    target_session = build_target_session_state(session)
    if session.verifier_mode == "llama_eagle_aligned":
        start_eagle_aligned_target_session(server, session, target_session)
    elif is_llama_cpp_native_verifier_mode(session.verifier_mode):
        start_llama_cpp_native_target_session(server, session, target_session)
    elif session.verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens"} and server.config.llama_server_base_url:
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
                server.config,
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
    t_service_begin = time.perf_counter()
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
    draft_tree = None
    if not is_llama_cpp_native_verifier_mode(session.verifier_mode):
        draft_tree = parse_optional_draft_tree_payload(payload.get("draftTree"))
    max_correction_tokens = max(1, int(payload.get("maxCorrectionTokens") or 1))
    if not proposed_token_ids:
        raise ValueError("proposedTokenIds must not be empty.")

    if session.verifier_mode not in {"llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"}:
        refresh_target_session_driver_state(
            server.config,
            target_session,
            session.accepted_token_ids,
            session.accepted_token_count,
            len(proposed_token_ids) + max_correction_tokens,
        )
        apply_target_session_state_to_session(session, target_session)
    debug_token_mode = (
        draft_tree.token_mode
        if draft_tree is not None
        else ("real_token" if is_real_token_verifier_mode(session.verifier_mode) else "codepoint_legacy")
    )
    debug_acceptance_mode = "other"

    if session.verifier_mode == "llama_true_step":
        debug_acceptance_mode = "step_compare"
        computation = compute_true_verifier_result(
            server.config,
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
            )
    elif session.verifier_mode == "llama_eagle_aligned":
        debug_token_mode = "real_token"
        debug_acceptance_mode = "token_pq_exact"
        computation = compute_eagle_aligned_verifier_result(
            server,
            target_session,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
            draft_tree=draft_tree,
        )
    elif is_llama_cpp_native_verifier_mode(session.verifier_mode):
        debug_token_mode = "real_token"
        debug_acceptance_mode = "llama_cpp_accept_n"
        computation = compute_llama_cpp_native_verifier_result(
            server,
            session,
            target_session,
            proposed_token_ids=proposed_token_ids,
        )
    elif session.verifier_mode == "llama_true_tree_pq_tokens":
        if draft_tree is not None and draft_tree.token_mode == "real_token":
            debug_acceptance_mode = "token_pq"
            computation = compute_true_tree_pq_token_verifier_result(
                server.config,
                target_session,
                accepted_token_ids=session.accepted_token_ids,
                accepted_token_count=session.accepted_token_count,
                proposed_token_ids=proposed_token_ids,
                max_correction_tokens=max_correction_tokens,
                draft_tree=draft_tree,
            )
        else:
            debug_acceptance_mode = "fallback_piece_prefix"
            computation = compute_true_tree_verifier_result(
                server.config,
                target_session,
                accepted_token_ids=session.accepted_token_ids,
                accepted_token_count=session.accepted_token_count,
                proposed_token_ids=proposed_token_ids,
                max_correction_tokens=max_correction_tokens,
                draft_tree=draft_tree,
            )
    elif session.verifier_mode == "llama_true_tree":
        debug_acceptance_mode = "piece_prefix"
        computation = compute_true_tree_verifier_result(
            server.config,
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
            draft_tree=draft_tree,
        )
    else:
        debug_acceptance_mode = "prompt_stub"
        computation = compute_proxy_verifier_result(
            target_session,
            accepted_token_ids=session.accepted_token_ids,
            accepted_token_count=session.accepted_token_count,
            proposed_token_ids=proposed_token_ids,
            max_correction_tokens=max_correction_tokens,
        )
    computation.timing_service_total_ms = (time.perf_counter() - t_service_begin) * 1000.0
    accepted_count = len(computation.accepted_token_ids)
    apply_verify_computation_to_sessions(
        server.config,
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

    if session.verifier_mode in {"llama_true_tree_pq_tokens", "llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"} and computation.rejected_from_index == -1:
        base_status = "accepted"
    else:
        base_status = "accepted" if not computation.correction_token_ids and computation.rejected_from_index == -1 else "corrected"
    if session.verifier_mode == "llama_replay_proxy":
        status = f"{base_status}_by_llama_replay"
    elif session.verifier_mode == "llama_true_step":
        status = f"{base_status}_by_llama_true_step"
    elif session.verifier_mode == "llama_true_tree":
        status = f"{base_status}_by_llama_true_tree"
    elif session.verifier_mode == "llama_true_tree_pq_tokens":
        status = f"{base_status}_by_llama_true_tree_pq_tokens"
    elif session.verifier_mode == "llama_eagle_aligned":
        status = f"{base_status}_by_llama_eagle_aligned"
    elif session.verifier_mode == "llama_cpp_spec_native":
        status = f"{base_status}_by_llama_cpp_spec_native"
    elif session.verifier_mode == "llama_cpp_spec_split":
        status = f"{base_status}_by_llama_cpp_spec_split"
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
        "Desktop speculative verification is now building a shallow target-side tree from llama-server top-k candidates and can also consume optional Android draft-tree metadata. "
        "This first tree verifier node still keeps the wire protocol largely unchanged and uses draft/target tree overlap to score a best path, "
        "but it is still not a full EAGLE-style posterior/KV-copy implementation."
        if session.verifier_mode == "llama_true_tree"
        else
        "Desktop speculative verification is now using the experimental unified-token tree verifier path. "
        "Android may send real-token draft ids and real-token draft-tree metadata on this path, but the desktop verifier is still only at the first integration stage "
        "and does not yet implement the full final paper-style posterior/correction algorithm."
        if session.verifier_mode == "llama_true_tree_pq_tokens"
        else
        "Desktop speculative verification is now using the exact EAGLE-aligned verifier lane. "
        "This lane is intended to preserve target-model output semantics by delegating acceptance and correction to the native desktop target runtime helper. "
        "It will fail closed if the helper is unavailable or if the Android draft payload is missing exact branch-conditioned draftPathSteps."
        if session.verifier_mode == "llama_eagle_aligned"
        else
        "Desktop speculative verification is now using a native llama.cpp-style speculative verifier lane. "
        "Android sends a real-token draft sequence, and the desktop helper reproduces llama.cpp's current speculative control flow: "
        "batch verify the draft, accept the longest matching prefix, then append one target token."
        if session.verifier_mode == "llama_cpp_spec_native"
        else
        "Desktop speculative verification is now using the experimental split-contract llama.cpp speculative lane. "
        "Android owns the draft runtime state in ai_chat.cpp, the desktop helper owns the verifier state in desktop_target_runtime.cpp, "
        "and the Python service only routes token batches between the two sides."
        if session.verifier_mode == "llama_cpp_spec_split"
        else
        "Desktop speculative verification is currently using llama preview text as a target proxy. "
        "It now computes accepted prefixes and correction tokens from the preview text, but it still does not run true target-model token verification yet."
        if session.verifier_mode in {"llama_preview", "llama_step_proxy"}
        else
        "Desktop speculative verification is currently a deterministic prompt-derived stub. "
        "It now computes accepted prefixes and correction tokens, but it still does not run target-model token verification yet."
    )
    if session.verifier_mode == "llama_true_tree_pq_tokens" and debug_acceptance_mode == "fallback_piece_prefix":
        warning += (
            " This run fell back to piece-prefix acceptance because the desktop verifier did not receive a usable real-token draft-tree payload."
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
        "tokenMode": debug_token_mode,
        "acceptanceMode": debug_acceptance_mode,
        "warning": warning,
        "acceptedText": session.accepted_text,
        "error": "",
        "debug": {
            "targetSessionId": session.target_session_id,
            "verifierMode": session.verifier_mode,
            "tokenMode": debug_token_mode,
            "acceptanceMode": debug_acceptance_mode,
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
            "draftTreeNodeCount": draft_tree.node_count if draft_tree is not None else 0,
            "draftTreeDepthEvaluated": draft_tree.depth_evaluated if draft_tree is not None else 0,
            "draftTreeBestPathNodeIndices": draft_tree.best_path_node_indices if draft_tree is not None else [],
            "draftPathStepCount": len(draft_tree.draft_path_steps) if draft_tree is not None else 0,
            "timingPrepareMs": computation.timing_prepare_ms,
            "timingDecodeMs": computation.timing_decode_ms,
            "timingSampleMs": computation.timing_sample_ms,
            "timingRollbackMs": computation.timing_rollback_ms,
            "timingHelperTotalMs": computation.timing_helper_total_ms,
            "timingHelperRoundTripMs": computation.timing_helper_round_trip_ms,
            "timingServiceTotalMs": computation.timing_service_total_ms,
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
        and target_session.verifier_mode in {"llama_true_step", "llama_true_tree", "llama_true_tree_pq_tokens"}
        and server.config.llama_server_base_url
        and target_session.llama_server_slot_id >= 0
    ):
        try:
            erase_llama_server_slot(server.config.llama_server_base_url, target_session.llama_server_slot_id)
        except RuntimeError:
            pass
    if target_session is not None and target_session.verifier_mode in {"llama_eagle_aligned", "llama_cpp_spec_native", "llama_cpp_spec_split"} and server.desktop_target_runtime is not None:
        try:
            server.desktop_target_runtime.request("close_session", sessionId=target_session.target_session_id)
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
                "desktopTargetRuntimePath": str(self.server.config.desktop_target_runtime_path or ""),
                "desktopTargetRuntimeAvailable": bool(
                    self.server.config.desktop_target_runtime_path
                    and self.server.config.desktop_target_runtime_path.exists()
                ),
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
                "desktopTargetRuntimePath": str(self.server.config.desktop_target_runtime_path or ""),
                "desktopTargetRuntimeAvailable": bool(
                    self.server.config.desktop_target_runtime_path
                    and self.server.config.desktop_target_runtime_path.exists()
                ),
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
        self.send_header("Connection", "close")
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
        self.desktop_target_runtime = (
            DesktopTargetRuntimeClient(config.desktop_target_runtime_path, config.model_path)
            if config.desktop_target_runtime_path is not None
            else None
        )

    def session_count(self) -> int:
        with self.sessions_lock:
            return len(self.sessions)

    def target_session_count(self) -> int:
        with self.sessions_lock:
            return len(self.target_sessions)

    def server_close(self) -> None:
        if self.desktop_target_runtime is not None:
            self.desktop_target_runtime.close()
        super().server_close()


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

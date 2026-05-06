import argparse
import atexit
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


LOCK_DIR_NAME = ".experiment-lock"


def acquire_experiment_lock(repo_root: Path) -> Path:
    lock_dir = repo_root / LOCK_DIR_NAME
    owner_info_path = lock_dir / "owner.json"
    try:
        lock_dir.mkdir()
    except FileExistsError:
        owner_info = owner_info_path.read_text(encoding="utf-8") if owner_info_path.exists() else ""
        raise RuntimeError(f"Another experiment is already running. lockDir={lock_dir} owner={owner_info}")

    owner_info_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "script": str(Path(__file__).resolve()),
                "startedAt": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
                "host": os.environ.get("COMPUTERNAME", ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    def _cleanup() -> None:
        try:
            if owner_info_path.exists():
                owner_info_path.unlink()
            lock_dir.rmdir()
        except OSError:
            pass

    atexit.register(_cleanup)
    return lock_dir


def windows_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive[0].lower()
    tail = resolved.as_posix()[2:]
    return f"/mnt/{drive}{tail}"


def read_gradle_local_properties(repo_root: Path) -> dict[str, str]:
    props_path = repo_root / "gradle-local.properties"
    if not props_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in props_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_metrics(log_text: str, start: str, end: str) -> dict:
    decoded_tokens = None
    decoded_seconds = None
    decoded_tps = None
    prompt_tps = None
    generation_tps = None

    for line in log_text.splitlines():
        m = re.search(r"decoded\s+(\d+)\s+tokens\s+in\s+([0-9.]+)\s+seconds,\s+speed:\s+([0-9.]+)\s+t/s", line)
        if m:
            decoded_tokens = int(m.group(1))
            decoded_seconds = float(m.group(2))
            decoded_tps = float(m.group(3))
        m = re.search(r"\[\s*Prompt:\s*([0-9.]+)\s*t/s\s*\|\s*Generation:\s*([0-9.]+)\s*t/s\s*\]", line)
        if m:
            prompt_tps = float(m.group(1))
            generation_tps = float(m.group(2))
        m = re.search(r"prompt eval time\s*=\s*[0-9.]+\s*ms\s*/\s*\d+\s*tokens\s*\(\s*([0-9.]+)\s*tokens per second", line)
        if m:
            prompt_tps = float(m.group(1))
        m = re.search(r"eval time\s*=\s*[0-9.]+\s*ms\s*/\s*\d+\s*runs.*\(\s*([0-9.]+)\s*tokens per second", line)
        if m:
            generation_tps = float(m.group(1))
        m = re.search(r"sample time\s*=\s*[0-9.]+\s*ms\s*/\s*(\d+)\s*runs", line)
        if m and decoded_tokens is None:
            decoded_tokens = int(m.group(1))

    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S %z")
    end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S %z")
    wall_seconds = round((end_dt - start_dt).total_seconds(), 3)
    wall_tps = round(decoded_tokens / wall_seconds, 3) if decoded_tokens and wall_seconds > 0 else None
    return {
        "decodedTokens": decoded_tokens,
        "decodedSeconds": decoded_seconds,
        "decodedTokensPerSecond": decoded_tps,
        "promptTokensPerSecond": prompt_tps,
        "generationTokensPerSecond": generation_tps,
        "wallSeconds": wall_seconds,
        "wallTokensPerSecond": wall_tps,
    }


def extract_marker_timestamp(log_text: str, marker: str) -> str | None:
    pattern = rf"{re.escape(marker)}=(\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}} [+-]\d{{4}})"
    m = re.search(pattern, log_text)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Explain speculative decoding briefly.")
    parser.add_argument("--max-output-tokens", type=int, default=64)
    parser.add_argument("--ctx-size", type=int, default=512)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--llama-root", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    acquire_experiment_lock(repo_root)
    experiments_root = repo_root / "reference" / "spec-split-demo-project" / "experiments"
    date_dir = experiments_root / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    gradle_local = read_gradle_local_properties(repo_root)
    llama_root = Path(args.llama_root) if args.llama_root else Path(
        gradle_local.get("llamaCppSourceDir", str(repo_root.parent / "llama.cpp"))
    )
    model_path = Path(args.model_path)
    cli_path = llama_root / "build-wsl-cli" / "bin" / "llama-cli"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not cli_path.exists():
        raise FileNotFoundError(f"llama-cli not found: {cli_path}")

    cli_wsl = windows_to_wsl(cli_path)
    model_wsl = windows_to_wsl(model_path)
    ld_path = windows_to_wsl(cli_path.parent)
    bash_command = (
        f"export LD_LIBRARY_PATH='{ld_path}'; "
        f"START_TS=\"$(date '+%Y-%m-%d %H:%M:%S %z')\"; "
        f"echo \"__EXPERIMENT_START__=$START_TS\"; "
        f"'{cli_wsl}' -m '{model_wsl}' -p {json.dumps(args.prompt)} -n {max(1, args.max_output_tokens)} "
        f"--ctx-size {args.ctx_size} --no-warmup --simple-io --no-display-prompt -st -t {max(1, args.threads)} --temp 0 --top-k 1 --log-disable; "
        f"END_TS=\"$(date '+%Y-%m-%d %H:%M:%S %z')\"; "
        f"echo \"__EXPERIMENT_END__=$END_TS\""
    )

    started_at = datetime.now(timezone.utc).astimezone()
    proc = subprocess.run(
        ["wsl.exe", "bash", "-lc", bash_command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ended_at = datetime.now(timezone.utc).astimezone()
    combined_log = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    if proc.returncode != 0:
        sys.stderr.write(combined_log)
        return proc.returncode

    start = extract_marker_timestamp(combined_log, "__EXPERIMENT_START__") or started_at.strftime("%Y-%m-%d %H:%M:%S %z")
    end = extract_marker_timestamp(combined_log, "__EXPERIMENT_END__") or ended_at.strftime("%Y-%m-%d %H:%M:%S %z")

    stamp = start.replace(":", "-").replace(" ", "T")
    log_path = date_dir / f"desktop_direct_{stamp}.log"
    log_path.write_text(combined_log, encoding="utf-8")

    metrics = parse_metrics(combined_log, start, end)
    summary = {
        "generatedAt": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "script": str(Path(__file__).resolve()),
        "start": start,
        "end": end,
        "prompt": args.prompt,
        "timingBasis": "generation_metrics_from_llama_cli; shell markers bound the binary invocation",
        "maxOutputTokens": args.max_output_tokens,
        "ctxSize": args.ctx_size,
        "threads": max(1, args.threads),
        "modelPath": str(model_path.resolve()),
        "logPath": str(log_path.resolve()),
        "metrics": metrics,
    }
    summary_stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S%z")
    summary_path = date_dir / f"desktop_direct_summary_{summary_stamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"desktop direct experiment complete")
    print(f"summary: {summary_path}")
    print(f"log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

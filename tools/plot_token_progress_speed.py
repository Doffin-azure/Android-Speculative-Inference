from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SINGLE_RE = re.compile(
    r"\[spec-simple\]\[timing\]\s+round=(?P<round>\d+)\s+drafted=(?P<drafted>\d+)\s+"
    r"accept=(?P<accept>\d+)\s+reject=(?P<reject>\d+)\s+draft=(?P<draft_ms>[0-9.]+)ms\s+"
    r"decode=(?P<decode_ms>[0-9.]+)ms\s+sample=(?P<sample_ms>[0-9.]+)ms\s+"
    r"post=(?P<post_ms>[0-9.]+)ms\s+total=(?P<total_ms>[0-9.]+)ms"
)

DUAL_VERIFY_RE = re.compile(
    r"\[verify-native\]\[timing\]\s+round=(?P<round>\d+)\s+draft=(?P<draft>\d+)\s+"
    r"accept=(?P<accept>\d+)\s+reject=(?P<reject>\d+)\s+comm=(?P<comm_ms>[0-9.]+)ms\s+"
    r"decode=(?P<decode_ms>[0-9.]+)ms\s+sample=(?P<sample_ms>[0-9.]+)ms\s+"
    r"rollback=(?P<rollback_ms>[0-9.]+)ms"
)

DUAL_DRAFT_RE = re.compile(
    r"\[draft-native\]\[timing\]\s+round=(?P<round>\d+)\s+drafted=(?P<drafted>\d+)\s+"
    r"sync=(?P<sync_ms>[0-9.]+)ms(?:\s+rollbackMs=(?P<rollback_ms>[0-9.]+)ms)?\s+"
    r"tail=(?P<tail_ms>[0-9.]+)ms\s+draft=(?P<draft_ms>[0-9.]+)ms\s+"
    r"decision->draft=(?P<decision_ms>[-0-9.]+)ms"
)

ANDROID_STEP_RE = re.compile(
    r"^step=(?P<step>\d+)\s+draftMax=(?P<draft_max>\d+)\s+proposed=(?P<proposed>\d+)\s+"
    r"accepted=(?P<accepted>\d+)\s+corrections=(?P<corrections>\d+)\s+"
    r"committed=(?P<committed>\d+)\s+draftFetchMs=(?P<draft_fetch_ms>\d+)\s+"
    r"draftGenerateMs=(?P<draft_generate_ms>\d+)\s+draftRollbackMs=(?P<draft_rollback_ms>\d+)\s+"
    r"remoteMs=(?P<remote_ms>\d+)"
)


@dataclass
class Point:
    token_index: int
    cumulative_ms: float
    avg_tps: float


@dataclass
class Degradation:
    peak_token: int
    peak_tps: float
    degradation_token: int | None
    degradation_tps: float | None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_single_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    if "metrics" in summary:
        return summary["metrics"]
    if "baseline" in summary and isinstance(summary["baseline"], dict) and "metrics" in summary["baseline"]:
        return summary["baseline"]["metrics"]
    raise KeyError("single-process metrics not found in summary")


def scale_points(points: list[Point], official_total_ms: float | None) -> list[Point]:
    if not points or official_total_ms is None or official_total_ms <= 0:
        return points
    raw_total_ms = points[-1].cumulative_ms
    if raw_total_ms <= 0:
        return points
    scale = official_total_ms / raw_total_ms
    return [
        Point(
            token_index=point.token_index,
            cumulative_ms=point.cumulative_ms * scale,
            avg_tps=point.token_index * 1000.0 / (point.cumulative_ms * scale),
        )
        for point in points
    ]


def parse_single(log_path: Path) -> list[Point]:
    points: list[Point] = []
    cumulative_tokens = 0
    cumulative_ms = 0.0
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = SINGLE_RE.search(line)
        if not match:
            continue
        accepted = int(match.group("accept"))
        total_ms = float(match.group("total_ms"))
        committed = accepted + 1
        cumulative_tokens += committed
        cumulative_ms += total_ms
        points.append(Point(cumulative_tokens, cumulative_ms, cumulative_tokens * 1000.0 / cumulative_ms))
    return points


def parse_dual(draft_log_path: Path, verify_log_path: Path) -> list[Point]:
    draft_rounds: dict[int, dict[str, float]] = {}
    verify_rounds: dict[int, dict[str, float]] = {}

    for line in draft_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = DUAL_DRAFT_RE.search(line)
        if not match:
            continue
        round_idx = int(match.group("round"))
        draft_rounds[round_idx] = {
            "sync_ms": float(match.group("sync_ms")),
            "tail_ms": float(match.group("tail_ms")),
            "draft_ms": float(match.group("draft_ms")),
            "decision_ms": max(0.0, float(match.group("decision_ms"))),
        }

    for line in verify_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = DUAL_VERIFY_RE.search(line)
        if not match:
            continue
        round_idx = int(match.group("round"))
        verify_rounds[round_idx] = {
            "accept": float(match.group("accept")),
            "comm_ms": float(match.group("comm_ms")),
            "decode_ms": float(match.group("decode_ms")),
            "sample_ms": float(match.group("sample_ms")),
            "rollback_ms": float(match.group("rollback_ms")),
        }

    round_indices = sorted(set(draft_rounds) & set(verify_rounds))
    points: list[Point] = []
    cumulative_tokens = 0
    cumulative_ms = 0.0
    for round_idx in round_indices:
        draft_metrics = draft_rounds[round_idx]
        verify_metrics = verify_rounds[round_idx]
        committed = int(verify_metrics["accept"]) + 1
        total_ms = (
            draft_metrics["sync_ms"]
            + draft_metrics["tail_ms"]
            + draft_metrics["draft_ms"]
            + draft_metrics["decision_ms"]
            + verify_metrics["comm_ms"]
            + verify_metrics["decode_ms"]
            + verify_metrics["sample_ms"]
            + verify_metrics["rollback_ms"]
        )
        cumulative_tokens += committed
        cumulative_ms += total_ms
        points.append(Point(cumulative_tokens, cumulative_ms, cumulative_tokens * 1000.0 / cumulative_ms))
    return points


def parse_android(app_output_path: Path) -> list[Point]:
    points: list[Point] = []
    cumulative_tokens = 0
    cumulative_ms = 0.0
    for line in app_output_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = ANDROID_STEP_RE.search(line.strip())
        if not match:
            continue
        accepted = int(match.group("accepted"))
        corrections = int(match.group("corrections"))
        committed = accepted + corrections
        total_ms = float(match.group("draft_fetch_ms")) + float(match.group("remote_ms"))
        cumulative_tokens += committed
        cumulative_ms += total_ms
        points.append(Point(cumulative_tokens, cumulative_ms, cumulative_tokens * 1000.0 / cumulative_ms))
    return points


def extract_android_total_ms(app_output_path: Path) -> float | None:
    for line in app_output_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("totalMs="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def detect_degradation(points: list[Point], warmup_tokens: int = 64, drop_ratio: float = 0.03, sustain_points: int = 8) -> Degradation:
    eligible = [p for p in points if p.token_index >= warmup_tokens]
    if not eligible:
        peak = max(points, key=lambda p: p.avg_tps)
        return Degradation(peak.token_index, peak.avg_tps, None, None)

    peak = max(eligible, key=lambda p: p.avg_tps)
    peak_index = points.index(peak)
    threshold = peak.avg_tps * (1.0 - drop_ratio)

    for idx in range(peak_index + 1, max(peak_index + 1, len(points) - sustain_points + 1)):
        window = points[idx : idx + sustain_points]
        if len(window) < sustain_points:
            break
        if all(point.avg_tps <= threshold for point in window):
            point = window[0]
            return Degradation(peak.token_index, peak.avg_tps, point.token_index, point.avg_tps)
    return Degradation(peak.token_index, peak.avg_tps, None, None)


def svg_polyline(points: list[Point], plot_x: float, plot_y: float, plot_w: float, plot_h: float, max_tokens: int, max_tps: float) -> str:
    coords: list[str] = []
    for point in points:
        x = plot_x + (point.token_index / max_tokens) * plot_w
        y = plot_y + plot_h - (point.avg_tps / max_tps) * plot_h
        coords.append(f"{x:.2f},{y:.2f}")
    return " ".join(coords)


def render_svg(series: list[tuple[str, str, list[Point], Degradation]], output_path: Path) -> None:
    width = 1100
    height = 700
    plot_x = 90
    plot_y = 70
    plot_w = 760
    plot_h = 520
    max_tokens = max(point.token_index for _, _, points, _ in series for point in points)
    max_tps = max(point.avg_tps for _, _, points, _ in series for point in points)
    max_tps = math.ceil(max_tps / 2.0) * 2.0

    y_ticks = 6
    x_ticks = 5

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif;fill:#1f2328}",
        ".axis{font-size:16px}",
        ".label{font-size:18px}",
        ".legend{font-size:16px}",
        ".note{font-size:15px}",
        "</style>",
    ]

    for idx in range(y_ticks + 1):
        y = plot_y + plot_h - idx * plot_h / y_ticks
        value = max_tps * idx / y_ticks
        parts.append(f'<line x1="{plot_x}" y1="{y:.2f}" x2="{plot_x + plot_w}" y2="{y:.2f}" stroke="#d8dee4" stroke-width="1"/>')
        parts.append(f'<text x="{plot_x - 12}" y="{y + 6:.2f}" text-anchor="end" class="axis">{value:.1f}</text>')

    for idx in range(x_ticks + 1):
        x = plot_x + idx * plot_w / x_ticks
        value = round(max_tokens * idx / x_ticks)
        parts.append(f'<line x1="{x:.2f}" y1="{plot_y}" x2="{x:.2f}" y2="{plot_y + plot_h}" stroke="#eef2f6" stroke-width="1"/>')
        parts.append(f'<text x="{x:.2f}" y="{plot_y + plot_h + 28}" text-anchor="middle" class="axis">{value}</text>')

    parts.extend(
        [
            f'<line x1="{plot_x}" y1="{plot_y + plot_h}" x2="{plot_x + plot_w}" y2="{plot_y + plot_h}" stroke="#333" stroke-width="2"/>',
            f'<line x1="{plot_x}" y1="{plot_y}" x2="{plot_x}" y2="{plot_y + plot_h}" stroke="#333" stroke-width="2"/>',
            f'<text x="{plot_x + plot_w / 2:.2f}" y="{height - 34}" text-anchor="middle" class="label">Generated token index</text>',
            f'<text x="28" y="{plot_y + plot_h / 2:.2f}" transform="rotate(-90 28 {plot_y + plot_h / 2:.2f})" class="label">Average throughput / token s^-1</text>',
        ]
    )

    legend_x = 875
    legend_y = 110
    parts.append(f'<rect x="{legend_x - 20}" y="{legend_y - 36}" width="200" height="220" rx="12" fill="#f6f8fa" stroke="#d0d7de"/>')

    for idx, (name, color, points, degradation) in enumerate(series):
        y = legend_y + idx * 62
        polyline = svg_polyline(points, plot_x, plot_y, plot_w, plot_h, max_tokens, max_tps)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{polyline}"/>')
        if degradation.degradation_token is not None:
            deg_x = plot_x + (degradation.degradation_token / max_tokens) * plot_w
            parts.append(
                f'<line x1="{deg_x:.2f}" y1="{plot_y}" x2="{deg_x:.2f}" y2="{plot_y + plot_h}" '
                f'stroke="{color}" stroke-width="1.5" stroke-dasharray="6 4"/>'
            )
        parts.extend(
            [
                f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 24}" y2="{y}" stroke="{color}" stroke-width="4"/>',
                f'<text x="{legend_x + 34}" y="{y + 5}" class="legend">{name}</text>',
                f'<text x="{legend_x}" y="{y + 24}" class="note">peak: {degradation.peak_tps:.2f} @ token {degradation.peak_token}</text>',
                f'<text x="{legend_x}" y="{y + 44}" class="note">degrade: '
                + (
                    f'{degradation.degradation_tps:.2f} @ token {degradation.degradation_token}'
                    if degradation.degradation_token is not None
                    else "not detected"
                )
                + "</text>",
            ]
        )

    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot average throughput by generated token index for three speculative decoding schemes.")
    parser.add_argument("--single-log", required=True)
    parser.add_argument("--single-summary", required=True)
    parser.add_argument("--dual-draft-log", required=True)
    parser.add_argument("--dual-verify-log", required=True)
    parser.add_argument("--dual-summary", required=True)
    parser.add_argument("--android-output", required=True)
    parser.add_argument("--android-summary", required=True)
    parser.add_argument("--output-svg", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    single_points = parse_single(Path(args.single_log))
    dual_points = parse_dual(Path(args.dual_draft_log), Path(args.dual_verify_log))
    android_points = parse_android(Path(args.android_output))

    single_summary = load_json(Path(args.single_summary))
    dual_summary = load_json(Path(args.dual_summary))
    android_summary = load_json(Path(args.android_summary))

    single_metrics = extract_single_metrics(single_summary)
    single_official_ms = float(single_metrics["steadyStateWallSeconds"]) * 1000.0
    dual_official_ms = float(dual_summary["nativeFull"]["wallSeconds"]) * 1000.0
    android_official_ms = extract_android_total_ms(Path(args.android_output))
    android_output_text = Path(args.android_output).read_text(encoding="utf-8", errors="ignore")
    if android_official_ms is None:
        started_at = android_summary.get("startedAt")
        finished_at = android_summary.get("finishedAt")
        if started_at and finished_at:
            raise RuntimeError("android totalMs not found in app output; add parser support before plotting")

    single_points = scale_points(single_points, single_official_ms)
    dual_points = scale_points(dual_points, dual_official_ms)
    android_points = scale_points(android_points, android_official_ms)

    single_deg = detect_degradation(single_points)
    dual_deg = detect_degradation(dual_points)
    android_deg = detect_degradation(android_points)

    series = [
        ("PC single", "#4c78a8", single_points, single_deg),
        ("PC dual", "#72b7b2", dual_points, dual_deg),
        ("Android + PC", "#f58518", android_points, android_deg),
    ]
    render_svg(series, Path(args.output_svg))

    summary = {
        "single": {
            "peak_token": single_deg.peak_token,
            "peak_tps": round(single_deg.peak_tps, 3),
            "degradation_token": single_deg.degradation_token,
            "degradation_tps": round(single_deg.degradation_tps, 3) if single_deg.degradation_tps is not None else None,
            "final_token": single_points[-1].token_index,
            "final_tps": round(single_points[-1].avg_tps, 3),
            "official_final_tps": round(single_metrics["overallTokensPerSecond"], 3),
        },
        "dual": {
            "peak_token": dual_deg.peak_token,
            "peak_tps": round(dual_deg.peak_tps, 3),
            "degradation_token": dual_deg.degradation_token,
            "degradation_tps": round(dual_deg.degradation_tps, 3) if dual_deg.degradation_tps is not None else None,
            "final_token": dual_points[-1].token_index,
            "final_tps": round(dual_points[-1].avg_tps, 3),
            "official_final_tps": round(dual_summary["nativeFull"]["overallTokensPerSecond"], 3),
        },
        "android": {
            "peak_token": android_deg.peak_token,
            "peak_tps": round(android_deg.peak_tps, 3),
            "degradation_token": android_deg.degradation_token,
            "degradation_tps": round(android_deg.degradation_tps, 3) if android_deg.degradation_tps is not None else None,
            "final_token": android_points[-1].token_index,
            "final_tps": round(android_points[-1].avg_tps, 3),
            "official_final_tps": round(float(re.search(r"overallTokensPerSecond=([0-9.]+)", android_output_text).group(1)), 3),
        },
    }
    Path(args.output_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

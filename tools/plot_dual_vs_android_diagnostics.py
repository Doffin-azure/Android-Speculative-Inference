from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


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
    proposed: int
    committed: int
    accept_ratio: float
    avg_tps: float
    round_ms: float


def moving_average(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        chunk = values[start : idx + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def parse_dual(draft_log: Path, verify_log: Path, official_total_ms: float) -> list[Point]:
    draft_rounds: dict[int, dict[str, float]] = {}
    verify_rounds: dict[int, dict[str, float]] = {}

    for line in draft_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = DUAL_DRAFT_RE.search(line)
        if not m:
            continue
        round_idx = int(m.group("round"))
        draft_rounds[round_idx] = {
            "drafted": float(m.group("drafted")),
            "sync_ms": float(m.group("sync_ms")),
            "tail_ms": float(m.group("tail_ms")),
            "draft_ms": float(m.group("draft_ms")),
            "decision_ms": max(0.0, float(m.group("decision_ms"))),
        }

    for line in verify_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = DUAL_VERIFY_RE.search(line)
        if not m:
            continue
        round_idx = int(m.group("round"))
        verify_rounds[round_idx] = {
            "accepted": float(m.group("accept")),
            "comm_ms": float(m.group("comm_ms")),
            "decode_ms": float(m.group("decode_ms")),
            "sample_ms": float(m.group("sample_ms")),
            "rollback_ms": float(m.group("rollback_ms")),
        }

    round_indices = sorted(set(draft_rounds) & set(verify_rounds))
    raw_round_ms: list[float] = []
    for round_idx in round_indices:
        d = draft_rounds[round_idx]
        v = verify_rounds[round_idx]
        raw_round_ms.append(
            d["sync_ms"] + d["tail_ms"] + d["draft_ms"] + d["decision_ms"] + v["comm_ms"] + v["decode_ms"] + v["sample_ms"] + v["rollback_ms"]
        )
    scale = official_total_ms / sum(raw_round_ms)

    points: list[Point] = []
    cumulative_ms = 0.0
    cumulative_tokens = 0
    for round_idx, raw_ms in zip(round_indices, raw_round_ms):
        d = draft_rounds[round_idx]
        v = verify_rounds[round_idx]
        proposed = int(d["drafted"])
        accepted = int(v["accepted"])
        committed = accepted + 1
        round_ms = raw_ms * scale
        cumulative_ms += round_ms
        cumulative_tokens += committed
        points.append(
            Point(
                token_index=cumulative_tokens,
                proposed=proposed,
                committed=committed,
                accept_ratio=(accepted / proposed if proposed > 0 else 0.0),
                avg_tps=cumulative_tokens * 1000.0 / cumulative_ms,
                round_ms=round_ms,
            )
        )
    return points


def parse_android(app_output: Path) -> list[Point]:
    points: list[Point] = []
    cumulative_ms = 0.0
    cumulative_tokens = 0
    for line in app_output.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = ANDROID_STEP_RE.match(line.strip())
        if not m:
            continue
        proposed = int(m.group("proposed"))
        accepted = int(m.group("accepted"))
        corrections = int(m.group("corrections"))
        committed = accepted + corrections
        round_ms = float(m.group("draft_fetch_ms")) + float(m.group("remote_ms"))
        cumulative_ms += round_ms
        cumulative_tokens += committed
        points.append(
            Point(
                token_index=cumulative_tokens,
                proposed=proposed,
                committed=committed,
                accept_ratio=(accepted / proposed if proposed > 0 else 0.0),
                avg_tps=cumulative_tokens * 1000.0 / cumulative_ms,
                round_ms=round_ms,
            )
        )
    return points


def map_series(points: list[Point], left: int, top: int, plot_w: int, panel_h: int, max_tokens: int, max_y: float, field: str, smooth_window: int | None = None, percent: bool = False) -> list[tuple[float, float]]:
    values = [getattr(p, field) * (100.0 if percent else 1.0) for p in points]
    if smooth_window and smooth_window > 1:
        values = moving_average(values, smooth_window)
    coords: list[tuple[float, float]] = []
    for point, value in zip(points, values):
        x = left + point.token_index / max_tokens * plot_w
        y = top + panel_h - (value / max_y) * panel_h if max_y > 0 else top + panel_h
        coords.append((x, y))
    return coords


def polyline(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def render_svg(dual_points: list[Point], android_points: list[Point], output_path: Path) -> None:
    width = 1250
    height = 1180
    left = 90
    plot_w = 800
    panel_h = 190
    gap = 55
    tops = [60, 305, 550, 795]
    legend_x = 930
    max_tokens = max(dual_points[-1].token_index, android_points[-1].token_index)

    dual_color = "#2f6fdf"
    android_color = "#ef8a17"

    max_avg_tps = math.ceil(max(max(p.avg_tps for p in dual_points), max(p.avg_tps for p in android_points)) / 2.0) * 2.0
    max_proposed = max(max(p.proposed for p in dual_points), max(p.proposed for p in android_points))
    max_committed = max(max(p.committed for p in dual_points), max(p.committed for p in android_points))
    max_round_ms = math.ceil(max(max(p.round_ms for p in dual_points), max(p.round_ms for p in android_points)) / 100.0) * 100.0

    specs = [
        ("Average throughput (token/s)", "avg_tps", max_avg_tps, False, None),
        ("Proposed tokens per round/step (8-point avg)", "proposed", max_proposed, False, 8),
        ("Committed tokens per round/step (8-point avg)", "committed", max_committed, False, 8),
        ("Acceptance ratio (%) (8-point avg)", "accept_ratio", 100.0, True, 8),
    ]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif;fill:#1f2328}",
        ".axis{font-size:14px}",
        ".label{font-size:18px;font-weight:600}",
        ".sub{font-size:15px}",
        ".note{font-size:14px}",
        "</style>",
    ]

    for (title, field, max_y, percent, smooth_window), top in zip(specs, tops):
        parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{panel_h}" fill="#fbfcfe" stroke="#d0d7de"/>')
        parts.append(f'<text x="{left}" y="{top - 14}" class="sub">{title}</text>')
        tick_count = 4
        for idx in range(tick_count + 1):
            tick = max_y * idx / tick_count
            y = top + panel_h - idx * panel_h / tick_count
            parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>')
            label = f"{tick:.0f}" if max_y >= 10 else f"{tick:.1f}"
            parts.append(f'<text x="{left - 10}" y="{y + 5:.2f}" text-anchor="end" class="axis">{label}</text>')
        for idx in range(6):
            x = left + idx * plot_w / 5
            token = round(max_tokens * idx / 5)
            parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + panel_h}" stroke="#eef2f6" stroke-width="1"/>')
            if top == tops[-1]:
                parts.append(f'<text x="{x:.2f}" y="{top + panel_h + 26}" text-anchor="middle" class="axis">{token}</text>')
        parts.append(f'<line x1="{left}" y1="{top + panel_h}" x2="{left + plot_w}" y2="{top + panel_h}" stroke="#333" stroke-width="1.5"/>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + panel_h}" stroke="#333" stroke-width="1.5"/>')

        dual_series = map_series(dual_points, left, top, plot_w, panel_h, max_tokens, max_y, field, smooth_window, percent)
        android_series = map_series(android_points, left, top, plot_w, panel_h, max_tokens, max_y, field, smooth_window, percent)
        parts.append(f'<polyline fill="none" stroke="{dual_color}" stroke-width="3" points="{polyline(dual_series)}"/>')
        parts.append(f'<polyline fill="none" stroke="{android_color}" stroke-width="3" points="{polyline(android_series)}"/>')

    parts.append(f'<text x="{left + plot_w / 2:.2f}" y="{height - 36}" text-anchor="middle" class="label">Committed token index</text>')

    parts.append(f'<rect x="{legend_x - 18}" y="72" width="250" height="95" rx="12" fill="#f6f8fa" stroke="#d0d7de"/>')
    for idx, (color, text) in enumerate([(dual_color, "PC dual"), (android_color, "Android + PC")]):
        y = 100 + idx * 30
        parts.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 32}" y2="{y}" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<text x="{legend_x + 42}" y="{y + 5}" class="note">{text}</text>')

    dual_first = dual_points[:30]
    dual_last = dual_points[-30:]
    android_first = android_points[:30]
    android_last = android_points[-30:]
    parts.append(f'<rect x="{legend_x - 18}" y="200" width="285" height="250" rx="12" fill="#fffaf2" stroke="#e2c08d"/>')
    summary_lines = [
        f"PC dual proposed/round: {sum(p.proposed for p in dual_first)/len(dual_first):.2f} -> {sum(p.proposed for p in dual_last)/len(dual_last):.2f}",
        f"Android proposed/step: {sum(p.proposed for p in android_first)/len(android_first):.2f} -> {sum(p.proposed for p in android_last)/len(android_last):.2f}",
        f"PC dual committed/round: {sum(p.committed for p in dual_first)/len(dual_first):.2f} -> {sum(p.committed for p in dual_last)/len(dual_last):.2f}",
        f"Android committed/step: {sum(p.committed for p in android_first)/len(android_first):.2f} -> {sum(p.committed for p in android_last)/len(android_last):.2f}",
        f"PC dual accept ratio: {sum(p.accept_ratio for p in dual_first)/len(dual_first)*100:.1f}% -> {sum(p.accept_ratio for p in dual_last)/len(dual_last)*100:.1f}%",
        f"Android accept ratio: {sum(p.accept_ratio for p in android_first)/len(android_first)*100:.1f}% -> {sum(p.accept_ratio for p in android_last)/len(android_last)*100:.1f}%",
        f"PC dual avg round ms: {sum(p.round_ms for p in dual_points)/len(dual_points):.1f}",
        f"Android avg step ms: {sum(p.round_ms for p in android_points)/len(android_points):.1f}",
        f"PC dual final t/s: {dual_points[-1].avg_tps:.3f}",
        f"Android final t/s: {android_points[-1].avg_tps:.3f}",
    ]
    for idx, line in enumerate(summary_lines):
        parts.append(f'<text x="{legend_x}" y="{225 + idx * 22}" class="note">{line}</text>')

    parts.append(f'<rect x="{legend_x - 18}" y="480" width="285" height="165" rx="12" fill="#f8fbff" stroke="#bfd4f2"/>')
    notes = [
        "Why Android + PC slows down:",
        "1. Proposed tokens per step do not grow as much.",
        "2. Committed tokens per step remain lower.",
        "3. Acceptance ratio improves later, but too late.",
        "4. Step latency stays much higher overall.",
        "So slower speed is caused by both less speculative",
        "gain per step and larger end-to-end step cost.",
    ]
    for idx, line in enumerate(notes):
        parts.append(f'<text x="{legend_x}" y="{505 + idx * 22}" class="note">{line}</text>')

    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare PC dual and Android+PC diagnostics over committed token progress.")
    parser.add_argument("--dual-draft-log", required=True)
    parser.add_argument("--dual-verify-log", required=True)
    parser.add_argument("--dual-summary", required=True)
    parser.add_argument("--android-output", required=True)
    parser.add_argument("--output-svg", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    dual_summary = json.loads(Path(args.dual_summary).read_text(encoding="utf-8-sig"))
    dual_total_ms = float(dual_summary["nativeFull"]["wallSeconds"]) * 1000.0
    dual_points = parse_dual(Path(args.dual_draft_log), Path(args.dual_verify_log), dual_total_ms)
    android_points = parse_android(Path(args.android_output))

    render_svg(dual_points, android_points, Path(args.output_svg))

    dual_first = dual_points[:30]
    dual_last = dual_points[-30:]
    android_first = android_points[:30]
    android_last = android_points[-30:]
    result = {
        "pc_dual": {
            "final_tps": round(dual_points[-1].avg_tps, 3),
            "first30_avg_proposed": round(sum(p.proposed for p in dual_first) / len(dual_first), 3),
            "last30_avg_proposed": round(sum(p.proposed for p in dual_last) / len(dual_last), 3),
            "first30_avg_committed": round(sum(p.committed for p in dual_first) / len(dual_first), 3),
            "last30_avg_committed": round(sum(p.committed for p in dual_last) / len(dual_last), 3),
            "first30_avg_accept_ratio": round(sum(p.accept_ratio for p in dual_first) / len(dual_first), 3),
            "last30_avg_accept_ratio": round(sum(p.accept_ratio for p in dual_last) / len(dual_last), 3),
            "avg_round_ms": round(sum(p.round_ms for p in dual_points) / len(dual_points), 3),
        },
        "android_pc": {
            "final_tps": round(android_points[-1].avg_tps, 3),
            "first30_avg_proposed": round(sum(p.proposed for p in android_first) / len(android_first), 3),
            "last30_avg_proposed": round(sum(p.proposed for p in android_last) / len(android_last), 3),
            "first30_avg_committed": round(sum(p.committed for p in android_first) / len(android_first), 3),
            "last30_avg_committed": round(sum(p.committed for p in android_last) / len(android_last), 3),
            "first30_avg_accept_ratio": round(sum(p.accept_ratio for p in android_first) / len(android_first), 3),
            "last30_avg_accept_ratio": round(sum(p.accept_ratio for p in android_last) / len(android_last), 3),
            "avg_round_ms": round(sum(p.round_ms for p in android_points) / len(android_points), 3),
        },
    }
    Path(args.output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

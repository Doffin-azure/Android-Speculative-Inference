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


@dataclass
class RoundPoint:
    round_idx: int
    token_index: int
    drafted: int
    accepted: int
    accept_ratio: float
    avg_tps: float
    draft_ms: float
    draft_tps: float


def parse_rounds(draft_log_path: Path, verify_log_path: Path, official_total_ms: float) -> list[RoundPoint]:
    draft_rounds: dict[int, dict[str, float]] = {}
    verify_rounds: dict[int, dict[str, float]] = {}

    for line in draft_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = DUAL_DRAFT_RE.search(line)
        if not match:
            continue
        round_idx = int(match.group("round"))
        draft_rounds[round_idx] = {
            "drafted": float(match.group("drafted")),
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
            "accepted": float(match.group("accept")),
            "comm_ms": float(match.group("comm_ms")),
            "decode_ms": float(match.group("decode_ms")),
            "sample_ms": float(match.group("sample_ms")),
            "rollback_ms": float(match.group("rollback_ms")),
        }

    round_indices = sorted(set(draft_rounds) & set(verify_rounds))
    raw_elapsed: list[float] = []
    raw_tokens: list[int] = []
    for round_idx in round_indices:
        d = draft_rounds[round_idx]
        v = verify_rounds[round_idx]
        raw_elapsed.append(
            d["sync_ms"] + d["tail_ms"] + d["draft_ms"] + d["decision_ms"] + v["comm_ms"] + v["decode_ms"] + v["sample_ms"] + v["rollback_ms"]
        )
        raw_tokens.append(int(v["accepted"]) + 1)

    scale = official_total_ms / sum(raw_elapsed)

    points: list[RoundPoint] = []
    cumulative_ms = 0.0
    cumulative_tokens = 0
    for round_idx, round_ms, committed in zip(round_indices, raw_elapsed, raw_tokens):
        d = draft_rounds[round_idx]
        v = verify_rounds[round_idx]
        cumulative_ms += round_ms * scale
        cumulative_tokens += committed
        drafted = int(d["drafted"])
        accepted = int(v["accepted"])
        points.append(
            RoundPoint(
                round_idx=round_idx,
                token_index=cumulative_tokens,
                drafted=drafted,
                accepted=accepted,
                accept_ratio=(accepted / drafted if drafted > 0 else 0.0),
                avg_tps=cumulative_tokens * 1000.0 / cumulative_ms,
                draft_ms=d["draft_ms"],
                draft_tps=(drafted * 1000.0 / d["draft_ms"] if d["draft_ms"] > 0 else 0.0),
            )
        )
    return points


def polyline(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def moving_average(values: list[float], window: int) -> list[float]:
    result: list[float] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        chunk = values[start : idx + 1]
        result.append(sum(chunk) / len(chunk))
    return result


def render_svg(points: list[RoundPoint], output_path: Path) -> None:
    width = 1180
    height = 930
    left = 90
    right = 1080
    plot_w = 760
    panel_h = 210
    gap = 55
    top1 = 60
    top2 = top1 + panel_h + gap
    top3 = top2 + panel_h + gap
    legend_x = 885

    max_tokens = points[-1].token_index
    max_avg_tps = math.ceil(max(p.avg_tps for p in points) / 2.0) * 2.0
    max_round_tokens = max(p.drafted for p in points)
    x_ticks = 5

    avg_series = [(left + p.token_index / max_tokens * plot_w, top1 + panel_h - p.avg_tps / max_avg_tps * panel_h) for p in points]
    drafted_series = [(left + p.token_index / max_tokens * plot_w, top2 + panel_h - p.drafted / max_round_tokens * panel_h) for p in points]
    accepted_series = [(left + p.token_index / max_tokens * plot_w, top2 + panel_h - p.accepted / max_round_tokens * panel_h) for p in points]
    accept_ratio_smoothed = moving_average([p.accept_ratio * 100.0 for p in points], 8)
    ratio_series = [(left + p.token_index / max_tokens * plot_w, top3 + panel_h - accept_ratio_smoothed[idx] / 100.0 * panel_h) for idx, p in enumerate(points)]

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

    panel_specs = [
        (top1, "Average throughput (token/s)", max_avg_tps, [0, max_avg_tps / 3, 2 * max_avg_tps / 3, max_avg_tps]),
        (top2, "Tokens per round", max_round_tokens, [0, max_round_tokens / 4, max_round_tokens / 2, 3 * max_round_tokens / 4, max_round_tokens]),
        (top3, "Acceptance ratio (%)", 100.0, [0, 25, 50, 75, 100]),
    ]

    for top, title, max_value, ticks in panel_specs:
        parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{panel_h}" fill="#fbfcfe" stroke="#d0d7de"/>')
        parts.append(f'<text x="{left}" y="{top - 14}" class="sub">{title}</text>')
        for tick in ticks:
            y = top + panel_h - tick / max_value * panel_h if max_value > 0 else top + panel_h
            parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>')
            label = f"{tick:.0f}" if abs(tick - round(tick)) < 1e-9 else f"{tick:.1f}"
            parts.append(f'<text x="{left - 10}" y="{y + 5:.2f}" text-anchor="end" class="axis">{label}</text>')
        for idx in range(x_ticks + 1):
            x = left + idx * plot_w / x_ticks
            token = round(max_tokens * idx / x_ticks)
            parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + panel_h}" stroke="#eef2f6" stroke-width="1"/>')
            if top == top3:
                parts.append(f'<text x="{x:.2f}" y="{top + panel_h + 26}" text-anchor="middle" class="axis">{token}</text>')
        parts.append(f'<line x1="{left}" y1="{top + panel_h}" x2="{left + plot_w}" y2="{top + panel_h}" stroke="#333" stroke-width="1.5"/>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + panel_h}" stroke="#333" stroke-width="1.5"/>')

    parts.append(f'<text x="{left + plot_w / 2:.2f}" y="{height - 34}" text-anchor="middle" class="label">Committed token index</text>')

    parts.append(f'<polyline fill="none" stroke="#2f6fdf" stroke-width="3" points="{polyline(avg_series)}"/>')
    parts.append(f'<polyline fill="none" stroke="#ef8a17" stroke-width="2.5" points="{polyline(drafted_series)}"/>')
    parts.append(f'<polyline fill="none" stroke="#2aa876" stroke-width="2.5" points="{polyline(accepted_series)}"/>')
    parts.append(f'<polyline fill="none" stroke="#c0392b" stroke-width="3" points="{polyline(ratio_series)}"/>')

    legend_y = 92
    parts.append(f'<rect x="{legend_x - 18}" y="{legend_y - 26}" width="220" height="150" rx="12" fill="#f6f8fa" stroke="#d0d7de"/>')
    legend_items = [
        ("#2f6fdf", "Average throughput"),
        ("#ef8a17", "Drafted tokens / round"),
        ("#2aa876", "Accepted tokens / round"),
        ("#c0392b", "Acceptance ratio (8-round avg)"),
    ]
    for idx, (color, text) in enumerate(legend_items):
        y = legend_y + idx * 28
        parts.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 28}" y2="{y}" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<text x="{legend_x + 38}" y="{y + 5}" class="note">{text}</text>')

    summary_y = 270
    parts.append(f'<rect x="{legend_x - 18}" y="{summary_y - 18}" width="240" height="190" rx="12" fill="#fffaf2" stroke="#e2c08d"/>')
    first50 = points[:50]
    last50 = points[-50:]
    summary_lines = [
        f"avg throughput final: {points[-1].avg_tps:.3f} t/s",
        f"drafted/round first50 -> last50: {sum(p.drafted for p in first50)/len(first50):.2f} -> {sum(p.drafted for p in last50)/len(last50):.2f}",
        f"accept ratio first50 -> last50: {sum(p.accept_ratio for p in first50)/len(first50)*100:.1f}% -> {sum(p.accept_ratio for p in last50)/len(last50)*100:.1f}%",
        f"draft t/s first50 -> last50: {sum(p.draft_tps for p in first50)/len(first50):.1f} -> {sum(p.draft_tps for p in last50)/len(last50):.1f}",
        "note: raw draft t/s is inflated in 1-token rounds",
        "because many rounds skip looped drafting and",
        "only execute a tiny tail step.",
    ]
    for idx, line in enumerate(summary_lines):
        parts.append(f'<text x="{legend_x}" y="{summary_y + idx * 22}" class="note">{line}</text>')

    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot dual-process diagnostics: average throughput, drafted tokens per round, and acceptance ratio.")
    parser.add_argument("--dual-draft-log", required=True)
    parser.add_argument("--dual-verify-log", required=True)
    parser.add_argument("--dual-summary", required=True)
    parser.add_argument("--output-svg", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    summary = json.loads(Path(args.dual_summary).read_text(encoding="utf-8-sig"))
    official_total_ms = float(summary["nativeFull"]["wallSeconds"]) * 1000.0
    points = parse_rounds(Path(args.dual_draft_log), Path(args.dual_verify_log), official_total_ms)
    render_svg(points, Path(args.output_svg))

    first50 = points[:50]
    last50 = points[-50:]
    result = {
        "final_avg_tps": round(points[-1].avg_tps, 3),
        "first50_avg_drafted": round(sum(p.drafted for p in first50) / len(first50), 3),
        "last50_avg_drafted": round(sum(p.drafted for p in last50) / len(last50), 3),
        "first50_avg_accept_ratio": round(sum(p.accept_ratio for p in first50) / len(first50), 3),
        "last50_avg_accept_ratio": round(sum(p.accept_ratio for p in last50) / len(last50), 3),
        "first50_avg_draft_tps": round(sum(p.draft_tps for p in first50) / len(first50), 3),
        "last50_avg_draft_tps": round(sum(p.draft_tps for p in last50) / len(last50), 3),
    }
    Path(args.output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

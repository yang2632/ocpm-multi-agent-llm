#!/usr/bin/env python3
"""Scan multi-agent runs for candidate failure themes.

One-off helper used to seed the inductive thematic analysis behind §4.4.
Loads results/runs/all_results.json, filters to the 36 multi-agent runs,
computes per-run signals (tool calls, tool errors, empty subtasks,
self-acknowledged limitations, latency, short final answers), and surfaces
three candidate themes with illustrative examples.

Output is human-readable text saved to results/analysis/failure_patterns_scan.txt.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from src.config import runs_dir, analysis_dir  # noqa: E402

RESULTS_FILE = runs_dir() / "all_results.json"
OUTPUT_FILE = analysis_dir() / "failure_patterns_scan.txt"


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

LIMITATION_PATTERNS = [
    r"\bno results?\b",
    r"\bundefined\b",
    r"\bcould not\b",
    r"\bcouldn'?t\b",
    r"\bfailed\b",
    r"\bunable\b",
    r"\bnot able\b",
    r"\bcannot\b",
    r"\bcan'?t\b",
    r"\binsufficient\b",
    r"\bnot available\b",
    r"\bno data\b",
]
LIMITATION_RE = re.compile("|".join(LIMITATION_PATTERNS), re.IGNORECASE)

TOOL_ERROR_KEYS = ("error", "exception", "traceback", "failed", "not found")
SHORT_ANSWER_THRESHOLD = 200  # chars


# ---------------------------------------------------------------------------
# Per-run signals
# ---------------------------------------------------------------------------

def _is_empty_finding(finding) -> bool:
    """A subtask is considered empty/failed if its finding is missing or trivial."""
    if finding is None:
        return True
    text = finding if isinstance(finding, str) else json.dumps(finding)
    if not text or not text.strip():
        return True
    if len(text.strip()) < 30:
        return True
    lowered = text.lower()
    failure_markers = (
        "no result", "no data", "could not", "unable", "failed",
        "not available", "undefined", "exception", "error:",
    )
    return any(m in lowered for m in failure_markers)


def _is_tool_error(tool_call) -> bool:
    preview = tool_call.get("result_preview")
    if preview is None or preview == "":
        return True
    text = preview if isinstance(preview, str) else json.dumps(preview)
    if not text.strip():
        return True
    lowered = text.lower()
    # Empty-result envelopes and explicit error envelopes
    if any(k in lowered for k in TOOL_ERROR_KEYS):
        # Avoid false positives on the literal word "error" inside a successful payload:
        # require it near the start or as a key.
        if '"error"' in lowered or "'error'" in lowered or lowered.startswith("error"):
            return True
        if "traceback" in lowered or "exception" in lowered:
            return True
        if "failed" in lowered[:200] or "not found" in lowered[:200]:
            return True
    # Heuristic: very short or empty-looking JSON arrays/objects suggest no data.
    stripped = text.strip()
    if stripped in {"[]", "{}", "null", '""'}:
        return True
    return False


def compute_signals(run: dict) -> dict:
    tool_calls = run.get("tool_calls") or []
    subtasks = run.get("subtask_results") or []
    final_answer = run.get("final_answer") or ""

    tool_total = len(tool_calls)
    tool_errors = sum(1 for tc in tool_calls if _is_tool_error(tc))
    tool_error_rate = (tool_errors / tool_total) if tool_total else 0.0

    subtask_count = len(subtasks)
    empty_subtasks = sum(1 for st in subtasks if _is_empty_finding(st.get("finding")))

    limitation_hits = len(LIMITATION_RE.findall(final_answer))
    short_answer = len(final_answer) < SHORT_ANSWER_THRESHOLD

    return {
        "task_id": run.get("task_id"),
        "run_index": run.get("run_index"),
        "category": run.get("category"),
        "tool_total": tool_total,
        "tool_errors": tool_errors,
        "tool_error_rate": tool_error_rate,
        "subtask_count": subtask_count,
        "empty_subtasks": empty_subtasks,
        "final_answer_len": len(final_answer),
        "short_answer": short_answer,
        "limitation_hits": limitation_hits,
        "latency_s": run.get("latency_s") or 0.0,
        "timed_out": bool(run.get("timed_out")),
        "error": run.get("error"),
    }


def run_id(s: dict) -> str:
    return f"{s['task_id']}_run{s['run_index']}"


# ---------------------------------------------------------------------------
# Aggregate + theme detection
# ---------------------------------------------------------------------------

def aggregate_stats(signals: list[dict]) -> dict:
    arr = lambda key: np.array([s[key] for s in signals], dtype=float)
    return {
        "n_runs": len(signals),
        "tool_total_mean": float(arr("tool_total").mean()),
        "tool_total_median": float(np.median(arr("tool_total"))),
        "tool_errors_mean": float(arr("tool_errors").mean()),
        "tool_error_rate_mean": float(arr("tool_error_rate").mean()),
        "empty_subtasks_mean": float(arr("empty_subtasks").mean()),
        "empty_subtasks_total": int(arr("empty_subtasks").sum()),
        "limitation_hits_mean": float(arr("limitation_hits").mean()),
        "limitation_hits_runs_with_any": int(sum(1 for s in signals if s["limitation_hits"] > 0)),
        "short_answer_runs": int(sum(1 for s in signals if s["short_answer"])),
        "latency_mean": float(arr("latency_s").mean()),
        "latency_median": float(np.median(arr("latency_s"))),
        "timed_out_runs": int(sum(1 for s in signals if s["timed_out"])),
    }


def theme_a_tool_overhead(signals: list[dict]) -> list[dict]:
    """Tool exploration overhead.

    The original spec required >=50% empty/error tool calls, but in this dataset
    explicit tool errors are rare (mean 1.8%). The dominant overhead pattern is
    instead extreme tool-call volume relative to the number of subtasks. We
    flag runs in the top quartile of tool calls per subtask (>=20) with at
    least one tool error or empty subtask, indicating wasted exploration.
    """
    candidates = []
    for s in signals:
        if s["subtask_count"] == 0:
            continue
        calls_per_subtask = s["tool_total"] / s["subtask_count"]
        if calls_per_subtask >= 20 and (s["tool_errors"] >= 1 or s["empty_subtasks"] >= 1):
            s_copy = dict(s)
            s_copy["calls_per_subtask"] = calls_per_subtask
            candidates.append(s_copy)
    candidates.sort(
        key=lambda s: (s["calls_per_subtask"], s["tool_total"]),
        reverse=True,
    )
    return candidates


def theme_b_partial_synthesis(signals: list[dict]) -> list[dict]:
    """At least one empty/failed subtask but final answer is non-trivial
    (no self-acknowledgement, length above the short-answer threshold)."""
    matched = [
        s for s in signals
        if s["empty_subtasks"] >= 1
        and not s["short_answer"]
        and s["limitation_hits"] == 0
    ]
    matched.sort(
        key=lambda s: (s["empty_subtasks"], s["final_answer_len"]),
        reverse=True,
    )
    return matched


def theme_c_self_acknowledged(signals: list[dict]) -> list[dict]:
    """Final answer mentions a limitation marker at least once."""
    matched = [s for s in signals if s["limitation_hits"] >= 1]
    matched.sort(key=lambda s: s["limitation_hits"], reverse=True)
    return matched


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt_run_row(s: dict) -> str:
    return (
        f"  - {run_id(s)} (cat {s['category']})"
        f"  tools={s['tool_total']:>3} errs={s['tool_errors']:>3}"
        f" ({s['tool_error_rate']*100:>5.1f}%)"
        f"  subtasks={s['subtask_count']} empty={s['empty_subtasks']}"
        f"  limhits={s['limitation_hits']}"
        f"  ans_len={s['final_answer_len']:>5}"
        f"  lat={s['latency_s']:>6.1f}s"
    )


def render_report(signals: list[dict]) -> str:
    agg = aggregate_stats(signals)
    theme_a = theme_a_tool_overhead(signals)
    theme_b = theme_b_partial_synthesis(signals)
    theme_c = theme_c_self_acknowledged(signals)

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Multi-agent failure pattern scan (36 runs)")
    lines.append("=" * 78)
    lines.append("")
    lines.append("Source : results/runs/all_results.json")
    lines.append("Filter : mode == 'multi_agent'")
    lines.append("")
    lines.append("-" * 78)
    lines.append("Aggregate statistics")
    lines.append("-" * 78)
    lines.append(f"  n_runs                       : {agg['n_runs']}")
    lines.append(f"  tool calls       mean/median : "
                 f"{agg['tool_total_mean']:.2f} / {agg['tool_total_median']:.1f}")
    lines.append(f"  tool errors      mean        : {agg['tool_errors_mean']:.2f}")
    lines.append(f"  tool error rate  mean        : "
                 f"{agg['tool_error_rate_mean']*100:.1f}%")
    lines.append(f"  empty subtasks   mean / total: "
                 f"{agg['empty_subtasks_mean']:.2f} / {agg['empty_subtasks_total']}")
    lines.append(f"  limitation hits  mean        : "
                 f"{agg['limitation_hits_mean']:.2f}")
    lines.append(f"  runs with >=1 limitation hit : "
                 f"{agg['limitation_hits_runs_with_any']}")
    lines.append(f"  runs with short final answer : "
                 f"{agg['short_answer_runs']}  (< {SHORT_ANSWER_THRESHOLD} chars)")
    lines.append(f"  latency (s)      mean/median : "
                 f"{agg['latency_mean']:.1f} / {agg['latency_median']:.1f}")
    lines.append(f"  timed_out runs               : {agg['timed_out_runs']}")
    lines.append("")

    # Per-run table
    lines.append("-" * 78)
    lines.append("Per-run signals")
    lines.append("-" * 78)
    header = (
        "  run_id          cat  tools  errs   err%  st  empty  lim  ans_len  lat(s)"
    )
    lines.append(header)
    for s in sorted(signals, key=lambda r: (r["category"], r["task_id"], r["run_index"])):
        lines.append(
            f"  {run_id(s):<14} {s['category']:>3}  "
            f"{s['tool_total']:>5}  {s['tool_errors']:>4}  "
            f"{s['tool_error_rate']*100:>5.1f}  "
            f"{s['subtask_count']:>2}  {s['empty_subtasks']:>5}  "
            f"{s['limitation_hits']:>3}  {s['final_answer_len']:>7}  "
            f"{s['latency_s']:>6.1f}"
        )
    lines.append("")

    # ----- Theme A
    lines.append("=" * 78)
    lines.append("Theme A — Tool exploration overhead")
    lines.append("=" * 78)
    lines.append(
        "  Definition: tool_calls / subtask_count >= 20 AND (>=1 tool error OR "
        ">=1 empty subtask).\n"
        "  Interpretation: the agent fires many tool calls per subtask (top of "
        "the distribution) yet still leaves subtasks empty or hits tool errors "
        "— exploration without payoff."
    )
    lines.append(f"  Match count: {len(theme_a)}")
    lines.append("  Top 5 offenders:")
    for s in theme_a[:5]:
        lines.append(_fmt_run_row(s) + f"  cps={s['calls_per_subtask']:.1f}")
    if theme_a:
        ex = theme_a[0]
        lines.append("")
        lines.append(
            f"  Illustrative example: {run_id(ex)} — "
            f"{ex['tool_total']} tool calls across {ex['subtask_count']} subtasks "
            f"({ex['calls_per_subtask']:.1f} per subtask) with "
            f"{ex['empty_subtasks']} empty subtasks and {ex['tool_errors']} tool "
            f"errors."
        )
    lines.append("")

    # ----- Theme B
    lines.append("=" * 78)
    lines.append("Theme B — Synthesis under partial data")
    lines.append("=" * 78)
    lines.append(
        "  Definition: >=1 empty/failed subtask AND final answer is non-trivial "
        f"(>= {SHORT_ANSWER_THRESHOLD} chars)\n"
        "  AND the final answer contains no self-acknowledged limitation.\n"
        "  Interpretation: the agent produces confident-sounding output despite "
        "missing intermediate findings."
    )
    lines.append(f"  Match count: {len(theme_b)}")
    lines.append("  Top 5 offenders:")
    for s in theme_b[:5]:
        lines.append(_fmt_run_row(s))
    if theme_b:
        ex = theme_b[0]
        lines.append("")
        lines.append(
            f"  Illustrative example: {run_id(ex)} — "
            f"{ex['empty_subtasks']}/{ex['subtask_count']} subtasks empty yet "
            f"the final answer is {ex['final_answer_len']} chars with zero "
            f"limitation markers."
        )
    lines.append("")

    # ----- Theme C
    lines.append("=" * 78)
    lines.append("Theme C — Self-acknowledged limitations")
    lines.append("=" * 78)
    lines.append(
        "  Definition: final answer contains >=1 limitation marker (\"no result\","
        " \"unable\", \"could not\", ...).\n"
        "  Interpretation: GOOD agent behaviour — the assistant flags what it "
        "cannot answer instead of fabricating."
    )
    lines.append(f"  Match count: {len(theme_c)}")
    lines.append("  Top 5 offenders:")
    for s in theme_c[:5]:
        lines.append(_fmt_run_row(s))
    if theme_c:
        ex = theme_c[0]
        lines.append("")
        lines.append(
            f"  Illustrative example: {run_id(ex)} — "
            f"final answer flags the gap {ex['limitation_hits']} times across "
            f"{ex['final_answer_len']} chars."
        )
    lines.append("")

    lines.append("=" * 78)
    lines.append("End of scan")
    lines.append("=" * 78)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    with RESULTS_FILE.open() as f:
        runs = json.load(f)

    multi_agent = [r for r in runs if r.get("mode") == "multi_agent"]
    if len(multi_agent) != 36:
        print(f"WARNING: expected 36 multi_agent runs, found {len(multi_agent)}")

    signals = [compute_signals(r) for r in multi_agent]
    report = render_report(signals)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(report)

    print(report)
    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

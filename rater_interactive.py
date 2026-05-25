#!/usr/bin/env python3
"""Independent non-expert rater TUI.

Shows minimal information per item — no mode label (single_agent/multi_agent),
no LLM suggestions, no prior author scores. The rater scores 4 structural
dimensions only (Factual Alignment is omitted because it requires OCPM
domain expertise — that dimension is author-only).

Sample: 18 items (6 A + 6 B + 6 C), drawn with seed=99 stratified random.
This is intentionally distinct from `audit.py`'s seed=42 sample.

Output: results/scores/rater_scores.csv (auto-saved after each item).
Resume-safe: re-run anytime; already-scored blind_ids are skipped.

Usage:
    python3 rater_interactive.py
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path
from typing import Any

# Reuse helpers from the main scoring script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_interactive import (  # noqa: E402
    BOLD,
    B,
    DIM,
    G,
    R,
    RESET,
    Y,
    GROUND_TRUTH,
    GROUND_TRUTH_ZH,
    QUESTION_ZH,
    load_blind_items,
    load_translations,
    prompt_int,
)

PROJECT = Path(__file__).resolve().parent
from src.config import scores_dir  # noqa: E402  (sys.path set above)

RATER_CSV = scores_dir() / "rater_scores.csv"
RATER_SEED = 99
SAMPLE_PER_CATEGORY: dict[str, int] = {"A": 6, "B": 6, "C": 6}  # 18 total

# NOTE: 'mode' and 'run_index' are deliberately excluded — including them
# would un-blind the rater to the architecture under evaluation.
RATER_FIELDS = [
    "blind_id",
    "task_id",
    "category",
    "correctness",
    "analytical_depth",
    "evidence_grounding",
    "traceability",
]


def select_rater_sample(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stratified random sample: 6 from each of A, B, C (seed=99)."""
    rnd = random.Random(RATER_SEED)
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in items:
        by_cat.setdefault(r["category"], []).append(r)
    sample: list[dict[str, Any]] = []
    for cat, n in SAMPLE_PER_CATEGORY.items():
        sample.extend(rnd.sample(by_cat[cat], n))
    rnd.shuffle(sample)
    return sample


def display_rater_card(r: dict[str, Any], tr: dict[str, Any] | None) -> None:
    """Minimal display for the rater.

    DELIBERATELY HIDDEN: mode (single_agent/multi_agent), run_index, latency,
    LLM suggestions, prior author scores, plan/subtask findings detail.
    SHOWN: blind_id, task_id, category, question (EN+ZH), ground truth (Cat A
    only), Chinese-translated agent answer, tool call count, subtask count.
    """
    bar = "=" * 76
    print(f"\n{BOLD}{B}{bar}{RESET}")
    n_tools = len(r.get("tool_calls", []))
    n_subs = len(r.get("subtask_results", []))
    sub_part = f"  {n_subs} subtasks" if n_subs else ""
    # NOTE: do NOT print r['mode'] or r['run_index'] — that would un-blind
    # the rater. Only blind_id, task_id, and category are surfaced.
    print(
        f"{BOLD}ITEM {r['_blind_id']}{RESET}  "
        f"({r['task_id']}, Cat {r['category']})  "
        f"{n_tools} tool calls{sub_part}"
    )
    print(f"{B}{bar}{RESET}")

    # Question (EN + ZH)
    print(f"Q: {r.get('question', '')}")
    zh_q = QUESTION_ZH.get(r["task_id"])
    if zh_q:
        print(f"   {DIM}{zh_q}{RESET}")

    # Ground truth — only for Category A (closed-form questions)
    if r["category"] == "A":
        print(f"\nGround truth: {GROUND_TRUTH.get(r['task_id'], '?')}")
        print(f"   {DIM}{GROUND_TRUTH_ZH.get(r['task_id'], '')}{RESET}")

    # Agent answer in Chinese (fall back to EN if no translation)
    answer_zh = ((tr or {}).get("final_answer_zh") or "").strip()
    print(f"\n{BOLD}-- Agent answer (Chinese) --{RESET}")
    if answer_zh:
        print(answer_zh)
    else:
        print(f"{DIM}(no Chinese translation; English follows){RESET}")
        print((r.get("final_answer") or "")[:2000])
    print()


def score_one(
    r: dict[str, Any], row: dict[str, str]
) -> dict[str, str] | str | None:
    """Prompt for the rater's scores.

    Cat A: Correctness (0-2) + Traceability (0-2).
    Cat B/C: Analytical Depth (1-10) + Evidence Grounding (1-10) + Traceability (0-2).
    Factual Alignment is INTENTIONALLY OMITTED (author-only).
    """
    cat = r["category"]
    print(f"\n{BOLD}--- Score (rubric only) ---{RESET}")
    if cat == "A":
        c = prompt_int("Correctness (0-2)", 0, 2)
        if c is None or c == "SKIP":
            return c
        t = prompt_int("Traceability (0-2)", 0, 2)
        if t is None or t == "SKIP":
            return t
        row["correctness"] = str(c)
        row["traceability"] = str(t)
        return row

    # Category B/C: structural dimensions only — NO Factual Alignment
    ad = prompt_int("Analytical Depth (1-10)", 1, 10)
    if ad is None or ad == "SKIP":
        return ad
    eg = prompt_int("Evidence Grounding (1-10)", 1, 10)
    if eg is None or eg == "SKIP":
        return eg
    tt = prompt_int("Traceability (0-2)", 0, 2)
    if tt is None or tt == "SKIP":
        return tt
    row["analytical_depth"] = str(ad)
    row["evidence_grounding"] = str(eg)
    row["traceability"] = str(tt)
    return row


def make_empty(r: dict[str, Any]) -> dict[str, str]:
    """Empty CSV row for a sampled item. Note: NO mode, NO run_index."""
    return {
        "blind_id": r["_blind_id"],
        "task_id": r["task_id"],
        "category": r["category"],
        "correctness": "",
        "analytical_depth": "",
        "evidence_grounding": "",
        "traceability": "",
    }


def is_scored(row: dict[str, str]) -> bool:
    """A row is complete when its required dimensions are all filled."""
    if row["category"] == "A":
        return row["correctness"] != "" and row["traceability"] != ""
    return all(
        row[k] != ""
        for k in ("analytical_depth", "evidence_grounding", "traceability")
    )


def load_existing() -> dict[str, dict[str, str]]:
    if not RATER_CSV.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with RATER_CSV.open() as f:
        for row in csv.DictReader(f):
            rows[row["blind_id"]] = row
    return rows


def save_all(rows: dict[str, dict[str, str]]) -> None:
    RATER_CSV.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(rows.values(), key=lambda r: r["blind_id"])
    with RATER_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RATER_FIELDS)
        w.writeheader()
        w.writerows(sorted_rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.parse_args()

    items = load_blind_items()
    sample = select_rater_sample(items)
    sample.sort(key=lambda r: r["_blind_id"])
    translations = load_translations()
    rows = load_existing()

    for r in sample:
        rows.setdefault(r["_blind_id"], make_empty(r))

    todo = [r for r in sample if not is_scored(rows[r["_blind_id"]])]

    if not todo:
        print(f"{G}All 18 items scored. Thank you!{RESET}")
        save_all(rows)
        return

    print(f"\n{BOLD}{B}=== Independent rater mode ==={RESET}")
    print(
        f"{Y}You will see {len(todo)} item(s). "
        f"Score each one using the rubric.{RESET}"
    )
    print(
        f"{DIM}Commands during entry: integer = score, "
        f"'s' = skip current item, 'q' = quit and save{RESET}\n"
    )

    n = 0
    for r in todo:
        display_rater_card(r, translations.get(r["_blind_id"]))
        result = score_one(r, rows[r["_blind_id"]])
        if result is None:
            save_all(rows)
            print(
                f"{Y}Saved progress. "
                f"Re-run `python3 rater_interactive.py` to continue.{RESET}"
            )
            return
        if result == "SKIP":
            print(f"{Y}-> Skipped{RESET}")
            continue
        save_all(rows)
        n += 1
        print(f"{G}-> Saved ({n}/{len(todo)}){RESET}")

    save_all(rows)
    total = sum(1 for r in rows.values() if is_scored(r))
    print(
        f"\n{G}Done. {n} item(s) scored this session. "
        f"Total complete: {total}/18{RESET}"
    )


if __name__ == "__main__":
    main()

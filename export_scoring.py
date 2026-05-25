#!/usr/bin/env python3
"""Export evaluation answers to readable scoring sheet + CSV template."""

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.config import runs_dir, scores_dir  # noqa: E402


def main():
    results = json.loads(
        (runs_dir() / "all_results.json").read_text(encoding="utf-8")
    )

    out = scores_dir()
    out.mkdir(parents=True, exist_ok=True)

    # Randomize for blind scoring (reproducible seed)
    all_items = list(results)
    random.seed(42)
    random.shuffle(all_items)

    # Assign blind IDs
    for i, r in enumerate(all_items):
        r["_blind_id"] = f"ITEM-{i+1:03d}"

    lines = []
    lines.append("# Evaluation Answers for Scoring\n")
    lines.append("## Scoring Rubric\n")
    lines.append("### Category A (Closed Tasks — Ground Truth)")
    lines.append("- **Correctness**: 0 = incorrect/missing, 1 = partially correct (right direction but imprecise), 2 = correct")
    lines.append("- **Traceability**: 0 = no intermediate steps visible, 1 = some steps traceable, 2 = all claims linked to tool outputs\n")
    lines.append("### Category B/C (Open Tasks — Rubric)")
    lines.append("- **Factual Alignment** (1-10): Is the answer consistent with the data evidence?")
    lines.append("- **Analytical Depth** (1-10): Does it go beyond surface description to structured reasoning?")
    lines.append("- **Evidence Grounding** (1-10): Does it reference specific computed values or tool outputs?")
    lines.append("- **Traceability** (0/1/2): Same as Category A\n")
    lines.append("### Ground Truth Reference (Category A)")
    lines.append("- **A1**: Highest median sojourn for Application = `A_Complete` (861,382s)")
    lines.append("- **A2**: Top 3 frequency activities for Offer, then compare waiting times")
    lines.append("- **A3**: Activity with highest sync time between Application + Offer")
    lines.append("- **A4**: Pooling time at first convergence activity for Application + Offer\n")
    lines.append("---\n")

    csv_rows = []

    for r in all_items:
        blind_id = r["_blind_id"]
        task_id = r["task_id"]
        category = r["category"]
        question = r.get("question", "")
        answer = r.get("final_answer", "(no answer)")
        tool_calls = r.get("tool_calls", [])
        latency = r.get("latency_s", 0)
        plan = r.get("plan", [])

        lines.append(f"## {blind_id}")
        lines.append(
            f"**Task**: {task_id} (Category {category}) | "
            f"**Run**: {r['run_index']+1}/3 | "
            f"**Latency**: {latency:.1f}s | "
            f"**Tool Calls**: {len(tool_calls)}\n"
        )
        lines.append(f"**Question**: {question}\n")

        # Show plan if multi-agent
        if plan:
            lines.append("**Plan (subtasks)**:")
            for p in plan:
                lines.append(f"  {p.get('id', '?')}. {p.get('description', '')}")
            lines.append("")

        # Tool calls summary
        if tool_calls:
            lines.append("**Tool Calls** (first 10):")
            for tc in tool_calls[:10]:
                tool_name = tc.get("tool", "?")
                args = tc.get("args", {})
                args_short = json.dumps(args)
                if len(args_short) > 80:
                    args_short = args_short[:80] + "..."
                lines.append(f"  - {tool_name}({args_short})")
            if len(tool_calls) > 10:
                lines.append(f"  - ... +{len(tool_calls)-10} more")
            lines.append("")

        # Subtask results if multi-agent
        subtask_results = r.get("subtask_results", [])
        if subtask_results:
            lines.append("**Intermediate Results** (first 3):")
            for sr in subtask_results[:3]:
                finding_short = sr.get("finding", "")[:200]
                lines.append(f"  - Subtask {sr.get('subtask_id','?')}: {finding_short}...")
            if len(subtask_results) > 3:
                lines.append(f"  - ... +{len(subtask_results)-3} more")
            lines.append("")

        lines.append("**Answer**:\n")
        lines.append(answer)
        lines.append("")

        # Scoring table
        if category == "A":
            lines.append(f"| {blind_id} Scoring | Value |")
            lines.append("|---|---|")
            lines.append("| Correctness (0/1/2) | |")
            lines.append("| Traceability (0/1/2) | |")
        else:
            lines.append(f"| {blind_id} Scoring | Value |")
            lines.append("|---|---|")
            lines.append("| Factual Alignment (1-10) | |")
            lines.append("| Analytical Depth (1-10) | |")
            lines.append("| Evidence Grounding (1-10) | |")
            lines.append("| Traceability (0/1/2) | |")

        lines.append("")
        lines.append("---\n")

        csv_rows.append({
            "blind_id": blind_id,
            "task_id": task_id,
            "category": category,
            "mode": r["mode"],
            "run_index": r["run_index"],
            "correctness": "",
            "factual_alignment": "",
            "analytical_depth": "",
            "evidence_grounding": "",
            "traceability": "",
        })

    # Write markdown
    md_path = out / "scoring_sheet.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Write CSV template
    csv_path = out / "scores_template.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "blind_id", "task_id", "category", "mode", "run_index",
            "correctness", "factual_alignment", "analytical_depth",
            "evidence_grounding", "traceability",
        ])
        w.writeheader()
        w.writerows(csv_rows)

    # Blind ID mapping (don't look during scoring!)
    mapping = {
        r["_blind_id"]: {
            "task_id": r["task_id"],
            "mode": r["mode"],
            "run_index": r["run_index"],
        }
        for r in all_items
    }
    mapping_path = out / "blind_id_mapping.json"
    mapping_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    print(f"Exported {len(all_items)} items:")
    print(f"  Readable answers: {md_path}")
    print(f"  CSV template:     {csv_path}")
    print(f"  Blind ID mapping: {mapping_path}")
    a = sum(1 for r in all_items if r["category"] == "A")
    b = sum(1 for r in all_items if r["category"] == "B")
    c = sum(1 for r in all_items if r["category"] == "C")
    print(f"  A: {a} items, B: {b} items, C: {c} items")


if __name__ == "__main__":
    main()

"""Scoring helper: CLI tool for human scoring of evaluation results.

Category A: semi-auto correctness (0/1/2) against ground truth.
Category B/C: human-scored 1-10 on 3 dimensions + traceability 0/1/2.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from ..config import runs_dir as _runs_dir, scores_dir as _scores_dir


def _load_run_results(runs_dir: Path) -> list[dict]:
    """Load all run result JSONs from the runs directory."""
    results = []
    combined = runs_dir / "all_results.json"
    if combined.exists():
        return json.loads(combined.read_text(encoding="utf-8"))

    for f in sorted(runs_dir.glob("*.json")):
        if f.name == "all_results.json":
            continue
        results.append(json.loads(f.read_text(encoding="utf-8")))
    return results


def run_scoring_session(
    runs_dir: Path | None = None,
    output_path: Path | None = None,
    blind: bool = True,
) -> Path:
    """Interactive CLI scoring session.

    Presents answers in randomized order (blind=True hides mode labels).
    Collects scores and writes to CSV.
    """
    runs_dir = runs_dir or _runs_dir()
    output_path = output_path or (_scores_dir() / "scores.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = _load_run_results(runs_dir)
    if not results:
        print("No run results found.")
        return output_path

    # Randomize presentation order for blind scoring
    if blind:
        random.shuffle(results)

    scores: list[dict] = []

    for i, r in enumerate(results):
        task_id = r.get("task_id", "?")
        category = r.get("category", "?")
        mode = r.get("mode", "?")
        run_idx = r.get("run_index", 0)
        answer = r.get("final_answer", "(no answer)")
        tool_calls = r.get("tool_calls", [])

        # Display
        print(f"\n{'='*60}")
        print(f"Item {i+1}/{len(results)}")
        if not blind:
            print(f"Mode: {mode}")
        print(f"Task: {task_id} (Category {category})")
        print(f"Question: {r.get('question', '?')}")
        print(f"\n--- Answer ---\n{answer}")
        print(f"\n--- Tool Calls ({len(tool_calls)}) ---")
        for tc in tool_calls[:10]:
            print(f"  {tc.get('tool', '?')}({json.dumps(tc.get('args', {}))[:80]})")
        print(f"{'='*60}")

        score_row = {
            "task_id": task_id,
            "category": category,
            "mode": mode,
            "run_index": run_idx,
        }

        if category == "A":
            # Closed tasks: 0/1/2 correctness
            score_row["correctness"] = _prompt_int(
                "Correctness (0=incorrect, 1=partial, 2=correct): ", 0, 2
            )
        else:
            # Open tasks: 1-10 on 3 dimensions
            score_row["factual_alignment"] = _prompt_int(
                "Factual alignment (1-10): ", 1, 10
            )
            score_row["analytical_depth"] = _prompt_int(
                "Analytical depth (1-10): ", 1, 10
            )
            score_row["evidence_grounding"] = _prompt_int(
                "Evidence grounding (1-10): ", 1, 10
            )
            score_row["correctness"] = round(
                (
                    score_row["factual_alignment"]
                    + score_row["analytical_depth"]
                    + score_row["evidence_grounding"]
                )
                / 3,
                2,
            )

        # Traceability for all tasks
        score_row["traceability"] = _prompt_int(
            "Traceability (0=none, 1=partial, 2=full): ", 0, 2
        )

        scores.append(score_row)

    # Write CSV
    if scores:
        fieldnames = [
            "task_id",
            "category",
            "mode",
            "run_index",
            "correctness",
            "factual_alignment",
            "analytical_depth",
            "evidence_grounding",
            "traceability",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(scores)

        print(f"\nScores saved to {output_path}")

    return output_path


def _prompt_int(prompt: str, min_val: int, max_val: int) -> int:
    """Prompt the user for an integer within a range."""
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"  Please enter a value between {min_val} and {max_val}.")
        except ValueError:
            print("  Please enter a valid integer.")
        except (EOFError, KeyboardInterrupt):
            print("\n  Scoring interrupted.")
            return min_val

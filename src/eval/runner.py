"""Execution harness: run tasks across both assistant modes, record logs."""

from __future__ import annotations

import json
import random
import signal
import time
from pathlib import Path
from typing import Callable

from ..config import Config, RESULTS_DIR, runs_dir
from .task_set import TASK_SET, EvalTask


class TimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TimeoutError("Task execution timed out")


def run_single_task(
    run_fn: Callable[[str], dict],
    task: EvalTask,
    timeout_s: int = 120,
) -> dict:
    """Execute a single task with timeout and error handling.

    Returns the run result dict, or an error dict on failure.
    """
    # Set timeout (Unix only)
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_s)

    try:
        result = run_fn(task.question)
        signal.alarm(0)  # Cancel alarm
        return {
            **result,
            "task_id": task.task_id,
            "category": task.category,
            "error": None,
            "timed_out": False,
        }
    except TimeoutError:
        return {
            "task_id": task.task_id,
            "category": task.category,
            "question": task.question,
            "final_answer": "",
            "tool_calls": [],
            "num_tool_calls": 0,
            "latency_s": timeout_s,
            "error": "timeout",
            "timed_out": True,
        }
    except Exception as e:
        signal.alarm(0)
        return {
            "task_id": task.task_id,
            "category": task.category,
            "question": task.question,
            "final_answer": "",
            "tool_calls": [],
            "num_tool_calls": 0,
            "latency_s": 0,
            "error": str(e),
            "timed_out": False,
        }
    finally:
        signal.signal(signal.SIGALRM, old_handler)


def run_evaluation(
    single_agent_fn: Callable[[str], dict],
    multi_agent_fn: Callable[[str], dict],
    tasks: tuple[EvalTask, ...] | None = None,
    n_runs: int = 3,
    timeout_s: int = 120,
    output_dir: Path | None = None,
) -> list[dict]:
    """Run full evaluation: all tasks × both modes × n_runs.

    Randomizes task order per run. Saves JSON per individual run.
    Returns list of all run result dicts.
    """
    if tasks is None:
        tasks = TASK_SET

    out_dir = output_dir or runs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []
    task_list = list(tasks)

    for run_idx in range(n_runs):
        # Randomize task order per run
        shuffled = list(task_list)
        random.shuffle(shuffled)

        for task in shuffled:
            for mode_name, run_fn in [
                ("single_agent", single_agent_fn),
                ("multi_agent", multi_agent_fn),
            ]:
                print(
                    f"Run {run_idx + 1}/{n_runs} | {mode_name} | {task.task_id}..."
                )

                result = run_single_task(run_fn, task, timeout_s)
                result["run_index"] = run_idx
                result["mode"] = mode_name
                all_results.append(result)

                # Save individual run JSON
                fname = f"{mode_name}_{task.task_id}_run{run_idx}.json"
                (out_dir / fname).write_text(
                    json.dumps(result, indent=2, default=str),
                    encoding="utf-8",
                )

    # Save combined results
    combined_path = out_dir / "all_results.json"
    combined_path.write_text(
        json.dumps(all_results, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Saved {len(all_results)} run results to {out_dir}")

    return all_results

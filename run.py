#!/usr/bin/env python3
"""Main entry point for the OCPM Multi-Agent Artifact evaluation.

Usage:
    # Pilot run (3 tasks, 1 run each)
    python run.py --pilot

    # Full evaluation
    python run.py --full

    # Score results
    python run.py --score

    # Analyze results
    python run.py --analyze
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src is importable
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--pilot", action="store_true", help="Run pilot (3 tasks × 1 run)")
    group.add_argument("--full", action="store_true", help="Run full evaluation")
    group.add_argument("--score", action="store_true", help="Run scoring session")
    group.add_argument("--analyze", action="store_true", help="Generate analysis")
    group.add_argument("--summary", action="store_true", help="Print log summary only")

    p.add_argument("--log-path", type=str, help="Path to OCEL 2.0 log file")
    p.add_argument("--dotenv", type=str, help="Path to .env file")
    p.add_argument("--tasks", type=str, help="Comma-separated task IDs (e.g., A1,B1,C1)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    from src.config import Config

    cfg = Config.from_env(Path(args.dotenv) if args.dotenv else None)

    if args.analyze:
        from src.eval.analysis import generate_full_analysis

        generate_full_analysis()
        return 0

    if args.score:
        from src.eval.scorer import run_scoring_session

        run_scoring_session()
        return 0

    # Load the OCEL log
    log_path = args.log_path or str(cfg.data_path)
    # Find an actual file in the data directory
    data_dir = Path(log_path)
    if data_dir.is_dir():
        candidates = list(data_dir.glob("*.jsonocel")) + list(data_dir.glob("*.json")) + list(data_dir.glob("*.sqlite"))
        if not candidates:
            print(f"No OCEL files found in {data_dir}")
            return 1
        log_path = str(candidates[0])
        print(f"Using log: {log_path}")

    from src.tools.log_loader import load_ocel_log, get_log_summary

    print(f"Loading OCEL log from {log_path}...")
    ocel_data = load_ocel_log(log_path)
    summary = get_log_summary(ocel_data)
    print(f"Log loaded: {summary['num_events']} events, {summary['num_objects']} objects, "
          f"types={summary['object_types']}")

    if args.summary:
        import json
        print(json.dumps(summary, indent=2))
        return 0

    # Build agent graphs
    from src.agents.single_agent import build_single_agent_graph
    from src.agents.multi_agent import build_multi_agent_graph

    if cfg.llm_provider == "openai":
        api_key = cfg.openai_api_key
        base_url = cfg.openai_base_url
    else:
        api_key = cfg.gemini_api_key
        base_url = cfg.gemini_base_url

    print(f"Building agents: provider={cfg.llm_provider}, model={cfg.llm_model}"
          + (f", endpoint={base_url}" if base_url else ""))
    single_fn = build_single_agent_graph(
        ocel_data,
        provider=cfg.llm_provider,
        model=cfg.llm_model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        api_key=api_key,
        base_url=base_url,
    )
    multi_fn = build_multi_agent_graph(
        ocel_data,
        provider=cfg.llm_provider,
        model=cfg.llm_model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        api_key=api_key,
        base_url=base_url,
    )

    # Select tasks for the active dataset
    from src.eval.task_set import get_task_set

    full_set = get_task_set(cfg.dataset)
    print(f"Dataset: {cfg.dataset} ({len(full_set)} tasks)")

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",")]
        tasks = tuple(t for t in full_set if t.task_id in task_ids)
        if not tasks:
            print(f"No matching tasks for: {task_ids}")
            return 1
    elif args.pilot:
        # First task of each category (dataset-agnostic)
        tasks = tuple(
            next(t for t in full_set if t.category == cat)
            for cat in ("A", "B", "C")
        )
    else:
        tasks = full_set

    n_runs = 1 if args.pilot else cfg.runs_per_task

    from src.eval.runner import run_evaluation
    from src.config import RESULTS_DIR

    # Isolate results per dataset so a new dataset never overwrites the
    # existing BPI 2017 results. BPI keeps its legacy path (results/runs);
    # other datasets write to results/<dataset>/runs.
    out_dir = (RESULTS_DIR / "runs" if cfg.dataset == "bpi2017"
               else RESULTS_DIR / cfg.dataset / "runs")

    print(f"\nStarting evaluation: {len(tasks)} tasks × 2 modes × {n_runs} runs "
          f"= {len(tasks) * 2 * n_runs} executions")
    print(f"Output dir: {out_dir}")

    results = run_evaluation(
        single_agent_fn=single_fn,
        multi_agent_fn=multi_fn,
        tasks=tasks,
        n_runs=n_runs,
        timeout_s=cfg.task_timeout_s,
        output_dir=out_dir,
    )

    # Quick summary
    errors = [r for r in results if r.get("error")]
    timeouts = [r for r in results if r.get("timed_out")]
    print(f"\nDone: {len(results)} runs, {len(errors)} errors, {len(timeouts)} timeouts")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

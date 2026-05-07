#!/usr/bin/env python3
"""Resume an interrupted full evaluation run.

Inspects results/runs/ for existing per-(mode, task, run_index) files and
executes only the missing ones. Writes incremental progress to a log file
so progress is durable even if the parent process is killed.

Usage:
    .venv/bin/python -u resume_run.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import Config
from src.tools.log_loader import load_ocel_log, get_log_summary
from src.agents.single_agent import build_single_agent_graph
from src.agents.multi_agent import build_multi_agent_graph
from src.eval.task_set import TASK_SET
from src.eval.runner import run_single_task

RUNS_DIR = ROOT / "results" / "runs"
N_RUNS = 3
MODES = ["single_agent", "multi_agent"]


def main() -> None:
    cfg = Config.from_env()

    # Find the OCEL log
    data_dir = cfg.data_path
    candidates = list(data_dir.glob("*.sqlite"))
    if not candidates:
        print("No SQLite log found", file=sys.stderr)
        sys.exit(1)
    log_path = str(candidates[0])
    print(f"[resume] Loading {log_path}", flush=True)
    ocel_data = load_ocel_log(log_path)
    summary = get_log_summary(ocel_data)
    print(f"[resume] Log: {summary['num_events']} events, {summary['num_objects']} objects", flush=True)

    # Build agent graphs
    api_key = cfg.openai_api_key
    base_url = cfg.openai_base_url
    print(f"[resume] Building agents: provider={cfg.llm_provider}, model={cfg.llm_model}", flush=True)
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
    fn_by_mode = {"single_agent": single_fn, "multi_agent": multi_fn}

    # Identify missing runs
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    missing: list[tuple[str, object, int]] = []
    for run_idx in range(N_RUNS):
        for task in TASK_SET:
            for mode in MODES:
                fname = RUNS_DIR / f"{mode}_{task.task_id}_run{run_idx}.json"
                if not fname.exists():
                    missing.append((mode, task, run_idx))

    total = N_RUNS * len(TASK_SET) * len(MODES)
    done = total - len(missing)
    print(f"[resume] Total: {total}; already done: {done}; missing: {len(missing)}", flush=True)

    if not missing:
        print("[resume] Nothing to do.", flush=True)
        _save_combined()
        return

    t_start = time.time()
    for i, (mode, task, run_idx) in enumerate(missing, 1):
        wall = time.time() - t_start
        print(f"[{i}/{len(missing)}] elapsed={wall:.0f}s | {mode} | {task.task_id} | run{run_idx}", flush=True)

        result = run_single_task(fn_by_mode[mode], task, cfg.task_timeout_s)
        result["run_index"] = run_idx
        result["mode"] = mode

        fname = RUNS_DIR / f"{mode}_{task.task_id}_run{run_idx}.json"
        fname.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

        err = result.get("error")
        if err:
            print(f"   ERROR: {err}", flush=True)

    print(f"[resume] All missing runs completed in {time.time() - t_start:.0f}s", flush=True)
    _save_combined()


def _save_combined() -> None:
    """Rebuild all_results.json from all per-run files."""
    all_results = []
    for f in sorted(RUNS_DIR.glob("*.json")):
        if f.name == "all_results.json":
            continue
        data = json.loads(f.read_text())
        # Defensive: infer mode/run_index from filename if missing
        name = f.stem
        if "mode" not in data:
            data["mode"] = "multi_agent" if name.startswith("multi") else "single_agent"
        if "run_index" not in data:
            try:
                data["run_index"] = int(name.split("run")[-1])
            except ValueError:
                data["run_index"] = -1
        all_results.append(data)

    all_results.sort(key=lambda r: (r.get("run_index", 0), r.get("mode", ""), r.get("task_id", "")))
    out = RUNS_DIR / "all_results.json"
    out.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    errors = [r for r in all_results if r.get("error")]
    timeouts = [r for r in all_results if r.get("timed_out")]
    print(f"[resume] all_results.json: {len(all_results)} runs ({len(errors)} errors, {len(timeouts)} timeouts)", flush=True)


if __name__ == "__main__":
    main()

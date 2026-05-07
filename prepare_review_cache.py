#!/usr/bin/env python3
"""Pre-compute LLM-assisted draft review for each evaluation item.

Output: results/scores/llm_review_zh.json (sidecar — NOT thesis pipeline).

For each item, the LLM produces:
- TL;DR of agent's answer (Chinese bullets)
- Strengths / concerns
- Suggested rubric scores with one-line reasoning per dimension

The human scorer reviews these as drafts and remains the sole final judge.
This is methodologically stronger than PM-LLM-Benchmark's pure
LLM-as-judge approach (Berti et al., 2024) because every score is
human-validated rather than auto-applied.

Usage:
    .venv/bin/python prepare_review_cache.py            # all missing
    .venv/bin/python prepare_review_cache.py --force    # re-do all
    .venv/bin/python prepare_review_cache.py --limit 5  # trial
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from openai import OpenAI

from src.config import Config

PROJECT_ROOT = Path(__file__).resolve().parent
RUNS_FILE = PROJECT_ROOT / "results" / "runs" / "all_results.json"
CACHE_FILE = PROJECT_ROOT / "results" / "scores" / "llm_review_zh.json"

# Single source of truth: import from score_interactive to avoid drift.
# This was a real bug — both files maintained their own GROUND_TRUTH copies
# and they fell out of sync after task_set.py rephrasing (May 2026).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from score_interactive import GROUND_TRUTH

SYSTEM_A = """You review an LLM agent's answer to a closed OCPM (object-centric process mining) question with known ground truth. Your job: produce a structured DRAFT review in Simplified Chinese for a human scorer who makes final decisions.

Rubric (Category A):
- Correctness 0/1/2: 0=wrong/missing, 1=partial (right direction, imprecise), 2=fully matches ground truth
- Traceability 0/1/2: 0=no intermediate steps visible, 1=some traceable, 2=every claim links to a tool output

Output JSON ONLY, no markdown, this exact schema:
{
  "match_status": "exact" | "partial" | "wrong" | "missing",
  "tldr_zh": "1-line Chinese summary of agent's claim",
  "strengths_zh": ["..."],
  "concerns_zh": ["..."],
  "suggested_correctness": 0|1|2,
  "reason_correctness_zh": "1-line Chinese justification",
  "suggested_traceability": 0|1|2,
  "reason_traceability_zh": "1-line Chinese justification"
}

Be honest and discriminating. Do not anchor to high scores."""

SYSTEM_BC = """You review an LLM agent's answer to an open-ended OCPM (object-centric process mining) question scored by rubric. Your job: produce a structured DRAFT review in Simplified Chinese for a human scorer who makes final decisions.

Rubric (Categories B and C):
- Factual Alignment 1-10: consistency with data evidence; numerical correctness vs reported tool outputs
- Analytical Depth 1-10: structured reasoning beyond surface description (causal chains, comparisons, hypotheses, counter-evidence)
- Evidence Grounding 1-10: density of specific computed values / tool outputs cited in the answer
- Traceability 0/1/2: 0=no intermediate steps visible, 1=some traceable, 2=every claim links to a tool output

Calibration anchors:
- 9-10: exceptional, publication-quality finding
- 7-8: solid; clear reasoning with proper evidence
- 5-6: acceptable; covers question but lacks depth or specificity
- 3-4: weak; superficial or partly off-topic
- 1-2: very poor; incorrect, hallucinated, or non-responsive

Be discriminating. Resist anchoring to 7-8.

Output JSON ONLY, no markdown, this exact schema:
{
  "tldr_bullets_zh": ["3-5 Chinese bullets of key findings, ≤30 chars each"],
  "tool_appropriate": "yes" | "partial" | "no",
  "tool_appropriate_reason_zh": "1 line",
  "strengths_zh": ["1-3 items, brief"],
  "concerns_zh": ["1-3 items, brief"],
  "suggested_factual": 1-10,
  "reason_factual_zh": "1 line",
  "suggested_depth": 1-10,
  "reason_depth_zh": "1 line",
  "suggested_grounding": 1-10,
  "reason_grounding_zh": "1 line",
  "suggested_traceability": 0|1|2,
  "reason_traceability_zh": "1 line"
}"""


def load_blind_items() -> list[dict[str, Any]]:
    results = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    items = list(results)
    random.seed(42)
    random.shuffle(items)
    for i, r in enumerate(items):
        r["_blind_id"] = f"ITEM-{i + 1:03d}"
    return items


def load_cache() -> dict[str, dict[str, Any]]:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def make_client(cfg: Config) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": cfg.openai_api_key}
    if cfg.openai_base_url:
        kwargs["base_url"] = cfg.openai_base_url
    return OpenAI(**kwargs)


def format_user_prompt(r: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(f"Question: {r.get('question', '')}")
    if r["category"] == "A":
        parts.append(f"Ground truth: {GROUND_TRUTH.get(r['task_id'], '')}")
    parts.append(f"Mode: {r['mode']}  |  Latency: {r.get('latency_s', 0):.1f}s")
    parts.append(f"Tool calls total: {len(r.get('tool_calls', []))}")

    plan = r.get("plan") or []
    if plan:
        parts.append("\nPlan:")
        for p in plan:
            parts.append(f"  {p.get('id', '?')}. {p.get('description', '')}")

    tool_calls = r.get("tool_calls") or []
    if tool_calls:
        tool_counts = Counter(tc.get("tool", "?") for tc in tool_calls)
        summary = ", ".join(
            f"{name}x{cnt}" for name, cnt in tool_counts.most_common()
        )
        parts.append(f"\nTool usage summary: {summary}")

    subs = r.get("subtask_results") or []
    if subs:
        parts.append("\nSubtask findings:")
        for sr in subs:
            finding = (sr.get("finding") or "")[:1500]
            parts.append(f"  Subtask {sr.get('subtask_id', '?')}: {finding}")

    parts.append(f"\nAgent's final answer:\n{r.get('final_answer', '')}")
    return "\n".join(parts)


def review_item(client: OpenAI, model: str, r: dict[str, Any]) -> dict[str, Any]:
    sys_prompt = SYSTEM_A if r["category"] == "A" else SYSTEM_BC
    user_prompt = format_user_prompt(r)

    resp = client.chat.completions.create(
        model=model,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    parsed = json.loads(content)
    parsed["_meta"] = {
        "task_id": r["task_id"],
        "category": r["category"],
        "mode": r["mode"],
        "run_index": r["run_index"],
    }
    return parsed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true",
                   help="Re-review all items even if cached.")
    p.add_argument("--limit", type=int, default=None,
                   help="Review at most N items.")
    p.add_argument("--workers", type=int, default=8,
                   help="Concurrent workers (default 8).")
    args = p.parse_args()

    cfg = Config.from_env()
    if not cfg.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = make_client(cfg)
    items = load_blind_items()
    cache = load_cache()

    todo = [r for r in items if args.force or r["_blind_id"] not in cache]
    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        print(f"All {len(items)} items already reviewed. Nothing to do.")
        return

    print(
        f"Reviewing {len(todo)} items "
        f"(model={cfg.llm_model}, workers={args.workers})..."
    )
    t0 = time.time()
    done = 0
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_to_id = {
            ex.submit(review_item, client, cfg.llm_model, r): r["_blind_id"]
            for r in todo
        }
        for fut in as_completed(future_to_id):
            blind_id = future_to_id[fut]
            try:
                cache[blind_id] = fut.result()
                done += 1
                save_cache(cache)
                elapsed = time.time() - t0
                print(f"  [{done}/{len(todo)}] {blind_id} done  ({elapsed:.1f}s elapsed)")
            except Exception as e:  # noqa: BLE001
                errors.append((blind_id, repr(e)))
                print(f"  [!!] {blind_id} failed: {e}", file=sys.stderr)

    save_cache(cache)
    print(f"\n=== Reviewed {done}/{len(todo)} succeeded. ===")
    if errors:
        print(f"{len(errors)} failures:")
        for bid, err in errors:
            print(f"  - {bid}: {err}")
    print(f"Cache: {CACHE_FILE}")


if __name__ == "__main__":
    main()

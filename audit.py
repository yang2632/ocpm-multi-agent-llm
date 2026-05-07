#!/usr/bin/env python3
"""Independent re-score audit for ~20% of items, with LLM suggestions hidden.

Validates whether the LLM-assisted scoring workflow produced human-determined
scores or whether the human rubber-stamped LLM suggestions.

Card shows ONLY: question + ground truth (Cat A) + Chinese answer.
NO LLM bullets, NO LLM strengths/concerns, NO previous scores.

Output:
  results/scores/audit_scores.csv
  Agreement report printed at end (also via --report).

Usage:
  .venv/bin/python audit.py            # 14-item stratified sample
  .venv/bin/python audit.py --report   # just print agreement, no scoring
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Reuse helpers from the main script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_interactive import (  # noqa: E402
    BOLD, B, DIM, G, R, RESET, Y,
    CSV_FIELDS, GROUND_TRUTH, GROUND_TRUTH_ZH, QUESTION_ZH,
    load_blind_items, load_translations, prompt_int,
)

PROJECT = Path(__file__).resolve().parent
MAIN_CSV = PROJECT / "results" / "scores" / "scores_template.csv"
AUDIT_CSV = PROJECT / "results" / "scores" / "audit_scores.csv"
AUDIT_SEED = 99
AUDIT_N: dict[str, int] = {"A": 4, "B": 5, "C": 5}  # 14 total


def select_audit_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rnd = random.Random(AUDIT_SEED)
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in items:
        by_cat.setdefault(r["category"], []).append(r)
    sampled: list[dict[str, Any]] = []
    for cat, n in AUDIT_N.items():
        sampled.extend(rnd.sample(by_cat[cat], n))
    rnd.shuffle(sampled)
    return sampled


def display_audit_card(r: dict[str, Any], tr: dict[str, Any] | None) -> None:
    """Minimal card: header + question + ground truth (A) + Chinese answer."""
    bar = "═" * 76
    print(f"\n{BOLD}{B}{bar}{RESET}")
    n_tools = len(r.get("tool_calls", []))
    print(
        f"{BOLD}AUDIT — {r['_blind_id']}{RESET}   "
        f"{BOLD}{r['task_id']}{RESET} / {r['mode']}   "
        f"⏱ {r.get('latency_s', 0):.1f}s   🛠 {n_tools} calls"
    )
    print(f"{B}{bar}{RESET}")

    print(f"❓ {r.get('question', '')}")
    zh_q = QUESTION_ZH.get(r["task_id"])
    if zh_q:
        print(f"   {DIM}{zh_q}{RESET}")

    if r["category"] == "A":
        print(f"\n🎯 标准: {GROUND_TRUTH.get(r['task_id'], '?')}")
        print(f"   {DIM}{GROUND_TRUTH_ZH.get(r['task_id'], '')}{RESET}")

    answer_zh = ((tr or {}).get("final_answer_zh") or "").strip()
    print(f"\n{BOLD}══ Agent 答案 (中){RESET}")
    if answer_zh:
        print(answer_zh)
    else:
        print(f"{DIM}(无中文翻译,显示 EN){RESET}")
        print((r.get("final_answer") or "")[:2000])
    print()


def score_audit_manual(
    r: dict[str, Any], row: dict[str, str]
) -> dict[str, str] | str | None:
    cat = r["category"]
    print(f"\n{BOLD}--- 独立打分 (无 LLM 提示) ---{RESET}")
    if cat == "A":
        c = prompt_int("Correctness", 0, 2)
        if c is None or c == "SKIP":
            return c
        t = prompt_int("Traceability", 0, 2)
        if t is None or t == "SKIP":
            return t
        row["correctness"] = str(c)
        row["traceability"] = str(t)
        return row
    fa = prompt_int("事实一致性 Factual", 1, 10)
    if fa is None or fa == "SKIP":
        return fa
    ad = prompt_int("分析深度 Depth", 1, 10)
    if ad is None or ad == "SKIP":
        return ad
    eg = prompt_int("证据接地 Grounding", 1, 10)
    if eg is None or eg == "SKIP":
        return eg
    tt = prompt_int("可追溯性 Traceability", 0, 2)
    if tt is None or tt == "SKIP":
        return tt
    row["factual_alignment"] = str(fa)
    row["analytical_depth"] = str(ad)
    row["evidence_grounding"] = str(eg)
    row["traceability"] = str(tt)
    return row


def make_empty_row(r: dict[str, Any]) -> dict[str, str]:
    return {
        "blind_id": r["_blind_id"],
        "task_id": r["task_id"],
        "category": r["category"],
        "mode": r["mode"],
        "run_index": str(r["run_index"]),
        "correctness": "",
        "factual_alignment": "",
        "analytical_depth": "",
        "evidence_grounding": "",
        "traceability": "",
    }


def is_audit_scored(row: dict[str, str]) -> bool:
    if row["category"] == "A":
        return row["correctness"] != "" and row["traceability"] != ""
    return all(
        row[k] != ""
        for k in ("factual_alignment", "analytical_depth",
                  "evidence_grounding", "traceability")
    )


def load_audit_scores() -> dict[str, dict[str, str]]:
    if not AUDIT_CSV.exists():
        return {}
    rows = {}
    with AUDIT_CSV.open() as f:
        for row in csv.DictReader(f):
            rows[row["blind_id"]] = row
    return rows


def save_audit_scores(rows: dict[str, dict[str, str]]) -> None:
    AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(rows.values(), key=lambda r: r["blind_id"])
    with AUDIT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(sorted_rows)


def report(
    audit_rows: dict[str, dict[str, str]],
    main_rows: dict[str, dict[str, str]],
) -> None:
    print(f"\n{BOLD}═══ 审计一致性报告 ═══{RESET}\n")

    exact = Counter()
    w1 = Counter()
    w2 = Counter()
    total = Counter()
    deltas: list[tuple[str, str, int, int, int]] = []

    rows_compared = 0
    for bid, ar in audit_rows.items():
        if not is_audit_scored(ar):
            continue
        mr = main_rows.get(bid)
        if not mr:
            continue
        rows_compared += 1
        cat = ar["category"]
        dims = (
            ["correctness", "traceability"] if cat == "A"
            else ["factual_alignment", "analytical_depth",
                  "evidence_grounding", "traceability"]
        )
        for d in dims:
            if not ar[d] or not mr[d]:
                continue
            a = int(ar[d])
            m = int(mr[d])
            total[d] += 1
            if a == m:
                exact[d] += 1
            if abs(a - m) <= 1:
                w1[d] += 1
            if abs(a - m) <= 2:
                w2[d] += 1
            if a != m:
                deltas.append((bid, d, m, a, a - m))

    if not total:
        print(f"{Y}没有可比对的条目。先打完审计批次。{RESET}")
        return

    print(f"已审计条目: {rows_compared}")
    print(f"总维度比对: {sum(total.values())}\n")
    print(f"{'Dimension':<25} {'exact':>14} {'±1':>14} {'±2':>14}")
    for d in sorted(total.keys()):
        n = total[d]
        print(
            f"  {d:<23} "
            f"{exact[d]}/{n} ({100 * exact[d] / n:.0f}%)  "
            f"{w1[d]}/{n} ({100 * w1[d] / n:.0f}%)  "
            f"{w2[d]}/{n} ({100 * w2[d] / n:.0f}%)"
        )

    n_all = sum(total.values())
    o_exact = 100 * sum(exact.values()) / n_all
    o_w1 = 100 * sum(w1.values()) / n_all
    o_w2 = 100 * sum(w2.values()) / n_all
    print(f"\n{BOLD}Overall:{RESET}")
    print(f"  Exact match:  {sum(exact.values())}/{n_all} ({o_exact:.1f}%)")
    print(f"  Within ±1:    {sum(w1.values())}/{n_all} ({o_w1:.1f}%)")
    print(f"  Within ±2:    {sum(w2.values())}/{n_all} ({o_w2:.1f}%)")

    if deltas:
        print(f"\n{BOLD}差异最大的 (主批次 → 审计):{RESET}")
        for bid, d, m, a, delta in sorted(
            deltas, key=lambda x: -abs(x[4])
        )[:15]:
            sign = "+" if delta > 0 else ""
            print(f"  {bid}  {d:25} {m} → {a}  ({sign}{delta})")

    print(f"\n{BOLD}评估:{RESET}")
    if o_w1 >= 80:
        print(f"  {G}✅ 通过 (≥80% 在 ±1 内) — 工作流验证有效{RESET}")
        print(f"  Method.tex 披露 acceptance rate (100%) + audit agreement "
              f"({o_w1:.0f}% within ±1) 即可。数据可用。")
    elif o_w1 >= 60:
        print(f"  {Y}⚠️  边缘 (60-80% 在 ±1 内) — 部分验证{RESET}")
        print(f"  考虑对差异 ≥2 的维度在主批次中重新评分。")
    else:
        print(f"  {R}❌ 不通过 (<60% 在 ±1 内) — 主批次需重打{RESET}")
        print(f"  建议关闭 LLM 建议,重新打 72 条。")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", action="store_true",
                   help="Just print agreement report; no scoring.")
    args = p.parse_args()

    items = load_blind_items()
    audit_items = select_audit_items(items)
    translations = load_translations()
    audit_rows = load_audit_scores()

    for r in audit_items:
        audit_rows.setdefault(r["_blind_id"], make_empty_row(r))

    main_rows = {row["blind_id"]: row for row in csv.DictReader(MAIN_CSV.open())}

    if args.report:
        report(audit_rows, main_rows)
        return

    audit_items.sort(key=lambda r: r["_blind_id"])
    todo = [r for r in audit_items if not is_audit_scored(audit_rows[r["_blind_id"]])]

    if not todo:
        print(f"{G}审计 14 项全部完成。{RESET}")
        report(audit_rows, main_rows)
        return

    print(f"\n{BOLD}{B}═══ 独立审计模式 ═══{RESET}")
    print(f"{Y}LLM 建议和你之前的分都被屏蔽。请独立打分。{RESET}")
    print(f"{DIM}抽样: 4 A + 5 B + 5 C, seed={AUDIT_SEED}{RESET}")
    print(f"待打分: {len(todo)} 项 / 共 14")
    print(f"操作: 输数字 / s=跳过 / q=退出并保存\n")

    n = 0
    for r in todo:
        display_audit_card(r, translations.get(r["_blind_id"]))
        result = score_audit_manual(r, audit_rows[r["_blind_id"]])
        if result is None:
            save_audit_scores(audit_rows)
            print("已保存,退出。下次跑 audit.py 续上。")
            return
        if result == "SKIP":
            print(f"{Y}-> 跳过{RESET}")
            continue
        save_audit_scores(audit_rows)
        n += 1
        print(f"{G}-> 已保存 ({n}/{len(todo)}){RESET}")

    save_audit_scores(audit_rows)
    print(f"\n{G}审计完成。{RESET}")
    report(audit_rows, main_rows)


if __name__ == "__main__":
    main()

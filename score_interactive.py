#!/usr/bin/env python3
"""Interactive blind scoring TUI with optional LLM-assisted suggestions.

Loads run results, applies seed-42 shuffle to recover blind IDs, displays a
compact card view with optional draft scores from `llm_review_zh.json`, and
saves to `scores_template.csv` after every confirmed item.

Methodology note: when LLM suggestions are shown, the human author still
confirms or overrides every score — final scores remain author-determined.
This is more conservative than PM-LLM-Benchmark's pure LLM-as-judge approach.

Usage:
    python3 score_interactive.py --calibration   # 12-item batch, no LLM hints
    python3 score_interactive.py                 # all unscored (LLM hints on)
    python3 score_interactive.py --no-llm        # force pure manual entry
    python3 score_interactive.py --limit 10      # cap session
    python3 score_interactive.py --verbose       # show full tool/subtask info
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.config import runs_dir, scores_dir  # noqa: E402

RUNS_FILE = runs_dir() / "all_results.json"
CSV_FILE = scores_dir() / "scores_template.csv"
TRANSLATIONS_FILE = scores_dir() / "translations_zh.json"
LLM_REVIEW_FILE = scores_dir() / "llm_review_zh.json"

CSV_FIELDS = [
    "blind_id", "task_id", "category", "mode", "run_index",
    "correctness", "factual_alignment", "analytical_depth",
    "evidence_grounding", "traceability",
]

GROUND_TRUTH = {
    "A1": "A_Complete (median sojourn 861,382s ~= 10 days, n=31,309); verified via SQL + pm4py",
    "A2": "Top-3 freq Offer: O_Create Offer (n=42995), O_Created (n=42995), O_Sent (mail and online) (n=39707); compare median sojourn times: 1s, 29s, 941202s",
    "A3": "A_Cancelled exhibits highest median sync time between Application and Case_R: median 2,650,388.5s ~= 30.7 days, n=10,430",
    "A4": "Median lagging time at A_Complete between Application and Case_R = 860,588s ~= 9.96 days, n=31,303",
}

GROUND_TRUTH_ZH = {
    "A1": "Application 上 sojourn 中位数最高的活动 = A_Complete (861,382s ~= 10 天)",
    "A2": "Offer 频次前 3 = O_Create Offer / O_Created / O_Sent (mail and online); 对比 sojourn 中位数: 1s, 29s, 941202s",
    "A3": "Application 与 Case_R 之间同步时间最高的活动转换 = A_Cancelled (中位 2,650,388s)",
    "A4": "A_Complete 上 Application 与 Case_R 之间的 lagging time 中位数 = 860,588s",
}

QUESTION_ZH = {
    "A1": "在 application 对象上,哪一个活动的 sojourn time 中位数最高?",
    "A2": "offer 对象在频次最高的三个活动里,sojourn time 的分布对比如何?",
    "A3": "在 application 与 Case_R 对象之间,哪一个活动转换的同步时间最高?",
    "A4": "在活动 A_Complete (application 生命周期终点) 上,application 与 Case_R 对象之间的 lagging time 是多少?",
    "B1": "有哪些 object-type 之间的交互模式可以解释已识别的瓶颈活动?",
    "B2": "每个 application 拥有的 offer 数量,与该 application 的总流程时长之间是否存在关系?",
    "B3": "最慢的 10% application 与中位数 application 相比,在结构特征上有哪些差异?",
    "B4": "对某个同步时间异常偏高的活动,给出一条因果链 (causal chain) 解释。",
    "C1": "产出一份结构化报告:识别主要瓶颈、其可能的根因,以及一条改进建议。",
    "C2": "比较从 application 视角与从 offer 视角得到的性能诊断结果。",
    "C3": "把观测到的 application flow time 分解为 offer 侧活动贡献与其他组件;基于此分解,在何种假设下减少 offer 处理时间会显著影响整体流程时长。",
    "C4": "一位分析师声称活动 X 导致了大部分延迟,请基于可用证据评估该主张。",
}

# ANSI colours
G = "\033[32m"   # green
Y = "\033[33m"   # yellow
R = "\033[31m"   # red
B = "\033[34m"   # blue
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

MATCH_ICON = {
    "exact": f"{G}✅ 完全命中{RESET}",
    "partial": f"{Y}🔸 部分命中{RESET}",
    "wrong": f"{R}❌ 错误{RESET}",
    "missing": f"{R}❌ 未答{RESET}",
}

TOOL_FIT_ICON = {
    "yes": f"{G}✅ 选择恰当{RESET}",
    "partial": f"{Y}🔸 部分恰当{RESET}",
    "no": f"{R}❌ 选错工具{RESET}",
}


def bar_10(score: int) -> str:
    score = max(0, min(10, int(score)))
    if score >= 8:
        c = G
    elif score >= 5:
        c = Y
    else:
        c = R
    filled = "█" * score
    empty = "░" * (10 - score)
    return f"{c}{filled}{DIM}{empty}{RESET} {c}{score}/10{RESET}"


def bar_2(score: int) -> str:
    score = max(0, min(2, int(score)))
    c = G if score == 2 else (Y if score == 1 else R)
    bars = "██" if score == 2 else ("█░" if score == 1 else "░░")
    return f"{c}{bars}{RESET} {c}{score}/2{RESET}"


def load_blind_items() -> list[dict[str, Any]]:
    results = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    items = list(results)
    random.seed(42)
    random.shuffle(items)
    for i, r in enumerate(items):
        r["_blind_id"] = f"ITEM-{i + 1:03d}"
    return items


def load_translations() -> dict[str, dict[str, Any]]:
    if TRANSLATIONS_FILE.exists():
        return json.loads(TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    return {}


def load_llm_reviews() -> dict[str, dict[str, Any]]:
    if LLM_REVIEW_FILE.exists():
        return json.loads(LLM_REVIEW_FILE.read_text(encoding="utf-8"))
    return {}


def load_scores() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with CSV_FILE.open() as f:
        for row in csv.DictReader(f):
            rows[row["blind_id"]] = row
    return rows


def save_scores(rows: dict[str, dict[str, str]]) -> None:
    sorted_rows = sorted(rows.values(), key=lambda r: r["blind_id"])
    with CSV_FILE.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(sorted_rows)


def is_scored(row: dict[str, str]) -> bool:
    if row["category"] == "A":
        return row["correctness"] != "" and row["traceability"] != ""
    return all(
        row[k] != ""
        for k in ("factual_alignment", "analytical_depth",
                  "evidence_grounding", "traceability")
    )


def display_card(
    r: dict[str, Any],
    tr: dict[str, Any] | None,
    review: dict[str, Any] | None,
    show_suggest: bool,
    verbose: bool = False,
) -> None:
    bar = "═" * 76
    print(f"\n{BOLD}{B}{bar}{RESET}")
    n_tools = len(r.get("tool_calls", []))
    n_subs = len(r.get("subtask_results", []))
    sub_part = f"   {n_subs} subtasks" if n_subs else ""
    print(
        f"{BOLD}{r['_blind_id']}{RESET}   "
        f"{BOLD}{r['task_id']}{RESET} / {r['mode']}   "
        f"Run {r['run_index'] + 1}/3   "
        f"⏱ {r.get('latency_s', 0):.1f}s   "
        f"🛠 {n_tools} calls{sub_part}"
    )
    print(f"{B}{bar}{RESET}")

    # Question
    print(f"❓ {r.get('question', '')}")
    zh_q = QUESTION_ZH.get(r["task_id"])
    if zh_q:
        print(f"   {DIM}{zh_q}{RESET}")

    # Cat A: ground truth + agent claim + match status
    if r["category"] == "A":
        print(f"\n🎯 标准: {GROUND_TRUTH.get(r['task_id'], '?')}")
        if review:
            tldr = review.get("tldr_zh", "")
            print(f"💬 Agent: {tldr}")
            match = review.get("match_status", "")
            if match in MATCH_ICON:
                print(f"   {MATCH_ICON[match]}")
        else:
            ans = (r.get("final_answer") or "").strip().split("\n")[0][:120]
            print(f"💬 Agent: {ans}")

    # ── Agent's actual answer (the EVIDENCE you score) ─────────
    tr_local = tr or {}
    answer_zh = (tr_local.get("final_answer_zh") or "").strip()
    answer_en = (r.get("final_answer") or "").strip()
    print(f"\n{BOLD}══ Agent 答案 (中){RESET}")
    if answer_zh:
        # Truncate very long answers; user can press 'd' to see full
        MAX_INLINE = 1800
        if len(answer_zh) > MAX_INLINE:
            print(answer_zh[:MAX_INLINE])
            print(f"{DIM}... [+{len(answer_zh) - MAX_INLINE} 字, 输 'd' 看完整]{RESET}")
        else:
            print(answer_zh)
    elif answer_en:
        # Fallback to EN if no translation
        print(f"{DIM}(中文翻译缺失,显示 EN){RESET}")
        print(answer_en[:1800])

    # ── LLM analysis (assist; not a substitute for the answer above) ──
    if review:
        print(f"\n{BOLD}══ LLM 辅助评估{RESET}  {DIM}(参考用,你判断答案){RESET}")
        # Tool appropriateness
        if review.get("tool_appropriate"):
            fit = review["tool_appropriate"]
            reason = review.get("tool_appropriate_reason_zh", "")
            icon = TOOL_FIT_ICON.get(fit, fit)
            print(f"🛠 Tool: {icon}  {DIM}{reason}{RESET}")
        # TL;DR bullets (B/C only)
        if r["category"] != "A" and review.get("tldr_bullets_zh"):
            tldr_line = " | ".join(review["tldr_bullets_zh"])
            print(f"★ TL;DR: {DIM}{tldr_line}{RESET}")
        # Strengths / concerns (one line each, condensed)
        strengths = review.get("strengths_zh") or []
        concerns = review.get("concerns_zh") or []
        if strengths:
            print(f"{G}✅{RESET} " + f" {DIM}|{RESET} ".join(strengths))
        if concerns:
            print(f"{Y}⚠️ {RESET} " + f" {DIM}|{RESET} ".join(concerns))

    # No-review case: show tool summary so user has some clue
    tool_calls = r.get("tool_calls") or []
    if tool_calls and not review:
        tool_counts = Counter(tc.get("tool", "?") for tc in tool_calls)
        summary = ", ".join(
            f"{n}×{c}" if c > 1 else n
            for n, c in tool_counts.most_common(6)
        )
        print(f"\n🛠 Tools: {summary}")

    # Suggested scores
    if show_suggest and review:
        print(f"\n{DIM}{'─' * 76}{RESET}")
        print(f"{BOLD}💡 LLM 建议分数{RESET}  {DIM}(你是最终决定者){RESET}")
        if r["category"] == "A":
            sc = int(review.get("suggested_correctness", 1))
            st = int(review.get("suggested_traceability", 1))
            print(f"  Correctness  {bar_2(sc)}  {DIM}{review.get('reason_correctness_zh','')}{RESET}")
            print(f"  Traceability {bar_2(st)}  {DIM}{review.get('reason_traceability_zh','')}{RESET}")
        else:
            sf = int(review.get("suggested_factual", 7))
            sd = int(review.get("suggested_depth", 7))
            sg = int(review.get("suggested_grounding", 7))
            st = int(review.get("suggested_traceability", 1))
            print(f"  事实一致性 {bar_10(sf)}  {DIM}{review.get('reason_factual_zh','')}{RESET}")
            print(f"  分析深度   {bar_10(sd)}  {DIM}{review.get('reason_depth_zh','')}{RESET}")
            print(f"  证据接地   {bar_10(sg)}  {DIM}{review.get('reason_grounding_zh','')}{RESET}")
            print(f"  可追溯性   {bar_2(st)}  {DIM}{review.get('reason_traceability_zh','')}{RESET}")
        print(f"{DIM}{'─' * 76}{RESET}")

    # Verbose: full answer + subtask findings
    if verbose:
        tr = tr or {}
        print(f"\n{DIM}═══ 完整答案 (EN) ═══{RESET}")
        print(r.get("final_answer", "(no answer)"))
        if tr.get("final_answer_zh"):
            print(f"\n{DIM}═══ 完整答案 (中) ═══{RESET}")
            print(tr["final_answer_zh"])
        subs = r.get("subtask_results") or []
        subs_zh = {
            s.get("subtask_id"): s.get("finding_zh", "")
            for s in tr.get("subtask_findings_zh", [])
        }
        if subs:
            print(f"\n{DIM}═══ 子任务发现 ═══{RESET}")
            for sr in subs:
                sid = sr.get("subtask_id", "?")
                zh = subs_zh.get(sid, "")
                if zh:
                    print(f"\n  [Subtask {sid}] {zh[:600]}{'...' if len(zh) > 600 else ''}")


def show_full_answer(r: dict[str, Any], tr: dict[str, Any] | None) -> None:
    """Toggle to print full answer EN + 中."""
    tr = tr or {}
    print(f"\n{DIM}{'═' * 76}{RESET}")
    print(f"{BOLD}完整答案 (EN){RESET}")
    print(r.get("final_answer", "(no answer)"))
    if tr.get("final_answer_zh"):
        print(f"\n{BOLD}完整答案 (中){RESET}")
        print(tr["final_answer_zh"])
    subs = r.get("subtask_results") or []
    subs_zh = {
        s.get("subtask_id"): s.get("finding_zh", "")
        for s in tr.get("subtask_findings_zh", [])
    }
    if subs:
        print(f"\n{BOLD}子任务发现{RESET}")
        for sr in subs:
            sid = sr.get("subtask_id", "?")
            zh = subs_zh.get(sid, "")
            if zh:
                print(f"\n  [Subtask {sid}] {zh}")
    print(f"{DIM}{'═' * 76}{RESET}\n")


def prompt_int(label: str, lo: int, hi: int, default: int | None = None) -> int | str | None:
    while True:
        if default is not None:
            suffix = f"[{lo}-{hi}, Enter={default}]"
        else:
            suffix = f"[{lo}-{hi}]"
        raw = input(f"  {label} {suffix}: ").strip().lower()
        if raw in ("q", "quit"):
            return None
        if raw in ("s", "skip"):
            return "SKIP"
        if raw == "" and default is not None:
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
            print(f"  ! must be {lo}-{hi}")
        except ValueError:
            print("  ! integer; Enter=default; q=quit; s=skip")


def score_with_suggestions(
    r: dict[str, Any], row: dict[str, str], review: dict[str, Any]
) -> dict[str, str] | str | None:
    """Show suggested scores, allow Enter=accept all or e=edit."""
    cat = r["category"]
    if cat == "A":
        sc = int(review.get("suggested_correctness", 1))
        st = int(review.get("suggested_traceability", 1))
        prompt = (
            f"\n[Enter]=接受全部 ({sc},{st})  [e]=逐项编辑  "
            "[d]=完整答案  [s]=跳过  [q]=退出 > "
        )
    else:
        sf = int(review.get("suggested_factual", 7))
        sd = int(review.get("suggested_depth", 7))
        sg = int(review.get("suggested_grounding", 7))
        st = int(review.get("suggested_traceability", 1))
        prompt = (
            f"\n[Enter]=接受全部 ({sf},{sd},{sg},{st})  [e]=逐项编辑  "
            "[d]=完整答案  [s]=跳过  [q]=退出 > "
        )

    while True:
        choice = input(prompt).strip().lower()
        if choice == "":
            if cat == "A":
                row["correctness"] = str(sc)
                row["traceability"] = str(st)
                print(f"  {G}✓ 接受: ({sc},{st}){RESET}")
            else:
                row["factual_alignment"] = str(sf)
                row["analytical_depth"] = str(sd)
                row["evidence_grounding"] = str(sg)
                row["traceability"] = str(st)
                print(f"  {G}✓ 接受: ({sf},{sd},{sg},{st}){RESET}")
            return row
        if choice in ("q", "quit"):
            return None
        if choice in ("s", "skip"):
            return "SKIP"
        if choice in ("d", "detail", "details"):
            tr = SHOWN_DETAIL_CACHE.get("translations", {}).get(r["_blind_id"])
            show_full_answer(r, tr)
            continue
        if choice in ("e", "edit"):
            if cat == "A":
                c = prompt_int("Correctness", 0, 2, sc)
                if c is None or c == "SKIP":
                    return c
                t = prompt_int("Traceability", 0, 2, st)
                if t is None or t == "SKIP":
                    return t
                row["correctness"] = str(c)
                row["traceability"] = str(t)
            else:
                fa = prompt_int("事实一致性 Factual", 1, 10, sf)
                if fa is None or fa == "SKIP":
                    return fa
                ad = prompt_int("分析深度 Depth", 1, 10, sd)
                if ad is None or ad == "SKIP":
                    return ad
                eg = prompt_int("证据接地 Grounding", 1, 10, sg)
                if eg is None or eg == "SKIP":
                    return eg
                tt = prompt_int("可追溯性 Traceability", 0, 2, st)
                if tt is None or tt == "SKIP":
                    return tt
                row["factual_alignment"] = str(fa)
                row["analytical_depth"] = str(ad)
                row["evidence_grounding"] = str(eg)
                row["traceability"] = str(tt)
            return row
        print("  ! 无效输入。Enter=接受 / e=编辑 / d=完整答案 / s=跳过 / q=退出")


def score_manual(r: dict[str, Any], row: dict[str, str]) -> dict[str, str] | str | None:
    """Pure-manual entry (calibration mode or --no-llm)."""
    cat = r["category"]
    print(f"\n--- 打分 {r['_blind_id']} (Cat {cat})  [s=跳过 q=退出 d=完整答案] ---")

    def _maybe_detail(raw_str: str) -> bool:
        if raw_str.strip().lower() in ("d", "detail", "details"):
            tr = SHOWN_DETAIL_CACHE.get("translations", {}).get(r["_blind_id"])
            show_full_answer(r, tr)
            return True
        return False

    if cat == "A":
        while True:
            c = prompt_int("Correctness", 0, 2)
            if c is None or c == "SKIP":
                return c
            break
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


def select_calibration_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_ids = sorted({r["task_id"] for r in items})
    batch = []
    for i, tid in enumerate(task_ids):
        target_mode = "single_agent" if i % 2 == 0 else "multi_agent"
        candidates = [
            r for r in items
            if r["task_id"] == tid and r["mode"] == target_mode
        ]
        if candidates:
            batch.append(candidates[0])
    return batch


# Module-level cache for the show_full_answer detail toggle
SHOWN_DETAIL_CACHE: dict[str, Any] = {"translations": {}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--calibration", action="store_true",
        help="12-item calibration batch; auto-disables LLM hints.",
    )
    p.add_argument(
        "--no-llm", action="store_true",
        help="Force pure manual entry (ignore LLM cache).",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N items in this session.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show full answer + subtask findings in card.",
    )
    args = p.parse_args()

    items = load_blind_items()
    rows = load_scores()
    translations = load_translations()
    SHOWN_DETAIL_CACHE["translations"] = translations
    llm_reviews = load_llm_reviews() if not args.no_llm else {}

    use_llm_hints = bool(llm_reviews) and not args.calibration and not args.no_llm

    if args.calibration:
        target = select_calibration_batch(items)
        target.sort(key=lambda r: r["_blind_id"])
        print(f"\n{BOLD}{B}[CALIBRATION 模式]{RESET} 12 项 (1/任务,模式交替)")
        print(f"{Y}LLM 建议分关闭 — 请独立打分以建立你自己的尺{RESET}")
    else:
        target = sorted(items, key=lambda r: r["_blind_id"])
        if use_llm_hints:
            print(f"\n{G}[LLM 辅助模式]{RESET} 显示草拟分数,你最终决定")
        else:
            print(f"\n{Y}[纯人工模式]{RESET} 无 LLM 建议")

    todo = [r for r in target if not is_scored(rows[r["_blind_id"]])]
    if not todo:
        print("本批次全部已完成。")
        return

    overall_done = sum(1 for r in rows.values() if is_scored(r))
    print(
        f"\n本批次 {len(todo)} 项待打分  |  整体 {overall_done}/72 已完成。\n"
        f"操作: Enter/e/d/s/q\n"
    )

    n = 0
    for r in todo:
        if args.limit and n >= args.limit:
            print(f"\n达到 --limit {args.limit},停止。")
            break

        review = llm_reviews.get(r["_blind_id"]) if use_llm_hints else None
        # Calibration / pure-manual mode: auto-show full answer (no LLM TL;DR available)
        verbose_for_item = args.verbose or not use_llm_hints
        display_card(
            r,
            translations.get(r["_blind_id"]),
            review,
            show_suggest=use_llm_hints,
            verbose=verbose_for_item,
        )

        if review and use_llm_hints:
            result = score_with_suggestions(r, rows[r["_blind_id"]], review)
        else:
            result = score_manual(r, rows[r["_blind_id"]])

        if result is None:
            print("\n收到退出。已保存。")
            save_scores(rows)
            return
        if result == "SKIP":
            print(f"  {Y}-> 已跳过{RESET}")
            continue

        save_scores(rows)
        n += 1
        print(f"  {G}-> 已保存。本轮 {n} 项{RESET}")

    save_scores(rows)
    total_done = sum(1 for r in rows.values() if is_scored(r))
    print(f"\n{BOLD}=== 本轮完成,打分 {n} 项 ==={RESET}")
    print(f"整体进度: {total_done}/72")


if __name__ == "__main__":
    main()

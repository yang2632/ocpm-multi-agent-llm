#!/usr/bin/env python3
"""Path A: pool BPI + OM per-task paired differences for more power.

Inferential unit = TASK (3 replications collapsed to a per-task mean per mode),
NOT the run. Per-task paired diff = mean(multi reps) - mean(single reps).
Pools the two datasets' tasks and tests diff>0 with a one-sample Wilcoxon
signed-rank test. Also reports each dataset alone (heterogeneity) — pooling a
strong-effect (BPI) and weak-effect (OM) dataset must be read with dataset as a
factor, so per-dataset means are shown alongside the pooled test.

For each pooled dimension the script reports, in addition to the Wilcoxon p:
  * the matched-pairs rank-biserial effect size r = (W+ - W-) / (W+ + W-)
    (r=+1 means every non-zero per-task difference favours multi-agent), and
  * a two-sided exact sign test (binomial) as a distribution-free robustness
    check that does not rely on the Wilcoxon symmetry assumption.
The final "Thesis Table 3.5" block prints exactly the rows reported in the
thesis (n, Δ, r, p), so every column of that table is reproducible from this
script. No new scoring: uses the existing author scores for both datasets.
"""
import csv
import statistics as st
from collections import defaultdict

from scipy import stats

BPI = "results/scores/scores_template.csv"
OM = "results/order_management/scores/scores_template.csv"


def load(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def per_task_diffs(rows: list[dict], dim: str, cats: set[str]) -> dict[str, float]:
    """Return {task_id: multi_mean - single_mean} over reps, for tasks in cats."""
    by: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["category"] not in cats:
            continue
        v = r.get(dim, "").strip()
        if v == "":
            continue
        by[r["task_id"]][r["mode"]].append(float(v))
    out: dict[str, float] = {}
    for t, m in by.items():
        if m.get("multi_agent") and m.get("single_agent"):
            out[t] = st.mean(m["multi_agent"]) - st.mean(m["single_agent"])
    return out


def wilcox(diffs: list[float]) -> tuple[int, float, float, float | None]:
    """Two-sided Wilcoxon signed-rank. Pass the FULL vector and let scipy handle
    zeros via zero_method='wilcox' (standard; more conservative than pre-dropping
    zeros, which would force the exact distribution and understate p)."""
    d = [x for x in diffs]
    if not any(x != 0 for x in d):
        return (len(d), st.mean(d) if d else 0.0, 0.0, None)
    try:
        W, p = stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox")
    except ValueError:
        W, p = None, None
    return (len(d), st.mean(d), st.median(d), p)


def signed_rank_components(diffs: list[float]) -> tuple[float, float]:
    """Sum of positive and negative signed ranks over non-zero diffs.

    |diff| values are ranked with average ranks for ties (the standard Wilcoxon
    signed-rank ranking), matching scipy's zero_method='wilcox' (zeros excluded
    from the ranking)."""
    nz = [x for x in diffs if x != 0]
    if not nz:
        return (0.0, 0.0)
    order = sorted(range(len(nz)), key=lambda i: abs(nz[i]))
    ranks = [0.0] * len(nz)
    i = 0
    while i < len(nz):
        j = i
        while j + 1 < len(nz) and abs(nz[order[j + 1]]) == abs(nz[order[i]]):
            j += 1
        avg_rank = (i + j) / 2 + 1  # average of the 1-based ranks i+1..j+1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, nz) if x > 0)
    w_minus = sum(r for r, x in zip(ranks, nz) if x < 0)
    return (w_plus, w_minus)


def rank_biserial(diffs: list[float]) -> float | None:
    """Matched-pairs rank-biserial effect size r = (W+ - W-)/(W+ + W-).

    Returns None when all paired differences are zero (no effect to size)."""
    w_plus, w_minus = signed_rank_components(diffs)
    total = w_plus + w_minus
    if total == 0:
        return None
    return (w_plus - w_minus) / total


def sign_test_p(diffs: list[float]) -> float | None:
    """Two-sided exact sign test (binomial) on the signs of non-zero diffs.

    Distribution-free robustness check that, unlike the Wilcoxon signed-rank
    test, makes no symmetry assumption about the difference distribution."""
    nz = [x for x in diffs if x != 0]
    n = len(nz)
    if n == 0:
        return None
    n_pos = sum(1 for x in nz if x > 0)
    return float(stats.binomtest(n_pos, n, 0.5, alternative="two-sided").pvalue)


def f(x: float | None) -> str:
    return f"{x:.3f}" if x is not None else "  NA"


def fr(x: float | None) -> str:
    return f"{x:+.2f}" if x is not None else "  NA"


bpi = load(BPI)
om = load(OM)

print("Inferential unit = task (reps collapsed). Pooled = BPI tasks + OM tasks.")
print("r = matched-pairs rank-biserial; sign-p = two-sided exact sign test.\n")
CONTENT = ["factual_alignment", "analytical_depth", "evidence_grounding"]

for label, cats in [("B", {"B"}), ("C", {"C"}), ("B+C", {"B", "C"})]:
    print(f"================ Category {label} ================")
    for dim in CONTENT + ["traceability"]:
        b = per_task_diffs(bpi, dim, cats)
        o = per_task_diffs(om, dim, cats)
        pooled = list(b.values()) + list(o.values())
        nb, mb, _, pb = wilcox(list(b.values()))
        no, mo, _, po = wilcox(list(o.values()))
        n, mean, med, p = wilcox(pooled)
        r = rank_biserial(pooled)
        sp = sign_test_p(pooled)
        sig = "*" if (p is not None and p < 0.05) else " "
        print(f"  {dim:<20} BPI Δ={mb:+.2f}(p={f(pb)})  OM Δ={mo:+.2f}(p={f(po)})  "
              f"|{sig} POOLED n={n} Δ={mean:+.2f} r={fr(r)} p={f(p)} sign-p={f(sp)}")
    print()

# A category: correctness + traceability
print("================ Category A ================")
for dim in ["correctness", "traceability"]:
    b = per_task_diffs(bpi, dim, {"A"})
    o = per_task_diffs(om, dim, {"A"})
    pooled = list(b.values()) + list(o.values())
    nb, mb, _, pb = wilcox(list(b.values()))
    no, mo, _, po = wilcox(list(o.values()))
    n, mean, med, p = wilcox(pooled)
    r = rank_biserial(pooled)
    sp = sign_test_p(pooled)
    sig = "*" if (p is not None and p < 0.05) else " "
    print(f"  {dim:<20} BPI Δ={mb:+.2f}(p={f(pb)})  OM Δ={mo:+.2f}(p={f(po)})  "
          f"|{sig} POOLED n={n} Δ={mean:+.2f} r={fr(r)} p={f(p)} sign-p={f(sp)}")
print()

# ── Thesis Table 3.5 (tab:pooled): exact reproducible rows ──
print("================ Thesis Table 3.5 (pooled rows) ================")
print(f"  {'Dimension (pooled)':<28} {'n':>3} {'Δ':>7} {'r':>6} {'p':>8} {'sign-p':>8}")
THESIS_ROWS = [
    ("Open-task analytical depth", "analytical_depth", {"B", "C"}),
    ("Open-task factual alignment", "factual_alignment", {"B", "C"}),
    ("C factual alignment", "factual_alignment", {"C"}),
    ("B analytical depth", "analytical_depth", {"B"}),
    ("C analytical depth", "analytical_depth", {"C"}),
    ("A traceability", "traceability", {"A"}),
    ("Open-task evidence grounding", "evidence_grounding", {"B", "C"}),
    ("Open-task traceability", "traceability", {"B", "C"}),
    ("B traceability", "traceability", {"B"}),
]
for name, dim, cats in THESIS_ROWS:
    pooled = list(per_task_diffs(bpi, dim, cats).values()) + list(
        per_task_diffs(om, dim, cats).values()
    )
    n, mean, _, p = wilcox(pooled)
    r = rank_biserial(pooled)
    sp = sign_test_p(pooled)
    print(f"  {name:<28} {n:>3} {mean:>+7.2f} {fr(r):>6} {f(p):>8} {f(sp):>8}")

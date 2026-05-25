#!/usr/bin/env python3
"""Path A: pool BPI + OM per-task paired differences for more power.

Inferential unit = TASK (3 replications collapsed to a per-task mean per mode),
NOT the run. Per-task paired diff = mean(multi reps) - mean(single reps).
Pools the two datasets' tasks and tests diff>0 with a one-sample Wilcoxon
signed-rank test. Also reports each dataset alone (heterogeneity) — pooling a
strong-effect (BPI) and weak-effect (OM) dataset must be read with dataset as a
factor, so per-dataset means are shown alongside the pooled test.

No new scoring: uses the existing author scores for both datasets.
"""
import csv
import statistics as st
from collections import defaultdict

from scipy import stats

BPI = "results/scores/scores_template.csv"
OM = "results/order_management/scores/scores_template.csv"


def load(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


def per_task_diffs(rows, dim, cats):
    """Return {task_id: multi_mean - single_mean} over reps, for tasks in cats."""
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["category"] not in cats:
            continue
        v = r.get(dim, "").strip()
        if v == "":
            continue
        by[r["task_id"]][r["mode"]].append(float(v))
    out = {}
    for t, m in by.items():
        if m.get("multi_agent") and m.get("single_agent"):
            out[t] = st.mean(m["multi_agent"]) - st.mean(m["single_agent"])
    return out


def wilcox(diffs):
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


bpi = load(BPI)
om = load(OM)

print("Inferential unit = task (reps collapsed). Pooled = BPI tasks + OM tasks.\n")
CONTENT = ["factual_alignment", "analytical_depth", "evidence_grounding"]

for label, cats in [("B", {"B"}), ("C", {"C"}), ("B+C", {"B", "C"})]:
    print(f"================ Category {label} ================")
    for dim in CONTENT + (["traceability"] if label != "B+C" else ["traceability"]):
        b = per_task_diffs(bpi, dim, cats)
        o = per_task_diffs(om, dim, cats)
        pooled = list(b.values()) + list(o.values())
        nb, mb, _, pb = wilcox(list(b.values()))
        no, mo, _, po = wilcox(list(o.values()))
        n, mean, med, p = wilcox(pooled)
        def f(x):
            return f"{x:.3f}" if x is not None else "  NA"
        sig = "*" if (p is not None and p < 0.05) else " "
        print(f"  {dim:<20} BPI Δ={mb:+.2f}(p={f(pb)})  OM Δ={mo:+.2f}(p={f(po)})  "
              f"|{sig} POOLED n={n} Δ={mean:+.2f} p={f(p)}")
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
    def f(x):
        return f"{x:.3f}" if x is not None else "  NA"
    sig = "*" if (p is not None and p < 0.05) else " "
    print(f"  {dim:<20} BPI Δ={mb:+.2f}(p={f(pb)})  OM Δ={mo:+.2f}(p={f(po)})  "
          f"|{sig} POOLED n={n} Δ={mean:+.2f} p={f(p)}")

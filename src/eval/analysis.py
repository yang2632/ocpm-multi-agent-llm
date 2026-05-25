"""Comparative analysis of single-agent vs multi-agent results.

Produces:
- results/analysis/stats.json (per-dimension means, standard deviations, mean
  differences, plus exploratory Wilcoxon W/p and Cliff's delta values that are
  retained for transparency but NOT reported in the thesis; see README for why
  the thesis frame is descriptive-only at n = 4 task-level observations per
  category with replications sharing within-task variance)
- results/analysis/pass_fail.json (pass rates per category vs ACCEPTANCE_THRESHOLDS)
- results/analysis/inter_rater_kappa.json (paired-agreement percentages per
  dimension; Cohen's kappa is computed but not reported in the thesis)
- results/analysis/box_plots.png (per-metric paired box plots, B/C only)
- results/analysis/latency_tools.png (latency + tool count box plots)

Run from project root:
    .venv/bin/python -m src.eval.analysis
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

from ..config import ACCEPTANCE_THRESHOLDS, runs_dir, scores_dir, analysis_dir

# Dataset-isolated paths (DATASET env var; BPI keeps legacy results/*).
SCORES_CSV = scores_dir() / "scores_template.csv"
RATER_CSV = scores_dir() / "rater_scores.csv"
RUNS_FILE = runs_dir() / "all_results.json"
ANALYSIS_DIR = analysis_dir()

DIMS_A = ["correctness", "traceability"]
DIMS_BC = [
    "factual_alignment",
    "analytical_depth",
    "evidence_grounding",
    "traceability",
]


def cliffs_delta(x: list[float], y: list[float]) -> float:
    """Cliff's delta effect size for two independent samples."""
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    gt = sum(1 for xi in x for yi in y if xi > yi)
    lt = sum(1 for xi in x for yi in y if xi < yi)
    return (gt - lt) / (nx * ny)


def cliffs_delta_magnitude(d: float) -> str:
    """Romano et al. magnitude thresholds for |delta|."""
    a = abs(d)
    if a < 0.147:
        return "negligible"
    if a < 0.33:
        return "small"
    if a < 0.474:
        return "medium"
    return "large"


def cohen_kappa_manual(
    y1: list[int],
    y2: list[int],
    weights: str | None = None,
) -> float:
    """Compute Cohen's kappa without sklearn dependency.

    weights: None for unweighted, 'quadratic' for quadratic-weighted.
    """
    n = len(y1)
    if n == 0:
        return 0.0
    cats = sorted(set(y1) | set(y2))
    k = len(cats)
    if k == 1:
        return 1.0
    cat2i = {c: i for i, c in enumerate(cats)}
    obs = [[0] * k for _ in range(k)]
    for a, b in zip(y1, y2):
        obs[cat2i[a]][cat2i[b]] += 1
    row_marg = [sum(row) for row in obs]
    col_marg = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    if weights == "quadratic":
        rng = max(cats) - min(cats)
        if rng:
            wmat = [
                [1 - ((cats[i] - cats[j]) ** 2) / (rng * rng) for j in range(k)]
                for i in range(k)
            ]
        else:
            wmat = [[1] * k for _ in range(k)]
    else:
        wmat = [[1 if i == j else 0 for j in range(k)] for i in range(k)]
    po = sum(wmat[i][j] * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(
        wmat[i][j] * row_marg[i] * col_marg[j] for i in range(k) for j in range(k)
    ) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def landis_koch(k: float) -> str:
    """Landis & Koch (1977) interpretation bands for kappa."""
    if k < 0.20:
        return "poor"
    if k < 0.41:
        return "fair"
    if k < 0.61:
        return "moderate"
    if k < 0.81:
        return "substantial"
    return "almost perfect"


def _safe_int(v: str | None) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _wilcoxon_safe(multi: list[int], single: list[int]) -> tuple[float | None, float | None]:
    """Run Wilcoxon signed-rank, returning (None, None) if it can't be computed."""
    diffs = [m - s for m, s in zip(multi, single)]
    if all(d == 0 for d in diffs):
        return None, None
    try:
        w, p = stats.wilcoxon(
            multi, single, zero_method="wilcox", alternative="two-sided"
        )
        return float(w), float(p)
    except ValueError:
        return None, None


def _collect_pairs(
    score_map: dict,
    tids: Iterable[str],
    dim: str,
    runs: int = 3,
) -> tuple[list[int], list[int]]:
    """Collect paired (single, multi) numeric scores for a dimension across tids/runs."""
    single_vals: list[int] = []
    multi_vals: list[int] = []
    for tid in tids:
        for run in range(runs):
            s = score_map.get((tid, "single_agent", run))
            m = score_map.get((tid, "multi_agent", run))
            if not s or not m:
                continue
            sv = _safe_int(s.get(dim))
            mv = _safe_int(m.get(dim))
            if sv is None or mv is None:
                continue
            single_vals.append(sv)
            multi_vals.append(mv)
    return single_vals, multi_vals


def _summarize_pair(
    single_vals: list[int], multi_vals: list[int]
) -> dict:
    w, p = _wilcoxon_safe(multi_vals, single_vals)
    d = cliffs_delta(multi_vals, single_vals)
    return {
        "single_mean": float(np.mean(single_vals)) if single_vals else 0.0,
        "single_std": float(np.std(single_vals, ddof=1)) if len(single_vals) > 1 else 0.0,
        "multi_mean": float(np.mean(multi_vals)) if multi_vals else 0.0,
        "multi_std": float(np.std(multi_vals, ddof=1)) if len(multi_vals) > 1 else 0.0,
        "n_pairs": len(single_vals),
        "wilcoxon_W": w,
        "wilcoxon_p": p,
        "cliffs_delta": d,
        "delta_magnitude": cliffs_delta_magnitude(d),
    }


def main() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    with SCORES_CSV.open() as fh:
        scores = list(csv.DictReader(fh))
    runs = json.loads(RUNS_FILE.read_text())

    score_map = {
        (r["task_id"], r["mode"], int(r["run_index"])): r for r in scores
    }
    latency_map = {
        (r["task_id"], r["mode"], r["run_index"]): r.get("latency_s", 0.0) for r in runs
    }
    tools_map = {
        (r["task_id"], r["mode"], r["run_index"]): len(r.get("tool_calls", []))
        for r in runs
    }

    results: dict = {}

    # Category A: closed-answer tasks (correctness + traceability only)
    for dim in DIMS_A:
        single_vals, multi_vals = _collect_pairs(
            score_map, [f"A{i}" for i in range(1, 5)], dim
        )
        if len(single_vals) >= 6:
            results[f"A_{dim}"] = _summarize_pair(single_vals, multi_vals)

    # Category B and C: open-answer tasks (all four B/C dimensions)
    for cat in ("B", "C"):
        tids = [f"{cat}{i}" for i in range(1, 5)]
        for dim in DIMS_BC:
            single_vals, multi_vals = _collect_pairs(score_map, tids, dim)
            if len(single_vals) >= 6:
                results[f"{cat}_{dim}"] = _summarize_pair(single_vals, multi_vals)

    # Latency + tool calls
    s_lat = [v for k, v in latency_map.items() if k[1] == "single_agent"]
    m_lat = [v for k, v in latency_map.items() if k[1] == "multi_agent"]
    s_t = [v for k, v in tools_map.items() if k[1] == "single_agent"]
    m_t = [v for k, v in tools_map.items() if k[1] == "multi_agent"]
    results["latency"] = {
        "single_mean": float(np.mean(s_lat)) if s_lat else 0.0,
        "single_std": float(np.std(s_lat, ddof=1)) if len(s_lat) > 1 else 0.0,
        "multi_mean": float(np.mean(m_lat)) if m_lat else 0.0,
        "multi_std": float(np.std(m_lat, ddof=1)) if len(m_lat) > 1 else 0.0,
        "ratio": float(np.mean(m_lat) / np.mean(s_lat)) if s_lat and np.mean(s_lat) else 0.0,
        "n_single": len(s_lat),
        "n_multi": len(m_lat),
    }
    results["tool_calls"] = {
        "single_mean": float(np.mean(s_t)) if s_t else 0.0,
        "single_std": float(np.std(s_t, ddof=1)) if len(s_t) > 1 else 0.0,
        "multi_mean": float(np.mean(m_t)) if m_t else 0.0,
        "multi_std": float(np.std(m_t, ddof=1)) if len(m_t) > 1 else 0.0,
        "ratio": float(np.mean(m_t) / np.mean(s_t)) if s_t and np.mean(s_t) else 0.0,
        "n_single": len(s_t),
        "n_multi": len(m_t),
    }

    # Pass / Fail per ACCEPTANCE_THRESHOLDS
    pass_fail: dict = {}
    for cat in ("A", "B", "C"):
        tids = [f"{cat}{i}" for i in range(1, 5)]
        for mode in ("single_agent", "multi_agent"):
            passes = 0
            total = 0
            for tid in tids:
                for run in range(3):
                    s = score_map.get((tid, mode, run))
                    if not s:
                        continue
                    total += 1
                    if cat == "A":
                        cscore = _safe_int(s.get("correctness"))
                        tscore = _safe_int(s.get("traceability"))
                        if cscore is None or tscore is None:
                            continue
                        if (
                            cscore >= ACCEPTANCE_THRESHOLDS["A_correctness_min"]
                            and tscore >= ACCEPTANCE_THRESHOLDS["A_traceability_min"]
                        ):
                            passes += 1
                    else:
                        comps = [
                            _safe_int(s.get(d))
                            for d in (
                                "factual_alignment",
                                "analytical_depth",
                                "evidence_grounding",
                            )
                        ]
                        tscore = _safe_int(s.get("traceability"))
                        if any(c is None for c in comps) or tscore is None:
                            continue
                        mean_score = sum(comps) / 3.0
                        threshold_key = f"{cat}_mean_min"
                        if (
                            mean_score >= ACCEPTANCE_THRESHOLDS[threshold_key]
                            and tscore
                            >= ACCEPTANCE_THRESHOLDS["BC_traceability_min"]
                        ):
                            passes += 1
            pass_fail[f"{cat}_{mode}"] = {
                "pass": passes,
                "total": total,
                "rate": passes / total if total else 0.0,
            }

    # Inter-rater kappa (author vs second rater on 18 stratified items)
    with RATER_CSV.open() as fh:
        rater = {row["blind_id"]: row for row in csv.DictReader(fh) if row.get("blind_id")}
    with SCORES_CSV.open() as fh:
        author = {row["blind_id"]: row for row in csv.DictReader(fh) if row.get("blind_id")}

    common = sorted(set(author.keys()) & set(rater.keys()))
    kappa: dict = {}

    a_items = [bid for bid in common if author[bid].get("category") == "A"]
    bc_items = [
        bid for bid in common if author[bid].get("category") in ("B", "C")
    ]

    if a_items:
        a_pairs = []
        for bid in a_items:
            av = _safe_int(author[bid].get("correctness"))
            rv = _safe_int(rater[bid].get("correctness"))
            if av is not None and rv is not None:
                a_pairs.append((av, rv))
        if a_pairs:
            k = cohen_kappa_manual([p[0] for p in a_pairs], [p[1] for p in a_pairs])
            kappa["A_correctness"] = {
                "kappa": k,
                "n": len(a_pairs),
                "interpretation": landis_koch(k),
            }

    t_pairs = []
    for bid in common:
        av = _safe_int(author[bid].get("traceability"))
        rv = _safe_int(rater[bid].get("traceability"))
        if av is not None and rv is not None:
            t_pairs.append((av, rv))
    if t_pairs:
        y1 = [p[0] for p in t_pairs]
        y2 = [p[1] for p in t_pairs]
        k_unw = cohen_kappa_manual(y1, y2)
        k_w = cohen_kappa_manual(y1, y2, weights="quadratic")
        kappa["traceability"] = {
            "kappa": k_unw,
            "weighted_kappa_quadratic": k_w,
            "n": len(t_pairs),
            "interpretation": landis_koch(k_w),
        }

    for dim in ("analytical_depth", "evidence_grounding"):
        d_pairs = []
        for bid in bc_items:
            av = _safe_int(author[bid].get(dim))
            rv = _safe_int(rater[bid].get(dim))
            if av is not None and rv is not None:
                d_pairs.append((av, rv))
        if d_pairs:
            y1 = [p[0] for p in d_pairs]
            y2 = [p[1] for p in d_pairs]
            k_w = cohen_kappa_manual(y1, y2, weights="quadratic")
            within_1 = sum(1 for p in d_pairs if abs(p[0] - p[1]) <= 1) / len(d_pairs)
            within_2 = sum(1 for p in d_pairs if abs(p[0] - p[1]) <= 2) / len(d_pairs)
            kappa[f"BC_{dim}"] = {
                "weighted_kappa_quadratic": k_w,
                "n": len(d_pairs),
                "within_1": within_1,
                "within_2": within_2,
                "interpretation": landis_koch(k_w),
            }

    # Save outputs
    (ANALYSIS_DIR / "stats.json").write_text(json.dumps(results, indent=2))
    (ANALYSIS_DIR / "pass_fail.json").write_text(json.dumps(pass_fail, indent=2))
    (ANALYSIS_DIR / "inter_rater_kappa.json").write_text(json.dumps(kappa, indent=2))

    _plot_box(score_map, DIMS_BC, ANALYSIS_DIR / "box_plots.png")
    _plot_latency(latency_map, tools_map, ANALYSIS_DIR / "latency_tools.png")

    print(f"Saved stats to {ANALYSIS_DIR}/stats.json")
    print(f"Saved pass/fail to {ANALYSIS_DIR}/pass_fail.json")
    print(f"Saved kappa to {ANALYSIS_DIR}/inter_rater_kappa.json")
    print(f"Saved plots to {ANALYSIS_DIR}/box_plots.png and latency_tools.png")

    print("\n=== Wilcoxon results (significant: p<0.05) ===")
    for k, v in results.items():
        if k in ("latency", "tool_calls"):
            continue
        p_val = v.get("wilcoxon_p")
        sig = "*" if (p_val is not None and p_val < 0.05) else " "
        p_str = f"{p_val:.4f}" if p_val is not None else "NA"
        w_str = f"{v['wilcoxon_W']:.2f}" if v["wilcoxon_W"] is not None else "NA"
        print(
            f"  {sig} {k}: single={v['single_mean']:.2f} multi={v['multi_mean']:.2f}  "
            f"W={w_str} p={p_str}  delta={v['cliffs_delta']:.3f} ({v['delta_magnitude']})"
        )

    print("\n=== Latency / tool-call descriptives ===")
    print(
        f"  latency: single={results['latency']['single_mean']:.1f}s "
        f"multi={results['latency']['multi_mean']:.1f}s "
        f"ratio={results['latency']['ratio']:.2f}x"
    )
    print(
        f"  tools:   single={results['tool_calls']['single_mean']:.2f} "
        f"multi={results['tool_calls']['multi_mean']:.2f} "
        f"ratio={results['tool_calls']['ratio']:.2f}x"
    )

    print("\n=== Pass rates ===")
    for k, v in pass_fail.items():
        print(f"  {k}: {v['pass']}/{v['total']} ({100 * v['rate']:.0f}%)")

    print("\n=== Inter-rater kappa ===")
    for k, v in kappa.items():
        primary = v.get("weighted_kappa_quadratic", v.get("kappa", 0))
        extra = (
            f" (within_1={100 * v.get('within_1', 0):.0f}%)" if "within_1" in v else ""
        )
        print(
            f"  {k}: kappa={primary:.3f} ({v['interpretation']}, n={v['n']}){extra}"
        )


def _plot_box(score_map: dict, dims_BC: list[str], outpath: Path) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(16, 4))
    for ax, dim in zip(axes, dims_BC):
        s_data: list[int] = []
        m_data: list[int] = []
        for cat in ("B", "C"):
            for tid in [f"{cat}{i}" for i in range(1, 5)]:
                for run in range(3):
                    s = score_map.get((tid, "single_agent", run))
                    m = score_map.get((tid, "multi_agent", run))
                    if s:
                        v = _safe_int(s.get(dim))
                        if v is not None:
                            s_data.append(v)
                    if m:
                        v = _safe_int(m.get(dim))
                        if v is not None:
                            m_data.append(v)
        ax.boxplot([s_data, m_data], tick_labels=["Single", "Multi"])
        ax.set_title(dim.replace("_", " ").title())
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close()


def _plot_latency(latency_map: dict, tools_map: dict, outpath: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    s_lat = [v for k, v in latency_map.items() if k[1] == "single_agent"]
    m_lat = [v for k, v in latency_map.items() if k[1] == "multi_agent"]
    axes[0].boxplot([s_lat, m_lat], tick_labels=["Single", "Multi"])
    axes[0].set_title("Latency (seconds)")
    axes[0].set_ylabel("seconds")
    axes[0].grid(alpha=0.3)
    s_t = [v for k, v in tools_map.items() if k[1] == "single_agent"]
    m_t = [v for k, v in tools_map.items() if k[1] == "multi_agent"]
    axes[1].boxplot([s_t, m_t], tick_labels=["Single", "Multi"])
    axes[1].set_title("Tool calls per run")
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close()


if __name__ == "__main__":
    main()

"""Cross-object analysis: correlations and interaction patterns."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .log_loader import OCELData
from .variant import _compute_flow_times


def correlation_object_count_vs_flow_time(
    ocel_data: OCELData, parent_type: str, child_type: str
) -> dict:
    """Compute correlation between child object count per parent and flow time.

    Uses the O2O (object-to-object) relationship table, which is the correct
    source for parent-child links in OCEL 2.0. The previous implementation
    looked for shared events, which returns zero results when object types
    participate in disjoint event sets (e.g. Application vs Offer in BPI 2017).

    Returns: {parent_type, child_type, pearson_r, pearson_p, spearman_rho,
              spearman_p, n, child_count_stats, summary}
    """
    parent_ft = _compute_flow_times(ocel_data, parent_type)
    parent_objs = set(parent_ft["ocel:oid"])
    child_objs = set(
        ocel_data.objects_df[ocel_data.objects_df["ocel:type"] == child_type]["ocel:oid"]
    )

    # Use O2O table: direct object-to-object links (correct for OCEL 2.0)
    o2o = ocel_data.ocel.o2o  # columns: ocel:oid, ocel:oid_2, ocel:qualifier
    links = o2o[
        o2o["ocel:oid"].isin(parent_objs) & o2o["ocel:oid_2"].isin(child_objs)
    ]

    if links.empty:
        # Fallback: also try reversed direction (child→parent)
        links_rev = o2o[
            o2o["ocel:oid"].isin(child_objs) & o2o["ocel:oid_2"].isin(parent_objs)
        ]
        if not links_rev.empty:
            links = links_rev.rename(
                columns={"ocel:oid": "ocel:oid_2", "ocel:oid_2": "ocel:oid"}
            )

    if links.empty:
        return {
            "parent_type": parent_type,
            "child_type": child_type,
            "error": f"No O2O links found between {parent_type} and {child_type}",
            "n": 0,
        }

    child_count = links.groupby("ocel:oid")["ocel:oid_2"].nunique().reset_index()
    child_count.columns = ["ocel:oid", "child_count"]

    merged = parent_ft.merge(child_count, on="ocel:oid", how="inner")
    if len(merged) < 3:
        return {
            "parent_type": parent_type,
            "child_type": child_type,
            "error": "Too few paired observations",
            "n": len(merged),
        }

    x = merged["child_count"].values
    y = merged["flow_time_s"].values

    # Guard against constant input (pearsonr returns NaN for zero-variance input)
    if np.std(x) == 0 or np.std(y) == 0:
        return {
            "parent_type": parent_type,
            "child_type": child_type,
            "error": "Correlation undefined: constant input (zero variance)",
            "n": len(merged),
            "child_count_unique": int(np.unique(x).shape[0]),
        }

    pearson_r, pearson_p = stats.pearsonr(x, y)
    spearman_rho, spearman_p = stats.spearmanr(x, y)

    return {
        "parent_type": parent_type,
        "child_type": child_type,
        "pearson_r": round(float(pearson_r), 4),
        "pearson_p": round(float(pearson_p), 6),
        "spearman_rho": round(float(spearman_rho), 4),
        "spearman_p": round(float(spearman_p), 6),
        "n": len(merged),
        "child_count_stats": {
            "mean": round(float(merged["child_count"].mean()), 2),
            "median": round(float(merged["child_count"].median()), 2),
            "min": int(merged["child_count"].min()),
            "max": int(merged["child_count"].max()),
        },
        "summary": (
            f"{'Positive' if pearson_r > 0 else 'Negative'} correlation "
            f"(r={pearson_r:.3f}, p={pearson_p:.4f}) between {child_type} "
            f"count and {parent_type} flow time."
        ),
    }


def get_object_interaction_patterns(ocel_data: OCELData, activity: str) -> dict:
    """Analyze object type co-occurrence at a specific activity.

    Returns: {activity, patterns: [{object_types, co_occurrence_count, pct}],
              total_events}
    """
    act_col = "ocel:activity"
    eid_col = "ocel:eid"

    act_events = ocel_data.events_df[ocel_data.events_df[act_col] == activity][eid_col]

    if act_events.empty:
        return {"activity": activity, "patterns": [], "total_events": 0}

    # For each event, find which object types are involved.
    # e2o_df already carries ocel:type — no merge needed.
    act_rels = ocel_data.e2o_df[ocel_data.e2o_df[eid_col].isin(act_events)]

    # Group by event, collect unique object types
    event_types = (
        act_rels.groupby(eid_col)["ocel:type"]
        .apply(lambda x: tuple(sorted(set(x))))
        .reset_index()
    )

    pattern_counts = event_types["ocel:type"].value_counts()
    total = len(event_types)

    patterns = [
        {
            "object_types": list(types),
            "co_occurrence_count": int(cnt),
            "pct": round(float(cnt / total * 100), 2),
        }
        for types, cnt in pattern_counts.items()
    ]

    # Also compute per-type counts
    type_counts = act_rels.groupby([eid_col, "ocel:type"])["ocel:oid"].nunique()
    type_summary = (
        type_counts.reset_index()
        .groupby("ocel:type")["ocel:oid"]
        .agg(["mean", "median", "max"])
        .round(2)
        .to_dict("index")
    )

    return {
        "activity": activity,
        "total_events": total,
        "patterns": patterns,
        "objects_per_event_by_type": {
            k: {"mean": v["mean"], "median": v["median"], "max": int(v["max"])}
            for k, v in type_summary.items()
        },
    }

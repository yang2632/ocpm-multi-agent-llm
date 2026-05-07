"""Variant analysis: filtering, percentile detection, structural comparison."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .log_loader import OCELData
from .bottleneck import _compute_flow_per_object


def _compute_flow_times(ocel_data: OCELData, object_type: str) -> pd.DataFrame:
    """Compute total flow time per object (first event to last event).

    Returns DataFrame: ocel:oid, flow_time_s, num_events, first_ts, last_ts
    """
    cache_key = f"flow_times_{object_type}"
    if cache_key in ocel_data._timing_cache:
        return ocel_data._timing_cache[cache_key]

    flow = _compute_flow_per_object(ocel_data, object_type)

    agg = flow.groupby("ocel:oid").agg(
        first_ts=("ocel:timestamp", "min"),
        last_ts=("ocel:timestamp", "max"),
        num_events=("ocel:eid", "count"),
    ).reset_index()

    agg["flow_time_s"] = (agg["last_ts"] - agg["first_ts"]).dt.total_seconds()

    ocel_data._timing_cache[cache_key] = agg
    return agg


def get_slowest_percentile(
    ocel_data: OCELData, object_type: str, percentile: float = 90.0
) -> dict:
    """Identify the slowest N% of objects by total flow time.

    Returns: {object_type, percentile, threshold_s, count, total_objects,
              slowest_objects: [{oid, flow_time_s, num_events}]}
    """
    ft = _compute_flow_times(ocel_data, object_type)

    if ft.empty:
        return {
            "object_type": object_type,
            "percentile": percentile,
            "threshold_s": None,
            "count": 0,
            "total_objects": 0,
            "slowest_objects": [],
        }

    threshold = np.percentile(ft["flow_time_s"], percentile)
    slow = ft[ft["flow_time_s"] >= threshold].sort_values(
        "flow_time_s", ascending=False
    )

    return {
        "object_type": object_type,
        "percentile": percentile,
        "threshold_s": round(float(threshold), 2),
        "count": len(slow),
        "total_objects": len(ft),
        "slowest_objects": [
            {
                "oid": row["ocel:oid"],
                "flow_time_s": round(float(row["flow_time_s"]), 2),
                "num_events": int(row["num_events"]),
            }
            for _, row in slow.head(20).iterrows()
        ],
    }


def compare_slow_vs_median(ocel_data: OCELData, object_type: str) -> dict:
    """Compare structural features of slowest 10% vs median objects.

    Features compared: num_events, activity distribution, flow_time.

    Returns: {object_type, slow_group, median_group, feature_diffs}
    """
    ft = _compute_flow_times(ocel_data, object_type)
    if len(ft) < 10:
        return {"error": "Too few objects for comparison", "count": len(ft)}

    p90 = np.percentile(ft["flow_time_s"], 90)
    p40 = np.percentile(ft["flow_time_s"], 40)
    p60 = np.percentile(ft["flow_time_s"], 60)

    slow_oids = set(ft[ft["flow_time_s"] >= p90]["ocel:oid"])
    median_oids = set(
        ft[(ft["flow_time_s"] >= p40) & (ft["flow_time_s"] <= p60)]["ocel:oid"]
    )

    flow = _compute_flow_per_object(ocel_data, object_type)

    def _group_stats(oids: set) -> dict:
        grp = flow[flow["ocel:oid"].isin(oids)]
        events_per_obj = grp.groupby("ocel:oid").size()
        act_freq = grp["ocel:activity"].value_counts().to_dict()
        grp_ft = ft[ft["ocel:oid"].isin(oids)]["flow_time_s"]

        return {
            "num_objects": len(oids),
            "mean_events_per_object": round(float(events_per_obj.mean()), 2),
            "median_flow_time_s": round(float(grp_ft.median()), 2),
            "mean_flow_time_s": round(float(grp_ft.mean()), 2),
            "top_activities": dict(
                sorted(act_freq.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
        }

    slow_stats = _group_stats(slow_oids)
    median_stats = _group_stats(median_oids)

    # Compute feature differences
    diffs = {
        "flow_time_ratio": round(
            slow_stats["mean_flow_time_s"] / max(median_stats["mean_flow_time_s"], 0.01),
            2,
        ),
        "event_count_ratio": round(
            slow_stats["mean_events_per_object"]
            / max(median_stats["mean_events_per_object"], 0.01),
            2,
        ),
    }

    # Activities disproportionately present in slow group
    slow_acts = slow_stats["top_activities"]
    med_acts = median_stats["top_activities"]
    disproportionate = {}
    for act, cnt in slow_acts.items():
        slow_rate = cnt / max(slow_stats["num_objects"], 1)
        med_rate = med_acts.get(act, 0) / max(median_stats["num_objects"], 1)
        if med_rate > 0:
            ratio = round(slow_rate / med_rate, 2)
            if ratio > 1.2:
                disproportionate[act] = ratio

    diffs["disproportionate_activities"] = disproportionate

    return {
        "object_type": object_type,
        "slow_group": slow_stats,
        "median_group": median_stats,
        "feature_diffs": diffs,
    }


def get_activity_frequency(ocel_data: OCELData, object_type: str) -> dict:
    """Get activity frequency ranking for a given object type.

    Returns: {object_type, frequencies: [{activity, count, pct}]}
    """
    flow = _compute_flow_per_object(ocel_data, object_type)
    total = len(flow)

    if total == 0:
        return {"object_type": object_type, "frequencies": [], "total_events": 0}

    freq = flow["ocel:activity"].value_counts()

    return {
        "object_type": object_type,
        "total_events": total,
        "frequencies": [
            {
                "activity": act,
                "count": int(cnt),
                "pct": round(float(cnt / total * 100), 2),
            }
            for act, cnt in freq.items()
        ],
    }

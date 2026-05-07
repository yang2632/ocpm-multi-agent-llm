"""OPerA performance measures: sojourn, waiting, synchronization, pooling, lagging.

Implements measures defined in Park et al. (2022) "OPerA: Object-Centric
Performance Analysis" on preprocessed OCEL 2.0 DataFrames.

All computations use vectorized pandas operations for performance on large logs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .log_loader import OCELData


def _compute_flow_per_object(
    ocel_data: OCELData, object_type: str
) -> pd.DataFrame:
    """Compute per-object event sequence with timestamps, sorted chronologically.

    Returns DataFrame: ocel:oid, ocel:eid, ocel:activity, ocel:timestamp,
                       prev_ts, next_ts  (shifted timestamps for vectorized diffs)
    Cached per object_type.
    """
    cache_key = f"flow_v2_{object_type}"
    if cache_key in ocel_data._timing_cache:
        return ocel_data._timing_cache[cache_key]

    type_objects = ocel_data.objects_df[
        ocel_data.objects_df["ocel:type"] == object_type
    ]["ocel:oid"]

    rels = ocel_data.e2o_df[ocel_data.e2o_df["ocel:oid"].isin(type_objects)][
        ["ocel:eid", "ocel:oid"]
    ]

    events = ocel_data.events_df[["ocel:eid", "ocel:activity", "ocel:timestamp"]]
    merged = rels.merge(events, on="ocel:eid", how="inner")
    merged = merged.sort_values(["ocel:oid", "ocel:timestamp"]).reset_index(drop=True)

    # Vectorized: prev and next timestamps within each object's event sequence
    merged["prev_ts"] = merged.groupby("ocel:oid")["ocel:timestamp"].shift(1)
    merged["next_ts"] = merged.groupby("ocel:oid")["ocel:timestamp"].shift(-1)

    ocel_data._timing_cache[cache_key] = merged
    return merged


def _build_prev_event_lookup(
    ocel_data: OCELData, object_type: str
) -> pd.DataFrame:
    """Build a lookup: for each (oid, eid), the previous event's timestamp.

    Returns DataFrame: ocel:oid, ocel:eid, prev_event_ts
    Cached per object_type.
    """
    cache_key = f"prev_lookup_{object_type}"
    if cache_key in ocel_data._timing_cache:
        return ocel_data._timing_cache[cache_key]

    flow = _compute_flow_per_object(ocel_data, object_type)
    lookup = flow[["ocel:oid", "ocel:eid", "ocel:timestamp", "prev_ts"]].copy()
    lookup = lookup.rename(columns={"prev_ts": "prev_event_ts"})

    ocel_data._timing_cache[cache_key] = lookup
    return lookup


def get_sojourn_time(ocel_data: OCELData, activity: str, object_type: str) -> dict:
    """Compute sojourn time for an activity-object_type pair.

    Sojourn time = time from current event to the next event for the same object.
    Vectorized using pre-computed next_ts column.

    Returns: {activity, object_type, median_s, mean_s, std_s, count, unit}
    """
    flow = _compute_flow_per_object(ocel_data, object_type)
    at_act = flow[flow["ocel:activity"] == activity]

    if at_act.empty:
        return _empty_result(activity, object_type)

    # Vectorized: sojourn = next_ts - current_ts
    diffs = (at_act["next_ts"] - at_act["ocel:timestamp"]).dt.total_seconds()
    diffs = diffs.dropna()
    diffs = diffs[diffs >= 0]

    if diffs.empty:
        return _empty_result(activity, object_type)

    return {
        "activity": activity,
        "object_type": object_type,
        "median_s": round(float(diffs.median()), 2),
        "mean_s": round(float(diffs.mean()), 2),
        "std_s": round(float(diffs.std()), 2),
        "count": len(diffs),
        "unit": "seconds",
    }


def get_waiting_time(ocel_data: OCELData, activity: str, object_type: str) -> dict:
    """Compute waiting time for an activity-object_type pair.

    Waiting time = time from previous event to current event for the same object.
    Vectorized using pre-computed prev_ts column.

    Returns: {activity, object_type, median_s, mean_s, std_s, count, p25_s, p75_s, unit}
    """
    flow = _compute_flow_per_object(ocel_data, object_type)
    at_act = flow[flow["ocel:activity"] == activity]

    if at_act.empty:
        return _empty_wait_result(activity, object_type)

    # Vectorized: waiting = current_ts - prev_ts
    diffs = (at_act["ocel:timestamp"] - at_act["prev_ts"]).dt.total_seconds()
    diffs = diffs.dropna()
    diffs = diffs[diffs >= 0]

    if diffs.empty:
        return _empty_wait_result(activity, object_type)

    return {
        "activity": activity,
        "object_type": object_type,
        "median_s": round(float(diffs.median()), 2),
        "mean_s": round(float(diffs.mean()), 2),
        "std_s": round(float(diffs.std()), 2),
        "p25_s": round(float(diffs.quantile(0.25)), 2),
        "p75_s": round(float(diffs.quantile(0.75)), 2),
        "count": len(diffs),
        "unit": "seconds",
    }


def get_synchronization_time(
    ocel_data: OCELData, activity: str, object_types: list[str]
) -> dict:
    """Compute synchronization time at an activity across multiple object types.

    For each event at the activity, finds the previous event timestamp for each
    involved object type, then measures the gap between earliest and latest arrival.

    Vectorized: builds per-type prev_ts lookups, joins to event relations, aggregates.

    Returns: {activity, object_types, median_s, mean_s, std_s, count, unit}
    """
    if len(object_types) < 2:
        return {
            "activity": activity,
            "object_types": object_types,
            "median_s": None, "mean_s": None, "std_s": None,
            "count": 0, "unit": "seconds",
            "error": "Need at least 2 object types",
        }

    eid_col = "ocel:eid"
    act_eids = set(
        ocel_data.events_df[ocel_data.events_df["ocel:activity"] == activity][eid_col]
    )

    if not act_eids:
        return _empty_sync_result(activity, object_types)

    # For each object type, get (eid, max_prev_ts) — the latest previous event
    # among all objects of that type involved in each event
    type_arrivals = {}
    for ot in object_types:
        lookup = _build_prev_event_lookup(ocel_data, ot)
        at_act = lookup[lookup[eid_col].isin(act_eids)]
        if at_act.empty:
            continue  # Skip types with no involvement at this activity

        arrival = (
            at_act.dropna(subset=["prev_event_ts"])
            .groupby(eid_col)["prev_event_ts"]
            .max()
        )
        if not arrival.empty:
            type_arrivals[ot] = arrival

    if len(type_arrivals) < 2:
        return _empty_sync_result(activity, object_types)

    # Align all types by event ID
    combined = pd.DataFrame(type_arrivals)
    combined = combined.dropna()  # Only events where ALL types have arrivals

    if combined.empty:
        return _empty_sync_result(activity, object_types)

    # Sync time = max arrival - min arrival across types per event
    sync_s = (combined.max(axis=1) - combined.min(axis=1)).dt.total_seconds()
    sync_s = sync_s[sync_s >= 0]

    if sync_s.empty:
        return _empty_sync_result(activity, object_types)

    return {
        "activity": activity,
        "object_types": object_types,
        "median_s": round(float(sync_s.median()), 2),
        "mean_s": round(float(sync_s.mean()), 2),
        "std_s": round(float(sync_s.std()), 2),
        "count": len(sync_s),
        "unit": "seconds",
    }


def get_pooling_time(
    ocel_data: OCELData, activity: str, object_type: str
) -> dict:
    """Compute pooling time at an activity for a given object type.

    Pooling = time gap between first and last arriving object of the SAME type
    at events where multiple objects of that type are involved.

    Vectorized: joins prev_ts lookup to E2O, groups by event, computes min/max.

    Returns: {activity, object_type, median_s, mean_s, std_s, count, unit}
    """
    eid_col = "ocel:eid"
    act_eids = set(
        ocel_data.events_df[ocel_data.events_df["ocel:activity"] == activity][eid_col]
    )

    if not act_eids:
        return _empty_result(activity, object_type)

    lookup = _build_prev_event_lookup(ocel_data, object_type)
    at_act = lookup[lookup[eid_col].isin(act_eids)].dropna(subset=["prev_event_ts"])

    if at_act.empty:
        return _empty_result(activity, object_type)

    # Group by event: need ≥2 objects, then pool = max(prev) - min(prev)
    grp = at_act.groupby(eid_col)["prev_event_ts"]
    counts = grp.count()
    multi_events = counts[counts >= 2].index

    if multi_events.empty:
        return _empty_result(activity, object_type)

    multi = at_act[at_act[eid_col].isin(multi_events)]
    agg = multi.groupby(eid_col)["prev_event_ts"].agg(["min", "max"])
    pool_s = (agg["max"] - agg["min"]).dt.total_seconds()
    pool_s = pool_s[pool_s >= 0]

    if pool_s.empty:
        return _empty_result(activity, object_type)

    return {
        "activity": activity,
        "object_type": object_type,
        "median_s": round(float(pool_s.median()), 2),
        "mean_s": round(float(pool_s.mean()), 2),
        "std_s": round(float(pool_s.std()), 2),
        "count": len(pool_s),
        "unit": "seconds",
    }


def get_lagging_time(
    ocel_data: OCELData, activity: str, object_types: list[str]
) -> dict:
    """Compute lagging time at an activity across object types.

    Lagging = gap between the earliest and latest departing object type after
    an event. Uses next_ts from flow data.

    Returns: {activity, object_types, median_s, mean_s, std_s, count, unit}
    """
    if len(object_types) < 2:
        return {
            "activity": activity,
            "object_types": object_types,
            "median_s": None, "mean_s": None, "std_s": None,
            "count": 0, "unit": "seconds",
            "error": "Need at least 2 object types",
        }

    eid_col = "ocel:eid"
    act_eids = set(
        ocel_data.events_df[ocel_data.events_df["ocel:activity"] == activity][eid_col]
    )

    if not act_eids:
        return _empty_sync_result(activity, object_types)

    # For each type, get (eid, min_next_ts) — earliest departure
    type_departures = {}
    for ot in object_types:
        flow = _compute_flow_per_object(ocel_data, ot)
        at_act = flow[flow[eid_col].isin(act_eids)]
        if at_act.empty:
            continue  # Skip types with no involvement at this activity

        departure = (
            at_act.dropna(subset=["next_ts"])
            .groupby(eid_col)["next_ts"]
            .min()
        )
        if not departure.empty:
            type_departures[ot] = departure

    if len(type_departures) < 2:
        return _empty_sync_result(activity, object_types)

    combined = pd.DataFrame(type_departures).dropna()

    if combined.empty:
        return _empty_sync_result(activity, object_types)

    lag_s = (combined.max(axis=1) - combined.min(axis=1)).dt.total_seconds()
    lag_s = lag_s[lag_s >= 0]

    if lag_s.empty:
        return _empty_sync_result(activity, object_types)

    return {
        "activity": activity,
        "object_types": object_types,
        "median_s": round(float(lag_s.median()), 2),
        "mean_s": round(float(lag_s.mean()), 2),
        "std_s": round(float(lag_s.std()), 2),
        "count": len(lag_s),
        "unit": "seconds",
    }


def rank_activities_by_metric(
    ocel_data: OCELData,
    metric: str,
    object_type: str,
    top_n: int = 5,
) -> dict:
    """Rank activities by a given OPerA metric for an object type.

    Returns: {metric, object_type, ranking: [{activity, median_s, mean_s, count}]}
    """
    metric_fn = {
        "sojourn": get_sojourn_time,
        "waiting": get_waiting_time,
        "pooling": get_pooling_time,
    }

    if metric not in metric_fn:
        return {"error": f"Unknown metric: {metric}. Use: sojourn, waiting, pooling"}

    fn = metric_fn[metric]
    results = []

    for act in ocel_data.activity_names:
        r = fn(ocel_data, act, object_type)
        if r["median_s"] is not None and r["count"] > 0:
            results.append(
                {
                    "activity": act,
                    "median_s": r["median_s"],
                    "mean_s": r["mean_s"],
                    "count": r["count"],
                }
            )

    results.sort(key=lambda x: x["median_s"], reverse=True)

    return {
        "metric": metric,
        "object_type": object_type,
        "ranking": results[:top_n],
        "total_activities_with_data": len(results),
    }


# ── Helper functions for empty results ────────────────────────────

def _empty_result(activity: str, object_type: str) -> dict:
    return {
        "activity": activity,
        "object_type": object_type,
        "median_s": None, "mean_s": None, "std_s": None,
        "count": 0, "unit": "seconds",
    }


def _empty_wait_result(activity: str, object_type: str) -> dict:
    return {
        "activity": activity,
        "object_type": object_type,
        "median_s": None, "mean_s": None, "std_s": None,
        "p25_s": None, "p75_s": None,
        "count": 0, "unit": "seconds",
    }


def _empty_sync_result(activity: str, object_types: list[str]) -> dict:
    return {
        "activity": activity,
        "object_types": object_types,
        "median_s": None, "mean_s": None, "std_s": None,
        "count": 0, "unit": "seconds",
    }

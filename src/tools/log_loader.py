"""Load and preprocess OCEL 2.0 event logs using pm4py."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pm4py


@dataclass(frozen=True)
class OCELData:
    """Immutable container for a preprocessed OCEL 2.0 log."""

    ocel: Any  # pm4py OCEL object
    events_df: pd.DataFrame
    objects_df: pd.DataFrame
    e2o_df: pd.DataFrame  # event-to-object relations
    object_types: tuple[str, ...]
    activity_names: tuple[str, ...]
    _timing_cache: dict = field(default_factory=dict, repr=False)


_LOG_CACHE: dict[str, OCELData] = {}


def load_ocel_log(path: str) -> OCELData:
    """Load an OCEL 2.0 log from JSON-OCEL or SQLite and preprocess it.

    Returns an immutable OCELData with validated E2O links and timing attributes.
    Caches by path to avoid redundant reloading.
    """
    if path in _LOG_CACHE:
        return _LOG_CACHE[path]

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    # Load based on file extension
    suffix = p.suffix.lower()
    if suffix == ".jsonocel" or suffix == ".json":
        ocel = pm4py.read.read_ocel2_json(str(p))
    elif suffix == ".sqlite" or suffix == ".db":
        ocel = pm4py.read.read_ocel2_sqlite(str(p))
    elif suffix == ".xml" or suffix == ".xmlocel":
        ocel = pm4py.read.read_ocel2_xml(str(p))
    else:
        raise ValueError(f"Unsupported OCEL format: {suffix}")

    # Extract DataFrames from OCEL object
    events_df = ocel.events.copy()
    objects_df = ocel.objects.copy()
    e2o_df = ocel.relations.copy()

    # Validate: remove events with missing timestamps
    ts_col = "ocel:timestamp"
    if ts_col in events_df.columns:
        before = len(events_df)
        events_df = events_df.dropna(subset=[ts_col])
        dropped = before - len(events_df)
        if dropped > 0:
            print(f"Dropped {dropped} events with missing timestamps")

    # Extract object types and activities
    object_types = tuple(sorted(objects_df["ocel:type"].unique().tolist()))
    activity_col = "ocel:activity"
    activity_names = tuple(sorted(events_df[activity_col].unique().tolist()))

    # Validate E2O links
    valid_event_ids = set(events_df["ocel:eid"].values)
    valid_object_ids = set(objects_df["ocel:oid"].values)
    e2o_before = len(e2o_df)
    e2o_df = e2o_df[
        e2o_df["ocel:eid"].isin(valid_event_ids)
        & e2o_df["ocel:oid"].isin(valid_object_ids)
    ]
    if len(e2o_df) < e2o_before:
        print(f"Removed {e2o_before - len(e2o_df)} orphan E2O links")

    # Validation per Method.tex §3.2 promise: log must support cross-type analysis
    if len(object_types) < 2:
        raise ValueError(
            f"Log has only {len(object_types)} object type(s); cross-object-type "
            "analysis (synchronization, pooling, lagging time, interaction patterns) "
            "requires at least 2 object types."
        )
    if len(e2o_df) == 0:
        raise ValueError(
            "Log has 0 event-to-object relations after validation; cannot proceed."
        )

    data = OCELData(
        ocel=ocel,
        events_df=events_df,
        objects_df=objects_df,
        e2o_df=e2o_df,
        object_types=object_types,
        activity_names=activity_names,
    )
    _LOG_CACHE[path] = data
    return data


def _e2o_cooccurrence(ocel_data: OCELData) -> list[dict]:
    """List object-type pairs that co-occur within the same event (E2O level).

    This is what synchronization/lagging analysis actually needs (events touching
    two types), which is distinct from the O2O parent/child relationships. Result
    is cached on the OCELData to keep get_log_summary fast on repeated tool calls.
    """
    cache = ocel_data._timing_cache
    if "e2o_cooccurrence" in cache:
        return cache["e2o_cooccurrence"]

    oid_type = dict(
        zip(ocel_data.objects_df["ocel:oid"], ocel_data.objects_df["ocel:type"])
    )
    df = pd.DataFrame(
        {
            "eid": ocel_data.e2o_df["ocel:eid"].values,
            "t": ocel_data.e2o_df["ocel:oid"].map(oid_type).values,
        }
    ).dropna().drop_duplicates()
    # self-join per event, keep ordered type pairs (t_x < t_y), count events
    merged = df.merge(df, on="eid")
    merged = merged[merged["t_x"] < merged["t_y"]]
    counts = merged.groupby(["t_x", "t_y"]).size().sort_values(ascending=False)
    pairs = [
        {"type_a": a, "type_b": b, "n_events": int(n)}
        for (a, b), n in counts.items()
    ]
    cache["e2o_cooccurrence"] = pairs
    return pairs


def get_log_summary(ocel_data: OCELData) -> dict:
    """Return a structured summary of the loaded log for agent context.

    Includes the set of valid (parent_type, child_type) O2O relationships
    so the agent knows in advance which object-type pairs can be queried
    for parent/child correlation analysis.
    """
    o2o = ocel_data.ocel.o2o
    if len(o2o) > 0:
        oid_to_type = dict(
            zip(ocel_data.objects_df["ocel:oid"], ocel_data.objects_df["ocel:type"])
        )
        parent_types = o2o["ocel:oid"].map(oid_to_type)
        child_types = o2o["ocel:oid_2"].map(oid_to_type)
        pair_counts: dict[tuple[str, str], int] = {}
        for p, c in zip(parent_types, child_types):
            if p is None or c is None:
                continue
            pair_counts[(p, c)] = pair_counts.get((p, c), 0) + 1
        o2o_pairs = [
            {"parent_type": p, "child_type": c, "n_links": n}
            for (p, c), n in sorted(pair_counts.items(), key=lambda x: -x[1])
        ]
    else:
        o2o_pairs = []

    return {
        "num_events": len(ocel_data.events_df),
        "num_objects": len(ocel_data.objects_df),
        "num_e2o_relations": len(ocel_data.e2o_df),
        "num_o2o_relations": len(o2o),
        "object_types": list(ocel_data.object_types),
        "activities": list(ocel_data.activity_names),
        "num_object_types": len(ocel_data.object_types),
        "num_activities": len(ocel_data.activity_names),
        "o2o_relationships": o2o_pairs,
        # E2O event-level co-occurrence: pairs of object types that share events.
        # These (not the O2O pairs) are the pairs valid for synchronization /
        # lagging analysis.
        "e2o_cooccurrence": _e2o_cooccurrence(ocel_data),
    }


def build_log_profile(summary: dict, display_name: str | None = None) -> str:
    """Build a dataset-agnostic log profile string for prompt injection.

    Derived entirely from the loaded log's own schema (object types, activities,
    O2O pairs), so it is automatically correct for any OCEL 2.0 log and removes
    the need to hardcode dataset-specific text in the prompts. The same function
    is used for the single- and multi-agent prompts to avoid any prompt
    asymmetry between architectures.
    """
    types = ", ".join(f'"{t}"' for t in summary["object_types"])
    acts = summary["activities"]
    act_str = ", ".join(acts[:40]) + (" ..." if len(acts) > 40 else "")
    o2o = summary.get("o2o_relationships", [])
    o2o_str = (
        "; ".join(
            f'{p["parent_type"]}->{p["child_type"]} (n={p["n_links"]})' for p in o2o
        )
        or "none"
    )
    # E2O event-level co-occurrence drives synchronization/lagging (NOT O2O).
    cooc = summary.get("e2o_cooccurrence", [])
    cooc_str = (
        "; ".join(
            f'{p["type_a"]}&{p["type_b"]} (n={p["n_events"]})' for p in cooc
        )
        or "none"
    )
    name = display_name or "OCEL 2.0 log"
    return (
        f"Log: {name}. "
        f'Object types ({summary["num_object_types"]}): {types}. '
        f'Activities ({summary["num_activities"]}): {act_str}. '
        f"Valid O2O (parent->child) pairs for parent/child correlation: {o2o_str}; "
        f"only these can be used with the correlation tool. "
        f"Object-type pairs that co-occur in the same events (valid for "
        f"synchronization/lagging analysis): {cooc_str}. "
        f"Synchronization and lagging require an E2O co-occurrence pair above, "
        f"not an O2O pair."
    )

"""Independent reference computation for Cat A ground-truth tasks A1-A4.

Computes A1-A4 reference values via two independent methods:
  Method 1 (SQL): Raw SQL on the OCEL 2.0 SQLite log + numpy/statistics in Python
  Method 2 (Tool): Project tools (src.tools.bottleneck.get_*)
  Method 3 (pm4py): pm4py.statistics.ocel.edge_metrics for sojourn-time validation
                    (only applied where pm4py supports the metric)

Then cross-checks the two/three methods with a +/-5% tolerance and reports
agreement so we can lock numerical ground truth values into task_set.py
without relying solely on our own tool implementations (which would be
circular).

Tasks (REVISED 2026-05-03 to match BPI 2017 OCEL 2.0 data structure):
  A1 - highest-median-sojourn activity for Application objects (UNCHANGED)
  A2 - sojourn-time medians for top-3 most-frequent Offer activities
       (CHANGED from waiting-time -- O_Create Offer has n=0 waiting because
        it is the first event in every Offer's lifecycle)
  A3 - activity transition with highest synchronization time between
       Application and Case_R objects
       (CHANGED from Application+Offer because the BPI 2017 OCEL conversion
        has 0 events touching both Application and Offer via E2O; instead,
        239,595 events touch both Application and Case_R)
  A4 - lagging time at A_Complete between Application and Case_R objects
       (CHANGED from pooling -- pooling requires >=2 same-type objects per
        event, which never occurs in this log; lagging at A_Complete
        captures the lifecycle-terminator gap between the two types)

Run:
    .venv/bin/python scripts/compute_ground_truth.py 2>&1 \
        | tee scripts/ground_truth_output.txt
"""

from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Project tool layer (Method 2)
from src.tools.bottleneck import (
    get_lagging_time,
    get_sojourn_time,
    get_synchronization_time,
)
from src.tools.log_loader import load_ocel_log

# pm4py for Method 3 (only used for sojourn-time cross-check on A1)
from pm4py.statistics.ocel import edge_metrics

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = PROJECT_ROOT / "data" / "bpi2017" / "bpic2017.sqlite"
TOLERANCE = 0.05  # +/-5 % cross-method agreement gate


# ── SQL helpers ────────────────────────────────────────────────────────


def _open_conn() -> sqlite3.Connection:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"OCEL SQLite log not found: {SQLITE_PATH}")
    conn = sqlite3.connect(str(SQLITE_PATH))
    return conn


def _all_activity_event_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'event\\_%' ESCAPE '\\' "
        "AND name NOT IN ('event_object','event_map_type')"
    ).fetchall()
    return [r[0] for r in rows]


def _build_unified_events_view(conn: sqlite3.Connection) -> None:
    """Create a temp VIEW unifying (ocel_id, ocel_type, ocel_time)."""
    tables = _all_activity_event_tables(conn)
    parts = [
        f"SELECT ocel_id, ocel_time FROM `{t}`"
        for t in tables
    ]
    union = " UNION ALL ".join(parts)
    conn.execute("DROP VIEW IF EXISTS v_event_with_time")
    conn.execute(
        "CREATE TEMP VIEW v_event_with_time AS "
        "SELECT e.ocel_id AS ocel_id, e.ocel_type AS activity, "
        "       t.ocel_time AS ocel_time "
        "FROM event e "
        f"JOIN ({union}) t ON t.ocel_id = e.ocel_id"
    )


def _median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return float(statistics.median(vals))


def _within_tolerance(a: float | None, b: float | None, tol: float = TOLERANCE) -> bool:
    """Return True if a and b agree within +/- tol*max(|a|,|b|)."""
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom <= tol


def _tick(ok: bool) -> str:
    return "OK" if ok else "MISMATCH"


def _parse_ts(s: str) -> datetime:
    # SQLite stores ISO 8601 strings like '2016-01-02T09:19:21+00:00'
    return datetime.fromisoformat(s)


# ── A1: highest-median-sojourn activity for Application ─────────────


def a1_sql(conn: sqlite3.Connection) -> tuple[str, float, int, dict[str, tuple[float, int]]]:
    """SQL implementation: highest median sojourn for Application objects.

    Sojourn time = next event timestamp - current event timestamp for
    the same Application object (chronological order). Returns the
    activity with the highest median, the median (seconds), the count,
    and a mapping {activity: (median_s, count)} for diagnostic.
    """
    rows = conn.execute(
        """
        SELECT eo.ocel_object_id AS oid,
               v.ocel_id        AS eid,
               v.activity       AS activity,
               v.ocel_time      AS ts
        FROM v_event_with_time v
        JOIN event_object eo ON eo.ocel_event_id = v.ocel_id
        JOIN object o        ON o.ocel_id = eo.ocel_object_id
        WHERE o.ocel_type = 'Application'
        ORDER BY oid, ts
        """
    ).fetchall()

    by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for oid, _eid, activity, ts in rows:
        by_oid[oid].append((activity, ts))

    activity_sojourns: dict[str, list[float]] = defaultdict(list)
    for _oid, seq in by_oid.items():
        for i in range(len(seq) - 1):
            act, ts = seq[i]
            _, next_ts = seq[i + 1]
            diff = (_parse_ts(next_ts) - _parse_ts(ts)).total_seconds()
            if diff >= 0:
                activity_sojourns[act].append(diff)

    medians = {
        act: (float(statistics.median(vals)), len(vals))
        for act, vals in activity_sojourns.items()
        if vals
    }
    if not medians:
        return ("", 0.0, 0, {})

    top_act, (top_median, top_count) = max(medians.items(), key=lambda kv: kv[1][0])
    return (top_act, top_median, top_count, medians)


def a1_tool(ocel_data) -> tuple[str, float, int, dict[str, tuple[float, int]]]:
    """Use project tools to find highest-median-sojourn activity for Application."""
    medians: dict[str, tuple[float, int]] = {}
    for act in ocel_data.activity_names:
        r = get_sojourn_time(ocel_data, act, "Application")
        if r["median_s"] is not None and r["count"] > 0:
            medians[act] = (float(r["median_s"]), int(r["count"]))
    if not medians:
        return ("", 0.0, 0, {})
    top_act, (top_median, top_count) = max(medians.items(), key=lambda kv: kv[1][0])
    return (top_act, top_median, top_count, medians)


def a1_pm4py(ocel) -> tuple[str, float, int]:
    """pm4py edge_metrics: aggregate sojourn-time per source activity for Application."""
    edges = edge_metrics.find_associations_per_edge(ocel)
    agg = edge_metrics.aggregate_total_objects(edges)
    perf = edge_metrics.performance_calculation_ocel_aggregation(ocel, agg)
    if "Application" not in perf:
        return ("", 0.0, 0)
    src_times: dict[str, list[float]] = defaultdict(list)
    for (src, _tgt), values in perf["Application"].items():
        src_times[src].extend(values)
    medians = {
        act: (float(statistics.median(vals)), len(vals))
        for act, vals in src_times.items()
        if vals
    }
    if not medians:
        return ("", 0.0, 0)
    top_act, (top_median, top_count) = max(medians.items(), key=lambda kv: kv[1][0])
    return (top_act, top_median, top_count)


# ── A2: sojourn-time medians for top-3 most-frequent Offer activities ──


def a2_sql(conn: sqlite3.Connection) -> tuple[list[tuple[str, int]], dict[str, tuple[float | None, int]]]:
    """Top-3 most-frequent activities for Offer objects + median sojourn time per.

    Sojourn = next event timestamp - current event timestamp within each
    Offer object's chronology.
    """
    freq_rows = conn.execute(
        """
        SELECT v.activity, COUNT(*) AS n
        FROM v_event_with_time v
        JOIN event_object eo ON eo.ocel_event_id = v.ocel_id
        JOIN object o        ON o.ocel_id = eo.ocel_object_id
        WHERE o.ocel_type = 'Offer'
        GROUP BY v.activity
        ORDER BY n DESC
        """
    ).fetchall()
    top3 = [(act, n) for act, n in freq_rows[:3]]
    top3_acts = {a for a, _ in top3}

    flow_rows = conn.execute(
        """
        SELECT eo.ocel_object_id AS oid,
               v.ocel_id        AS eid,
               v.activity       AS activity,
               v.ocel_time      AS ts
        FROM v_event_with_time v
        JOIN event_object eo ON eo.ocel_event_id = v.ocel_id
        JOIN object o        ON o.ocel_id = eo.ocel_object_id
        WHERE o.ocel_type = 'Offer'
        ORDER BY oid, ts
        """
    ).fetchall()

    by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for oid, _eid, activity, ts in flow_rows:
        by_oid[oid].append((activity, ts))

    sojourns: dict[str, list[float]] = defaultdict(list)
    for _oid, seq in by_oid.items():
        for i in range(len(seq) - 1):
            act, ts = seq[i]
            _, next_ts = seq[i + 1]
            if act not in top3_acts:
                continue
            diff = (_parse_ts(next_ts) - _parse_ts(ts)).total_seconds()
            if diff >= 0:
                sojourns[act].append(diff)

    medians: dict[str, tuple[float | None, int]] = {}
    for act in top3_acts:
        vals = sojourns.get(act, [])
        if vals:
            medians[act] = (float(statistics.median(vals)), len(vals))
        else:
            medians[act] = (None, 0)
    return top3, medians


def a2_tool(ocel_data) -> tuple[list[tuple[str, int]], dict[str, tuple[float | None, int]]]:
    offer_oids = set(
        ocel_data.objects_df[ocel_data.objects_df["ocel:type"] == "Offer"]["ocel:oid"]
    )
    rels = ocel_data.e2o_df[ocel_data.e2o_df["ocel:oid"].isin(offer_oids)]
    eids = set(rels["ocel:eid"])
    events = ocel_data.events_df[ocel_data.events_df["ocel:eid"].isin(eids)]
    freq = events["ocel:activity"].value_counts().sort_values(ascending=False)
    top3 = [(act, int(n)) for act, n in list(freq.items())[:3]]
    medians: dict[str, tuple[float | None, int]] = {}
    for act, _ in top3:
        r = get_sojourn_time(ocel_data, act, "Offer")
        med = float(r["median_s"]) if r["median_s"] is not None else None
        medians[act] = (med, int(r["count"]))
    return top3, medians


# ── A3: activity transition with highest sync time (App + Case_R) ───


def a3_sql(conn: sqlite3.Connection) -> tuple[str, float, int, dict[str, tuple[float, int]]]:
    """Activity with highest median synchronization time between Application and Case_R.

    Definition (matches src/tools/bottleneck.get_synchronization_time):
      For each event e at activity A:
        For each object type T in {Application, Case_R} that participates in e:
          arrival_T(e) = max(prev_event_ts of any T-object in e)
        sync(e) = max_T arrival_T(e) - min_T arrival_T(e)
      Aggregate sync(e) across events at activity A; report median.
    """
    def prev_ts_lookup(object_type: str) -> dict[tuple[str, str], str]:
        rows = conn.execute(
            """
            SELECT eo.ocel_object_id AS oid,
                   v.ocel_id        AS eid,
                   v.activity       AS activity,
                   v.ocel_time      AS ts
            FROM v_event_with_time v
            JOIN event_object eo ON eo.ocel_event_id = v.ocel_id
            JOIN object o        ON o.ocel_id = eo.ocel_object_id
            WHERE o.ocel_type = ?
            ORDER BY oid, ts
            """,
            (object_type,),
        ).fetchall()
        by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for oid, eid, _activity, ts in rows:
            by_oid[oid].append((eid, ts))
        result: dict[tuple[str, str], str] = {}
        for oid, seq in by_oid.items():
            for i in range(1, len(seq)):
                eid, _ = seq[i]
                _prev_eid, prev_ts = seq[i - 1]
                result[(oid, eid)] = prev_ts
        return result

    app_prev = prev_ts_lookup("Application")
    case_prev = prev_ts_lookup("Case_R")

    rel_rows = conn.execute(
        """
        SELECT eo.ocel_event_id AS eid,
               eo.ocel_object_id AS oid,
               o.ocel_type      AS otype,
               v.activity       AS activity
        FROM event_object eo
        JOIN object o        ON o.ocel_id = eo.ocel_object_id
        JOIN v_event_with_time v ON v.ocel_id = eo.ocel_event_id
        WHERE o.ocel_type IN ('Application','Case_R')
        """
    ).fetchall()

    arrivals: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"Application": [], "Case_R": []}
    )
    eid_to_act: dict[str, str] = {}
    for eid, oid, otype, activity in rel_rows:
        eid_to_act[eid] = activity
        if otype == "Application":
            ts = app_prev.get((oid, eid))
        else:
            ts = case_prev.get((oid, eid))
        if ts is not None:
            arrivals[eid][otype].append(ts)

    activity_syncs: dict[str, list[float]] = defaultdict(list)
    for eid, per_type in arrivals.items():
        if not per_type["Application"] or not per_type["Case_R"]:
            continue
        app_arrival = max(_parse_ts(t) for t in per_type["Application"])
        case_arrival = max(_parse_ts(t) for t in per_type["Case_R"])
        sync = abs((app_arrival - case_arrival).total_seconds())
        act = eid_to_act[eid]
        activity_syncs[act].append(sync)

    medians = {
        act: (float(statistics.median(vals)), len(vals))
        for act, vals in activity_syncs.items() if vals
    }
    if not medians:
        return ("", 0.0, 0, {})
    top_act, (top_median, top_count) = max(medians.items(), key=lambda kv: kv[1][0])
    return (top_act, top_median, top_count, medians)


def a3_tool(ocel_data) -> tuple[str, float, int, dict[str, tuple[float, int]]]:
    medians: dict[str, tuple[float, int]] = {}
    for act in ocel_data.activity_names:
        r = get_synchronization_time(ocel_data, act, ["Application", "Case_R"])
        if r.get("median_s") is not None and r.get("count", 0) > 0:
            medians[act] = (float(r["median_s"]), int(r["count"]))
    if not medians:
        return ("", 0.0, 0, {})
    top_act, (top_median, top_count) = max(medians.items(), key=lambda kv: kv[1][0])
    return (top_act, top_median, top_count, medians)


# ── A4: lagging time at A_Complete between Application and Case_R ───


def a4_sql(conn: sqlite3.Connection, activity: str) -> tuple[float | None, int]:
    """Compute median lagging time at `activity` between Application and Case_R.

    Definition (matches src/tools/bottleneck.get_lagging_time):
      For each event e at activity A:
        For each object type T in {Application, Case_R} that participates in e:
          departure_T(e) = min(next_event_ts of any T-object in e)
        lag(e) = max_T departure_T(e) - min_T departure_T(e)
      Aggregate lag(e); report median.
    """
    def next_ts_lookup(object_type: str) -> dict[tuple[str, str], str]:
        rows = conn.execute(
            """
            SELECT eo.ocel_object_id AS oid,
                   v.ocel_id        AS eid,
                   v.ocel_time      AS ts
            FROM v_event_with_time v
            JOIN event_object eo ON eo.ocel_event_id = v.ocel_id
            JOIN object o        ON o.ocel_id = eo.ocel_object_id
            WHERE o.ocel_type = ?
            ORDER BY oid, ts
            """,
            (object_type,),
        ).fetchall()
        by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for oid, eid, ts in rows:
            by_oid[oid].append((eid, ts))
        result: dict[tuple[str, str], str] = {}
        for oid, seq in by_oid.items():
            for i in range(len(seq) - 1):
                eid, _ = seq[i]
                _next_eid, next_ts = seq[i + 1]
                result[(oid, eid)] = next_ts
        return result

    app_next = next_ts_lookup("Application")
    case_next = next_ts_lookup("Case_R")

    rel_rows = conn.execute(
        """
        SELECT eo.ocel_event_id AS eid,
               eo.ocel_object_id AS oid,
               o.ocel_type      AS otype
        FROM event_object eo
        JOIN object o        ON o.ocel_id = eo.ocel_object_id
        JOIN v_event_with_time v ON v.ocel_id = eo.ocel_event_id
        WHERE o.ocel_type IN ('Application','Case_R')
          AND v.activity = ?
        """,
        (activity,),
    ).fetchall()

    departures: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"Application": [], "Case_R": []}
    )
    for eid, oid, otype in rel_rows:
        if otype == "Application":
            ts = app_next.get((oid, eid))
        else:
            ts = case_next.get((oid, eid))
        if ts is not None:
            departures[eid][otype].append(ts)

    lags: list[float] = []
    for _eid, per_type in departures.items():
        if not per_type["Application"] or not per_type["Case_R"]:
            continue
        app_departure = min(_parse_ts(t) for t in per_type["Application"])
        case_departure = min(_parse_ts(t) for t in per_type["Case_R"])
        lag = abs((app_departure - case_departure).total_seconds())
        lags.append(lag)

    if not lags:
        return (None, 0)
    return (float(statistics.median(lags)), len(lags))


def a4_tool(ocel_data, activity: str) -> tuple[float | None, int]:
    r = get_lagging_time(ocel_data, activity, ["Application", "Case_R"])
    med = float(r["median_s"]) if r["median_s"] is not None else None
    return (med, int(r["count"]))


# ── Driver ──────────────────────────────────────────────────────────


def main() -> dict:
    print("=" * 78)
    print("OPerA Cat-A ground-truth verification (REVISED A2/A3/A4)")
    print("=" * 78)
    print(f"SQLite log : {SQLITE_PATH}")
    print(f"Tolerance  : +/- {TOLERANCE * 100:.0f} % between methods")
    print()

    print("Loading via project tool (Method 2) ...")
    ocel_data = load_ocel_log(str(SQLITE_PATH))
    print(f"  events: {len(ocel_data.events_df)}   "
          f"objects: {len(ocel_data.objects_df)}   "
          f"object_types: {ocel_data.object_types}")
    print()

    print("Opening SQLite for raw SQL (Method 1) ...")
    conn = _open_conn()
    _build_unified_events_view(conn)
    print("  v_event_with_time view ready")
    print()

    locked: dict = {}

    # ── A1 ──
    print("-" * 78)
    print("A1: highest-median-sojourn activity for Application")
    print("-" * 78)
    sql_act, sql_med, sql_n, sql_table = a1_sql(conn)
    tool_act, tool_med, tool_n, _tool_table = a1_tool(ocel_data)
    print(f"  SQL  : activity={sql_act!r}  median={sql_med:.2f}s  n={sql_n}")
    print(f"  Tool : activity={tool_act!r}  median={tool_med:.2f}s  n={tool_n}")
    try:
        pm_act, pm_med, pm_n = a1_pm4py(ocel_data.ocel)
        print(f"  pm4py: activity={pm_act!r}  median={pm_med:.2f}s  n={pm_n}")
    except Exception as e:  # pragma: no cover
        pm_act, pm_med, pm_n = ("", 0.0, 0)
        print(f"  pm4py: FAILED ({e})")

    a1_ok_st = (sql_act == tool_act) and _within_tolerance(sql_med, tool_med)
    a1_ok_tp = (tool_act == pm_act) and _within_tolerance(tool_med, pm_med)
    print(f"  Agree (SQL vs Tool):   {_tick(a1_ok_st)}")
    print(f"  Agree (Tool vs pm4py): {_tick(a1_ok_tp)}")
    print()
    print("  Top-5 medians by SQL:")
    for act, (med, n) in sorted(sql_table.items(), key=lambda kv: -kv[1][0])[:5]:
        print(f"    {act!r:40s}  median={med/86400:7.3f} d  n={n}")
    locked["A1"] = {
        "activity": sql_act,
        "median_s": sql_med,
        "count": sql_n,
        "agree_sql_vs_tool": a1_ok_st,
        "agree_tool_vs_pm4py": a1_ok_tp,
    }

    # ── A2 (REVISED: sojourn instead of waiting) ──
    print()
    print("-" * 78)
    print("A2: SOJOURN time for top-3 most-frequent Offer activities (REVISED)")
    print("-" * 78)
    sql_top3, sql_sojourns = a2_sql(conn)
    tool_top3, tool_sojourns = a2_tool(ocel_data)
    print(f"  SQL  top3: {sql_top3}")
    print(f"  Tool top3: {tool_top3}")
    sql_top3_set = {a for a, _ in sql_top3}
    tool_top3_set = {a for a, _ in tool_top3}
    a2_top3_set_ok = sql_top3_set == tool_top3_set
    a2_top3_order_ok = [a for a, _ in sql_top3] == [a for a, _ in tool_top3]
    print(f"  Agree on top-3 set:   {_tick(a2_top3_set_ok)}")
    print(f"  Agree on top-3 order: {_tick(a2_top3_order_ok)} "
          f"(ties are uninformative)")
    print()
    a2_all_match = True
    for act, _ in sql_top3:
        s_med, s_n = sql_sojourns.get(act, (None, 0))
        t_med, t_n = tool_sojourns.get(act, (None, 0))
        ok = (s_med is None and t_med is None) or _within_tolerance(s_med, t_med)
        if not ok:
            a2_all_match = False
        s_str = "n/a" if s_med is None else f"{s_med:.2f}s"
        t_str = "n/a" if t_med is None else f"{t_med:.2f}s"
        print(f"  {act!r:35s}  SQL={s_str} n={s_n}   "
              f"Tool={t_str} n={t_n}   {_tick(ok)}")
    locked["A2"] = {
        "metric": "sojourn",
        "top3": [{"activity": a, "n_events": n} for a, n in sql_top3],
        "sojourn_medians_s": {
            a: (None if sql_sojourns.get(a, (None, 0))[0] is None
                else round(sql_sojourns[a][0], 2))
            for a, _ in sql_top3
        },
        "sojourn_counts": {a: sql_sojourns.get(a, (None, 0))[1] for a, _ in sql_top3},
        "agree_top3_set": a2_top3_set_ok,
        "agree_top3_order": a2_top3_order_ok,
        "agree_medians": a2_all_match,
    }

    # ── A3 (REVISED: App + Case_R instead of App + Offer) ──
    print()
    print("-" * 78)
    print("A3: highest-median sync time activity (Application + Case_R) (REVISED)")
    print("-" * 78)
    n_both_app_case = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT eo.ocel_event_id
          FROM event_object eo JOIN object o ON o.ocel_id = eo.ocel_object_id
          WHERE o.ocel_type = 'Application'
          INTERSECT
          SELECT eo.ocel_event_id
          FROM event_object eo JOIN object o ON o.ocel_id = eo.ocel_object_id
          WHERE o.ocel_type = 'Case_R'
        )
        """
    ).fetchone()[0]
    print(f"  Dataset diagnostic: events involving BOTH Application and Case_R = {n_both_app_case}")
    print()
    sql_act, sql_med, sql_n, sql_table = a3_sql(conn)
    tool_act, tool_med, tool_n, _tool_table = a3_tool(ocel_data)
    sql_act_repr = sql_act if sql_act else "<none>"
    tool_act_repr = tool_act if tool_act else "<none>"
    print(f"  SQL  : activity={sql_act_repr!r}  median={sql_med:.2f}s  n={sql_n}")
    print(f"  Tool : activity={tool_act_repr!r}  median={tool_med:.2f}s  n={tool_n}")
    a3_act_ok = sql_act == tool_act
    a3_med_ok = _within_tolerance(sql_med, tool_med) or (sql_n == 0 and tool_n == 0)
    print(f"  Agree on activity: {_tick(a3_act_ok)}")
    print(f"  Agree on count:    {_tick(sql_n == tool_n)}")
    print(f"  Agree on median:   {_tick(a3_med_ok)}")
    print()
    if sql_table:
        print("  Top-5 sync medians by SQL:")
        for act, (med, n) in sorted(sql_table.items(), key=lambda kv: -kv[1][0])[:5]:
            print(f"    {act!r:40s}  median={med/86400:7.3f} d  n={n}")
    locked["A3"] = {
        "object_pair": ["Application", "Case_R"],
        "activity": sql_act,
        "median_s": sql_med,
        "count": sql_n,
        "events_with_both_types": n_both_app_case,
        "agree_activity": a3_act_ok,
        "agree_count": sql_n == tool_n,
        "agree_median": a3_med_ok,
    }

    # ── A4 (REVISED: lagging at A_Complete between App + Case_R) ──
    print()
    print("-" * 78)
    print("A4: lagging time at A_Complete (Application + Case_R) (REVISED)")
    print("-" * 78)
    target_activity = "A_Complete"
    sql_med, sql_n = a4_sql(conn, target_activity)
    tool_med, tool_n = a4_tool(ocel_data, target_activity)
    sql_str = "n/a" if sql_med is None else f"{sql_med:.2f}s"
    tool_str = "n/a" if tool_med is None else f"{tool_med:.2f}s"
    print(f"  Activity: {target_activity!r}")
    print(f"  SQL  : median={sql_str}  n={sql_n}")
    print(f"  Tool : median={tool_str}  n={tool_n}")
    a4_ok = (sql_med is None and tool_med is None) or _within_tolerance(sql_med, tool_med)
    print(f"  Agree on count:  {_tick(sql_n == tool_n)}")
    print(f"  Agree on median: {_tick(a4_ok)}")
    locked["A4"] = {
        "object_pair": ["Application", "Case_R"],
        "activity": target_activity,
        "median_s": sql_med,
        "count": sql_n,
        "agree_count": sql_n == tool_n,
        "agree_median": a4_ok,
    }

    # ── Summary ──
    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"A1 SQL vs Tool:        {_tick(locked['A1']['agree_sql_vs_tool'])}")
    print(f"A1 Tool vs pm4py:      {_tick(locked['A1']['agree_tool_vs_pm4py'])}")
    print(f"A2 top-3 set:          {_tick(locked['A2']['agree_top3_set'])}")
    print(f"A2 sojourn medians:    {_tick(locked['A2']['agree_medians'])}")
    print(f"A3 activity:           {_tick(locked['A3']['agree_activity'])}")
    print(f"A3 median:             {_tick(locked['A3']['agree_median'])}")
    print(f"A4 median:             {_tick(locked['A4']['agree_median'])}")
    print()
    print("Locked dict (for downstream task_set.py update):")
    import json
    print(json.dumps(locked, indent=2, default=str))
    return locked


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Spike green-light #3: independent ground-truth for Order Management Cat-A tasks.

VERIFICATION = TWO INDEPENDENT PATHS (NOT three-way):
  Method 1 (SQL)  : raw SQL on the OCEL 2.0 SQLite log + Python statistics
  Method 2 (Tool) : src.tools.bottleneck.* (the agents' own tools)
  (pm4py is NOT used here; do not describe this as a three-way / pm4py check.)

The SQL definitions are PORTED from scripts/compute_ground_truth.py (BPI 2017),
which already matched the tool definitions there, parametrised by object type.

DATA PROVENANCE
  Dataset : Order Management (artificial OCEL 2.0 log, CPN-simulated)
  Source  : https://www.ocel-standard.org/event-logs/overview/ -> Zenodo
  Zenodo  : record 18373906 (file); concept DOI 10.5281/zenodo.8337463
  File    : order-management.sqlite
  SHA-256 : bec5e88bc9275894a0e29d506a3916925022a61a760a82756e85bd4161a54920
  Fetched : 2026-05-25

OM Cat-A task design (after schema_summary.py + tool probing; see constraints):
  A1 - highest median sojourn activity for ORDERS  -> 'confirm order'
  A2 - top-3 EMPLOYEES activities by OBJECT-EVENT PARTICIPATION frequency +
       their median sojourn. Frequency口径 = object-event participation count
       (COUNT(*)), matching the project tool get_activity_frequency() — NOT
       distinct events. Under this correct semantics the top-3 is UNIQUE:
         1. pick item     n=7659  median sojourn 3,973s
         2. send package  n=2256  median sojourn 6,721s   (1,128 events x 2 employees)
         3. confirm order n=2000  median sojourn 36,300s
       (A 'distinct events' count would wrongly tie reorder item & item out of
       stock at 1,544 and is the wrong口径; do not use it.)
  A3 - highest median SYNCHRONIZATION between EMPLOYEES and ITEMS
       (this pair co-occurs in many events; richer/cleaner than orders x items)
  A4 - LAGGING at 'reorder item' between EMPLOYEES and ITEMS

Run from artifact root:
    cd thesis_workspace/ocpm_artifact
    .venv/bin/python scripts/compute_ground_truth_om.py data/order_management/order-management.sqlite \
        | tee scripts/ground_truth_om_output.txt
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from src.tools.log_loader import load_ocel_log  # noqa: E402
from src.tools import bottleneck  # noqa: E402
from src.tools.variant import get_activity_frequency  # noqa: E402

TOL = 0.05  # +/-5% agreement tolerance (same as the BPI script)

# OM Cat-A specification (object types verified to exist via schema_summary.py)
A1_TYPE = "orders"
A2_TYPE = "employees"
A3_PAIR = ("employees", "items")
A4_PAIR = ("employees", "items")
A4_ACTIVITY = "reorder item"


# ── timestamp parsing (OCEL2 sqlite uses ISO 8601 with 'T') ──
def _parse_dt(ts: str) -> datetime:
    s = str(ts).strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    raise ValueError(f"Unparseable timestamp: {ts!r}")


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _build_event_time_view(conn: sqlite3.Connection) -> None:
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'event\\_%' ESCAPE '\\' "
            "AND name NOT IN ('event_object','event_map_type')"
        )
    ]
    if not tables:
        raise RuntimeError("No event_<activity> tables found; not an OCEL2 sqlite?")
    union = " UNION ALL ".join(f"SELECT ocel_id, ocel_time FROM `{t}`" for t in tables)
    conn.execute("DROP VIEW IF EXISTS v_event_with_time")
    conn.execute(
        "CREATE TEMP VIEW v_event_with_time AS "
        "SELECT e.ocel_id AS ocel_id, e.ocel_type AS activity, t.ocel_time AS ocel_time "
        f"FROM event e JOIN ({union}) t ON t.ocel_id = e.ocel_id"
    )


def _prev_ts_lookup(conn, object_type: str) -> dict[tuple[str, str], str]:
    """{(oid, eid): timestamp of the PREVIOUS event of that object}."""
    rows = conn.execute(
        "SELECT eo.ocel_object_id AS oid, v.ocel_id AS eid, v.ocel_time AS ts "
        "FROM v_event_with_time v "
        "JOIN event_object eo ON eo.ocel_event_id = v.ocel_id "
        "JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "WHERE o.ocel_type = ? ORDER BY oid, ts",
        (object_type,),
    ).fetchall()
    by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for oid, eid, ts in rows:
        by_oid[oid].append((eid, ts))
    out: dict[tuple[str, str], str] = {}
    for oid, seq in by_oid.items():
        for i in range(1, len(seq)):
            out[(oid, seq[i][0])] = seq[i - 1][1]
    return out


def _next_ts_lookup(conn, object_type: str) -> dict[tuple[str, str], str]:
    """{(oid, eid): timestamp of the NEXT event of that object}."""
    rows = conn.execute(
        "SELECT eo.ocel_object_id AS oid, v.ocel_id AS eid, v.ocel_time AS ts "
        "FROM v_event_with_time v "
        "JOIN event_object eo ON eo.ocel_event_id = v.ocel_id "
        "JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "WHERE o.ocel_type = ? ORDER BY oid, ts",
        (object_type,),
    ).fetchall()
    by_oid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for oid, eid, ts in rows:
        by_oid[oid].append((eid, ts))
    out: dict[tuple[str, str], str] = {}
    for oid, seq in by_oid.items():
        for i in range(len(seq) - 1):
            out[(oid, seq[i][0])] = seq[i + 1][1]
    return out


def _report(label: str, sql_val, tool_val, n_sql=None, n_tool=None) -> bool:
    print(f"\n[{label}]")
    print(f"    SQL  : {sql_val:,.1f}" + (f"  (n={n_sql})" if n_sql is not None else ""))
    print(f"    Tool : {tool_val:,.1f}" + (f"  (n={n_tool})" if n_tool is not None else ""))
    base = sql_val or 1.0
    ok = abs(sql_val - tool_val) / base <= TOL
    print(f"    SQL vs Tool within {TOL:.0%}: {'OK' if ok else 'MISMATCH'}")
    return ok


# ── A1: highest median sojourn for ORDERS ──
def sql_median_sojourn_per_activity(conn, object_type: str) -> dict[str, tuple[float, int]]:
    rows = conn.execute(
        "SELECT eo.ocel_object_id AS oid, v.activity AS activity, v.ocel_time AS t "
        "FROM v_event_with_time v "
        "JOIN event_object eo ON eo.ocel_event_id = v.ocel_id "
        "JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "WHERE o.ocel_type = ? ORDER BY oid, t",
        (object_type,),
    ).fetchall()
    per_act: dict[str, list[float]] = {}
    cur, trace = None, []
    def flush(tr):
        for i in range(len(tr) - 1):
            per_act.setdefault(tr[i][0], []).append(tr[i + 1][1] - tr[i][1])
    for oid, act, t in rows:
        if oid != cur:
            flush(trace); trace = []; cur = oid
        trace.append((act, _parse_dt(t).timestamp()))
    flush(trace)
    return {a: (statistics.median(v), len(v)) for a, v in per_act.items() if v}


def run_A1(conn, data):
    sql_map = sql_median_sojourn_per_activity(conn, A1_TYPE)
    top, (med, n) = max(sql_map.items(), key=lambda kv: kv[1][0])
    tool = bottleneck.get_sojourn_time(data, activity=top, object_type=A1_TYPE)
    print(f"\n=== A1  highest median sojourn for {A1_TYPE} ===")
    print(f"  answer: {top!r}")
    _report(f"A1 {top}", med, float(tool["median_s"]), n, tool["count"])
    print(f"  -> GT: '{top} (median sojourn {med:.0f}s, n={n})'")


# ── A2: EMPLOYEES top-3 activities by OBJECT-EVENT PARTICIPATION frequency + sojourn ──
# Frequency semantics MUST match the project tool get_activity_frequency(), which
# counts object-event participation rows (COUNT(*)), NOT distinct events. Under
# this (correct) semantics the employees top-3 is UNIQUE because 'send package'
# involves 2 employee participations per event (1,128 events -> 2,256 rows).
def run_A2(conn, data):
    # SQL frequency = object-event participation count (COUNT(*)), tool-consistent
    freq_rows = conn.execute(
        "SELECT v.activity, COUNT(*) AS n "
        "FROM v_event_with_time v "
        "JOIN event_object eo ON eo.ocel_event_id = v.ocel_id "
        "JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "WHERE o.ocel_type = ? GROUP BY v.activity ORDER BY n DESC",
        (A2_TYPE,),
    ).fetchall()
    sql_freq = {a: n for a, n in freq_rows}
    # Tool frequency cross-check (get_activity_frequency)
    tool_freq = {f["activity"]: f["count"] for f in get_activity_frequency(data, A2_TYPE)["frequencies"]}
    print(f"\n=== A2  top-3 by object-event participation frequency for {A2_TYPE} + sojourn ===")
    print(f"  {'activity':<22} {'SQL n':>8} {'Tool n':>8}  match")
    freq_ok = True
    for a, n in freq_rows:
        tn = tool_freq.get(a, -1)
        m = (n == tn)
        freq_ok &= m
        print(f"    {a:<22} {n:>8} {tn:>8}  {'OK' if m else 'MISMATCH'}")
    ranked = [a for a, _ in freq_rows]
    tie = len(freq_rows) >= 4 and freq_rows[2][1] == freq_rows[3][1]
    print(f"  frequency SQL vs Tool all-match: {freq_ok}; rank-3 tie: {tie}")
    top3 = ranked[:3]
    sql_map = sql_median_sojourn_per_activity(conn, A2_TYPE)
    print("  top-3 sojourn (SQL vs Tool):")
    soj_ok = True
    for a in top3:
        smed, sn = sql_map.get(a, (float("nan"), 0))
        t = bottleneck.get_sojourn_time(data, activity=a, object_type=A2_TYPE)
        soj_ok &= _report(f"A2 {a}", smed, float(t["median_s"]), sn, t["count"])
    gt = "; ".join(f"{a} n={sql_freq[a]} median {sql_map[a][0]:.0f}s" for a in top3)
    print(f"  -> GT (top-3 by participation freq): {gt}")
    print(f"     freq_match={freq_ok}  unique_top3={not tie}  sojourn_match={soj_ok}")


# ── A3: highest median SYNCHRONIZATION between a type pair ──
def sql_sync_rank(conn, ta: str, tb: str) -> dict[str, tuple[float, int]]:
    prev_a, prev_b = _prev_ts_lookup(conn, ta), _prev_ts_lookup(conn, tb)
    rel = conn.execute(
        "SELECT eo.ocel_event_id AS eid, eo.ocel_object_id AS oid, o.ocel_type AS ot, "
        "v.activity AS act FROM event_object eo "
        "JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "JOIN v_event_with_time v ON v.ocel_id = eo.ocel_event_id "
        "WHERE o.ocel_type IN (?, ?)",
        (ta, tb),
    ).fetchall()
    arr: dict[str, dict[str, list[str]]] = defaultdict(lambda: {ta: [], tb: []})
    eid_act: dict[str, str] = {}
    for eid, oid, ot, act in rel:
        eid_act[eid] = act
        ts = (prev_a if ot == ta else prev_b).get((oid, eid))
        if ts is not None:
            arr[eid][ot].append(ts)
    syncs: dict[str, list[float]] = defaultdict(list)
    for eid, pt in arr.items():
        if not pt[ta] or not pt[tb]:
            continue
        a_arr = max(_parse_dt(t) for t in pt[ta])
        b_arr = max(_parse_dt(t) for t in pt[tb])
        syncs[eid_act[eid]].append(abs((a_arr - b_arr).total_seconds()))
    return {a: (statistics.median(v), len(v)) for a, v in syncs.items() if v}


def run_A3(conn, data):
    ta, tb = A3_PAIR
    sql_map = sql_sync_rank(conn, ta, tb)
    top, (med, n) = max(sql_map.items(), key=lambda kv: kv[1][0])
    tr = bottleneck.get_synchronization_time(data, activity=top, object_types=[ta, tb])
    print(f"\n=== A3  highest median synchronization between {ta} & {tb} ===")
    print(f"  answer: {top!r}")
    _report(f"A3 {top}", med, float(tr["median_s"]), n, tr["count"])
    print(f"  -> GT: '{top} (median sync {med:.0f}s, n={n}, types={ta}+{tb})'")


# ── A4: LAGGING at an activity between a type pair ──
def sql_lagging_at(conn, activity: str, ta: str, tb: str) -> tuple[float | None, int]:
    next_a, next_b = _next_ts_lookup(conn, ta), _next_ts_lookup(conn, tb)
    rel = conn.execute(
        "SELECT eo.ocel_event_id AS eid, eo.ocel_object_id AS oid, o.ocel_type AS ot "
        "FROM event_object eo JOIN object o ON o.ocel_id = eo.ocel_object_id "
        "JOIN v_event_with_time v ON v.ocel_id = eo.ocel_event_id "
        "WHERE o.ocel_type IN (?, ?) AND v.activity = ?",
        (ta, tb, activity),
    ).fetchall()
    dep: dict[str, dict[str, list[str]]] = defaultdict(lambda: {ta: [], tb: []})
    for eid, oid, ot in rel:
        ts = (next_a if ot == ta else next_b).get((oid, eid))
        if ts is not None:
            dep[eid][ot].append(ts)
    lags: list[float] = []
    for _eid, pt in dep.items():
        if not pt[ta] or not pt[tb]:
            continue
        a_dep = min(_parse_dt(t) for t in pt[ta])
        b_dep = min(_parse_dt(t) for t in pt[tb])
        lags.append(abs((a_dep - b_dep).total_seconds()))
    return (statistics.median(lags), len(lags)) if lags else (None, 0)


def run_A4(conn, data):
    ta, tb = A4_PAIR
    med, n = sql_lagging_at(conn, A4_ACTIVITY, ta, tb)
    tr = bottleneck.get_lagging_time(data, A4_ACTIVITY, [ta, tb])
    print(f"\n=== A4  lagging at '{A4_ACTIVITY}' between {ta} & {tb} ===")
    if med is None:
        print("  no lagging observations — choose another activity/pair")
        return
    _report(f"A4 {A4_ACTIVITY}", med, float(tr["median_s"]), n, tr["count"])
    print(f"  -> GT: 'lagging at {A4_ACTIVITY} = {med:.0f}s (n={n}, types={ta}+{tb})'")


def main(path: str) -> None:
    data = load_ocel_log(path)
    conn = _connect(path); _build_event_time_view(conn)
    print(f"Loaded {path}\nobject types: {data.object_types}")
    run_A1(conn, data)
    run_A2(conn, data)
    run_A3(conn, data)
    run_A4(conn, data)
    conn.close()
    print("\nDONE. If all 'SQL vs Tool' = OK, paste the GT lines into OM_TASK_SET.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else str(__import__("src.config", fromlist=["Config"]).Config.from_env().data_path))

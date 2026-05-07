#!/usr/bin/env python3
"""Smoke tests for all 14 OCPM artifact tools.

Verifies each tool returns a valid response on real BPI 2017 data,
including graceful handling of invalid inputs (e.g., non-existent O2O pairs
or activities with no co-occurring object types).

Tools covered (14 total):
    log_loader.py:   load_ocel_log, get_log_summary
    bottleneck.py:   get_sojourn_time, get_waiting_time, get_synchronization_time,
                     get_pooling_time, get_lagging_time, rank_activities_by_metric
    correlation.py:  correlation_object_count_vs_flow_time,
                     get_object_interaction_patterns
    variant.py:      get_activity_frequency, get_slowest_percentile,
                     compare_slow_vs_median

Run with:
    .venv/bin/python -m pytest tests/test_tools.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.bottleneck import (
    get_lagging_time,
    get_pooling_time,
    get_sojourn_time,
    get_synchronization_time,
    get_waiting_time,
    rank_activities_by_metric,
)
from src.tools.correlation import (
    correlation_object_count_vs_flow_time,
    get_object_interaction_patterns,
)
from src.tools.log_loader import get_log_summary, load_ocel_log
from src.tools.variant import (
    compare_slow_vs_median,
    get_activity_frequency,
    get_slowest_percentile,
)

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "bpi2017" / "bpic2017.sqlite"
)

pytestmark = pytest.mark.skipif(
    not DATA_PATH.exists(),
    reason=f"BPI 2017 SQLite log not found at {DATA_PATH}",
)


@pytest.fixture(scope="module")
def data():
    """Load BPI 2017 log once for the whole module (load_ocel_log is expensive)."""
    return load_ocel_log(str(DATA_PATH))


# ── log_loader (2 tools) ─────────────────────────────────────────────────────


def test_load_ocel_log_basic(data):
    """load_ocel_log should produce a 4-object-type, multi-million-relation OCELData."""
    assert len(data.object_types) == 4
    assert "Application" in data.object_types
    assert "Offer" in data.object_types
    assert "Case_R" in data.object_types
    assert "Workflow" in data.object_types
    assert len(data.e2o_df) > 2_000_000


def test_get_log_summary_includes_o2o(data):
    """get_log_summary must report exactly 2 O2O pairs in BPI 2017."""
    s = get_log_summary(data)

    assert s["num_events"] > 1_000_000
    assert s["num_objects"] > 100_000
    assert s["num_o2o_relations"] > 70_000
    assert s["num_object_types"] == 4
    assert "o2o_relationships" in s

    pairs = s["o2o_relationships"]
    # BPI 2017 has only TWO valid O2O pairs.
    assert len(pairs) == 2

    types_pairs = {(p["parent_type"], p["child_type"]) for p in pairs}
    assert ("Application", "Offer") in types_pairs
    assert ("Application", "Workflow") in types_pairs

    # Verified link counts from prior ground-truth investigation.
    counts = {(p["parent_type"], p["child_type"]): p["n_links"] for p in pairs}
    assert counts[("Application", "Offer")] == 42995
    assert counts[("Application", "Workflow")] == 31509


# ── bottleneck (6 tools) ─────────────────────────────────────────────────────


def test_sojourn_time_application_complete(data):
    """A_Complete on Application: ground-truth median ≈ 861382s, count = 31309."""
    r = get_sojourn_time(data, "A_Complete", "Application")
    assert r["count"] == 31309
    assert abs(r["median_s"] - 861382) < 5.0  # Allow a few seconds rounding tolerance.
    assert r["unit"] == "seconds"
    assert r["activity"] == "A_Complete"
    assert r["object_type"] == "Application"


def test_waiting_time_application_validating(data):
    """get_waiting_time should produce a valid distribution for A_Validating."""
    r = get_waiting_time(data, "A_Validating", "Application")
    assert r["count"] > 0
    assert r["median_s"] > 0
    assert r["p25_s"] <= r["median_s"] <= r["p75_s"]
    assert r["unit"] == "seconds"


def test_synchronization_time_app_caser_cancelled(data):
    """Application + Case_R DO co-occur (large median sync time)."""
    r = get_synchronization_time(data, "A_Cancelled", ["Application", "Case_R"])
    assert r["count"] > 0
    assert r["median_s"] is not None
    assert r["median_s"] > 1_000_000  # Verified ≈ 2.65M seconds.


def test_synchronization_time_no_cooccurrence_returns_zero(data):
    """Application + Offer never co-occur as object pair on Application events.

    The function must NOT raise; it should return count == 0 cleanly.
    """
    r = get_synchronization_time(data, "A_Complete", ["Application", "Offer"])
    assert r["count"] == 0
    # median_s may be None; the contract is just "no crash".


def test_synchronization_time_skips_missing_type(data):
    """Even when one type has no involvement, the function must return cleanly."""
    r = get_synchronization_time(data, "A_Validating", ["Application", "Case_R"])
    assert r["count"] >= 0  # Just verify no crash; non-negative count.


def test_pooling_time_no_same_type_pairs(data):
    """BPI 2017 has no events with ≥2 same-type objects → count == 0, no raise."""
    r = get_pooling_time(data, "A_Complete", "Application")
    assert r["count"] == 0
    # Pooling is structurally undefined on this log.


def test_lagging_time_app_caser_complete(data):
    """A_Complete + [Application, Case_R]: median lag ≈ 860588s, count > 30k."""
    r = get_lagging_time(data, "A_Complete", ["Application", "Case_R"])
    assert r["count"] > 30_000
    assert r["median_s"] is not None
    assert abs(r["median_s"] - 860588) < 5.0


def test_rank_activities_by_metric(data):
    """rank_activities_by_metric should rank Application sojourn with A_Complete on top."""
    r = rank_activities_by_metric(data, "sojourn", "Application", top_n=5)
    assert "ranking" in r
    assert len(r["ranking"]) == 5

    # Top entry should be A_Complete with count 31309.
    top = r["ranking"][0]
    assert top["activity"] == "A_Complete"
    assert top["count"] == 31309

    # Ranking must be sorted descending by median_s.
    medians = [row["median_s"] for row in r["ranking"]]
    assert medians == sorted(medians, reverse=True)


# ── correlation (2 tools) ────────────────────────────────────────────────────


def test_correlation_valid_pair_app_offer(data):
    """Application → Offer has O2O links; expect Pearson r ≈ 0.22, n ≈ 31509."""
    r = correlation_object_count_vs_flow_time(data, "Application", "Offer")
    assert "error" not in r
    assert r["n"] > 30_000
    assert "pearson_r" in r
    assert "spearman_rho" in r
    # Verified value is small but positive.
    assert 0.1 < r["pearson_r"] < 0.4


def test_correlation_invalid_pair_graceful(data):
    """Case_R + Workflow have no O2O links; tool reports error, does not raise."""
    r = correlation_object_count_vs_flow_time(data, "Case_R", "Workflow")
    assert "error" in r
    assert r["n"] == 0


def test_get_object_interaction_patterns_a_validating(data):
    """A_Validating: ~100% Application + Case_R co-occurrence."""
    r = get_object_interaction_patterns(data, "A_Validating")
    assert r["total_events"] > 30_000
    assert len(r["patterns"]) >= 1

    top = r["patterns"][0]
    types = sorted(top["object_types"])
    assert "Application" in types
    assert "Case_R" in types
    assert top["pct"] > 99.0  # Should be ~100%.


# ── variant (3 tools) ────────────────────────────────────────────────────────


def test_activity_frequency_offer(data):
    """Offer's most frequent activities: O_Create Offer / O_Created tied at 42995."""
    r = get_activity_frequency(data, "Offer")
    assert r["object_type"] == "Offer"
    assert r["total_events"] > 100_000
    assert len(r["frequencies"]) > 0

    top = r["frequencies"][0]
    assert top["count"] == 42995
    assert top["activity"] in ("O_Create Offer", "O_Created")

    # Percentages should sum to ~100.
    total_pct = sum(f["pct"] for f in r["frequencies"])
    assert 99.0 <= total_pct <= 101.0


def test_slowest_percentile_application(data):
    """get_slowest_percentile returns: object_type, percentile, threshold_s,
    count, total_objects, slowest_objects."""
    r = get_slowest_percentile(data, "Application", 90.0)
    assert r["object_type"] == "Application"
    assert r["percentile"] == 90.0
    assert r["total_objects"] > 0
    assert r["count"] > 0
    assert r["count"] <= r["total_objects"]
    assert r["threshold_s"] is not None
    assert r["threshold_s"] > 0
    # slowest_objects is a preview list (capped at 20).
    assert isinstance(r["slowest_objects"], list)
    assert len(r["slowest_objects"]) <= 20


def test_compare_slow_vs_median_application(data):
    """compare_slow_vs_median returns slow_group, median_group, feature_diffs.

    By construction (slow = top 10%, median = middle 20%), slow group's mean
    flow time must exceed median group's, and the ratio must be ≥ 1.0.
    """
    r = compare_slow_vs_median(data, "Application")
    assert "error" not in r
    assert "slow_group" in r
    assert "median_group" in r
    assert "feature_diffs" in r

    slow = r["slow_group"]
    med = r["median_group"]
    diffs = r["feature_diffs"]

    assert slow["mean_flow_time_s"] > 0
    assert med["mean_flow_time_s"] > 0
    assert slow["mean_flow_time_s"] > med["mean_flow_time_s"]
    assert diffs["flow_time_ratio"] >= 1.0

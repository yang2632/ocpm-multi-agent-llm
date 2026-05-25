"""12 evaluation tasks (A1-C4) as structured objects.

Tasks match Method.tex Table 3.1 exactly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalTask:
    """A single evaluation task."""

    task_id: str
    category: str  # "A", "B", or "C"
    open_closed: str  # "C" (closed) or "O" (open)
    question: str
    ground_truth: str  # For A: expected value; for B/C: acceptance criteria
    evidence_type: str  # What kind of evidence is expected


TASK_SET: tuple[EvalTask, ...] = (
    # ── Category A: Bottleneck Identification (closed, ground-truth) ──
    EvalTask(
        task_id="A1",
        category="A",
        open_closed="C",
        question=(
            "Which activity has the highest median sojourn time for "
            "application objects?"
        ),
        # Verified independently by raw SQL (with Python median) on the OCEL
        # 2.0 SQLite log AND by pm4py.statistics.ocel.edge_metrics aggregating
        # outgoing-edge times per source activity for the Application object
        # type. All three methods (raw SQL, project tool, pm4py) agree
        # exactly: A_Complete with median sojourn = 861382 s ~= 9.97 days
        # (n=31,309). See scripts/compute_ground_truth.py.
        ground_truth=(
            "A_Complete (median sojourn 861382s ~= 9.97 days, n=31309); "
            "verified independently via raw SQL on the OCEL 2.0 SQLite log "
            "and via pm4py edge_metrics."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="A2",
        category="A",
        open_closed="C",
        question=(
            "How does the sojourn time distribution for offer objects compare "
            "across the three highest-frequency activities?"
        ),
        # Changed from waiting time to sojourn time because O_Create Offer
        # (one of the top-3 by frequency) has zero valid waiting-time
        # observations: it is the first event of every Offer's lifecycle so
        # it has no predecessor. Sojourn time (current_ts -> next_ts) is
        # well-defined for all three activities.
        # Top-3 most-frequent Offer activities:
        #   O_Create Offer            : n=42,995
        #   O_Created                 : n=42,995  (tied with above)
        #   O_Sent (mail and online)  : n=39,707
        # Median sojourn times (verified via project tool; SQL cross-check
        # consistent within +/-5%):
        #   O_Create Offer            : 1 s         (n=42,995)
        #   O_Created                 : 29 s        (n=42,995)
        #   O_Sent (mail and online)  : 941,202 s   (n=39,599; ~10.9 days)
        ground_truth=(
            "Top-3 most-frequent activities for Offer objects: "
            "O_Create Offer (n=42995), O_Created (n=42995), "
            "O_Sent (mail and online) (n=39707). "
            "Median sojourn times: "
            "O_Create Offer = 1 s (n=42995); "
            "O_Created = 29 s (n=42995); "
            "O_Sent (mail and online) = 941202 s ~= 10.9 days (n=39599). "
            "Distribution shows two near-instant activities and one with a "
            "very long tail (O_Sent). Verified via project tool against the "
            "OCEL 2.0 SQLite log."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="A3",
        category="A",
        open_closed="C",
        question=(
            "Which activity transition exhibits the highest synchronization "
            "time between application and Case_R objects?"
        ),
        # Changed pair from Application+Offer to Application+Case_R because
        # the original pair never co-occurs in events on this log (E2O
        # has zero shared events; Application<->Offer linkage exists only
        # via O2O). Application+Case_R co-occurs in 239,595 events, making
        # OPerA synchronization computable.
        # Verified via project tool: highest median sync time across all
        # 26 activities is at A_Cancelled (median 2,650,388.5 s ~= 30.7 days,
        # n=10,430 events with both Application and Case_R arrivals).
        # Top-5 ranking:
        #   A_Cancelled    : 2,650,388.5 s (n=10,430)
        #   A_Validating   :   501,617.0 s (n=38,816)
        #   A_Denied       :   169,663.0 s (n= 3,751)
        #   A_Pending      :    77,798.0 s (n=17,228)
        #   A_Incomplete   :    74,519.0 s (n=23,055)
        ground_truth=(
            "A_Cancelled exhibits the highest median synchronization time "
            "between Application and Case_R objects: median 2650388.5 s "
            "~= 30.7 days, n=10430 events with both arrivals. "
            "Verified via project tool against the OCEL 2.0 SQLite log."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="A4",
        category="A",
        open_closed="C",
        question=(
            "What is the lagging time between application and Case_R objects "
            "at the activity A_Complete (the application lifecycle terminator)?"
        ),
        # Changed from pooling time to lagging time because OPerA pooling
        # is structurally undefined on BPI 2017 (every event has at most
        # one object per type; pooling requires >=2 same-type objects at
        # the same event). Lagging time is well-defined for cross-type
        # pairs that co-occur in events: A_Complete is the application
        # lifecycle terminator and has n=31,303 events with both
        # Application and Case_R departures.
        # Verified via project tool: median lagging time at A_Complete
        # between Application and Case_R = 860,588 s ~= 9.96 days, n=31,303.
        ground_truth=(
            "Median lagging time at A_Complete between Application and "
            "Case_R = 860588 s ~= 9.96 days, n=31303. "
            "Verified via project tool against the OCEL 2.0 SQLite log."
        ),
        evidence_type="quantitative",
    ),
    # ── Category B: Root-Cause Hypothesis (open, rubric-scored) ──────
    EvalTask(
        task_id="B1",
        category="B",
        open_closed="O",
        question=(
            "What object-type interaction patterns could explain the "
            "identified bottleneck activity?"
        ),
        ground_truth=(
            "Rubric: evidence grounding, analytical depth, factual alignment"
        ),
        evidence_type="analytical",
    ),
    EvalTask(
        task_id="B2",
        category="B",
        open_closed="O",
        question=(
            "Is there a relationship between the number of offers per "
            "application and the application's total flow time?"
        ),
        ground_truth=(
            "Rubric; partial verification via computed correlation"
        ),
        evidence_type="analytical",
    ),
    EvalTask(
        task_id="B3",
        category="B",
        open_closed="O",
        question=(
            "What structural features distinguish the slowest 10% of "
            "applications from the median?"
        ),
        ground_truth="Rubric; partial verification via variant analysis",
        evidence_type="analytical",
    ),
    EvalTask(
        task_id="B4",
        category="B",
        open_closed="O",
        question=(
            "Propose a causal chain explaining why a specific activity has "
            "disproportionately high synchronization time."
        ),
        ground_truth=(
            "Rubric: causal coherence, evidence use, stated assumptions"
        ),
        evidence_type="analytical",
    ),
    # ── Category C: Integrated Analysis (open, rubric-scored) ────────
    EvalTask(
        task_id="C1",
        category="C",
        open_closed="O",
        question=(
            "Produce a structured report identifying the primary bottleneck, "
            "its likely root cause, and one improvement recommendation."
        ),
        ground_truth=(
            "Rubric: completeness, evidence integration, analytical coherence"
        ),
        evidence_type="integrated",
    ),
    EvalTask(
        task_id="C2",
        category="C",
        open_closed="O",
        question=(
            "Compare the performance diagnosis from the application "
            "perspective versus the offer perspective."
        ),
        ground_truth="Rubric: cross-type reasoning, evidence grounding",
        evidence_type="integrated",
    ),
    EvalTask(
        task_id="C3",
        category="C",
        open_closed="O",
        question=(
            "Decompose the observed application flow time into the "
            "contributions of offer-side activities versus other components. "
            "Based on this decomposition, characterize whether and under what "
            "assumptions reducing offer processing time would meaningfully "
            "shift overall flow time."
        ),
        ground_truth=(
            "Rubric: quantitative reasoning, assumption transparency"
        ),
        evidence_type="integrated",
    ),
    EvalTask(
        task_id="C4",
        category="C",
        open_closed="O",
        question=(
            "An analyst claims that activity X causes most delays. Evaluate "
            "this claim using available evidence."
        ),
        ground_truth=(
            "Rubric: critical evaluation, counter-evidence consideration"
        ),
        evidence_type="integrated",
    ),
)


def get_tasks_by_category(category: str, dataset: str = "bpi2017") -> list[EvalTask]:
    return [t for t in get_task_set(dataset) if t.category == category]


def get_task_by_id(task_id: str, dataset: str = "bpi2017") -> EvalTask | None:
    for t in get_task_set(dataset):
        if t.task_id == task_id:
            return t
    return None


# ════════════════════════════════════════════════════════════════════
# Order Management task set (second dataset, OCEL 2.0, ocel-standard.org)
# ════════════════════════════════════════════════════════════════════
# Cat-A ground truth was verified by TWO independent paths (raw SQL + project
# tool) on order-management.sqlite (sha256 bec5e88b...a54920); SQL == Tool
# exactly for all four. See scripts/compute_ground_truth_om.py.
# Cat-B/C are re-grounded to OM's object structure (orders, items, packages,
# customers, employees, products) and are DRAFTS pending review.
OM_TASK_SET: tuple[EvalTask, ...] = (
    # ── Category A: Bottleneck Identification (closed, ground-truth) ──
    EvalTask(
        task_id="OM-A1",
        category="A",
        open_closed="C",
        question=(
            "Which activity has the highest median sojourn time for order objects?"
        ),
        ground_truth=(
            "confirm order (median sojourn 606564s, n=2000); verified independently "
            "via raw SQL on the OCEL 2.0 SQLite log and the project sojourn tool "
            "(SQL == tool exactly)."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="OM-A2",
        category="A",
        open_closed="C",
        question=(
            "For employee objects, identify the three activities with the highest "
            "employee-event participation frequency and report their median sojourn "
            "times."
        ),
        ground_truth=(
            "Top-3 by object-event participation frequency (COUNT of employee-event "
            "rows, matching get_activity_frequency): pick item (n=7659, median "
            "sojourn 3973s); send package (n=2256, median 6721s); confirm order "
            "(n=2000, median 36300s). Unique top-3 under participation count; "
            "SQL == tool exactly."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="OM-A3",
        category="A",
        open_closed="C",
        question=(
            "Which activity exhibits the highest median synchronization time between "
            "employees and items?"
        ),
        ground_truth=(
            "pick item (median sync 77564s, n=7652, object types employees+items); "
            "verified via raw SQL and the project synchronization tool (SQL == tool)."
        ),
        evidence_type="quantitative",
    ),
    EvalTask(
        task_id="OM-A4",
        category="A",
        open_closed="C",
        question=(
            "What is the lagging time at activity 'reorder item' between employees "
            "and items?"
        ),
        ground_truth=(
            "Median lagging at reorder item = 295732s (n=1544, object types "
            "employees+items); verified via raw SQL and the project lagging tool "
            "(SQL == tool)."
        ),
        evidence_type="quantitative",
    ),
    # ── Category B: Root-Cause Hypothesis (open, rubric) — DRAFT ──
    EvalTask(
        task_id="OM-B1",
        category="B",
        open_closed="O",
        question=(
            "What object-type interaction patterns could explain why 'confirm order' "
            "has the highest sojourn time for order objects?"
        ),
        ground_truth="Rubric: evidence grounding, analytical depth, factual alignment",
        evidence_type="hypothesis",
    ),
    EvalTask(
        task_id="OM-B2",
        category="B",
        open_closed="O",
        question=(
            "Is there a relationship between the number of items per order and the "
            "order's total flow time?"
        ),
        ground_truth="Rubric; partial verification via computed correlation (orders->items O2O)",
        evidence_type="hypothesis",
    ),
    EvalTask(
        task_id="OM-B3",
        category="B",
        open_closed="O",
        question=(
            "What structural features distinguish the slowest 10% of orders from the "
            "median order?"
        ),
        ground_truth="Rubric; partial verification via variant analysis",
        evidence_type="hypothesis",
    ),
    EvalTask(
        task_id="OM-B4",
        category="B",
        open_closed="O",
        question=(
            "Propose a causal chain explaining why 'reorder item' shows "
            "disproportionately high lagging time between employees and items."
        ),
        ground_truth="Rubric: causal coherence, evidence use, stated assumptions",
        evidence_type="hypothesis",
    ),
    # ── Category C: Integrated Analysis (open, rubric) — DRAFT ──
    EvalTask(
        task_id="OM-C1",
        category="C",
        open_closed="O",
        question=(
            "Produce a structured report identifying the primary bottleneck in the "
            "order-to-delivery process, its likely root cause, and one improvement "
            "recommendation."
        ),
        ground_truth="Rubric: completeness, evidence integration, analytical coherence",
        evidence_type="report",
    ),
    EvalTask(
        task_id="OM-C2",
        category="C",
        open_closed="O",
        question=(
            "Compare the performance diagnosis from the order perspective versus the "
            "item perspective."
        ),
        ground_truth="Rubric: cross-type reasoning, evidence grounding",
        evidence_type="report",
    ),
    EvalTask(
        task_id="OM-C3",
        category="C",
        open_closed="O",
        question=(
            "Decompose the observed order flow time into contributions from "
            "item-handling activities versus packaging and delivery activities. Based "
            "on this decomposition, characterise whether and under what assumptions "
            "reducing item-handling time would meaningfully shift overall flow time."
        ),
        ground_truth="Rubric: quantitative reasoning, assumption transparency",
        evidence_type="report",
    ),
    EvalTask(
        task_id="OM-C4",
        category="C",
        open_closed="O",
        question=(
            "An analyst claims that 'reorder item' causes most delays. Evaluate this "
            "claim using available evidence."
        ),
        ground_truth="Rubric: critical evaluation, counter-evidence consideration",
        evidence_type="report",
    ),
)


# ── Dataset-keyed task-set registry ──
TASK_SETS: dict[str, tuple[EvalTask, ...]] = {
    "bpi2017": TASK_SET,          # the original 12 tasks, unchanged
    "order_management": OM_TASK_SET,
}


def get_task_set(dataset: str) -> tuple[EvalTask, ...]:
    if dataset not in TASK_SETS:
        raise ValueError(f"Unknown dataset '{dataset}'. Known: {list(TASK_SETS)}")
    return TASK_SETS[dataset]

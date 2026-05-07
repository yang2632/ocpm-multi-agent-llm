"""Central tool dispatch: maps function names to OCPM tool implementations."""

from __future__ import annotations

from typing import Any

from ..tools.log_loader import OCELData, get_log_summary
from ..tools.bottleneck import (
    get_sojourn_time,
    get_waiting_time,
    get_synchronization_time,
    get_pooling_time,
    get_lagging_time,
    rank_activities_by_metric,
)
from ..tools.variant import (
    get_activity_frequency,
    get_slowest_percentile,
    compare_slow_vs_median,
)
from ..tools.correlation import (
    correlation_object_count_vs_flow_time,
    get_object_interaction_patterns,
)


def execute_tool_call(
    ocel_data: OCELData, tool_name: str, args: dict[str, Any]
) -> Any:
    """Dispatch a tool call to the appropriate OCPM function.

    Returns the tool's result as a JSON-serializable dict.
    """
    dispatch = {
        "get_log_summary": lambda: get_log_summary(ocel_data),
        "get_sojourn_time": lambda: get_sojourn_time(
            ocel_data, args["activity"], args["object_type"]
        ),
        "get_waiting_time": lambda: get_waiting_time(
            ocel_data, args["activity"], args["object_type"]
        ),
        "get_synchronization_time": lambda: get_synchronization_time(
            ocel_data, args["activity"], args["object_types"]
        ),
        "get_pooling_time": lambda: get_pooling_time(
            ocel_data, args["activity"], args["object_type"]
        ),
        "get_lagging_time": lambda: get_lagging_time(
            ocel_data, args["activity"], args["object_types"]
        ),
        "rank_activities_by_metric": lambda: rank_activities_by_metric(
            ocel_data, args["metric"], args["object_type"], args.get("top_n", 5)
        ),
        "get_activity_frequency": lambda: get_activity_frequency(
            ocel_data, args["object_type"]
        ),
        "get_slowest_percentile": lambda: get_slowest_percentile(
            ocel_data, args["object_type"], args.get("percentile", 90.0)
        ),
        "compare_slow_vs_median": lambda: compare_slow_vs_median(
            ocel_data, args["object_type"]
        ),
        "correlation_object_count_vs_flow_time": lambda: correlation_object_count_vs_flow_time(
            ocel_data, args["parent_type"], args["child_type"]
        ),
        "get_object_interaction_patterns": lambda: get_object_interaction_patterns(
            ocel_data, args["activity"]
        ),
    }

    handler = dispatch.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return handler()
    except Exception as e:
        return {"error": f"{tool_name} failed: {e!s}"}

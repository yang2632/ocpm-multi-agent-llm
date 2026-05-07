"""Tool definitions for LLM function calling (OpenAI format).

LangChain automatically converts these to provider-specific formats.
"""

from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_log_summary",
            "description": "Get a summary of the loaded OCEL 2.0 event log: number of events, objects, object types, and activities. CRITICALLY also returns 'o2o_relationships' — the list of valid (parent_type, child_type) pairs that have O2O links in the log. Only these pairs can be queried with correlation_object_count_vs_flow_time. ALWAYS call this tool first to discover what relationships exist before attempting cross-type analysis.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sojourn_time",
            "description": "Compute sojourn time (time from arrival to departure) for a specific activity and object type. Returns median, mean, std in seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name to analyze.",
                    },
                    "object_type": {
                        "type": "string",
                        "description": "The object type (e.g., 'application', 'offer').",
                    },
                },
                "required": ["activity", "object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_waiting_time",
            "description": "Compute waiting time (time between previous activity completion and current activity start) for a specific activity and object type. Returns median, mean, std, p25, p75 in seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name to analyze.",
                    },
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                },
                "required": ["activity", "object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_synchronization_time",
            "description": "Compute synchronization time at an activity across multiple object types. Measures delay caused by waiting for different object types to converge.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name.",
                    },
                    "object_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of object types (at least 2).",
                    },
                },
                "required": ["activity", "object_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pooling_time",
            "description": "Compute pooling time at an activity for a given object type. Measures how long objects of the same type wait to accumulate before proceeding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name.",
                    },
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                },
                "required": ["activity", "object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lagging_time",
            "description": "Compute lagging time at an activity across object types. Measures delay between fastest and slowest departing object type after an event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name.",
                    },
                    "object_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of object types (at least 2).",
                    },
                },
                "required": ["activity", "object_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_activities_by_metric",
            "description": "Rank all activities by a performance metric (sojourn, waiting, or pooling) for a given object type. Returns top N activities sorted by median time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["sojourn", "waiting", "pooling"],
                        "description": "The OPerA metric to rank by.",
                    },
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Number of top activities to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["metric", "object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_frequency",
            "description": "Get activity frequency ranking for a given object type. Returns count and percentage for each activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                },
                "required": ["object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_slowest_percentile",
            "description": "Identify the slowest N% of objects by total flow time. Returns threshold and list of slowest objects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                    "percentile": {
                        "type": "number",
                        "description": "Percentile threshold (e.g., 90 for slowest 10%). Default 90.",
                        "default": 90.0,
                    },
                },
                "required": ["object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_slow_vs_median",
            "description": "Compare structural features (event count, activity distribution, flow time) of the slowest 10% objects versus median objects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_type": {
                        "type": "string",
                        "description": "The object type.",
                    },
                },
                "required": ["object_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correlation_object_count_vs_flow_time",
            "description": "Compute correlation between the number of child objects per parent object and the parent's total flow time. Returns Pearson and Spearman correlations. PRECONDITION: the (parent_type, child_type) pair must appear in get_log_summary's 'o2o_relationships' list; calling with non-existent pairs returns an empty result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_type": {
                        "type": "string",
                        "description": "Parent object type (e.g., 'application').",
                    },
                    "child_type": {
                        "type": "string",
                        "description": "Child object type (e.g., 'offer').",
                    },
                },
                "required": ["parent_type", "child_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_object_interaction_patterns",
            "description": "Analyze object type co-occurrence patterns at a specific activity. Shows which object types appear together and how many objects per type per event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {
                        "type": "string",
                        "description": "The activity name.",
                    },
                },
                "required": ["activity"],
            },
        },
    },
]

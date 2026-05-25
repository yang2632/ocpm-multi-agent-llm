"""Multi-agent artifact: Planner → Analyst → Synthesizer (LangGraph, 3 nodes)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from ..tools.log_loader import OCELData
from .llm_provider import create_llm
from ._tool_executor import execute_tool_call

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class MultiAgentState(TypedDict):
    """State threaded through the multi-agent graph."""

    question: str
    messages: list  # full message history for LLM context
    plan: list[dict]  # list of subtask dicts from Planner
    current_subtask_idx: int
    subtask_results: list[dict]
    tool_calls_log: list[dict]
    final_answer: str
    timestamps: dict


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def build_multi_agent_graph(
    ocel_data: OCELData,
    provider: str = "openai",
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    api_key: str = "",
    base_url: str = "",
):
    """Build a LangGraph StateGraph for the multi-agent artifact.

    Graph: [START] → Planner → Analyst ⟲ (loop over subtasks) → Synthesizer → [END]
    """
    from ..tools.schema import TOOL_DEFINITIONS

    llm = create_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=base_url,
    )
    llm_with_tools = llm.bind_tools(TOOL_DEFINITIONS)

    # Inject the dataset-agnostic log profile (same builder as single-agent),
    # replacing dataset-specific hardcoding in the planner prompt.
    from ..tools.log_loader import get_log_summary, build_log_profile

    _profile = build_log_profile(get_log_summary(ocel_data))
    planner_prompt = _load_prompt("planner").replace("{log_profile}", _profile)
    analyst_prompt = _load_prompt("analyst").replace("{log_profile}", _profile)
    synthesizer_prompt = _load_prompt("synthesizer").replace("{log_profile}", _profile)

    # ── Planner Node ──────────────────────────────────────────────

    def planner_node(state: MultiAgentState) -> dict:
        """Decompose the question into ordered subtasks."""
        messages = [
            SystemMessage(content=planner_prompt),
            HumanMessage(
                content=(
                    f"Question: {state['question']}\n\n"
                    "Decompose this into subtasks. Return a JSON array of objects "
                    'with keys: id, description, tool_hint.'
                )
            ),
        ]
        response = llm.invoke(messages)

        # Parse the plan from LLM response
        plan = _parse_plan(response.content)

        timestamps = dict(state["timestamps"])
        timestamps["planner_done"] = time.time()

        return {
            "plan": plan,
            "current_subtask_idx": 0,
            "timestamps": timestamps,
            "messages": list(state["messages"])
            + [
                SystemMessage(content="[Planner output]"),
                AIMessage(content=response.content),
            ],
        }

    # ── Analyst Node ──────────────────────────────────────────────

    def analyst_node(state: MultiAgentState) -> dict:
        """Execute the current subtask using tools."""
        idx = state["current_subtask_idx"]
        plan = state["plan"]

        if idx >= len(plan):
            return state

        subtask = plan[idx]
        messages = [
            SystemMessage(content=analyst_prompt),
            HumanMessage(
                content=(
                    f"Original question: {state['question']}\n\n"
                    f"Subtask {subtask['id']}: {subtask['description']}\n"
                    f"Tool hint: {subtask.get('tool_hint', 'use appropriate tool')}\n\n"
                    "Execute this subtask using the available tools."
                )
            ),
        ]

        # LLM may need multiple tool calls for one subtask
        tool_log = list(state["tool_calls_log"])
        all_messages = list(messages)
        # Bumped from 5 to 15 per audit Gap #8: previous setting caused ~30%
        # of subtasks to return empty findings due to budget exhaustion.
        max_tool_rounds = 15

        for _ in range(max_tool_rounds):
            response = llm_with_tools.invoke(all_messages)
            all_messages.append(response)

            if not (isinstance(response, AIMessage) and response.tool_calls):
                break

            for tc in response.tool_calls:
                t0 = time.perf_counter()
                result = execute_tool_call(ocel_data, tc["name"], tc["args"])
                elapsed = time.perf_counter() - t0

                result_str = json.dumps(result, default=str)
                all_messages.append(
                    ToolMessage(content=result_str, tool_call_id=tc["id"])
                )
                tool_log.append(
                    {
                        "subtask_id": subtask["id"],
                        "tool": tc["name"],
                        "args": tc["args"],
                        "result_preview": result_str[:500],
                        "elapsed_s": round(elapsed, 3),
                    }
                )

        # Extract analyst's finding from last AI message
        finding = ""
        for msg in reversed(all_messages):
            if isinstance(msg, AIMessage) and msg.content:
                finding = msg.content
                break

        finding_text = (
            finding
            if (finding and str(finding).strip())
            else "(no result returned within tool budget)"
        )
        subtask_results = list(state["subtask_results"]) + [
            {
                "subtask_id": subtask["id"],
                "description": subtask["description"],
                "finding": finding_text,
            }
        ]

        # Update main message history with a summary
        main_messages = list(state["messages"]) + [
            SystemMessage(
                content=f"[Analyst result for subtask {subtask['id']}]"
            ),
            AIMessage(content=finding_text),
        ]

        return {
            "subtask_results": subtask_results,
            "current_subtask_idx": idx + 1,
            "tool_calls_log": tool_log,
            "messages": main_messages,
        }

    # ── Synthesizer Node ──────────────────────────────────────────

    def synthesizer_node(state: MultiAgentState) -> dict:
        """Synthesize all subtask results into a final answer."""
        results_text = "\n\n".join(
            f"--- Subtask {r['subtask_id']}: {r['description']} ---\n{r['finding']}"
            for r in state["subtask_results"]
        )

        messages = [
            SystemMessage(content=synthesizer_prompt),
            HumanMessage(
                content=(
                    f"Original question: {state['question']}\n\n"
                    f"Intermediate analysis results:\n{results_text}\n\n"
                    "Synthesize these findings into a comprehensive final answer."
                )
            ),
        ]

        response = llm.invoke(messages)

        timestamps = dict(state["timestamps"])
        timestamps["end"] = time.time()

        return {
            "final_answer": response.content,
            "timestamps": timestamps,
        }

    # ── Routing ───────────────────────────────────────────────────

    def after_analyst(state: MultiAgentState) -> str:
        """Route: more subtasks → analyst again, otherwise → synthesizer."""
        if state["current_subtask_idx"] < len(state["plan"]):
            return "analyst"
        return "synthesizer"

    # ── Build Graph ───────────────────────────────────────────────

    graph = StateGraph(MultiAgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "analyst")
    graph.add_conditional_edges(
        "analyst", after_analyst, {"analyst": "analyst", "synthesizer": "synthesizer"}
    )
    graph.add_edge("synthesizer", END)

    compiled = graph.compile()

    def run(question: str) -> dict:
        """Execute a question through the multi-agent pipeline."""
        initial_state: MultiAgentState = {
            "question": question,
            "messages": [
                SystemMessage(content="Multi-agent OCPM analysis system"),
                HumanMessage(content=question),
            ],
            "plan": [],
            "current_subtask_idx": 0,
            "subtask_results": [],
            "tool_calls_log": [],
            "final_answer": "",
            "timestamps": {"start": time.time()},
        }

        result = compiled.invoke(initial_state)

        return {
            "mode": "multi_agent",
            "question": question,
            "plan": result["plan"],
            "subtask_results": result["subtask_results"],
            "final_answer": result["final_answer"],
            "tool_calls": result["tool_calls_log"],
            "num_tool_calls": len(result["tool_calls_log"]),
            "timestamps": result["timestamps"],
            "latency_s": round(
                result["timestamps"].get("end", time.time())
                - result["timestamps"]["start"],
                3,
            ),
        }

    return run


def _parse_plan(content: str) -> list[dict]:
    """Extract a JSON array of subtasks from LLM response text."""
    # Try to find JSON array in the response
    text = content.strip()

    # Look for JSON block
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    # Try to find array brackets
    if "[" in text:
        bracket_start = text.index("[")
        bracket_end = text.rindex("]") + 1
        text = text[bracket_start:bracket_end]

    try:
        plan = json.loads(text)
        if isinstance(plan, list):
            # Normalize keys
            normalized = []
            for i, item in enumerate(plan):
                normalized.append(
                    {
                        "id": item.get("id", i + 1),
                        "description": item.get("description", str(item)),
                        "tool_hint": item.get("tool_hint", ""),
                    }
                )
            return normalized
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: treat entire question as one subtask
    return [
        {
            "id": 1,
            "description": "Analyze the question directly using available tools",
            "tool_hint": "use appropriate tools",
        }
    ]

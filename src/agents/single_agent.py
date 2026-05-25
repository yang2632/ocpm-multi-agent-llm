"""Single-agent baseline: one LangGraph node with tool-calling loop."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from ..tools.log_loader import OCELData
from .llm_provider import create_llm
from ._tool_executor import execute_tool_call

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "single_agent.txt"


class SingleAgentState(TypedDict):
    """State for the single-agent graph."""

    messages: list
    tool_calls_log: list[dict]
    final_answer: str
    timestamps: dict


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_single_agent_graph(
    ocel_data: OCELData,
    provider: str = "openai",
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    api_key: str = "",
    base_url: str = "",
):
    """Build a LangGraph StateGraph for the single-agent baseline.

    Returns a compiled graph that can be invoked with a question string.
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

    # Bind tools to the LLM
    llm_with_tools = llm.bind_tools(TOOL_DEFINITIONS)

    def agent_node(state: SingleAgentState) -> dict:
        """Call the LLM; it may request tool calls or produce a final answer."""
        response = llm_with_tools.invoke(state["messages"])
        new_messages = list(state["messages"]) + [response]
        return {"messages": new_messages}

    def tool_node(state: SingleAgentState) -> dict:
        """Execute tool calls from the last AI message."""
        last_msg = state["messages"][-1]
        new_messages = list(state["messages"])
        tool_log = list(state["tool_calls_log"])

        for tc in last_msg.tool_calls:
            t0 = time.perf_counter()
            result = execute_tool_call(ocel_data, tc["name"], tc["args"])
            elapsed = time.perf_counter() - t0

            result_str = json.dumps(result, default=str)
            new_messages.append(
                ToolMessage(content=result_str, tool_call_id=tc["id"])
            )
            tool_log.append(
                {
                    "tool": tc["name"],
                    "args": tc["args"],
                    "result_preview": result_str[:500],
                    "elapsed_s": round(elapsed, 3),
                }
            )

        return {"messages": new_messages, "tool_calls_log": tool_log}

    def should_continue(state: SingleAgentState) -> str:
        """Route: if last message has tool calls, go to tools; else finish."""
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "tools"
        return "end"

    def finalize(state: SingleAgentState) -> dict:
        """Extract the final text answer."""
        last_msg = state["messages"][-1]
        answer = last_msg.content if isinstance(last_msg, AIMessage) else ""
        timestamps = dict(state.get("timestamps", {}))
        timestamps["end"] = time.time()
        return {"final_answer": answer, "timestamps": timestamps}

    # Build the graph
    graph = StateGraph(SingleAgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)

    compiled = graph.compile()

    # Build the dataset-agnostic log profile once and inject into the prompt,
    # removing dataset-specific hardcoding. Same builder is used for the
    # multi-agent prompt, so no prompt asymmetry is introduced.
    from ..tools.log_loader import get_log_summary, build_log_profile

    _system_prompt = _load_system_prompt().replace(
        "{log_profile}", build_log_profile(get_log_summary(ocel_data))
    )

    def run(question: str) -> dict:
        """Execute a single question and return full trace."""
        system_prompt = _system_prompt
        initial_state: SingleAgentState = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=question),
            ],
            "tool_calls_log": [],
            "final_answer": "",
            "timestamps": {"start": time.time()},
        }

        result = compiled.invoke(initial_state)

        return {
            "mode": "single_agent",
            "question": question,
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

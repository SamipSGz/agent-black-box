"""The customer-support agent, built as an explicit LangGraph so we control
exactly where each failure mode fires. The whole run is wrapped in one root
span (`support_agent.session`) so a session == one trace in SigNoz.

Graph:
    classify -> lookup_order -> retrieve_policy -> reason
    reason --(low confidence & budget left)--> retrieve_policy   (loop)
    reason --(decided)--> act -> respond -> END
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import SpanKind

from . import llm, metrics, tools
from .scenarios import Scenario
from .telemetry import get_tracer

log = logging.getLogger("agent.graph")

CONFIDENCE_FLOOR = 0.55
NORMAL_LOOP_CAP = 2       # healthy guardrail
RUNAWAY_LOOP_CAP = 7      # trips the ">5 calls" alert but stays under LangGraph's
                          # default recursion_limit (25 node visits)


class AgentState(TypedDict, total=False):
    session_id: str
    scenario: Scenario
    ticket: str
    order_id: Optional[str]
    order: Optional[dict]
    policy: Optional[dict]
    retrieve_count: int
    decision: str
    response: str
    failure_mode: Optional[str]
    # routing state (declared so LangGraph gives them channels)
    confidence: float
    route: str


def _order_id_from(ticket: str) -> Optional[str]:
    m = re.search(r"#?(A-\d{3,5})", ticket)
    return m.group(1) if m else None


def _classify(state: AgentState) -> AgentState:
    intent = llm.chat(
        state["session_id"], "classify_ticket",
        system="You classify support tickets. Reply with ONE word: refund, question, or other.",
        user=state["ticket"],
    )
    state["order_id"] = _order_id_from(state["ticket"])
    log.info("classified intent=%s order_id=%s", intent.strip(), state["order_id"])
    return state


def _lookup(state: AgentState) -> AgentState:
    try:
        state["order"] = tools.lookup_order(state["session_id"], state["order_id"] or "", state["scenario"])
    except tools.ToolOutage:
        state["order"] = None
        state["failure_mode"] = "retry_storm"
    return state


def _retrieve(state: AgentState) -> AgentState:
    state["retrieve_count"] = state.get("retrieve_count", 0) + 1
    state["policy"] = tools.retrieve_policy(state["session_id"], state["scenario"])
    return state


def _reason(state: AgentState) -> AgentState:
    policy = state.get("policy") or {}
    order = state.get("order") or {}
    verdict = llm.chat(
        state["session_id"], "reason_about_policy",
        system=(
            "You decide whether to APPROVE or DENY a refund based ONLY on the policy text. "
            "Reply with one word: approve or deny."
        ),
        user=f"Policy: {policy.get('text')}\nOrder condition: {order.get('condition')}",
    )
    state["decision"] = "approve" if "approve" in verdict.lower() else "deny"

    # Decide routing HERE (node functions merge state; the conditional-edge
    # function below must stay pure and only read `route`).
    conf = policy.get("confidence", 1.0)
    state["confidence"] = conf
    cap = RUNAWAY_LOOP_CAP if state["scenario"].unbounded_loop else NORMAL_LOOP_CAP
    if conf < CONFIDENCE_FLOOR and state.get("retrieve_count", 0) < cap:
        state["route"] = "retrieve"
        if state["scenario"].unbounded_loop:
            state["failure_mode"] = "tool_loop"
        log.warning("re-querying policy (confidence=%.2f, attempt=%d)", conf, state.get("retrieve_count", 0))
    else:
        state["route"] = "act"
        if conf < CONFIDENCE_FLOOR:
            state["failure_mode"] = state.get("failure_mode") or "bad_rag"
    return state


def _route_after_reason(state: AgentState) -> str:
    # Pure: just read the decision the node already made.
    return state.get("route", "act")


def _act(state: AgentState) -> AgentState:
    order = state.get("order") or {}
    if state.get("failure_mode") == "retry_storm" or not order.get("amount"):
        tools.create_support_ticket(state["session_id"], state.get("order_id") or "?", "order lookup failed")
    elif state["decision"] == "approve":
        tools.issue_refund(state["session_id"], order["id"], order["amount"])
    else:
        tools.create_support_ticket(state["session_id"], order.get("id", "?"), "refund denied by policy")
    return state


def _respond(state: AgentState) -> AgentState:
    state["response"] = llm.chat(
        state["session_id"], "final_response",
        system="Write a short, empathetic reply to the customer about the outcome.",
        user=f"Decision: {state.get('decision')}. Order: {state.get('order_id')}.",
    )
    return state


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", _classify)
    g.add_node("lookup", _lookup)
    g.add_node("retrieve", _retrieve)
    g.add_node("reason", _reason)
    g.add_node("act", _act)
    g.add_node("respond", _respond)

    g.add_edge(START, "classify")
    g.add_edge("classify", "lookup")
    g.add_edge("lookup", "retrieve")
    g.add_edge("retrieve", "reason")
    g.add_conditional_edges("reason", _route_after_reason, {"retrieve": "retrieve", "act": "act"})
    g.add_edge("act", "respond")
    g.add_edge("respond", END)
    return g.compile()


_GRAPH = None


def run_session(scenario: Scenario, session_id: str | None = None) -> AgentState:
    """Run one support session end-to-end under a single root trace."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()

    session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    tracer = get_tracer()
    started = time.perf_counter()

    with tracer.start_as_current_span("support_agent.session", kind=SpanKind.SERVER) as span:
        span.set_attribute("agent.name", "support-agent")
        span.set_attribute("agent.session_id", session_id)
        span.set_attribute("scenario", scenario.key)
        log.info("=== session %s start (scenario=%s) ===", session_id, scenario.key)

        state: AgentState = {
            "session_id": session_id,
            "scenario": scenario,
            "ticket": scenario.ticket,
            "retrieve_count": 0,
        }
        final: AgentState = _GRAPH.invoke(state)

        duration_ms = (time.perf_counter() - started) * 1000
        failure = final.get("failure_mode")
        span.set_attribute("failure.mode", failure or "none")
        span.set_attribute("session.duration_ms", round(duration_ms, 1))
        metrics.record_session_end(session_id, duration_ms, failure)
        log.info("=== session %s end (failure=%s, %.0fms) ===", session_id, failure, duration_ms)
        return final

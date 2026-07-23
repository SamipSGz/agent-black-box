"""Custom metric instruments — the numeric backbone of the Agent Flight Deck.

These feed both the dashboard panels and the alert rules. Every instrument is
created lazily off the global meter so `init_telemetry()` must run first.
"""
from __future__ import annotations

from functools import lru_cache

from .telemetry import get_meter


@lru_cache(maxsize=1)
def _instruments():
    m = get_meter()
    return {
        # Histograms (distributions -> p95, heatmaps)
        "session_duration_ms": m.create_histogram(
            "agent.session.duration", unit="ms", description="End-to-end support session latency"
        ),
        "tool_latency_ms": m.create_histogram(
            "agent.tool.latency", unit="ms", description="Per-tool-call latency"
        ),
        "rag_confidence": m.create_histogram(
            "agent.rag.confidence", unit="1", description="Retrieval confidence score (0-1)"
        ),
        # Counters (rates, totals)
        "tool_calls": m.create_counter(
            "agent.tool.calls", description="Tool invocations"
        ),
        "retries": m.create_counter(
            "agent.retries", description="Tool retries"
        ),
        "tokens": m.create_counter(
            "agent.tokens", description="LLM tokens consumed"
        ),
        "cost_usd": m.create_counter(
            "agent.cost.usd", unit="USD", description="LLM spend"
        ),
        "failed_sessions": m.create_counter(
            "agent.sessions.failed", description="Sessions that ended in a failure mode"
        ),
        "low_conf_retrievals": m.create_counter(
            "agent.rag.low_confidence", description="RAG lookups below the confidence floor"
        ),
    }


def _base_attrs(session_id: str, extra: dict | None = None) -> dict:
    # NOTE: deliberately NO agent.session_id here. session_id is high-cardinality
    # and, on a cumulative counter, makes every session its own short-lived series
    # so SigNoz rate()/increase() evaluate to ~0 and alerts never fire. Metrics
    # stay low-cardinality (aggregatable/alertable); per-session detail lives on
    # traces and logs, which carry agent.session_id for correlation.
    attrs = {"agent.name": "support-agent"}
    if extra:
        attrs.update(extra)
    return attrs


def record_tool_call(session_id: str, tool: str, latency_ms: float, retries: int = 0) -> None:
    inst = _instruments()
    attrs = _base_attrs(session_id, {"tool.name": tool})
    inst["tool_calls"].add(1, attrs)
    inst["tool_latency_ms"].record(latency_ms, attrs)
    if retries:
        inst["retries"].add(retries, attrs)


def record_llm_usage(session_id: str, tokens: int, cost_usd: float) -> None:
    inst = _instruments()
    attrs = _base_attrs(session_id)
    inst["tokens"].add(tokens, attrs)
    inst["cost_usd"].add(cost_usd, attrs)


def record_rag(session_id: str, confidence: float, floor: float = 0.55) -> None:
    inst = _instruments()
    attrs = _base_attrs(session_id)
    inst["rag_confidence"].record(confidence, attrs)
    if confidence < floor:
        inst["low_conf_retrievals"].add(1, attrs)


def record_session_end(session_id: str, duration_ms: float, failure_mode: str | None) -> None:
    inst = _instruments()
    attrs = _base_attrs(session_id, {"failure.mode": failure_mode or "none"})
    inst["session_duration_ms"].record(duration_ms, attrs)
    if failure_mode:
        inst["failed_sessions"].add(1, attrs)

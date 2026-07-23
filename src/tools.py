"""Agent tools + a tiny RAG store. Each tool is a traced span so a session
becomes a clean tree in SigNoz, and each carries the failure switches from the
active Scenario.
"""
from __future__ import annotations

import logging
import time

from opentelemetry.trace import SpanKind, Status, StatusCode

from . import config, metrics
from .scenarios import Scenario
from .telemetry import get_tracer

log = logging.getLogger("agent.tools")

# --- fake order database ---
_ORDERS = {
    "A-1042": {"id": "A-1042", "status": "delivered", "amount": 79.0, "condition": "damaged"},
    "A-2091": {"id": "A-2091", "status": "delivered", "amount": 129.0, "condition": "damaged"},
    "A-3157": {"id": "A-3157", "status": "delivered", "amount": 54.0, "condition": "damaged"},
    "A-4480": {"id": "A-4480", "status": "delivered", "amount": 210.0, "condition": "damaged"},
}

# --- refund policy "documents" for RAG ---
_POLICY_DOCS = {
    "refund_policy_v2": {
        "id": "refund_policy_v2",
        "text": "Damaged items are eligible for a full refund within 30 days of delivery.",
        "allows_refund": True,
    },
    "gift_card_policy": {
        "id": "gift_card_policy",
        "text": "Gift cards are non-refundable under any circumstances.",
        "allows_refund": False,
    },
}


class ToolOutage(Exception):
    """Raised when a tool exhausts its (simulated) upstream availability."""


def lookup_order(session_id: str, order_id: str, scenario: Scenario) -> dict:
    """Look up an order, honoring the scenario's 503 injection + retry behavior."""
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.lookup_order", kind=SpanKind.CLIENT) as span:
        span.set_attribute("tool.name", "lookup_order")
        span.set_attribute("agent.session_id", session_id)
        span.set_attribute("order.id", order_id)

        # The fix the copilot recommends: a retry budget. config.RETRY_BUDGET=0
        # is the buggy v1 (no budget — hammer until the upstream count is
        # exhausted). A positive budget is the fixed v2 (give up after N tries
        # and fall back gracefully).
        budget = config.RETRY_BUDGET
        span.set_attribute("retry.budget", budget)
        hard_cap = budget if budget > 0 else scenario.order_503_count

        started = time.perf_counter()
        retries = 0
        order = None
        while True:
            upstream_ok = scenario.order_503_count == 0 or (
                scenario.order_recovers and retries >= scenario.order_503_count
            )
            if upstream_ok:
                order = _ORDERS.get(order_id)
                break
            retries += 1
            span.add_event("upstream_503", {"attempt": retries})
            log.warning("lookup_order 503 order_id=%s attempt=%d", order_id, retries)
            time.sleep(0.05)  # simulate network cost of a retry
            if retries >= hard_cap:
                break

        latency_ms = (time.perf_counter() - started) * 1000
        span.set_attribute("tool.retry_count", retries)
        metrics.record_tool_call(session_id, "lookup_order", latency_ms, retries)

        if order is None:
            if budget == 0:
                # v1: no budget -> retry storm. Loud failure.
                span.set_status(Status(StatusCode.ERROR, "order service unavailable"))
                span.set_attribute("failure.mode", "retry_storm")
                log.error("lookup_order gave up order_id=%s after %d retries", order_id, retries)
                raise ToolOutage(f"order service unavailable after {retries} retries")
            # v2: budget honored -> stop after N, hand back a controlled result
            # so the agent can fall back to opening a support ticket. No storm.
            span.set_attribute("order.found", False)
            span.set_attribute("lookup.outcome", "unavailable_handled")
            log.info("lookup_order gave up politely after %d/%d retries", retries, budget)
            return {"id": order_id, "status": "unavailable", "handled": True}

        span.set_attribute("order.found", True)
        return order


def retrieve_policy(session_id: str, scenario: Scenario) -> dict:
    """RAG lookup. bad_rag returns the wrong doc with a low confidence score."""
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.retrieve_policy", kind=SpanKind.CLIENT) as span:
        span.set_attribute("tool.name", "retrieve_policy")
        span.set_attribute("agent.session_id", session_id)
        span.set_attribute("rag.top_k", 1)

        started = time.perf_counter()
        if scenario.bad_rag:
            doc, confidence = _POLICY_DOCS["gift_card_policy"], 0.41
        else:
            doc, confidence = _POLICY_DOCS["refund_policy_v2"], 0.92

        latency_ms = (time.perf_counter() - started) * 1000
        span.set_attribute("rag.document_id", doc["id"])
        span.set_attribute("rag.confidence", confidence)
        metrics.record_tool_call(session_id, "retrieve_policy", latency_ms)
        metrics.record_rag(session_id, confidence)
        if confidence < 0.55:
            span.set_attribute("failure.mode", "bad_rag")
        log.info("retrieve_policy doc=%s confidence=%.2f", doc["id"], confidence)
        return {**doc, "confidence": confidence}


def issue_refund(session_id: str, order_id: str, amount: float) -> dict:
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.issue_refund", kind=SpanKind.CLIENT) as span:
        span.set_attribute("tool.name", "issue_refund")
        span.set_attribute("agent.session_id", session_id)
        span.set_attribute("order.id", order_id)
        span.set_attribute("refund.amount", amount)
        started = time.perf_counter()
        metrics.record_tool_call(session_id, "issue_refund", (time.perf_counter() - started) * 1000)
        log.info("issue_refund order_id=%s amount=%.2f", order_id, amount)
        return {"refunded": True, "amount": amount}


def create_support_ticket(session_id: str, order_id: str, reason: str) -> dict:
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.create_support_ticket", kind=SpanKind.CLIENT) as span:
        span.set_attribute("tool.name", "create_support_ticket")
        span.set_attribute("agent.session_id", session_id)
        span.set_attribute("order.id", order_id)
        started = time.perf_counter()
        metrics.record_tool_call(session_id, "create_support_ticket", (time.perf_counter() - started) * 1000)
        log.info("create_support_ticket order_id=%s reason=%s", order_id, reason)
        return {"ticket_id": f"T-{order_id}", "reason": reason}

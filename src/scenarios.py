"""Failure-mode definitions. Each scenario flips deterministic switches so the
demo can reproduce the *same* incident before and after a fix.

Keep this small: three failure modes carry the whole story.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    ticket: str
    # order-lookup tool returns 503 this many times before (maybe) succeeding
    order_503_count: int = 0
    order_recovers: bool = True
    # force RAG to return the WRONG policy doc with a low confidence score
    bad_rag: bool = False
    # remove the reasoning loop guardrail so ambiguous context spirals
    unbounded_loop: bool = False
    notes: str = ""


HAPPY = Scenario(
    key="happy",
    title="Healthy refund",
    ticket="My order #A-1042 arrived damaged, I'd like a refund please.",
    notes="Baseline: everything works, no failure mode fires.",
)

RETRY_STORM = Scenario(
    key="retry_storm",
    title="Retry storm on order lookup",
    ticket="Order #A-2091 was broken on arrival — please refund me.",
    order_503_count=11,
    order_recovers=False,
    notes="lookup_order flaps 503; no retry budget -> tokens + latency explode.",
)

BAD_RAG = Scenario(
    key="bad_rag",
    title="Bad RAG retrieval -> wrong denial",
    ticket="My order #A-3157 came damaged, requesting a refund.",
    bad_rag=True,
    notes="Vector search returns the wrong policy; a valid refund gets denied.",
)

TOOL_LOOP = Scenario(
    key="tool_loop",
    title="Ambiguous-context tool loop",
    ticket="Is my damaged order #A-4480 eligible for a refund or store credit?",
    bad_rag=True,
    unbounded_loop=True,
    notes="Ambiguous retrieval keeps confidence low -> agent re-queries in a loop.",
)

ALL: dict[str, Scenario] = {s.key: s for s in [HAPPY, RETRY_STORM, BAD_RAG, TOOL_LOOP]}

"""Central config + pricing table.

Everything reads from the environment (see .env.example). Keeping pricing here
lets the LLM wrapper turn token counts into a `gen_ai` cost that we push to
SigNoz as a metric, which is what powers the "token cost by session" panel and
the cost-spike alert.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")

OTEL_ENDPOINT = _env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
SERVICE_NAME = _env("OTEL_SERVICE_NAME", "agent-black-box")
AGENT_VERSION = _env("AGENT_VERSION", "v1")

# Retry budget for the order-lookup tool. 0 = buggy v1 (no budget -> retry
# storm). A positive value is the fixed v2: give up after N retries and fall
# back to opening a support ticket. Set RETRY_BUDGET=3 with AGENT_VERSION=v2
# for the "after" half of the before/after demo.
RETRY_BUDGET = int(_env("RETRY_BUDGET", "0"))

SIGNOZ_API_URL = _env("SIGNOZ_API_URL", "http://localhost:8080").rstrip("/")
SIGNOZ_API_KEY = _env("SIGNOZ_API_KEY")

COPILOT_HOST = _env("COPILOT_HOST", "0.0.0.0")
COPILOT_PORT = int(_env("COPILOT_PORT", "8099"))

# USD per 1M tokens. Extend as needed; unknown models fall back to gpt-4o-mini.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-nano-2025-08-07": (0.05, 0.40),
    "gpt-5.1": (1.25, 10.00),
}


@dataclass(frozen=True)
class Cost:
    input_tokens: int
    output_tokens: int
    usd: float


def cost_for(model: str, input_tokens: int, output_tokens: int) -> Cost:
    in_rate, out_rate = PRICING.get(model, PRICING["gpt-4o-mini"])
    usd = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
    return Cost(input_tokens, output_tokens, round(usd, 6))

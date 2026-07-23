---
title: "Agent Black Box: giving AI agents a flight recorder with SigNoz"
event: "Agents of SigNoz — WeMakeDevs × SigNoz"
track: "Track 01 — AI & Agent Observability"
---

# Agent Black Box: giving AI agents a flight recorder with SigNoz

When a plane crashes, investigators don't guess. They pull the black box —
the flight recorder that captured every input, every control surface, every
second leading up to the failure — and they reconstruct exactly what happened.

AI agents have no black box. They chain LLM calls, invoke tools, query vector
databases, retry on flaky upstreams, and occasionally spiral into loops that
quietly burn tokens. When one misbehaves in production, the on-call engineer is
left squinting at raw logs trying to answer a simple question: *what did the
agent actually do, and why did it go wrong?*

**Agent Black Box** is my entry for the Agents of SigNoz hackathon (Track 01).
It's two things working as one loop:

1. A **flight recorder** that traces every step of an AI agent into SigNoz —
   LLM calls, tool calls, retries, RAG lookups, token spend, and errors.
2. An **SRE copilot** that, when an agent misbehaves, reads that telemetry back
   out of SigNoz and produces an *evidence-backed* root-cause report with a
   suggested guardrail — then you fix it and **replay the same incident** to
   prove it's gone.

The demo tells one story: **before → failure → observability → diagnosis → fix
→ after.**

## The test subject: a support agent that breaks on purpose

The agent itself is deliberately boring — a customer-support bot built with
LangGraph that handles refund tickets. It classifies the ticket, looks up the
order, retrieves the refund policy from a vector store, reasons about
eligibility, acts (issue refund / open a ticket), and replies.

The *interesting* part is that it breaks in three realistic, reproducible ways:

- **Retry storm.** The `lookup_order` tool flaps `503`. With no retry budget and
  no fallback, the agent hammers it 11 times — latency and token cost climb for
  nothing.
- **Bad RAG retrieval.** The vector search returns the *wrong* policy document
  with a low confidence score, and the agent denies a perfectly valid refund.
- **Ambiguous-context tool loop.** Low-confidence retrieval keeps the agent
  re-querying the same policy in a loop instead of escalating.

These aren't contrived — they're exactly the failure classes the hackathon
brief calls out about agents being a black box. Because each is a deterministic
switch (see `scenarios.py`), I can reproduce the *same* incident on demand,
which is what makes the before/after replay credible.

## What SigNoz records

The whole point is to use SigNoz as the centerpiece, not a checkbox — traces,
metrics, logs, dashboards, **and** alerts, together.

**Traces.** Each support session is one trace, `support_agent.session`, with a
clean span tree: `classify → lookup_order → retrieve_policy → chat <model> →
issue_refund → final_response`. LLM spans follow the OpenTelemetry **GenAI
semantic conventions** — `gen_ai.system`, `gen_ai.request.model`,
`gen_ai.usage.input_tokens` / `output_tokens`, plus a computed `cost_usd`. Tool
spans carry `tool.name`, `tool.retry_count`, `rag.document_id`, and
`rag.confidence`. That means a retry storm *looks like* a retry storm in the
trace view: eleven red `lookup_order` attempts, right there.

**Metrics.** Custom instruments — `agent.retries`, `agent.tokens`,
`agent.cost.usd`, `agent.rag.confidence`, `agent.sessions.failed`,
`agent.tool.latency` — power an "Agent Flight Deck" dashboard: p95 session
latency, token cost by session, failed sessions by failure mode, retry count by
tool, a tool-latency heatmap, and error rate by agent version.

**Logs.** Every decision is a structured log line, bridged through OTLP so it
carries its `trace_id` — click a spike on the dashboard, land on the trace,
read the exact log that explains it.

**Alerts.** A mix of alert types (metric thresholds, trace/exception rates,
composite conditions) — retry storm, cost spike, tool loop, RAG risk, tool
outage — each routed to a webhook that wakes the copilot, carrying the
`agent_session_id` and `trace_id` as labels.

## The copilot: evidence, not vibes

Here's the design decision I care most about. SigNoz already ships an MCP server
that lets an assistant *ask questions* of your telemetry. So "a chatbot for your
metrics" isn't the interesting product — SigNoz already does that. The
interesting product is **incident-driven and replayable**.

When an alert fires, the copilot receives the webhook, queries SigNoz for the
relevant trace and session metrics, and writes a report like:

> **Incident: Retry storm in session sess-1a2b3c4d**
> The agent spent 142s and $1.87 in tokens because `lookup_order` failed 11
> times. The retry loop began after `tool.lookup_order` returned HTTP 503; no
> max-retry guardrail stopped it.
>
> **Evidence:** trace `…`, failing span `tool.lookup_order`, `agent.retries = 11`.
> **Likely root cause:** no retry budget and no fallback path.
> **Suggested fixes:** add `max_retries=3` with backoff; fall back to
> `create_support_ticket` on outage.
> **Suggested guardrail:** alert when `agent.retries > 5` per session.

The rule that keeps it honest: **every claim is grounded in telemetry the
copilot actually pulled.** The LLM narrates the evidence; it doesn't invent
trace IDs or numbers. And it degrades gracefully — with no live SigNoz it falls
back to the alert labels, and with no LLM key it emits a templated but still
evidence-backed report. Good insurance for a live demo.

## Why this maps to the judging rubric

- **Best Use of SigNoz** — traces + metrics + logs + dashboards + alerts operate
  as a single closed loop, and the copilot consumes the query API / MCP server
  as an evidence source.
- **Technical excellence** — real OpenTelemetry GenAI conventions, custom metric
  instruments, trace↔log correlation via the OTLP logging bridge, and an
  in-memory-exporter test suite that verifies the instrumentation with no
  external dependencies.
- **Impact & creativity** — debugging agents is a genuine production pain, and
  "flight recorder + incident replay + root-cause copilot" is more memorable
  than another dashboard.
- **UX & presentation** — one incident report instead of manual telemetry
  spelunking, and the before/after replay is the whole story.

## Try it

```bash
# 1. SigNoz self-hosted
git clone -b main https://github.com/SigNoz/signoz.git
cd signoz/deploy/docker && docker compose up -d

# 2. the agent
cd agent-black-box && pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY
python -m src.main demo            # happy → retry_storm → bad_rag → tool_loop

# 3. the copilot
python -m copilot.webhook_server
python scripts/send_test_alert.py retry_storm   # see the RCA at localhost:8099
```

The most important design call: **the agent's job is trivial on purpose.** The
observability story is where the complexity lives — because the point isn't the
smartest support bot, it's proving that SigNoz can make an AI agent
understandable, debuggable, and safer to operate.

*Built for [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz).*

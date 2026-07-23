# Dashboard — "Agent Flight Deck"

Build this in SigNoz (Dashboards → New). Panels, in order, tell the flight-deck
story top-to-bottom: health → cost → failures → drilldown.

| Panel | Type | Query (builder) |
|-------|------|-----------------|
| Session latency p95 | Time series | `p95(agent.session.duration)` |
| Token cost by session | Time series (stacked) | `sum(agent.cost.usd)` group by `agent.session_id` |
| Failed sessions by failure mode | Bar | `sum(agent.sessions.failed)` group by `failure.mode` |
| Retry count by tool | Bar | `sum(agent.retries)` group by `tool.name` |
| Tool latency heatmap | Heatmap | `agent.tool.latency` group by `tool.name` |
| RAG confidence over time | Time series | `avg(agent.rag.confidence)` |
| Top expensive traces | Traces (table) | traces sorted by duration, filter `agent.name = support-agent` |
| Error rate by agent version | Time series | error span rate group by `service.version` |

## Fast path: build once, then export

The SigNoz dashboard JSON schema is verbose and version-specific, so rather than
ship a JSON that may not import cleanly on your build:

1. Build the panels above in the UI (5–10 min).
2. Dashboard → **⋯ → Export JSON**, and commit the file here as
   `agent_flight_deck.json` so your repo/blog has a reproducible artifact.

The attribute keys emitted by the app (match these in your queries):
`agent.session_id`, `agent.name`, `tool.name`, `tool.retry_count`,
`failure.mode`, `rag.confidence`, `rag.document_id`, `service.version`,
plus GenAI keys `gen_ai.usage.input_tokens` / `output_tokens` / `cost_usd`.

# Alert rules — SigNoz → webhook → SRE copilot

This is the **verified-working** setup (tested end-to-end on self-hosted SigNoz
via Foundry). The retry-storm rule below fires a real SigNoz alert that reaches
the copilot at `http://host.docker.internal:8099/alerts` and produces an
evidence-backed RCA report.

## Notification channel

Settings → Alert Channels → New → **Webhook**:
- Webhook URL: `http://host.docker.internal:8099/alerts`
  (use `host.docker.internal`, not `localhost` — SigNoz runs in Docker and must
  reach the copilot on the host; verified reachable from the `signoz` container).

## The retry-storm rule (verified firing)

| Field | Value |
|-------|-------|
| Metric | `agent.retries` |
| Time aggregation | **`max`** (see gotcha #2 — `rate`/`increase` return 0 here) |
| Space aggregation | `max` |
| Group by | `tool.name` |
| Condition | value **above** `5`, at least once |
| Evaluation | rolling **15m** window, frequency 1m |
| Static labels | `failure_mode=retry_storm`, `severity=critical` |
| Channel | the webhook above |

`max(agent.retries) by tool.name` peaks at 11 during a retry storm (one bad
session), cleanly above the threshold of 5.

## Three gotchas that cost real debugging time (blog-worthy)

1. **Evaluation delay + window.** SigNoz evaluates on a *delayed* window
   `[now-eval_delay-window, now-eval_delay]`, with `eval_delay≈2m`. A fresh burst
   of data lands inside that 2-minute blind spot, so a 5-minute window sees
   nothing and the rule stays inactive. Widening to a **15m window** makes recent
   data reliably visible. (Symptom in the ruler logs: `query result is nil`.)

2. **`rate()`/`increase()` return 0 for per-process cumulative counters.** Each
   demo session is a short-lived process. Two problems compounded:
   - the OTel SDK assigns a fresh `service.instance.id` per process, so every run
     became its own ephemeral series (31 distinct series for one metric!). Fixed
     by pinning a stable `service.instance.id` in the resource.
   - even then, `increase`/`rate` need a *rising* series across the window;
     these counters jump 0→11 and vanish, so the delta reads ~0. Use **`max`**
     (peak value in window) instead — semantically "the worst session had >5
     retries," which is exactly the alert we want.
   (Symptom: ruler logs `alert.count: 0` while ClickHouse clearly shows 11.)

3. **Keep metrics low-cardinality.** `agent.session_id` on a metric makes every
   session its own series and breaks aggregation/alerting. session_id belongs on
   **traces and logs** (for correlation), not metric attributes. The copilot
   recovers the offending session by querying SigNoz, not from the alert label.

## Real webhook payload

SigNoz sends Alertmanager v4 format. A captured real payload is committed at
[`sample_webhook_payload.json`](./sample_webhook_payload.json). Shape:

```json
{
  "receiver": "agent-black-box-copilot",
  "status": "firing",
  "alerts": [{
    "status": "firing",
    "labels": {
      "alertname": "Agent retry storm (per session)",
      "failure_mode": "retry_storm",
      "severity": "critical",
      "tool.name": "lookup_order"
    },
    "annotations": {
      "summary": "This alert is fired when the defined metric (current value: 11) crosses the threshold (5)"
    },
    "startsAt": "2026-07-22T05:10:00Z",
    "fingerprint": "d9adbc3c95b23c4f"
  }],
  "commonLabels": { "...": "..." },
  "version": "4"
}
```

The copilot (`copilot/rca.py`) reads: `failure_mode` (→ classify), `tool.name`
(→ failing span), and parses the **observed value (11)** and **threshold (5)**
out of the annotation text for hard evidence.

## More rules to add (same pattern)

| Name | Type | Condition | Static label |
|------|------|-----------|--------------|
| Cost spike | Metric | `max(agent.cost.usd)` by `agent.name` > 0.02 / 15m | `failure_mode=cost_spike` |
| RAG risk | Metric | `sum(agent.rag.low_confidence)` > 0 | `failure_mode=bad_rag` |
| Tool loop | Trace | count of span `tool.retrieve_policy` > 5 in 2m | `failure_mode=tool_loop` |
| Tool outage | Trace/Exceptions | error rate of `tool.lookup_order` > 20% / 5m | `failure_mode=retry_storm` |

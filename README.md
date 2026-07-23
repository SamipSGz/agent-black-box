# 🛰️ Agent Black Box

**Flight recorder + SRE copilot for AI agents — powered by SigNoz.**

Built for the [Agents of SigNoz hackathon](https://www.wemakedevs.org/hackathons/signoz) (Track 01: AI & Agent Observability).

AI agents are a black box: they chain LLM calls, hit tools and vector DBs, retry,
loop, and burn tokens — and when they fail, you're squinting at raw logs. **Agent
Black Box** records every step into SigNoz (traces + metrics + logs), fires
**alerts** when an agent misbehaves, and triggers an **SRE copilot** that reads
the telemetry back out and produces an *evidence-backed* root-cause report with a
suggested guardrail. Then you apply the fix and **replay the same incident** to
prove it's gone.

> The demo story: **before → failure → observability → diagnosis → fix → after.**

## Architecture

```
 support ticket
      │
      ▼
 LangGraph support-agent ── OpenAI LLM + tools + mock APIs + RAG
      │                         │
      │        OpenTelemetry SDK (GenAI semantic conventions)
      ▼                         ▼
 support_agent.session   traces · metrics · logs  ──OTLP──▶  SigNoz
   (one trace/session)                                        ├─ dashboards ("Agent Flight Deck")
                                                              └─ alerts ──webhook──┐
                                                                                   ▼
                                                              Agent Black Box SRE Copilot
                                                              (queries SigNoz → RCA report → guardrail)
```

## Repo layout

| Path | What |
|------|------|
| `src/telemetry.py` | OTel bootstrap: traces + metrics + logs → SigNoz |
| `src/llm.py` | OpenAI wrapper emitting `gen_ai.*` spans + token/cost metrics |
| `src/tools.py` | Agent tools + tiny RAG store, each a traced span |
| `src/metrics.py` | Custom instruments behind the Flight Deck + alerts |
| `src/scenarios.py` | The 3 failure modes (retry storm, bad RAG, tool loop) + happy path |
| `src/agent.py` | The LangGraph support-agent (one trace per session) |
| `src/main.py` | CLI: `run <scenario>` / `demo` / `list` |
| `copilot/` | SRE copilot: SigNoz client, RCA generator, webhook server + UI |
| `dashboards/` | "Agent Flight Deck" panel spec |
| `alerts/` | Alert rules + webhook payload contract |
| `tests/` | In-memory-exporter tests: verify instrumentation with no SigNoz/OpenAI |
| `blog/` | Blog draft (doubles as the pre-event challenge + submission write-up) |

## Quickstart

### Step 1 — run SigNoz (self-hosted)

```bash
git clone -b main https://github.com/SigNoz/signoz.git
cd signoz/deploy/docker
docker compose up -d
# UI: http://localhost:8080  (older builds: http://localhost:3301)
# OTLP ingest: gRPC :4317 / HTTP :4318
```

### Step 2 — configure this project

```bash
cd agent-black-box
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set OPENAI_API_KEY; SIGNOZ_API_KEY once you make one in the UI
```

### Step 3 — generate telemetry

```bash
python -m src.main list          # see scenarios
python -m src.main run happy      # baseline
python -m src.main demo           # happy → retry_storm → bad_rag → tool_loop
```

Open SigNoz → **Traces** and find `support_agent.session`. Each session is one
trace with LLM spans (`chat <model>`), tool spans, retries, and token/cost
attributes.

### Step 4 — build the dashboard + alerts

- Dashboard: follow `dashboards/agent_flight_deck.md`, then export the JSON back
  into that folder for a reproducible artifact.
- Alerts: create the rules in `alerts/alert_rules.md`. Point a **Webhook alert
  channel** at `http://<your-host>:8099/alerts` and group by `agent.session_id`.

### Step 5 — run the SRE copilot

```bash
python -m copilot.webhook_server         # serves :8099 + a UI at /
```

Test the RCA path immediately, without waiting for a real alert:

```bash
python scripts/send_test_alert.py retry_storm
open http://localhost:8099/              # see the rendered incident report
```

## The winning demo (≈4 min)

1. `python -m src.main run retry_storm` — kick off a broken session.
2. SigNoz **trace**: show the `tool.lookup_order` span retrying 11×, the LLM
   spans, token/cost attributes.
3. **Dashboard** spike: retries + cost climb on the Flight Deck.
4. **Alert** fires → webhook → copilot.
5. Copilot **RCA report** (`http://localhost:8099/`): root cause + trace-linked
   evidence + suggested fix + suggested guardrail alert.
6. Apply the fix the copilot suggested — a retry budget + fallback — which ships
   as **v2** behavior (`AGENT_VERSION=v2 RETRY_BUDGET=3`).
7. Replay the **same** scenario on v2 — `lookup_order` stops after **3 retries**
   (below the alert's threshold of 5) and opens a support ticket instead of
   storming. `failure_mode=none`, the alert resolves. Split any panel by
   `service.version` to show v1 (failing) vs v2 (clean).

Run the whole before → after in one go:

```bash
python -m copilot.webhook_server        # terminal 1
./scripts/demo_before_after.sh          # terminal 2
```

The fix is a single knob so the same code demonstrates both halves:
`RETRY_BUDGET=0` is the buggy v1 (no budget → storm); `RETRY_BUDGET=3` is the
fixed v2 (give up after 3, fall back gracefully). See `src/tools.py`.

## Tests

Verify the flight recorder with **no SigNoz and no OpenAI key** — an in-memory
OTel exporter captures spans/metrics and the OpenAI client is stubbed:

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite asserts the things dashboards, alerts, and the copilot depend on:
gen_ai spans exist, `tool.retry_count == 11` in a retry storm, the tool loop
caps at 7, failure modes are labelled on the root span, and the custom metrics
(`agent.retries`, `agent.tokens`, `agent.session.duration`) are emitted.

## Running on the same Docker network as SigNoz

`docker-compose.yaml` reaches SigNoz via `host.docker.internal`. For a cleaner
setup with service-name DNS and no host ports, use
`docker-compose.signoz-net.yaml`, which joins SigNoz's own Docker network — see
the header of that file for the two-step network discovery.

## Design choices that map to the judging rubric

- **Best Use of SigNoz** — traces, metrics, logs, dashboards, *and* alerts work
  as one loop; the copilot uses the query API (and optionally the SigNoz **MCP
  server**) to gather evidence, not to chat.
- **Technical excellence** — OpenTelemetry **GenAI semantic conventions**
  (`gen_ai.system`, `gen_ai.usage.*`), custom metric instruments, trace↔log
  correlation via the OTLP logging bridge.
- **Impact / creativity** — incident-driven & *replayable*: the same failure is
  reproduced before and after the fix.
- **UX / presentation** — one incident report instead of manual telemetry
  spelunking; the before/after replay is the story.

## Notes

- The copilot degrades gracefully: with no `OPENAI_API_KEY` it still produces a
  templated, evidence-backed report; with no live SigNoz it uses the alert
  labels as evidence. Great insurance for a live demo.
- SigNoz's query/trace API paths shift across versions — `copilot/signoz_client.py`
  centralizes them; copy the exact `query_range` body from the SigNoz UI's
  Network tab for your build if a call 404s.

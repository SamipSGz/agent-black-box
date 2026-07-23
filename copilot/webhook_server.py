"""SRE copilot service.

Runs a FastAPI server that SigNoz alerts POST to. On each alert it builds an
evidence-backed RCA report and (a) prints it, (b) stores it, (c) serves a tiny
UI at `/` so the live demo can show the report next to the SigNoz dashboard.

Point a SigNoz Alert Channel (Settings -> Alert Channels -> Webhook) at:
    http://<host>:8099/alerts

Run:
    python -m copilot.webhook_server
"""
from __future__ import annotations

import json
import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src import config
from .rca import build_report

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("copilot.server")

app = FastAPI(title="Agent Black Box — SRE Copilot")
_REPORTS: list[dict] = []  # newest last


@app.post("/alerts")
async def alerts(request: Request):
    payload = await request.json()
    log.info("RAW WEBHOOK PAYLOAD: %s", json.dumps(payload))
    # SigNoz webhooks may send a single alert or a list under "alerts".
    incidents = payload.get("alerts") or [payload]
    out = []
    for alert in incidents:
        report = build_report(alert)
        md = report.to_markdown()
        _REPORTS.append({"markdown": md, "incident": report.incident})
        log.info("\n%s", md)
        out.append({"incident": report.incident})
    return JSONResponse({"received": len(incidents), "reports": out})


@app.get("/", response_class=HTMLResponse)
async def index():
    if not _REPORTS:
        body = "<p>No incidents yet. Trigger a scenario and wait for an alert to fire.</p>"
    else:
        body = "".join(
            f"<article><pre>{r['markdown']}</pre></article>" for r in reversed(_REPORTS)
        )
    return f"""<!doctype html><meta charset=utf-8>
<title>Agent Black Box — SRE Copilot</title>
<style>
 body{{font:14px/1.5 ui-monospace,Menlo,monospace;max-width:900px;margin:2rem auto;padding:0 1rem;background:#0b0d12;color:#e6e8ee}}
 h1{{font-size:1.4rem}} article{{border:1px solid #2a2f3a;border-radius:8px;padding:1rem;margin:1rem 0;background:#12151c}}
 pre{{white-space:pre-wrap;margin:0}}
</style>
<h1>🛰️ Agent Black Box — SRE Copilot</h1>
<p>{len(_REPORTS)} incident report(s). Latest first.</p>
{body}
"""


@app.get("/health")
async def health():
    return {"ok": True, "reports": len(_REPORTS)}


def main() -> None:
    uvicorn.run(app, host=config.COPILOT_HOST, port=config.COPILOT_PORT)


if __name__ == "__main__":
    main()

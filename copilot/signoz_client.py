"""Thin client over the SigNoz query API — how the copilot gathers *evidence*.

NOTE ON VERSIONS: SigNoz's query surface has moved across v3/v4 and the
builder payload is verbose. Rather than hard-code a payload that breaks on a
different SigNoz build, we expose small helpers and keep the exact request
bodies in one place so you can tweak them against your running instance
(check the Network tab in the SigNoz UI to copy the exact query_range body).

The official SigNoz MCP server is the other supported path: point an MCP client
at it and the copilot can ask for traces/metrics/logs/alerts in natural
language. `mcp_hint()` documents that route.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src import config

log = logging.getLogger("copilot.signoz")


class SigNozClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or config.SIGNOZ_API_URL).rstrip("/")
        self.api_key = api_key or config.SIGNOZ_API_KEY
        self._http = httpx.Client(timeout=20.0, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["SIGNOZ-API-KEY"] = self.api_key
        return h

    # --- traces -------------------------------------------------------------
    def get_trace(self, trace_id: str) -> dict[str, Any]:
        """Fetch the full span tree for a trace. Endpoint path may differ by
        version; adjust to your build if you get a 404."""
        url = f"{self.base_url}/api/v1/traces/{trace_id}"
        try:
            r = self._http.get(url)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("get_trace failed (%s); returning stub", e)
            return {"traceId": trace_id, "spans": [], "_error": str(e)}

    # --- metrics / logs via query_range ------------------------------------
    def query_range(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a composite query to /api/v4/query_range. Pass a builder payload
        copied from the SigNoz UI's Network tab for your version."""
        url = f"{self.base_url}/api/v4/query_range"
        try:
            r = self._http.post(url, json=payload)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("query_range failed (%s); returning stub", e)
            return {"data": {}, "_error": str(e)}

    def session_metrics(self, session_id: str, start_ms: int, end_ms: int) -> dict[str, Any]:
        """Convenience: pull the key counters for one session window.
        Returns {retries, tokens, cost_usd, tool_calls} best-effort."""
        # Builder query skeleton — filter each metric by agent.session_id.
        def _q(metric: str, alias: str) -> dict:
            return {
                "queryName": alias, "dataSource": "metrics", "aggregateOperator": "sum",
                "aggregateAttribute": {"key": metric},
                "filters": {"op": "AND", "items": [
                    {"key": {"key": "agent.session_id"}, "op": "=", "value": session_id}
                ]},
                "expression": alias, "disabled": False,
            }
        payload = {
            "start": start_ms, "end": end_ms, "step": 60,
            "compositeQuery": {"queryType": "builder", "panelType": "value", "builderQueries": {
                "A": _q("agent.retries", "A"),
                "B": _q("agent.tokens", "B"),
                "C": _q("agent.cost.usd", "C"),
                "D": _q("agent.tool.calls", "D"),
            }},
        }
        return self.query_range(payload)


def mcp_hint() -> str:
    return (
        "Alternatively, run the SigNoz MCP server and let the copilot query "
        "traces/metrics/logs/alerts in natural language: "
        "https://github.com/SigNoz/signoz (see docs -> MCP)."
    )

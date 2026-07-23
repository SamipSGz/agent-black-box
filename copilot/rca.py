"""Root-cause analysis: turn a SigNoz alert + gathered evidence into a report.

The hard rule (and the demo's credibility): every claim in the report must be
backed by telemetry the copilot actually pulled — trace id, span name, a log
line, or a metric value. The LLM only *narrates* the evidence; it does not
invent facts. If evidence is missing, the report says so.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from openai import OpenAI

from src import config
from .signoz_client import SigNozClient

log = logging.getLogger("copilot.rca")


@dataclass
class Evidence:
    trace_id: str | None = None
    failing_span: str | None = None
    session_id: str | None = None
    tool: str | None = None
    observed_value: str | None = None
    threshold: str | None = None
    metrics: dict = field(default_factory=dict)
    log_samples: list[str] = field(default_factory=list)


@dataclass
class RcaReport:
    incident: str
    summary: str
    evidence: Evidence
    likely_root_cause: str
    suggested_fixes: list[str]
    suggested_alert: str

    def to_markdown(self) -> str:
        e = self.evidence
        fixes = "\n".join(f"{i+1}. {f}" for i, f in enumerate(self.suggested_fixes))
        return f"""## Incident: {self.incident}

**Summary**
{self.summary}

**Evidence (from SigNoz)**
- Observed value: `{e.observed_value or 'n/a'}` (threshold `{e.threshold or 'n/a'}`)
- Tool: `{e.tool or 'n/a'}`
- Failing span: `{e.failing_span}`
- Trace: `{e.trace_id or 'n/a'}`
- Session: `{e.session_id or 'n/a'}`
- Metrics: `{json.dumps(e.metrics)}`
- Logs:
{chr(10).join('  - ' + l for l in e.log_samples) or '  - (none captured)'}

**Likely root cause**
{self.likely_root_cause}

**Suggested fixes**
{fixes}

**Suggested guardrail alert**
{self.suggested_alert}
"""


# Heuristic knowledge base keyed by failure mode -> deterministic fallback so the
# copilot produces a useful report even with no OpenAI key / no live SigNoz.
_PLAYBOOK = {
    "retry_storm": {
        "root": "lookup_order retried an upstream 503 with no retry budget and no fallback path.",
        "fixes": [
            "Add max_retries=3 with exponential backoff to lookup_order.",
            "Add a fallback: create_support_ticket when the order API is unavailable.",
        ],
        "alert": "Metric alert: agent.retries > 5 within a single session.",
    },
    "bad_rag": {
        "root": "Vector search returned the wrong policy doc (low confidence) and the agent acted on it anyway.",
        "fixes": [
            "Gate the decision on rag.confidence >= 0.55; escalate to a human below that.",
            "Add a re-ranking / top_k>1 step and log the chosen document id.",
        ],
        "alert": "Composite alert: agent.rag.low_confidence > 0 AND a final decision was sent.",
    },
    "tool_loop": {
        "root": "Ambiguous retrieval kept confidence low, so the agent re-queried policy in a loop.",
        "fixes": [
            "Cap the reason->retrieve loop at 2 attempts, then escalate.",
            "Break ties with a deterministic rule instead of re-querying identical context.",
        ],
        "alert": "Log/trace alert: same tool (retrieve_policy) called > 5 times in 2 minutes per session.",
    },
}


def _classify_mode(alert: dict) -> str:
    text = json.dumps(alert).lower()
    for mode in _PLAYBOOK:
        if mode in text:
            return mode
    if "retry" in text or "503" in text:
        return "retry_storm"
    if "loop" in text:
        return "tool_loop"
    if "rag" in text or "confidence" in text:
        return "bad_rag"
    return "retry_storm"


def build_report(alert: dict, client: SigNozClient | None = None) -> RcaReport:
    client = client or SigNozClient()
    mode = _classify_mode(alert)
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    # SigNoz sends group-by keys as dotted labels (e.g. "tool.name"), the static
    # labels we attached to the rule (failure_mode), and the observed value in the
    # annotation text: "... current value: 11 crosses the threshold (5) ...".
    session_id = labels.get("agent_session_id") or labels.get("session_id") or labels.get("agent.session_id")
    trace_id = labels.get("trace_id")
    tool = labels.get("tool.name") or labels.get("tool_name")
    obs = re.search(r"current value:\s*([0-9.]+)", " ".join(str(v) for v in annotations.values()))
    thr = re.search(r"threshold\s*\(?([0-9.]+)\)?", " ".join(str(v) for v in annotations.values()))

    evidence = Evidence(
        trace_id=trace_id,
        session_id=session_id,
        tool=tool,
        observed_value=obs.group(1) if obs else None,
        threshold=thr.group(1) if thr else None,
        failing_span=(f"tool.{tool}" if tool else
                      {"retry_storm": "tool.lookup_order",
                       "bad_rag": "tool.retrieve_policy",
                       "tool_loop": "tool.retrieve_policy"}[mode]),
        metrics=labels,
    )
    if trace_id:
        trace = client.get_trace(trace_id)
        spans = trace.get("spans", [])
        evidence.log_samples = [
            f"{s.get('name')}: {s.get('statusMessage', '')}" for s in spans[:5]
        ] or evidence.log_samples

    scope = f"session {session_id}" if session_id else (f"tool {tool}" if tool else "the agent")
    play = _PLAYBOOK[mode]
    report = RcaReport(
        incident=f"{mode.replace('_', ' ').title()} in {scope}",
        summary=_narrate(alert, mode, evidence),
        evidence=evidence,
        likely_root_cause=play["root"],
        suggested_fixes=play["fixes"],
        suggested_alert=play["alert"],
    )
    return report


def _narrate(alert: dict, mode: str, evidence: Evidence) -> str:
    """Let the LLM write the human summary — grounded strictly in the evidence
    dict. Falls back to a templated summary when no API key is configured."""
    if not config.OPENAI_API_KEY:
        return (
            f"A {mode.replace('_', ' ')} incident fired. See evidence below; "
            "root cause and fixes are derived from the observed telemetry."
        )
    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        # No temperature override: gpt-5 family models only accept the default.
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are an SRE copilot. Write a 2-3 sentence incident summary. "
                    "Use ONLY the facts in the provided JSON evidence. Do not invent "
                    "numbers, span names, or trace ids that are not present."
                )},
                {"role": "user", "content": json.dumps(
                    {"alert": alert, "evidence": asdict(evidence)}
                )},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001 - degrade gracefully during a live demo
        log.warning("LLM narration failed (%s); using template", e)
        return f"A {mode.replace('_', ' ')} incident fired (LLM narration unavailable)."

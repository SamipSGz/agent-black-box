"""Verify the flight recorder without needing SigNoz or OpenAI running.

Strategy:
  - install in-memory OTel providers (via `otel_setup`, imported first),
  - stub `src.llm.chat` so no OpenAI call is made,
  - run each scenario and assert the spans/attributes we rely on for the
    dashboards, alerts, and the copilot's evidence actually get emitted.
"""
from __future__ import annotations

# Import order matters: install in-memory providers BEFORE app modules.
from tests import otel_setup  # noqa: E402  (side-effecting import)

import src.llm as llm  # noqa: E402
from src.agent import run_session  # noqa: E402
from src.scenarios import BAD_RAG, HAPPY, RETRY_STORM, TOOL_LOOP  # noqa: E402


# Stub ONLY the OpenAI client, so the real llm.chat() runs and we genuinely
# verify the gen_ai span + token/cost metrics get emitted (no network/key).
class _FakeUsage:
    prompt_tokens = 30
    completion_tokens = 20


class _FakeMessage:
    # Routing depends on RAG confidence, not this text, so a constant is fine.
    content = "approve"


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    usage = _FakeUsage()
    model = "gpt-4o-mini"
    choices = [_FakeChoice()]


class _FakeCompletions:
    def create(self, **_kw):
        return _FakeResponse()


class _FakeClient:
    class chat:  # noqa: N801 - mirrors the OpenAI SDK shape
        completions = _FakeCompletions()


llm._client_singleton = lambda: _FakeClient()  # bypasses OpenAI entirely


def _spans_named(name):
    return [s for s in otel_setup.span_exporter.get_finished_spans() if s.name == name]


def _root():
    return _spans_named("support_agent.session")[0]


def setup_function(_fn):
    otel_setup.span_exporter.clear()


def test_happy_path_has_clean_trace():
    run_session(HAPPY, session_id="t-happy")
    assert _root().attributes["failure.mode"] == "none"
    # one lookup, exactly one policy retrieval (no loop), and a gen_ai span
    assert len(_spans_named("tool.retrieve_policy")) == 1
    chat_spans = [s for s in otel_setup.span_exporter.get_finished_spans() if s.name.startswith("chat ")]
    assert chat_spans, "expected at least one gen_ai chat span"
    assert chat_spans[0].attributes["gen_ai.system"] == "openai"


def test_retry_storm_records_retries_and_marks_failure():
    run_session(RETRY_STORM, session_id="t-retry")
    lookup = _spans_named("tool.lookup_order")[0]
    assert lookup.attributes["tool.retry_count"] == 11
    assert str(lookup.status.status_code) == "StatusCode.ERROR"
    assert _root().attributes["failure.mode"] == "retry_storm"


def test_bad_rag_loops_twice_then_denies():
    run_session(BAD_RAG, session_id="t-badrag")
    # low confidence -> one healthy re-query -> capped at NORMAL_LOOP_CAP (2)
    assert len(_spans_named("tool.retrieve_policy")) == 2
    assert _root().attributes["failure.mode"] == "bad_rag"


def test_tool_loop_spirals_to_cap():
    run_session(TOOL_LOOP, session_id="t-loop")
    # unbounded loop caps at RUNAWAY_LOOP_CAP (7) — enough to trip the >5 alert
    assert len(_spans_named("tool.retrieve_policy")) == 7
    assert _root().attributes["failure.mode"] == "tool_loop"


def test_custom_metrics_are_emitted():
    run_session(RETRY_STORM, session_id="t-metrics")
    names = otel_setup.metric_names()
    assert "agent.retries" in names
    assert "agent.tokens" in names
    assert "agent.session.duration" in names

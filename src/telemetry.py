"""OpenTelemetry bootstrap: traces + metrics + logs, all exported to SigNoz.

Call `init_telemetry()` exactly once at process start. After that:
    - `tracer` gives you spans
    - `meter`  gives you metric instruments (see metrics.py)
    - standard `logging` is bridged to OTLP, so every log line lands in SigNoz
      logs with its trace_id/span_id attached (trace<->log correlation).
"""
from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from . import config

_INITIALISED = False


def init_telemetry() -> None:
    global _INITIALISED
    if _INITIALISED:
        return

    resource = Resource.create(
        {
            "service.name": config.SERVICE_NAME,
            "service.version": config.AGENT_VERSION,
            "deployment.environment": "hackathon-demo",
            # Pin a stable instance id. Each demo run is a separate short-lived
            # process; without this the SDK assigns a fresh service.instance.id
            # per run, so every run becomes its own ephemeral counter series and
            # SigNoz's rate()/increase() (which need a rising series over time)
            # evaluate to ~0 — alerts never fire. A constant id lets sequential
            # runs share one series that accumulates across sessions.
            "service.instance.id": config.SERVICE_NAME + "-agent-1",
        }
    )

    # --- traces ---
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{config.OTEL_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    # --- metrics ---
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{config.OTEL_ENDPOINT}/v1/metrics"),
        export_interval_millis=5_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    # --- logs ---
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{config.OTEL_ENDPOINT}/v1/logs"))
    )
    set_logger_provider(logger_provider)

    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Also echo to the console so the live demo shows something.
    root.addHandler(logging.StreamHandler())

    _INITIALISED = True


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("agent-black-box")


def get_meter() -> metrics.Meter:
    return metrics.get_meter("agent-black-box")

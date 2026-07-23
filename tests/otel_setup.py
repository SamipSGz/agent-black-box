"""Test-only OTel harness.

Importing this module installs in-memory trace + metric providers on the global
OTel SDK. It MUST be imported before any app module that reads the global
providers (notably `src.metrics`, whose instruments are cached on first use).
Tests import this first, then import `src.agent`.
"""
from __future__ import annotations

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

span_exporter = InMemorySpanExporter()
_tp = TracerProvider()
_tp.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(_tp)

metric_reader = InMemoryMetricReader()
otel_metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))


def metric_names() -> set[str]:
    """Flatten the in-memory metric data into a set of metric names."""
    data = metric_reader.get_metrics_data()
    names: set[str] = set()
    if not data:
        return names
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                names.add(metric.name)
    return names

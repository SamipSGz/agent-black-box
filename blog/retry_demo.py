"""Minimal OpenTelemetry demo for the SigNoz trace<->log correlation tutorial.

Sends traces, logs, and one metric to a locally running SigNoz over OTLP/HTTP.
The order lookup fails with a 503 most of the time and retries, so the retry
storm shows up as events on the span, as correlated log lines, and as a
climbing retry counter you can chart on a dashboard.

    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    python retry_demo.py                 # send a short burst and exit
    RUN_SECONDS=90 python retry_demo.py  # keep sending for 90s (nicer charts)
"""
import logging
import os
import random
import time

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

ENDPOINT = "http://localhost:4318"
resource = Resource.create({"service.name": "order-service"})

# traces
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{ENDPOINT}/v1/traces"))
)
trace.set_tracer_provider(tracer_provider)

# logs, bridged into the standard logging module
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{ENDPOINT}/v1/logs"))
)
set_logger_provider(logger_provider)
logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))
logging.getLogger().setLevel(logging.INFO)

# metrics, exported on a 5s timer
meter_provider = MeterProvider(
    resource=resource,
    metric_readers=[
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{ENDPOINT}/v1/metrics"),
            export_interval_millis=5000,
        )
    ],
)
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("order-service")
retries_counter = meter.create_counter(
    "order.retries", unit="1", description="order lookup retries"
)

tracer = trace.get_tracer("order-service")
log = logging.getLogger("orders")


def lookup_order(order_id: str) -> dict:
    with tracer.start_as_current_span("lookup_order") as span:
        span.set_attribute("order.id", order_id)
        attempts = 0
        while True:
            attempts += 1
            if random.random() < 0.7 and attempts < 12:
                log.warning("order service 503, retrying (attempt %d)", attempts)
                span.add_event("retry", {"attempt": attempts})
                retries_counter.add(1, {"order.id": order_id})
                time.sleep(0.2)
                continue
            span.set_attribute("lookup.attempts", attempts)
            log.info("order %s resolved after %d attempts", order_id, attempts)
            return {"id": order_id}


if __name__ == "__main__":
    order_ids = ["A-1042", "A-2091", "A-3157", "A-4480", "A-5561"]
    run_seconds = float(os.environ.get("RUN_SECONDS", "0"))
    started = time.time()
    i = 0
    while True:
        order_id = order_ids[i % len(order_ids)]
        with tracer.start_as_current_span("handle_request") as root:
            root.set_attribute("request.id", f"req-{order_id}-{i}")
            lookup_order(order_id)
        i += 1
        if run_seconds <= 0 and i >= len(order_ids):
            break
        if run_seconds > 0 and (time.time() - started) >= run_seconds:
            break
        time.sleep(0.5)
    # flush the last batch of each signal before exit
    tracer_provider.shutdown()
    logger_provider.shutdown()
    meter_provider.shutdown()
    print(f"sent {i} traces + logs + retry metric to SigNoz")

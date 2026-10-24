from __future__ import annotations

from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_READY = False


def setup_otel(service_name: str, endpoint: str = "") -> None:
    global _READY
    if _READY:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _READY = True


def get_tracer(name: str = "agent-runtime"):
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attrs):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as current:
        for key, value in attrs.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                current.set_attribute(key, value if not isinstance(value, str) else value[:500])
            else:
                current.set_attribute(key, str(value)[:500])
        yield current

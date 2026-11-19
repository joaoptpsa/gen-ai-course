"""Trace incident runs with OpenTelemetry: one masked trace per run, exported over OTLP when set.

Every span passes through MaskingExporter before it reaches the in-memory RunCollector (whose spans
the workbench saves under results/) or the OTLP exporter. OTLP export is on whenever
OTEL_EXPORTER_OTLP_ENDPOINT or OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is set.
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Link, Span, Status, Tracer
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings

from app.core.masking import mask_personal_data

SERVICE_NAME = "meridian-workbench"
TRACER_NAME = "meridian.workbench"
# Pinned so the span format the critic and the span files rely on does not move with pydantic-ai.
INSTRUMENTATION_VERSION = 6
ATTRIBUTE_MAX_CHARS = 4000
# The root span holds one event per simulator tool call; the SDK default of 128 drops the earliest.
MAX_EVENTS_PER_SPAN = 10_000
OTLP_ENDPOINT_VARIABLES = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)
# Attributes a span file keeps, as in sessions/.../08-agents-in-production/lab/record.py.
KEPT_ATTRIBUTES = (
    "gen_ai.operation.name",
    "gen_ai.agent.name",
    "gen_ai.request.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.tool.name",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
    "gen_ai.output.messages",
    "final_result",
)
KEPT_PREFIX = "meridian."


# Masking -------------------------------------------------------------------------------


def _masked_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_personal_data(value)
    if isinstance(value, dict):
        return {
            mask_personal_data(key): _masked_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_masked_json_value(item) for item in value]
    return value


def _masked_json(text: str) -> str | None:
    """`text` with personal data masked in its strings only, or None when it is not JSON.

    Tool arguments and results arrive as JSON. Masking them as plain text would put a bare
    `[phone]` where a nine-digit number stood, and the critic could no longer parse them.
    """
    if not text.lstrip().startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    masked = json.dumps(_masked_json_value(parsed), ensure_ascii=False)
    return masked


def _masked_text(text: str) -> str:
    masked = _masked_json(text)
    if masked is None:
        masked = mask_personal_data(text)
    # Mask before capping: a cut can leave half an address that no pattern matches.
    capped = masked[:ATTRIBUTE_MAX_CHARS]
    return capped


def _masked_value(value: Any) -> Any:
    if isinstance(value, str):
        return _masked_text(value)
    if isinstance(value, Mapping):
        return {key: _masked_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return tuple(_masked_value(item) for item in value)
    return value


def _masked_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: _masked_value(value) for key, value in (attributes or {}).items()}


def masked_span(span: ReadableSpan) -> ReadableSpan:
    """A copy of `span` with personal data masked in every text it carries."""
    events = [
        Event(event.name, _masked_attributes(event.attributes), event.timestamp)
        for event in span.events
    ]
    links = [
        Link(link.context, _masked_attributes(link.attributes)) for link in span.links
    ]
    status = Status(
        span.status.status_code,
        _masked_text(span.status.description) if span.status.description else None,
    )
    resource = Resource(
        _masked_attributes(span.resource.attributes), span.resource.schema_url
    )
    masked = ReadableSpan(
        name=_masked_text(span.name),
        context=span.context,
        parent=span.parent,
        resource=resource,
        attributes=_masked_attributes(span.attributes),
        events=events,
        links=links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )
    return masked


class MaskingExporter(SpanExporter):
    """Exports masked copies of finished spans, which can no longer be changed in place."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([masked_span(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class RunCollector(SpanExporter):
    """Holds finished spans in memory by trace id until the run that made them takes them."""

    def __init__(self) -> None:
        self._spans: dict[int, list[ReadableSpan]] = {}
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            for span in spans:
                trace_id = span.context.trace_id if span.context else 0
                self._spans.setdefault(trace_id, []).append(span)
        return SpanExportResult.SUCCESS

    def take(self, trace_id: int) -> list[ReadableSpan]:
        """Remove and return the spans of one trace."""
        with self._lock:
            spans = self._spans.pop(trace_id, [])
        return spans

    def shutdown(self) -> None:
        with self._lock:
            self._spans.clear()


# Setup -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tracing:
    tracer: Tracer
    collector: RunCollector
    exports_otlp: bool


_TRACING: Tracing | None = None
_SETUP_LOCK = threading.Lock()


def otlp_endpoint_set() -> bool:
    return any(os.environ.get(name) for name in OTLP_ENDPOINT_VARIABLES)


def _build_tracing() -> Tracing:
    # OTEL_SERVICE_NAME, when set, wins over the workbench's own name.
    attributes = {} if os.environ.get("OTEL_SERVICE_NAME") else {"service.name": SERVICE_NAME}
    # Every span is kept: a sampler set through OTEL_TRACES_SAMPLER would leave runs without
    # the span files the results rely on.
    provider = TracerProvider(
        sampler=ALWAYS_ON,
        resource=Resource.create(attributes),
        span_limits=SpanLimits(max_events=MAX_EVENTS_PER_SPAN),
    )
    atexit.register(provider.shutdown)
    collector = RunCollector()
    provider.add_span_processor(SimpleSpanProcessor(MaskingExporter(collector)))
    exports_otlp = otlp_endpoint_set()
    if exports_otlp:
        provider.add_span_processor(
            BatchSpanProcessor(MaskingExporter(OTLPSpanExporter()))
        )
    Agent.instrument_all(
        InstrumentationSettings(
            tracer_provider=provider,
            include_content=True,
            version=INSTRUMENTATION_VERSION,
        )
    )
    tracing = Tracing(provider.get_tracer(TRACER_NAME), collector, exports_otlp)
    return tracing


def configure_tracing() -> Tracing:
    """Set up tracing for this process once, and instrument every PydanticAI agent.

    Call it before starting worker threads; later calls return the same setup.
    """
    global _TRACING
    with _SETUP_LOCK:
        if _TRACING is None:
            _TRACING = _build_tracing()
        tracing = _TRACING
    return tracing


# One trace per run -----------------------------------------------------------------------


@dataclass
class RunTrace:
    """The root span of one run while it is open; `spans` holds the masked span records after."""

    root: Span
    trace_id: str
    spans: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def run_span(tracing: Tracing, attributes: Mapping[str, Any]) -> Generator[RunTrace]:
    """Open the `workbench.run` root span; on exit, collect the run's spans as records.

    The spans are taken only after the root has ended, so the records include it. A run that
    raises still has its spans taken, so none stay in memory.
    """
    trace_id = 0
    try:
        # An empty context makes every run its own trace, even inside a caller's active span.
        with tracing.tracer.start_as_current_span(
            "workbench.run", context=Context(), attributes=dict(attributes)
        ) as root:
            trace_id = root.get_span_context().trace_id
            run_trace = RunTrace(root, f"{trace_id:032x}")
            yield run_trace
    finally:
        spans = tracing.collector.take(trace_id)
    run_trace.spans = span_records(spans)


# Span files -----------------------------------------------------------------------------


def _record_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {key: _record_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return [_record_value(item) for item in value]
    return str(value)


def _kept(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        key: _record_value(value)
        for key, value in (attributes or {}).items()
        if key in KEPT_ATTRIBUTES or key.startswith(KEPT_PREFIX)
    }


def span_records(spans: Sequence[ReadableSpan]) -> list[dict[str, Any]]:
    """Spans in the JSON shape of the session 8 lab (record.py), plus their events."""
    ordered = sorted(spans, key=lambda span: span.start_time or 0)
    start = ordered[0].start_time or 0 if ordered else 0
    records = []
    for span in ordered:
        context = span.context
        records.append(
            {
                "name": span.name,
                "trace_id": f"{context.trace_id:032x}" if context else "",
                "span_id": f"{context.span_id:016x}" if context else "",
                "parent_id": f"{span.parent.span_id:016x}" if span.parent else None,
                "start_ms": round(((span.start_time or start) - start) / 1e6, 1),
                "end_ms": round(((span.end_time or start) - start) / 1e6, 1),
                "status": span.status.status_code.name,
                "error": span.status.description,
                "attributes": _kept(span.attributes),
                "events": [
                    {
                        "name": event.name,
                        "attributes": _record_value(dict(event.attributes or {})),
                    }
                    for event in span.events
                ],
            }
        )
    return records

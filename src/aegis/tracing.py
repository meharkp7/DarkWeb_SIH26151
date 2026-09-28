"""Optional OpenTelemetry tracing with a dependency-free fallback."""
from __future__ import annotations
from contextlib import contextmanager
from collections.abc import Iterator

@contextmanager
def span(name: str, **attributes: object) -> Iterator[None]:
    """Create an OpenTelemetry span when the optional extra is installed."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield
        return
    tracer = trace.get_tracer("aegis")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, str(value))
        yield

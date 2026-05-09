"""
Azure Application Insights telemetry setup.
Production-ready OpenTelemetry configuration.
"""
import logging

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from config import APPLICATIONINSIGHTS_CONNECTION_STRING

logger = logging.getLogger(__name__)


_tracer = None


def setup_azure_telemetry(app=None):
    """
    Initialize Azure Application Insights.
    Must be called ONCE during application startup.
    """
    # Reads the connection string
    connection_string = APPLICATIONINSIGHTS_CONNECTION_STRING
    if not connection_string:
        # Telemetry disabled safely if env variable not present
        logger.info("App Insights connection string not set; telemetry disabled.")
        return None
    logger.info("App Insights telemetry enabled.")

    #Connects to Azure Application Insights
    #Starts sending logs, traces, errors, metrics to Azure
    #Enables live metrics dashboard
    configure_azure_monitor(
        connection_string=connection_string,
        enable_live_metrics=True,
    )


    # Framework instrumentation
    # Automatically logs ALL API requests (FastAPI)
    if app:
        FastAPIInstrumentor.instrument_app(app)


    #Automatically logs outgoing calls
    RequestsInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()

    global _tracer #global - it is created once , so it can be reused everywhere
  
    _tracer = trace.get_tracer("menabot")

    return _tracer


def get_tracer(): #If any other file needs the telemetry tracer, give them the same one.
    """
    Safe accessor for the telemetry tracer.
    """
    return _tracer


def get_tracer_span(span_name: str):
    """
    Returns a context manager for a tracer span.
    If tracer is None (telemetry not initialized), returns a no-op context manager.
    """
    from contextlib import contextmanager

    @contextmanager
    def no_op():
        yield

    tracer = get_tracer()
    if tracer is None:
        return no_op()

    return tracer.start_as_current_span(span_name)


def record_event(name: str, attributes: dict | None = None) -> None:
    """Add an event to the current active span. No-op if telemetry disabled."""
    try:
        span = trace.get_current_span()
        if span is None:
            return
        span.add_event(name, attributes=attributes or {})
    except Exception:
        logger.debug("record_event failed", exc_info=True)


def record_exception(exc: BaseException, attributes: dict | None = None) -> None:
    """Record an exception on the current active span. No-op if telemetry disabled."""
    try:
        span = trace.get_current_span()
        if span is None:
            return
        span.record_exception(exc, attributes=attributes or {})
    except Exception:
        logger.debug("record_exception failed", exc_info=True)

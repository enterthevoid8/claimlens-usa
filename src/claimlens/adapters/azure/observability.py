from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def configure_azure_monitor(connection_string: str) -> bool:
    """Send traces, metrics and logs to Application Insights (OpenTelemetry). No-op without a connection string."""
    if not connection_string:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor as _configure
    except ImportError:  # pragma: no cover
        log.warning("azure-monitor-opentelemetry not installed; telemetry disabled")
        return False
    _configure(connection_string=connection_string)
    return True

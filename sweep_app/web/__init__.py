"""Local web interface for Sweep.

The TUI and the web UI share the same engine: this package only adds an HTTP
transport, a background-job runner and a static single-page app.
"""
from __future__ import annotations

__all__ = ["server", "service", "jobs", "errors"]

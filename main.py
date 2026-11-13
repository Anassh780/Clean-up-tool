"""Sweep launcher — puts the bundled dependencies on sys.path, then runs."""
from __future__ import annotations

import os
import sys

# CLI output uses box-drawing characters; make redirected/piped runs safe too.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
if os.path.isdir(VENDOR) and VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from sweep_app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

"""``python -m sweep_app`` — same commands as ``main.py`` without a wrapper.

``main.py`` puts the bundled dependencies on ``sys.path`` before importing the
package. Running the module directly skips that step, so a clean checkout would
fail on ``psutil``; do the same setup here and the two entry points behave
identically.
"""
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
ROOT = os.path.dirname(HERE)
VENDOR = os.path.join(ROOT, "vendor")
if os.path.isdir(VENDOR) and VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from .cli import main  # noqa: E402

raise SystemExit(main())

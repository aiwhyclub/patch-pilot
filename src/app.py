"""Vercel Function entrypoint.

The Python builder resolves ``tool.vercel.entrypoint`` from the repository
root only. ``patchpilot.web.app`` looks for ``patchpilot/web/app.py``, which
this src-layout package does not have. ``src.app`` is ``src/app.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from patchpilot.web.app import app as app

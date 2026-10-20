#!/usr/bin/env python3
"""ArcOps TUI compatibility shim.

The Textual dashboard lives in the installed package
(``cloudops_fc.tui``) so ``arcops tui`` works from a wheel. This module
keeps ``python -m app.tui`` working from a checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.tui import main  # noqa: E402

__all__ = ["main"]


if __name__ == "__main__":
    main()

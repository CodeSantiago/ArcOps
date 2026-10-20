#!/usr/bin/env python3
"""ArcOps CLI shim — delegates to the installed package.

Installed console command: ``arcops`` (see ``[project.scripts]`` in
``pyproject.toml``). This file lets you run ``python cloudops.py`` from a
repo checkout without installing the package: it bootstraps ``src/`` onto
``sys.path`` so ``cloudops_fc`` resolves.

``python cloudops.py tui`` launches the terminal dashboard via the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

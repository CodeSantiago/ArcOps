"""ArcOps safety — compatibility shim.

The canonical safety layer lives in ``cloudops_fc.safety`` (part of the
installed package). This module re-exports it so ``app.safety`` imports keep
working for repo-checkout tools, with a ``src`` bootstrap so it works without
installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.safety import (  # noqa: E402
    EC2_PRICING,
    HOURS_PER_MONTH,
    RDS_PRICING,
    TOOL_SCHEMAS,
    SafetyResult,
    apply_policies,
    check,
    estimate_cost,
    main,
    validate_schema,
)

__all__ = [
    "EC2_PRICING",
    "HOURS_PER_MONTH",
    "RDS_PRICING",
    "TOOL_SCHEMAS",
    "SafetyResult",
    "apply_policies",
    "check",
    "estimate_cost",
    "main",
    "validate_schema",
]

if __name__ == "__main__":
    main()

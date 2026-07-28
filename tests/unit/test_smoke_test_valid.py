"""Tests that smoke_test.py is syntactically valid Python (RED phase)."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TEST_PATH = PROJECT_ROOT / "scripts" / "training" / "smoke_test.py"


class TestSmokeTestSyntax:
    """R1: smoke_test.py MUST be syntactically valid Python."""

    def test_file_exists(self) -> None:
        """smoke_test.py MUST exist at scripts/training/."""
        assert SMOKE_TEST_PATH.is_file(), (
            f"smoke_test.py not found at {SMOKE_TEST_PATH}"
        )

    def test_syntactically_valid(self) -> None:
        """smoke_test.py MUST parse as valid Python AST."""
        source = SMOKE_TEST_PATH.read_text("utf-8")
        tree = ast.parse(source, filename=str(SMOKE_TEST_PATH))
        assert isinstance(tree, ast.Module), "Expected a valid Python module"

    def test_contains_main_guard(self) -> None:
        """smoke_test.py MUST use if __name__ == '__main__' guard."""
        source = SMOKE_TEST_PATH.read_text("utf-8")
        assert 'if __name__ == "__main__"' in source or (
            "if __name__ == '__main__'" in source
        ), "Missing __name__ == '__main__' guard"

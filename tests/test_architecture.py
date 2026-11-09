from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_import_contracts_hold() -> None:
    """The contracts in pyproject.toml: the engine does not know its clients, the
    CLI only uses the public API, and layers only reach down."""
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    if lint_imports is None:
        pytest.skip("import-linter is not installed (uv sync --extra dev)")

    result = subprocess.run(
        [lint_imports, "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr

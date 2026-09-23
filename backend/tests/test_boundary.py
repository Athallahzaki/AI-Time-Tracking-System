"""backend <-> engine: the TCP NDJSON contract is the only runtime boundary."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _offenders(package: str, forbidden: str):
    for path in (ROOT / package).rglob("*.py"):
        if "tests" in path.parts:
            continue  # integration tests may drive both sides over a real socket
        for name in _imports(path):
            if name == forbidden or name.startswith(forbidden + "."):
                yield f"{path.relative_to(ROOT)} imports {name}"


def test_backend_never_imports_engine():
    assert list(_offenders("backend", "engine")) == []


def test_engine_never_imports_backend():
    assert list(_offenders("engine", "backend")) == []

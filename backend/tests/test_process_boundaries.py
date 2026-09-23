"""Regresi untuk menjaga engine dan backend tetap dapat dipasang terpisah."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _production_python_files(component: str):
    root = ROOT / component
    return (
        path
        for path in root.rglob("*.py")
        if "tests" not in path.relative_to(root).parts
    )


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_backend_does_not_import_engine_implementation():
    violations = [
        str(path.relative_to(ROOT))
        for path in _production_python_files("backend")
        if "engine" in _import_roots(path)
    ]
    assert violations == []


def test_engine_does_not_import_backend_implementation():
    violations = [
        str(path.relative_to(ROOT))
        for path in _production_python_files("engine")
        if "backend" in _import_roots(path)
    ]
    assert violations == []

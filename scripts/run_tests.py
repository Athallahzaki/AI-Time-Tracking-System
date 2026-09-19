#!/usr/bin/env python3
"""Penjalan tes cadangan, untuk lingkungan tanpa pytest.

`pytest` tetap yang sebenarnya — berkas tesnya ditulis dalam gaya pytest dan
`pytest -q` adalah perintah yang dipakai sehari-hari. Skrip ini ada untuk satu
alasan praktis: mesin CI yang belum sempat dipasangi apa-apa, dan kontainer
tertutup yang tidak bisa menjangkau PyPI. Di situ pilihannya bukan "pytest atau
ini", tapi "ini atau tidak menjalankan tes sama sekali", dan yang kedua adalah
bagaimana tes berhenti dipercaya.

Yang didukung: fungsi `test_*`, fixture sederhana lewat nama argumen,
`@pytest.mark.parametrize`, dan `pytest.raises`. Kalau sebuah tes butuh lebih
dari itu, tulis tesnya dan jalankan dengan pytest sungguhan — jangan menambah
fitur ke sini.

    python scripts/run_tests.py            # semua
    python scripts/run_tests.py fake_engine  # yang namanya mengandung ini
"""

from __future__ import annotations

import importlib
import inspect
import sys
import traceback
import types
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
TEST_MODULES = ["contracts.tests.test_contract", "contracts.tests.test_fake_engine"]


class _Raises:
    def __init__(self, expected):
        self.expected = expected
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        if exc_type is None:
            raise AssertionError(f"tidak ada {self.expected.__name__} yang dilempar")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        return True


def _install_pytest_shim() -> types.ModuleType:
    module = types.ModuleType("pytest")

    def fixture(*args, **kwargs):
        def decorate(function):
            function._is_fixture = True
            return function
        return decorate(args[0]) if args and callable(args[0]) else decorate

    def parametrize(argnames, argvalues, ids=None, **_):
        names = [n.strip() for n in argnames.split(",")]

        def decorate(function):
            cases = []
            for value in argvalues:
                values = value if isinstance(value, tuple) else (value,)
                label = ids(values[0]) if callable(ids) else str(values[0])
                cases.append((label, dict(zip(names, values))))
            function._parametrize = cases
            return function
        return decorate

    mark = types.SimpleNamespace(parametrize=parametrize)
    module.fixture = fixture
    module.mark = mark
    module.raises = lambda expected: _Raises(expected)
    module.skip = lambda reason="": (_ for _ in ()).throw(RuntimeError(f"skip: {reason}"))
    sys.modules["pytest"] = module
    return module


def _collect_fixtures(module) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    for name, value in vars(module).items():
        if callable(value) and getattr(value, "_is_fixture", False):
            resolved[name] = value()
    return resolved


def run(filter_text: str = "") -> int:
    _install_pytest_shim()
    sys.path.insert(0, str(ROOT))

    passed: List[str] = []
    failed: List[str] = []

    for module_name in TEST_MODULES:
        module = importlib.import_module(module_name)
        fixtures = _collect_fixtures(module)
        short = module_name.rsplit(".", 1)[-1]

        print(f"\n{module_name}")
        for name in sorted(n for n in dir(module) if n.startswith("test_")):
            function = getattr(module, name)
            if not callable(function):
                continue

            cases = getattr(function, "_parametrize", [("", {})])
            for label, bound in cases:
                display = f"{short}::{name}" + (f"[{label}]" if label else "")
                if filter_text and filter_text not in display:
                    continue

                kwargs = dict(bound)
                for parameter in inspect.signature(function).parameters:
                    if parameter in kwargs:
                        continue
                    if parameter not in fixtures:
                        failed.append(f"{display}: fixture `{parameter}` tidak ada")
                        break
                    kwargs[parameter] = fixtures[parameter]
                else:
                    try:
                        function(**kwargs)
                        passed.append(display)
                        print(f"  ok    {display}")
                        continue
                    except Exception as error:
                        failed.append(f"{display}: {error}")
                        print(f"  GAGAL {display}")
                        traceback.print_exc(limit=3)
                        continue
                print(f"  GAGAL {display}")

    print(f"\n{len(passed)} lulus, {len(failed)} gagal")
    for entry in failed:
        print(f"  - {entry}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else ""))

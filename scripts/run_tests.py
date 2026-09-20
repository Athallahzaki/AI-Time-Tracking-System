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

# Extended in B5. This list used to hold the two contract modules only, so in a
# container without PyPI — which is the exact situation the docstring above
# describes, and the situation B4 itself was written in — the fallback runner
# reported "76 lulus, 0 gagal" while never importing a single engine test. A
# green run that covers a third of the suite is worse than no runner, because it
# is believed.
TEST_MODULES = [
    "contracts.tests.test_contract",
    "contracts.tests.test_fake_engine",
    "engine.tests.test_admission",
    "engine.tests.test_api",
    "engine.tests.test_b0_port",
    "engine.tests.test_b1_bench",
    "engine.tests.test_b4_ingest",
    "engine.tests.test_b5_zones",
    "engine.tests.test_enrollment",
    "engine.tests.test_identity",
    "engine.tests.test_presence",
    "engine.tests.test_store",
]


_MISSING = object()


class _Skipped(Exception):
    """A test that declined to run. Not a pass and not a failure."""


class _Raises:
    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        if exc_type is None:
            raise AssertionError(f"tidak ada {self.expected.__name__} yang dilempar")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match is not None:
            import re

            if not re.search(self.match, str(exc)):
                raise AssertionError(f"pola {self.match!r} tidak ada di {str(exc)!r}")
        self.value = exc
        return True


class _Approx:
    """Enough of `pytest.approx` for the comparisons the engine tests make."""

    def __init__(self, expected, rel=None, abs=None):
        self.expected = expected
        self.rel = rel if rel is not None else 1e-6
        self.abs = abs if abs is not None else 1e-12

    def _close(self, a, b) -> bool:
        import math

        if a is None or b is None:
            return a is b
        return math.isclose(float(a), float(b), rel_tol=self.rel, abs_tol=max(self.abs, 1e-12))

    def __eq__(self, other):
        if isinstance(self.expected, (list, tuple)):
            return len(other) == len(self.expected) and all(
                self._close(o, e) for o, e in zip(other, self.expected)
            )
        if isinstance(self.expected, dict):
            return set(other) == set(self.expected) and all(
                self._close(other[k], self.expected[k]) for k in self.expected
            )
        return self._close(other, self.expected)

    def __repr__(self):
        return f"approx({self.expected!r})"


class _MonkeyPatch:
    """`setattr`/`delattr`/`setenv`, undone after the test. Nothing more."""

    def __init__(self) -> None:
        self._undo: List[Any] = []

    def setattr(self, target, name=_MISSING, value=_MISSING, raising: bool = True):
        # Both call styles, because the engine tests use both:
        #   setattr(module, "name", value)
        #   setattr("engine.factory.build_engine", value)   <- dotted string
        # The second used to raise NotImplementedError here, which turned three
        # real tests into three runner failures and made a green run impossible
        # to distinguish from a broken one.
        if isinstance(target, str):
            value = name
            module_path, _, name = target.rpartition(".")
            if not module_path:
                raise ValueError(f"monkeypatch.setattr needs a dotted path, got {target!r}")
            target = _resolve(module_path)

        old = getattr(target, name, _MISSING)
        if old is _MISSING and raising:
            raise AttributeError(f"{target!r} has no attribute {name!r}")
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def delattr(self, target, name, raising: bool = True):
        old = getattr(target, name, _MISSING)
        if old is _MISSING:
            if raising:
                raise AttributeError(name)
            return
        self._undo.append((target, name, old))
        delattr(target, name)

    def setenv(self, name, value):
        import os

        self.setattr(os.environ, "__setitem__", os.environ.__setitem__, raising=False)
        self._undo.append(("env", name, os.environ.get(name, _MISSING)))
        os.environ[name] = str(value)

    def undo(self) -> None:
        import os

        for target, name, old in reversed(self._undo):
            if target == "env":
                if old is _MISSING:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
            elif old is _MISSING:
                try:
                    delattr(target, name)
                except AttributeError:
                    pass
            else:
                setattr(target, name, old)
        self._undo.clear()


def _resolve(dotted: str):
    """`engine.factory` or `builtins` — imported, or walked from an import."""
    import builtins as _builtins
    import importlib

    try:
        return importlib.import_module(dotted)
    except ImportError:
        head, _, tail = dotted.rpartition(".")
        if not head:
            return _builtins
        return getattr(_resolve(head), tail)


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
    module.raises = lambda expected, match=None: _Raises(expected, match)
    module.approx = lambda expected, rel=None, abs=None: _Approx(expected, rel, abs)
    module.skip = lambda reason="": (_ for _ in ()).throw(_Skipped(reason))
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
    skipped: List[str] = []

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
                # Two builtin fixtures, because the engine tests use them and
                # skipping those tests would be the same silent partial pass this
                # runner was extended to stop.
                import tempfile

                temporary = tempfile.TemporaryDirectory()
                patcher = _MonkeyPatch()
                builtins = {"tmp_path": Path(temporary.name), "monkeypatch": patcher}

                try:
                    for parameter in inspect.signature(function).parameters:
                        if parameter in kwargs:
                            continue
                        if parameter in builtins:
                            kwargs[parameter] = builtins[parameter]
                            continue
                        if parameter not in fixtures:
                            failed.append(f"{display}: fixture `{parameter}` tidak ada")
                            print(f"  GAGAL {display}")
                            break
                        kwargs[parameter] = fixtures[parameter]
                    else:
                        try:
                            function(**kwargs)
                            passed.append(display)
                            print(f"  ok    {display}")
                        except _Skipped as reason:
                            skipped.append(f"{display}: {reason}")
                            print(f"  skip  {display}")
                        except Exception as error:
                            failed.append(f"{display}: {error}")
                            print(f"  GAGAL {display}")
                            traceback.print_exc(limit=3)
                finally:
                    patcher.undo()
                    temporary.cleanup()

    print(f"\n{len(passed)} lulus, {len(failed)} gagal, {len(skipped)} dilewati")
    for entry in failed:
        print(f"  - {entry}")
    for entry in skipped:
        print(f"  ~ {entry}")
    # A skip is printed, never counted as a pass: the tests that skip here say
    # so precisely because they cannot prove anything in this environment.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else ""))

"""Pytest entry point for the existing disposable V4 fixture corpus."""
import importlib.util
import json
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent
_SCRIPT = _ROOT / "run_code_fixtures.py"
_SPEC = importlib.util.spec_from_file_location("run_code_fixtures", _SCRIPT)
assert _SPEC and _SPEC.loader
_FIXTURE_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE_RUNNER)


def _cases():
    return json.loads((_ROOT / "fixtures" / "code_fixtures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_code_fixture(case):
    ok, detail = _FIXTURE_RUNNER._check(case)
    assert ok, detail

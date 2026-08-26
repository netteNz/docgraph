"""Optional organic/hub/code checks against disposable external repositories.

They are deliberately reported as skips when their prerequisite corpus is not
available. Pytest's configured ``-ra`` makes that state explicit in CI logs.
"""
import importlib.util
import json
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent
_SCRIPT = _ROOT / "run_link_fixtures.py"
_SPEC = importlib.util.spec_from_file_location("run_link_fixtures", _SCRIPT)
assert _SPEC and _SPEC.loader
_FIXTURE_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE_RUNNER)


def _cases():
    return json.loads((_ROOT / "fixtures" / "link_fixtures.json").read_text(encoding="utf-8"))


@pytest.mark.external_fixture
@pytest.mark.parametrize("case", _cases(), ids=lambda case: f'{case["bucket"]}-{case["task"]}')
def test_external_link_fixture(case):
    try:
        ok, detail = _FIXTURE_RUNNER._check(case)
    except _FIXTURE_RUNNER._Skip as skipped:
        pytest.skip(
            f"external fixture unavailable ({case['bucket']}: {case['repo']}, "
            f"task={case['task']!r}): {skipped.reason}"
        )
    assert ok, detail

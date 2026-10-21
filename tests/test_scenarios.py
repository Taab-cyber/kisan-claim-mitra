"""TC1-TC4 and failure scenarios (same definitions as run_tests.py and the judge console)."""
import pytest

from agent.scenarios import SCENARIOS, run_scenario


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(portal, sc):
    result = run_scenario(sc, portal, timeout=0.3)
    failed = [ch["label"] for ch in result["checks"] if not ch["ok"]]
    assert result["passed"], f"error={result['error']} failed_checks={failed}"

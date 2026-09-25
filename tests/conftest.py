import pytest
from support.golden import REGENERATE


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail regeneration runs so an exported flag cannot make later runs pass."""
    if REGENERATE:
        print("\nRULEHALL_GOLDEN_REGEN was set: fixtures were rewritten, nothing was checked.")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED

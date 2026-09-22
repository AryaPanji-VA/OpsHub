"""Verify tests preserve the user's runtime JSON bytes."""

from pathlib import Path

import pytest


DATA_DIR = Path(__file__).parent.parent / "data"
BASELINE = {
    name: (DATA_DIR / name).read_bytes() if (DATA_DIR / name).exists() else None
    for name in ("budgets.json", "schedules.json", "tickets.json")
}


@pytest.mark.parametrize("name", BASELINE)
def test_runtime_file_unchanged(name):
    path = DATA_DIR / name
    current = path.read_bytes() if path.exists() else None
    assert current == BASELINE[name], f"Runtime {name} changed during tests"

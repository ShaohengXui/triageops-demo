"""Shared pytest fixtures.

The tests require the synthetic dataset. If it is missing (fresh clone), the
seeder runs once so `pytest -q` works without a manual step.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "triageops.db"
CASES = ROOT / "data" / "eval_cases.json"


def pytest_configure(config):  # noqa: D401
    if not DB.exists() or not CASES.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_data.py")], check=True, cwd=ROOT)


@pytest.fixture(scope="session")
def cases() -> list[dict]:
    import json

    return json.loads(CASES.read_text(encoding="utf-8"))

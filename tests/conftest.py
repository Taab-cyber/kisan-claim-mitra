"""Shared pytest fixtures."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

# Make the repo root importable (so `import portal` works when running `pytest`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("VOICE_PROVIDER", "browser")

from farmer.samples import ensure_samples  # noqa: E402
from portal.app import STATE, app as portal_app  # noqa: E402

ensure_samples()   # synthetic sample images are generated, not stored in git


@pytest.fixture
def portal():
    """A fresh, re-seeded mock portal in normal mode for every test."""
    STATE["mode"] = "normal"
    STATE["slow_seconds"] = 0.2
    with TestClient(portal_app) as client:  # `with` runs startup -> seeds the DB
        yield client
    STATE["mode"] = "normal"

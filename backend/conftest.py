"""Pytest bootstrap.

Runs the suite in demo mode against an isolated runtime-config file, and makes
`import app` work regardless of the working directory. A global fixture reverts
the (module-level) settings to their env defaults after every test.
"""
import os
import sys
import tempfile
from pathlib import Path

# Must be set BEFORE app.config is imported (env defines the boot defaults).
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["CONFIG_PATH"] = str(Path(tempfile.mkdtemp(prefix="kopt-")) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from app import config  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_config():
    """Revert global settings + persisted file to env defaults after each test."""
    yield
    config.reset()

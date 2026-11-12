"""Test-wide isolation: never reach the real host download bridge from unit tests."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_download_bridge(monkeypatch):
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", "off")

"""Test-wide isolation: never reach the real host download bridge from unit tests."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_download_bridge(monkeypatch):
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", "off")


@pytest.fixture(autouse=True)
def _isolate_delivery_reader(monkeypatch):
    from paper_writing import reader_check
    monkeypatch.setattr(reader_check, "delivery_images", lambda *args: ([], [], {}))
    monkeypatch.setattr(reader_check, "delivery_read", lambda *args, **kwargs: (dict.fromkeys(
        ("question", "comparison", "answer", "meaning"), "supported") | {"repairs": []}, {}))

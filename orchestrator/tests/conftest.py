import pytest


@pytest.fixture(autouse=True)
def _isolated_local_compute_queue(tmp_path_factory, monkeypatch):
    """Ticks run in tests must never read or dispatch the real local overflow queue."""

    monkeypatch.setenv(
        "OPENLABS_LOCAL_QUEUE", str(tmp_path_factory.mktemp("local-compute-queue"))
    )

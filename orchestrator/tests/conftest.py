import pytest


@pytest.fixture(autouse=True)
def _isolated_local_compute_queue(tmp_path_factory, monkeypatch):
    """Ticks run in tests must never read or dispatch the real local overflow queue."""

    monkeypatch.setenv(
        "OPENLABS_LOCAL_QUEUE", str(tmp_path_factory.mktemp("local-compute-queue"))
    )
    # Nor the real ailab queue (the compute backlog gate and owner briefs read it), nor
    # the identity of an agent seat the test suite may itself be running in.
    monkeypatch.setenv(
        "OPENLABS_REMOTE_QUEUE", str(tmp_path_factory.mktemp("remote-compute-queue"))
    )
    for name in ("OPENLABS_CAMPAIGN_ID", "OPENLABS_TASK_ID", "OPENLABS_CAMPAIGN_COMPUTE_THREADS"):
        monkeypatch.delenv(name, raising=False)

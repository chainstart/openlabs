"""paper_writing reads two pure orchestrator modules (openlabs.holds, openlabs.delivery_facts).

2026-11-26: in the paper-writing environment (PYTHONPATH = workflows/paper only) run from
/workspace/openlabs, whose ``openlabs/`` directory is the code checkout, ``import openlabs``
bound a namespace package and the site-assignment sync after an upload failed with
``No module named 'openlabs.holds'``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PAPER = Path(__file__).resolve().parents[1]

PROBE = """
from paper_writing import deliverable, site_assignments
holds = site_assignments._holds()
facts = deliverable.openlabs_module("delivery_facts")
print(holds.__name__, callable(holds.assignment_hold), callable(facts.delivered))
print(site_assignments.manual_hold({"paper_id": "p", "assignments": []}, {}))
print(deliverable.delivered({}, ".", "p"))
"""


@pytest.mark.parametrize("shadow", [False, True])
def test_pure_modules_import_in_the_paper_environment(tmp_path, shadow):
    cwd = tmp_path / "work"
    cwd.mkdir()
    if shadow:
        # A directory named openlabs without __init__.py (the code checkout under /workspace/openlabs).
        (cwd / "openlabs" / "orchestrator").mkdir(parents=True)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONPATH"] = str(PAPER)
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=cwd, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    first, hold, delivered = result.stdout.splitlines()
    assert first.split()[1:] == ["True", "True"]
    assert hold == "None" and delivered == "False"


def test_only_pure_modules_are_loaded_this_way():
    from paper_writing.deliverable import openlabs_module

    with pytest.raises(ValueError):
        openlabs_module("program")

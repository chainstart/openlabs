"""The unified review shows the referees the figures and re-reviews changed figures."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from paper_writing import review_flow as flow
from paper_writing.review_launcher import claude_image_message, run_role

from test_review_flow import MANUSCRIPT, _delta_fixture, editor, referee

fitz = pytest.importorskip("pymupdf")


def _png(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=120, height=60)
    page.insert_text((10, 30), "Fig", fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap().save(str(path))
    return path


def _figure_pdf(path: Path, text: str = "Design") -> Path:
    doc = fitz.open()
    page = doc.new_page(width=200, height=80)
    page.insert_text((10, 40), text, fontsize=9)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def _fake(tmp_path, monkeypatch, name, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_claude_receives_images_as_stream_json_blocks(tmp_path, monkeypatch):
    payload = {"type": "result", "structured_output": {"answer": "ok"}, "modelUsage": {"claude-fable-5-2": {}}}
    _fake(tmp_path, monkeypatch, "claude",
          f"cat > {tmp_path}/stdin.txt\necho \"$@\" > {tmp_path}/args.txt\necho '{json.dumps(payload)}'\n")
    image = _png(tmp_path / "f.png")
    result, receipt = run_role(role_name="referee_a",
                               role={"provider": "anthropic", "tool": "Claude Code", "model": "claude-fable-5-2"},
                               system_prompt="s", user_prompt="read the figure", schema={"type": "object"},
                               workdir=tmp_path / "run", images=[image])
    message = json.loads((tmp_path / "stdin.txt").read_text())
    content = message["message"]["content"]
    assert content[0] == {"type": "text", "text": "read the figure"}
    assert content[1]["type"] == "image" and content[1]["source"]["media_type"] == "image/png"
    assert "--input-format stream-json" in (tmp_path / "args.txt").read_text()
    assert receipt["images"][0]["file"] == "f.png" and "stream-json" in receipt["image_transport"]
    assert result == {"answer": "ok"}


def test_codex_receives_images_with_the_image_flag(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, "codex",
          f"echo \"$@\" > {tmp_path}/args.txt\ncat >/dev/null\n"
          "while [ $# -gt 0 ]; do if [ \"$1\" = -o ]; then out=$2; fi; shift; done\n"
          "echo '{\"answer\": \"ok\"}' > \"$out\"\necho 'model: gpt-6.2-astra' >&2\n")
    image = _png(tmp_path / "f.png")
    _, receipt = run_role(role_name="editor", role={"provider": "openai-codex", "tool": "Codex",
                                                    "model": "gpt-6.2-astra"},
                          system_prompt="s", user_prompt="u", schema={"type": "object"},
                          workdir=tmp_path / "run", images=[image])
    args = (tmp_path / "args.txt").read_text().split()
    assert args[:3] == ["exec", "--image", str(image)] and args[-1] == "-"
    assert receipt["image_transport"] == "codex --image"


def test_unsupported_image_is_refused(tmp_path):
    from paper_writing.review_launcher import LaunchError

    with pytest.raises(LaunchError, match="unsupported"):
        run_role(role_name="editor", role={"provider": "openai-codex", "tool": "Codex", "model": "gpt-6.2-astra"},
                 system_prompt="s", user_prompt="u", schema={}, workdir=tmp_path / "run",
                 images=[tmp_path / "x.pdf"])


def test_claude_image_message_is_one_json_line(tmp_path):
    text = claude_image_message("hi", [_png(tmp_path / "a.png")])
    assert text.endswith("\n") and text.count("\n") == 1


def _with_figures(tmp_path, monkeypatch, base_files, current_text="Design"):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT)
    manuscript = tmp_path / "papers" / "p" / "manuscript"
    pdf = _figure_pdf(manuscript / "figures" / "fig-a.pdf", current_text)
    from paper_writing.figures import review_figure_files

    current = review_figure_files(manuscript, ["figures/fig-a.pdf"])
    base = tmp_path / "reviews/unified/p/20200101T000000Z/decision.json"
    record = json.loads(base.read_text())
    if base_files is not None:
        record["figure_files"] = base_files(current)
    base.write_text(json.dumps(record))
    pre = {'metadata': {'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
           'fingerprints': {}, 'expanded': MANUSCRIPT, 'bibliography': '', 'figure_files': current,
           'manuscript_path': str(manuscript)}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    seen = {}

    def role(**kw):
        calls.append(kw['role_name'])
        seen[kw['role_name']] = kw
        if kw['role_name'] == 'editor':
            return editor() | {'prior_rejections_addressed': []}, {}
        if kw['role_name'] == 'decision_letter':
            return {'letter': 'fresh letter'}, {}
        return referee('accept'), {}
    monkeypatch.setattr(flow, 'run_role', role)
    return calls, seen, pdf


def test_unchanged_figures_keep_the_delta_review(tmp_path, monkeypatch):
    calls, _, _ = _with_figures(tmp_path, monkeypatch, lambda current: current)
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert calls == [] and record["review_mode"] == "delta"
    assert record["figure_files"][0]["path"] == "figures/fig-a.pdf"
    assert record["delta_review"]["summary"]["figures_changed"] == []


def test_changed_figure_requires_a_full_review_that_shows_it(tmp_path, monkeypatch):
    calls, seen, _ = _with_figures(
        tmp_path, monkeypatch, lambda current: [dict(current[0], sha256="0" * 64)])
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert "referee_a" in calls and record.get("review_mode") != "delta"
    assert "figure files changed: figures/fig-a.pdf" in record["delta_review_refused"]["reasons"]
    for name in ("editor", "referee_a", "referee_b"):
        images = seen[name]["images"]
        assert len(images) == 1 and Path(images[0]).is_file()
        assert "## Figures" in seen[name]["user_prompt"]
        assert "figures/fig-a.pdf -- changed since the previous review round" in seen[name]["user_prompt"]
    assert "images" not in seen["decision_letter"]
    assert record["figure_review"]["changed_since_previous_round"] == ["figures/fig-a.pdf"]


def test_review_recorded_before_figure_hashes_is_not_invalidated(tmp_path, monkeypatch):
    calls, _, _ = _with_figures(tmp_path, monkeypatch, None)
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert calls == [] and record["review_mode"] == "delta"
    assert record["delta_review"]["summary"]["figures_compared"] is False


def test_figure_changes_lists_added_removed_and_changed():
    base = {"figure_files": [{"path": "a", "sha256": "1"}, {"path": "b", "sha256": "2"}]}
    pre = {"figure_files": [{"path": "a", "sha256": "1"}, {"path": "b", "sha256": "3"}, {"path": "c", "sha256": "4"}]}
    assert flow.figure_changes(base, pre) == ["b", "c"]
    assert flow.figure_changes({}, pre) == []


def test_no_figures_is_stated_to_the_reviewers(tmp_path):
    text, images, record = flow.figure_review_packet({"figure_files": []}, tmp_path, [])
    assert "no figures" in text and images == [] and record["images"] == []


def test_figure_sources_are_not_unused_review_sources(tmp_path):
    (tmp_path / "figure-src").mkdir()
    (tmp_path / "figure-src" / "fig-a.tex").write_text("\\begin{tikzpicture}\\end{tikzpicture}")
    (tmp_path / "figure-src" / "fig-b.svg").write_text("<svg/>")
    (tmp_path / "main.tex").write_text("x")
    assert flow.unused_source_files(tmp_path, set()) == []


def test_review_prompts_carry_the_figure_dimension():
    editor_md = (flow.PROMPTS / "editor.md").read_text()
    referee_md = (flow.PROMPTS / "referee.md").read_text()
    assert "Judge the figures" in editor_md and "presentation_problems" in editor_md
    assert "6. Figures." in referee_md and "`evidence` or `claim_narrowing`" in referee_md

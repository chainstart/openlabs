"""The unified review shows the referees the figures and re-reviews changed figures."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from paper_writing import review_flow as flow
from paper_writing.review_launcher import claude_image_message, run_role

from test_review_flow import MANUSCRIPT, _delta_fixture, _round_response, editor, referee

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
    if base_files is None:
        record.pop("figure_files", None)
    else:
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
            return editor() | {'prior_rejections_addressed': [], 'previous_items': [], 'new_findings': []}, {}
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
    record = flow.run_review('p', root=tmp_path, response_letter=_round_response(tmp_path), apply=False)
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
    assert "Judge the figures" in editor_md and "`figure_changes`" in editor_md
    assert "6. Figures." in referee_md and "required `figure`" in referee_md and "`evidence`" in referee_md


def test_required_figure_revision_is_tracked_as_presentation():
    edit = {"type": "figure", "location": "Methods", "change": "Show the paired sampling design."}
    screen = {**editor(), "figure_changes": [edit]}
    report = referee("accept")
    merged = flow.merge(screen, {"a": report, "b": report})
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "text_revision"
    assert not merged["scientific_blockers"]
    required = merged["required_changes"][0]
    assert not required["advisory"] and not flow.change_blocks(required)
    item = flow.tracked_item(edit)
    assert flow.previous_tracked_items({"merged": merged}) == [item]

    open_item = {"item": item, "resolved": False, "evidence": "Still missing."}
    rereview = flow.merge(editor(), {"a": {**report, "previous_items": [open_item]}, "b": report})
    assert rereview["next_action"] == "text_revision"
    assert flow.previous_tracked_items({"merged": rereview}) == [item]

    discrepancy = {**edit, "type": "evidence", "change": "Reconcile the plotted estimate with Table 2."}
    assert flow.merge({**editor(), "figure_changes": [discrepancy]},
                      {"a": report, "b": report})["next_action"] == "evidence_remediation"


def test_review_inventory_counts_only_included_and_binds_source(tmp_path, monkeypatch):
    from paper_writing import figures
    ws = figures.workspace(manuscript=tmp_path)
    ws.src_dir.mkdir()
    source = ws.src_dir / "mechanism.svg"
    source.write_text("<svg/>")
    rows = [{"pdf": str(ws.out_dir / (name + ".pdf")), "kind": kind, "source": str(source)}
            for name, kind in [("mechanism", "schematic"), ("validation", "result"), ("unused", "schematic")]]
    audit = dict(figures=rows, blocking=[], repair_required=[])
    monkeypatch.setattr(figures, "check", lambda *a, **k: audit)
    pre = dict(manuscript_path=str(tmp_path), figure_files=[
        dict(path="figures/mechanism.pdf", sha256="a"), dict(path="figures/validation.pdf", sha256="b")])
    metrics, sources = figures.review_inventory(pre)
    assert metrics == dict(check_passed=True, schematic_count=1, result_count=1,
                           required_changes=0, figure_seats=None)
    assert len(sources) == 1 and sources[0]["source"] == source.name
    audit["repair_required"].append("missing")
    assert figures.review_inventory(pre)[0]["check_passed"] is False


from paper_writing.reader_check import delivery_images as actual_delivery_images


def test_reader_sees_only_main_panels_in_print_order(tmp_path, monkeypatch):
    from paper_writing import figures
    seen = []
    def render(manuscript, ordered, output):
        seen.extend(item["path"] for item in ordered)
        return {"images": [{"png": str(output / "sheet.png")}], "notes": []}
    monkeypatch.setattr(figures, "review_images", render)
    source = "".join(r"\begin{figure}\includegraphics{" + name + r"}\end{figure}"
                     for name in ("z", "a")) + r"\appendix\begin{figure}\includegraphics{hidden}\end{figure}"
    paths = [{"path": "figures/" + name + ".pdf", "sha256": name} for name in ("a", "hidden", "z")]
    images, issues, bindings = actual_delivery_images({"expanded": source, "figure_files": paths,
                                                   "manuscript_path": str(tmp_path)}, tmp_path)
    assert seen == ["figures/z.pdf", "figures/a.pdf"] and len(images) == 1 and not issues
    assert bindings == {"figures/z.pdf": "z", "figures/a.pdf": "a"}


def test_antigravity_role_reviews_a_readonly_copy_and_reports_quota(tmp_path, monkeypatch):
    """2026-11-23: a Gemini role through the Antigravity CLI (a third model family)."""
    init = {"event": "init", "conversation_id": "c1", "init": {"model": "gemini-4-neon-high"}}
    result = {"event": "result", "result": {"status": "SUCCESS", "structured_output": {"answer": "ok"}}}
    usage = {"command": {"name": "usage", "data": {"groups": [{"name": "Gemini Models", "buckets": [
        {"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.6,
         "reset_time": "2099-01-01T00:00:00Z"}]}]}}}
    _fake(tmp_path, monkeypatch, "agy",
          f"case \"$*\" in *\"/usage\"*) echo '{json.dumps(usage)}'; exit 0;; esac\n"
          f"echo \"$@\" > {tmp_path}/args.txt\npwd > {tmp_path}/cwd.txt\ncat > {tmp_path}/stdin.txt\n"
          f"echo '{json.dumps(init)}'\necho '{json.dumps(result)}'\n")
    image = _png(tmp_path / "f.png")
    out, receipt = run_role(role_name="referee_a",
                            role={"provider": "google-antigravity", "tool": "Antigravity",
                                  "model": "gemini-4-neon-high"},
                            system_prompt="sys", user_prompt="read the figure", schema={"type": "object"},
                            workdir=tmp_path / "run", images=[image])
    assert out == {"answer": "ok"}
    args = (tmp_path / "args.txt").read_text().split()
    assert "--dangerously-skip-permissions" in args and "--json-schema" in args
    assert args[args.index("--model") + 1] == "gemini-4-neon-high"
    message = json.loads((tmp_path / "stdin.txt").read_text())
    text = message["message"]["content"][0]["text"]
    assert message["event"] == "user" and text.startswith("sys\n\nread the figure")
    assert "Figure renderings to inspect" in text and "review-images/0/f.png" in text
    assert receipt["runtime_reported_models"] == ["gemini-4-neon-high"]
    assert receipt["sandbox_mode"] == "readonly-copy" and receipt["tools_enabled"] is True
    assert receipt["image_transport"] == "agy read-only copy files"
    quota = json.loads((tmp_path / "run" / "quota.json").read_text())
    assert quota["provider"] == "google-antigravity" and quota["role"] == "referee_a"
    assert abs(quota["windows"][0]["used_fraction"] - 0.4) < 1e-9


def test_antigravity_role_refuses_a_different_reported_model(tmp_path, monkeypatch):
    from paper_writing.review_launcher import LaunchError

    init = {"event": "init", "init": {"model": "gemini-3.8-flash-low"}}
    result = {"event": "result", "result": {"status": "SUCCESS", "structured_output": {"answer": "ok"}}}
    _fake(tmp_path, monkeypatch, "agy",
          f"case \"$*\" in *\"/usage\"*) echo '{{}}'; exit 0;; esac\ncat >/dev/null\n"
          f"echo '{json.dumps(init)}'\necho '{json.dumps(result)}'\n")
    with pytest.raises(LaunchError, match="expected gemini-4-neon-high"):
        run_role(role_name="referee_a",
                 role={"provider": "google-antigravity", "tool": "Antigravity", "model": "gemini-4-neon-high"},
                 system_prompt="s", user_prompt="u", schema={"type": "object"}, workdir=tmp_path / "run")

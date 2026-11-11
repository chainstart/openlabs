from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from paper_writing import editorial_rewrite as er
from paper_writing import review_flow as flow

MAIN = r"""\documentclass{article}
\begin{document}
\title{T}
\begin{abstract}
We study widgets. Old abstract with fifteen words of text in it for the length check.
\end{abstract}
\section{Introduction}\label{sec:intro}
Widgets matter \cite{smith}. We do not claim anything\label{fn:claim}. This is the old introduction text here.
\section{Method}\label{sec:method}
The method body stays. See Section~\ref{sec:intro}.
% \section{Conclusion} commented-out draft must be ignored
\input{concl}
\bibliography{refs}
\end{document}
"""
CONCL = r"""\section{Conclusion}
Old conclusion with some words that should be replaced by the selected candidate text.
"""


def make_root(tmp_path: Path, checked: str = "2026-11-09") -> Path:
    root = tmp_path
    man = root / "papers/p/manuscript"
    man.mkdir(parents=True)
    (man / "main.tex").write_text(MAIN)
    (man / "concl.tex").write_text(CONCL)
    (man / "refs.bib").write_text("@article{smith, title={x}}\n@article{jones, title={y}}\n")
    (root / "registry/papers").mkdir(parents=True)
    (root / "registry/papers/p.yaml").write_text(yaml.safe_dump(
        {"paper_id": "p", "target_journal": "J Widgets", "target_journal_checked_at": checked, "version": "1"}))
    return root


def candidate(tag: str, cite: str = "smith") -> dict[str, str]:
    return {"abstract": f"{tag} abstract about widgets with enough words to stay inside the length band ok.",
            "introduction": rf"{tag} widgets matter to engineers \cite{{{cite}}}; we show a result\label{{fn:claim}} here ok.",
            "closing": f"{tag} conclusion stating the result once with a single limitation for the reader.",
            "change_notes": "n"}


def test_locate_parts_ignores_comments_and_follows_files(tmp_path):
    root = make_root(tmp_path)
    parts = er.locate_parts(root / "papers/p/manuscript")
    assert parts["closing"].file == "concl.tex" and parts["closing"].heading == "Conclusion"
    assert "old introduction" in parts["introduction"].body
    assert "Old abstract" in parts["abstract"].body


def test_deterministic_checks(tmp_path):
    root = make_root(tmp_path)
    man = root / "papers/p/manuscript"
    parts = er.locate_parts(man)
    expanded = flow.expand_tex(man / "main.tex", man)
    keys = er.bibliography_keys(man, expanded)
    assert er.candidate_problems(candidate("A"), parts, expanded=expanded, known_keys=keys, tolerance=0.5) == []
    bad = candidate("B", cite="invented2025")
    bad["introduction"] = bad["introduction"].replace(r"\label{fn:claim}", r"\section{X} see \ref{sec:nowhere}\label{sec:method}")
    problems = " | ".join(er.candidate_problems(bad, parts, expanded=expanded, known_keys=keys, tolerance=0.5))
    assert "invented2025" in problems and "fn:claim" in problems and "sec:nowhere" in problems
    assert "already defined elsewhere" in problems
    assert "sectioning" in problems


def test_verified_venue_abstract_limit_is_hard_for_candidates_and_original(tmp_path):
    root = make_root(tmp_path)
    man = root / "papers/p/manuscript"
    parts = er.locate_parts(man)
    expanded = flow.expanded_review_documents(man)
    problems = er.candidate_problems(candidate("A"), parts, expanded=expanded,
                                     known_keys=er.bibliography_keys(man, expanded),
                                     tolerance=0.5, abstract_bounds=(1, 10))
    assert any("verified venue limit" in problem for problem in problems)
    report = judgment(["V1", "V2"])
    selection = er.select("original", ["candidate"], {"judge": report},
                          {"judge": {"V1": "original", "V2": "candidate"}},
                          {"original": ["abstract too long"]})
    assert selection["selected"] == "original" and not selection["editorial_ready"]


def test_registered_abstract_limits_reach_prompt_and_cannot_be_bypassed_by_original(tmp_path):
    root, _metadata = required_root(tmp_path)
    path = root / "registry/papers/p.yaml"
    metadata = yaml.safe_load(path.read_text())
    metadata["target_journal_format"] = {"abstract_word_limits": [1, 10]}
    path.write_text(yaml.safe_dump(metadata))
    delegate = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})

    def runner(**kwargs):
        if kwargs["role_name"].startswith("rewriter_"):
            assert "Verified venue abstract word limit: 1–10" in kwargs["user_prompt"]
        return delegate(**kwargs)

    record = er.run_rewrite("p", root=root, runner=runner)
    assert record["outcome"] == "editorial_failed"
    assert "original" in record["deterministic_problems"]
    assert all(record["deterministic_problems"][key] for key in ("original", "gpt", "opus"))


def test_changed_venue_abstract_limit_is_rechecked_at_apply_and_preflight(tmp_path):
    root, metadata = required_root(tmp_path)
    record = er.run_rewrite("p", root=root, runner=fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"}))
    path = root / "registry/papers/p.yaml"
    metadata["target_journal_format"] = {"abstract_word_limits": [1, 10]}
    path.write_text(yaml.safe_dump(metadata))
    with pytest.raises(ValueError, match="verified venue limit"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    metadata.pop("target_journal_format")
    path.write_text(yaml.safe_dump(metadata))
    er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    metadata["target_journal_format"] = {"abstract_word_limits": [1, 10]}
    assert "verified venue limit" in er.preflight_blockers(metadata, root, "p")[0]


def test_registered_person_rule_distinguishes_pronouns_from_scientific_symbols():
    assert er._abstract_person_problems("We assessed the electrodes.", None) == []
    assert er._abstract_person_problems("We assessed the electrodes.", "third")
    assert er._abstract_person_problems("Our measurements were paired.", "third")
    assert er._abstract_person_problems("Copper(I), CO2, US data and $I=2$ were evaluated.", "third") == []


def test_venue_style_reaches_both_independent_roles(tmp_path):
    root, _ = required_root(tmp_path)
    path = root / "registry/papers/p.yaml"
    metadata = yaml.safe_load(path.read_text())
    metadata["target_journal_format"] = {
        "source": "https://journal.example/guide", "abstract_person": "third",
        "editorial_requirements": ["Use past tense in the abstract."]}
    path.write_text(yaml.safe_dump(metadata))
    delegate = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})
    roles = set()
    def runner(**kwargs):
        roles.add(kwargs["role_name"])
        assert "Use past tense in the abstract." in kwargs["user_prompt"]
        assert '"abstract_person": "third"' in kwargs["user_prompt"]
        return delegate(**kwargs)
    er.run_rewrite("p", root=root, runner=runner)
    assert roles == {"rewriter_gpt", "rewriter_opus", "judge_gpt", "judge_opus"}


def test_new_person_requirement_is_rechecked_before_apply_and_release(tmp_path):
    root, metadata = required_root(tmp_path)
    delegate = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})
    def runner(**kwargs):
        result, receipt = delegate(**kwargs)
        if kwargs["role_name"].startswith("rewriter_"):
            result["abstract"] += " We assessed the result."
        return result, receipt
    record = er.run_rewrite("p", root=root, runner=runner)
    path = root / "registry/papers/p.yaml"
    metadata["target_journal_format"] = {"abstract_person": "third"}
    path.write_text(yaml.safe_dump(metadata))
    with pytest.raises(ValueError, match="third person"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    metadata.pop("target_journal_format")
    path.write_text(yaml.safe_dump(metadata))
    er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    metadata["target_journal_format"] = {"abstract_person": "third"}
    assert any("third person" in problem for problem in er.preflight_blockers(metadata, root, "p"))


def judgment(order: list[str], major: str | None = None) -> dict:
    versions = {}
    for rank, label in enumerate(order):
        issues = [{"quote": "q", "problem": "p", "severity": "major"}] if label == major else []
        versions[label] = {"overall": 9 - rank, "fidelity_issues": issues,
                           **{name: 7 for name in er.VOICE_DIMENSIONS},
                           "editorial_ready": True, "editorial_blockers": []}
    return {"versions": versions, "ranking": order, "rationale": ""}


def test_selection_rule_is_unanimous_and_cancels_self_preference():
    keys = {"gpt": {"V1": "original", "V2": "gpt", "V3": "opus"},
            "opus": {"V1": "opus", "V2": "original", "V3": "gpt"}}
    # Each judge prefers its own family; the tie on summed rank is broken by fidelity, then score.
    judgments = {"gpt": judgment(["V2", "V3", "V1"]), "opus": judgment(["V1", "V3", "V2"])}
    result = er.select("original", ["gpt", "opus"], judgments, keys, {})
    assert result["eligible_ranked"] == ["gpt", "opus"] or result["eligible_ranked"] == ["opus", "gpt"]
    assert result["selected"] in {"gpt", "opus"}
    # One judge ranking the original above a candidate removes it.
    judgments["opus"] = judgment(["V1", "V2", "V3"])
    result = er.select("original", ["gpt", "opus"], judgments, keys, {})
    assert result["selected"] == "opus" and "gpt" in result["rejected_candidates"]
    # A major fidelity issue or deterministic problem disqualifies regardless of rank.
    judgments = {"gpt": judgment(["V2", "V3", "V1"], major="V3"), "opus": judgment(["V1", "V3", "V2"])}
    result = er.select("original", ["gpt", "opus"], judgments, keys, {"gpt": ["bad cite"]})
    assert result["selected"] == "original" and set(result["rejected_candidates"]) == {"gpt", "opus"}


def fake_runner(order_pref: dict[str, str]):
    def run(*, role_name, role, system_prompt, user_prompt, schema, workdir, timeout):
        workdir.mkdir(parents=True)
        if role_name.startswith("rewriter_"):
            return candidate(role_name.split("_", 1)[1].upper()), {"model": role["model"]}
        labels = schema["properties"]["ranking"]["items"]["enum"]
        # Prefer the label whose abstract starts with the preferred tag, original last.
        text = {l: user_prompt.split(f"## Version {l}\n", 1)[1][:120] for l in labels}
        order = sorted(labels, key=lambda l: (0 if text[l].startswith(f"### Abstract\n{order_pref[role_name]}")
                                              else 2 if "Old abstract" in text[l] else 1))
        versions = {l: {"naturalness": 7, "restraint": 7, "clarity": 7, "venue_fit": 7, "overall": 8 - i,
                        "send_to_review_probability": 50, "fidelity_issues": [], "comments": "",
                        "editorial_ready": True, "editorial_blockers": []}
                    for i, l in enumerate(order)}
        return {"versions": versions, "ranking": order, "rationale": ""}, {"model": role["model"]}
    return run


def test_run_select_apply_and_preflight_gate(tmp_path):
    root = make_root(tmp_path)
    (root / "registry/settings.yaml").write_text(yaml.safe_dump({"schema_version": "ara.paper_writing.registry.v1", "quality_gate": {"editorial_rewrite": {
        "required": True, "required_from": "2026-11-08", "rewriters": er.DEFAULT_ROLES, "judges": er.DEFAULT_ROLES}}}))
    metadata = yaml.safe_load((root / "registry/papers/p.yaml").read_text())
    assert er.preflight_blockers(metadata, root, "p")  # no pass yet
    record = er.run_rewrite("p", root=root, runner=fake_runner({"judge_gpt": "GPT", "judge_opus": "OPUS"}))
    assert record["outcome"] == "candidate_selected"
    assert set(record["blind_keys"]["gpt"].values()) == {"original", "gpt", "opus"}
    # A completed pass satisfies preflight; an unapplied candidate is advice only.
    assert er.preflight_blockers(metadata, root, "p") == []
    assert any("not applied" in note for note in er.advisory(metadata, root, "p")["notes"])
    applied = er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    man = root / "papers/p/manuscript"
    main, concl = (man / "main.tex").read_text(), (man / "concl.tex").read_text()
    winner = applied["selected"].upper()
    assert f"{winner} abstract" in main and "Old abstract" not in main
    assert r"\section{Method}\label{sec:method}" in main and "commented-out draft" in main
    assert f"{winner} conclusion" in concl and concl.startswith(r"\section{Conclusion}")
    assert er.preflight_blockers(metadata, root, "p") == []
    with pytest.raises(ValueError, match="already applied"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])


def test_failed_rewriters_do_not_satisfy_required_pass(tmp_path):
    root = make_root(tmp_path)
    (root / "registry/settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "quality_gate": {"editorial_rewrite": {"required": True, "required_from": "2026-11-08"}}
    }))

    def unavailable(**kwargs):
        raise er.LaunchError("backend unavailable")

    record = er.run_rewrite("p", root=root, runner=unavailable)
    assert record["outcome"] == "rewrite_failed"
    assert set(record["rewriter_failures"]) == {"gpt", "opus"}
    metadata = yaml.safe_load((root / "registry/papers/p.yaml").read_text())
    assert er.preflight_blockers(metadata, root, "p")
    assert (root / "papers/p/manuscript/main.tex").read_text() == MAIN


def test_gate_skips_old_targets_and_requires_two_judge_families(tmp_path):
    root = make_root(tmp_path, checked="2026-10-01")
    (root / "registry/settings.yaml").write_text(yaml.safe_dump({"schema_version": "ara.paper_writing.registry.v1", "quality_gate": {"editorial_rewrite": {
        "required": True, "required_from": "2026-11-08"}}}))
    metadata = yaml.safe_load((root / "registry/papers/p.yaml").read_text())
    assert er.preflight_blockers(metadata, root, "p") == []
    (root / "registry/settings.yaml").write_text(yaml.safe_dump({"schema_version": "ara.paper_writing.registry.v1", "quality_gate": {"editorial_rewrite": {
        "judges": {"gpt": er.DEFAULT_ROLES["gpt"]}}}}))
    with pytest.raises(ValueError, match="two model families"):
        er.rewrite_config(root)


def test_apply_refuses_changed_sources(tmp_path):
    root = make_root(tmp_path)
    record = er.run_rewrite("p", root=root, runner=fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"}))
    (root / "papers/p/manuscript/concl.tex").write_text(CONCL + "edited\n")
    with pytest.raises(ValueError, match="changed after"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    saved = json.loads((root / record["run_dir"] / "record.json").read_text())
    assert saved["selection"]["selected"] == "gpt"


def required_root(tmp_path):
    root = make_root(tmp_path)
    (root / "registry/settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "quality_gate": {"editorial_rewrite": {"required": True, "required_from": "2026-11-08"}}
    }))
    return root, yaml.safe_load((root / "registry/papers/p.yaml").read_text())


@pytest.mark.parametrize("dimension", er.VOICE_DIMENSIONS)
def test_relative_improvement_does_not_override_absolute_floor(dimension):
    keys = {"judge": {"V1": "original", "V2": "candidate"}}
    report = judgment(["V2", "V1"])
    report["versions"]["V2"][dimension] = 6
    result = er.select("original", ["candidate"], {"judge": report}, keys, {})
    assert result["selected"] == "original"
    assert dimension in str(result["rejected_candidates"])


def test_original_must_pass_and_full_body_blockers_cannot_be_outvoted():
    keys = {"judge": {"V1": "original", "V2": "candidate"}}
    report = judgment(["V1", "V2"])
    for scores in report["versions"].values():
        scores["editorial_ready"] = False
        scores["editorial_blockers"] = ["Methods paragraph 2 repeats internal review dialogue"]
    result = er.select("original", ["candidate"], {"judge": report}, keys, {})
    assert result["selected"] == "original" and not result["editorial_ready"]


def test_separate_journal_tables_reach_writers_judges_and_are_hash_bound(tmp_path):
    root, _metadata = required_root(tmp_path)
    man = root / "papers/p/manuscript"
    table = man / "table1.tex"
    table.write_text(r"\documentclass{article}\begin{document}SEPARATE_TABLE_DATA\end{document}")
    prompts = []
    delegate = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})

    def runner(**kwargs):
        prompts.append((kwargs["role_name"], kwargs["user_prompt"]))
        return delegate(**kwargs)

    record = er.run_rewrite("p", root=root, runner=runner)
    assert all("SEPARATE_TABLE_DATA" in prompt for _, prompt in prompts)
    assert "table1.tex" in record["source_sha256"]
    table.write_text(table.read_text().replace("TABLE_DATA", "TABLE_CHANGED"))
    with pytest.raises(ValueError, match="changed after"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])


@pytest.mark.parametrize("filename", ["body.tex", "refs.bib"])
def test_full_sources_bound_before_apply_and_after_approval(tmp_path, filename):
    root, metadata = required_root(tmp_path)
    man = root / "papers/p/manuscript"
    main = man / "main.tex"
    main.write_text(main.read_text().replace("The method body stays.", r"\input{body}"))
    (man / "body.tex").write_text("The method body stays.")
    record = er.run_rewrite("p", root=root, runner=fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"}))
    path = man / filename
    old = path.read_text()
    path.write_text(old + "\nchanged\n")
    with pytest.raises(ValueError, match="changed after"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    path.write_text(old)
    er.apply_rewrite("p", root=root, run_dir=record["run_dir"])
    assert er.preflight_blockers(metadata, root, "p") == []
    path.write_text(old + "\nchanged\n")
    # Later source edits no longer force a rerun; they are reported with the review.
    assert er.preflight_blockers(metadata, root, "p") == []
    assert any("changed since" in note for note in er.advisory(metadata, root, "p")["notes"])


def test_completed_pass_stays_valid_after_edits_and_later_technical_failures(tmp_path):
    root, metadata = required_root(tmp_path)
    record = er.run_rewrite("p", root=root, runner=fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"}))
    run = root / record["run_dir"]
    record["outcome"] = "original_kept"
    (run / "record.json").write_text(json.dumps(record))
    assert er.preflight_blockers(metadata, root, "p") == []
    (root / "papers/p/manuscript/refs.bib").write_text("changed")
    assert er.preflight_blockers(metadata, root, "p") == []
    newer = run.parent / "99991231T235959Z"
    newer.mkdir()
    (newer / "record.json").write_text(json.dumps({"target": "J Widgets", "outcome": "rewrite_failed"}))
    assert er.preflight_blockers(metadata, root, "p") == []
    advice = er.advisory(metadata, root, "p")
    assert advice["run_dir"] == record["run_dir"] and advice["blocking"] is False


def test_failed_full_manuscript_assessment_is_advisory(tmp_path):
    root, metadata = required_root(tmp_path)
    base_runner = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})

    def runner(**kwargs):
        result, receipt = base_runner(**kwargs)
        if kwargs["role_name"].startswith("judge_"):
            for scores in result["versions"].values():
                scores["editorial_ready"] = False
                scores["editorial_blockers"] = ["Discussion: repeated defensive qualifications"]
        return result, receipt

    record = er.run_rewrite("p", root=root, runner=runner)
    assert record["outcome"] == "editorial_failed"
    # The judges' verdict is advice for the review, not a preflight blocker.
    assert er.preflight_blockers(metadata, root, "p") == []
    advice = er.advisory(metadata, root, "p")
    assert advice["editorial_ready"] is False
    assert any("repeated defensive qualifications" in note for note in advice["notes"])
    with pytest.raises(ValueError, match="No candidate"):
        er.apply_rewrite("p", root=root, run_dir=record["run_dir"])


def test_judge_failure_is_recorded_and_blocks(tmp_path):
    root, metadata = required_root(tmp_path)
    base_runner = fake_runner({"judge_gpt": "GPT", "judge_opus": "GPT"})

    def runner(**kwargs):
        if kwargs["role_name"].startswith("judge_"):
            raise er.LaunchError("judge unavailable")
        return base_runner(**kwargs)

    record = er.run_rewrite("p", root=root, runner=runner)
    assert record["outcome"] == "judge_failed"
    assert er.preflight_blockers(metadata, root, "p")


def test_duplicate_judge_ranking_is_rejected():
    report = judgment(["V1", "V2"])
    report["ranking"] = ["V1", "V1"]
    with pytest.raises(ValueError, match="exactly once"):
        er.select("original", ["candidate"], {"judge": report},
                  {"judge": {"V1": "original", "V2": "candidate"}}, {})


# --------------------------------------------------------------------------- cross-model review

def roles():
    return {"editor": {"provider": "openai-codex", "model": "gpt"},
            "referee_a": {"provider": "anthropic", "model": "opus"},
            "referee_b": {"provider": "openai-codex", "model": "gpt"}}


def test_cross_model_blockers():
    config = {"roles": roles(), "referee_roles": ["referee_b"], "cross_model_required": True}
    assert "differs from the writer" in flow.cross_model_blockers(config, "gpt")[0]
    assert flow.cross_model_blockers(dict(config, referee_roles=["referee_a", "referee_b"]), "gpt") == []
    assert "two active referees" in flow.cross_model_blockers(dict(config, referee_roles=["referee_a"]), "gpt")[0]
    assert flow.cross_model_blockers(dict(config, cross_model_required=False), "gpt") == []
    assert flow.writer_model({"writer_model": "opus"}, {"writer_model": "gpt"}) == "opus"


def test_previous_panel_keeps_old_decisions_valid(monkeypatch):
    settings = {"review": {"referee_roles": ["referee_a", "referee_b"], "roles": roles(),
                           "previous_panels": [{"valid_for_reviews_started_before": "2026-11-07T11:30:00+00:00",
                                                "referee_roles": ["referee_b"], "roles": roles()}]}}
    monkeypatch.setattr(flow, "load_registry_settings", lambda root: settings)
    config = flow.review_config("x")
    old = {"started_at": "2026-11-01T00:00:00+00:00", "active_referee_roles": ["referee_b"]}
    new = {"started_at": "2026-11-08T00:00:00+00:00", "active_referee_roles": ["referee_b"]}
    old_policy = flow.policy_for_record(old, config)
    assert old_policy["referee_roles"] == ["referee_b"]
    assert flow.review_policy_sha256(old_policy) != flow.review_policy_sha256(config)
    assert flow.policy_for_record(new, config)["referee_roles"] == ["referee_a", "referee_b"]
    settings["review"]["previous_panels"] = [{"referee_roles": ["referee_b"]}]
    with pytest.raises(ValueError, match="previous_panels"):
        flow.review_config("x")


def test_run_review_blocks_self_review_panel(tmp_path, monkeypatch):
    config = {"process": flow.PROCESS, "roles": roles(), "referee_roles": ["referee_b"],
              "rejection_clearance_required": True, "timeout_seconds": 1, "max_rounds_per_target": 10,
              "writer_model": "gpt", "cross_model_required": True, "previous_panels": []}
    monkeypatch.setattr(flow, "review_config", lambda root: config)
    pre = {"metadata": {"version": "1", "target_journal": "J"}, "target": "J", "blockers": [],
           "fingerprints": {}, "expanded": "x", "bibliography": ""}
    monkeypatch.setattr(flow, "preflight", lambda *a: pre)
    monkeypatch.setattr(flow, "run_role", lambda **kw: pytest.fail("no model may start"))
    record = flow.run_review("p", root=tmp_path, apply=False)
    assert record["merged"]["outcome"] == "preflight_failed"
    assert any("differs from the writer" in b for b in record["merged"]["preflight_blockers"])
    assert record["writer_model"] == "gpt" and record["cross_model_referees"] == []

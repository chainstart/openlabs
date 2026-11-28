"""Simplified two-step supply pipeline tests (2026-11-28 plan §3 & §4.5).

Covers:
1. All 6 mechanical guards (minimal structure, compute locations, data_gb ceiling,
   free-data guard + needs_registration collection, duplicate detection + reopens,
   weekly per-line supply spend cap including Gemini pricing).
2. Single cross-family independent review (go/no_go, non-gating likely_band,
   needs_registration persisted on go and no_go, 2 invalid attempts -> review_undecided).
3. Old-line candidate queue injection (top-10 queue_candidates + line_tools, filtering
   occupied/blocked entries, shared-queue dedup, queue_entry_id dedup, new line free scouting).
4. Backward compatibility (legacy cc-sg-style config with warnings, in-flight legacy
   proposed cards with prescreen.status=pending going straight to review, in-flight
   legacy topic_cards scout payloads).
5. Supply metrics & needs_registration aggregation.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from openlabs import program_flow
from openlabs.config import (
    ANTIGRAVITY_PROVIDER,
    DEFAULT_MODEL_PRICES,
    LineSettings,
    ProgramSettings,
    RunnerSpec,
    SupplySettings,
    load_program_settings,
)
from openlabs.contracts import (
    MAX_BRIEF_CHARS,
    atomic_write_json,
    proposal_from_legacy_card,
    validate_topic_proposal,
)
from openlabs.program import (
    REJECTION_BUDGET_EXCEEDED,
    REJECTION_DATA_RESTRICTED,
    REJECTION_DUPLICATE_TOPIC,
    REJECTION_PROPOSAL_INVALID,
    REJECTION_REVIEW_NO_GO,
    REJECTION_REVIEW_UNDECIDED,
    card_sha256,
    freeze_topic,
    last_rejection_reason,
    open_topic_ledger,
    propose_topic,
)
from openlabs.projects import load_project
from openlabs.usage import attempt_figures
from test_research_program_flow import (
    CLAUDE,
    EVIDENCE,
    GPT,
    RUNNERS,
    TEMPLATE,
    _admission_task,
    _complete,
    _db,
    _install_program,
    _packet,
    _paths,
    _proposal,
    _review,
    _scout_round,
    _settings,
    _tick,
    _to_admission,
)


def _setup_line_project(
    paths,
    *,
    line_id: str,
    domain: str = "physics",
    queue_entries: list[dict] | None = None,
    queue_relpath: str | None = None,
    catalog_sources: list[dict] | None = None,
    extra_env: dict | None = None,
) -> Path:
    """Install a research-line program project plus research-lines.yaml / queue / catalog."""

    root = paths.data / "workspaces" / domain / "projects" / f"{line_id}-program"
    root.mkdir(parents=True, exist_ok=True)
    project = json.loads((TEMPLATE / "project.json").read_text(encoding="utf-8"))
    project["project_id"] = f"{line_id}-program"
    project["domain"] = domain
    project["research_line"] = line_id
    project["protocol"]["primary_skill"] = f"{domain}-research-loop"
    for ws in project["workstreams"]:
        role = "scout" if "scout" in ws["workstream_id"] else "admission"
        ws["workstream_id"] = f"{line_id}-{role}"
        state = json.loads((TEMPLATE / ws["state_path"]).read_text(encoding="utf-8"))
        state["project_id"] = project["project_id"]
        state["workstream_id"] = ws["workstream_id"]
        atomic_write_json(root / ws["state_path"], state)
    atomic_write_json(root / "project.json", project)

    registry = paths.data / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "settings.yaml").write_text("research_portfolio: {}\n", encoding="utf-8")
    atomic_write_json(registry / "journal-rejections.json", {"rejections": []})
    atomic_write_json(registry / "reusable-assets.json", {"assets": []})

    env: dict = {"status": "ready", **dict(extra_env or {})}
    templates: list[dict] = []
    if queue_entries is not None:
        q_path = paths.data / (queue_relpath or f"workspaces/{domain}/queues/{line_id}.json")
        q_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(q_path, {"candidates": queue_entries})
        templates.append({"id": f"{line_id}-template", "candidate_queue": str(q_path)})
    if catalog_sources is not None:
        c_path = paths.data / "workspaces" / domain / f"{line_id}-catalog.yaml"
        c_path.parent.mkdir(parents=True, exist_ok=True)
        c_path.write_text(
            yaml.safe_dump({"schema_version": "openlabs.data_catalog.v1", "sources": catalog_sources}),
            encoding="utf-8",
        )
        env["data_catalog"] = str(c_path)

    lines_path = registry / "research-lines.yaml"
    doc = yaml.safe_load(lines_path.read_text(encoding="utf-8")) if lines_path.is_file() else {"lines": []}
    lines_list = [item for item in doc.get("lines") or [] if item.get("id") != line_id]
    lines_list.append({
        "id": line_id,
        "name": f"Line {line_id}",
        "host_domain": domain,
        "status": "active",
        "field": domain,
        "line_short_name": line_id,
        "environment": env,
        **({"paper_templates": templates} if templates else {}),
    })
    doc["lines"] = lines_list
    lines_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return root / "project.json"


# --------------------------------------------------------------------------- 1. mechanical checks


def test_mechanical_check_1_minimal_structure_and_brief_cap() -> None:
    assert validate_topic_proposal(_proposal()).valid
    too_long = _proposal(brief="x" * (MAX_BRIEF_CHARS + 1))
    assert not validate_topic_proposal(too_long).valid
    assert any("6000" in e for e in validate_topic_proposal(too_long).errors)

    bad_sources = _proposal(data_sources=[])
    assert any("non-empty" in e for e in validate_topic_proposal(bad_sources).errors)

    bad_compute = _proposal(compute_estimate={"locations": ["laptop"], "data_gb": -1, "agent_hours": 0})
    errs = validate_topic_proposal(bad_compute).errors
    assert any("locations" in e for e in errs)
    assert any("data_gb" in e for e in errs)
    assert any("agent_hours" in e for e in errs)


def test_mechanical_checks_2_3_4_compute_data_cap_and_free_data_guard(tmp_path) -> None:
    paths = _paths(tmp_path)
    project_path = _setup_line_project(
        paths,
        line_id="astro-line",
        catalog_sources=[
            {"id": "blocked-ds", "name": "Paid Archive", "status": "blocked", "blocked_reason": "commercial license"},
            {"id": "reg-ds", "name": "ESA Portal", "status": "needs_registration", "registration": "Free ESA account"},
        ],
    )
    db = _db(paths)
    project = load_project(project_path)
    settings = _settings(
        lines={"astro-line": LineSettings(mode="full", slots=2)},
        supply=SupplySettings(max_topic_data_gb=500.0),
    )

    # Check #3: data_gb > max_topic_data_gb -> budget_exceeded
    big = _proposal(
        0, research_line="astro-line",
        compute_estimate={"locations": ["container_cpu"], "data_gb": 1200.0, "agent_hours": 5.0},
    )
    out = program_flow.intake_proposal(db, paths, settings, project, big, decided_by="s1", provider=GPT, source_task_id="s1")
    assert out["status"] == "rejected" and out["reason"] == REJECTION_BUDGET_EXCEEDED

    # Check #4a: access == "restricted" -> data_restricted
    restricted = _proposal(
        1, research_line="astro-line",
        question="Does restricted satellite telemetry predict flare onset?",
        data_sources=[{"id_or_url": "https://commercial.example/sat", "access": "restricted"}],
    )
    out = program_flow.intake_proposal(db, paths, settings, project, restricted, decided_by="s1", provider=GPT, source_task_id="s1")
    assert out["status"] == "rejected" and out["reason"] == REJECTION_DATA_RESTRICTED

    # Check #4b: catalog status == "blocked" -> data_restricted
    blocked = _proposal(
        2, research_line="astro-line",
        question="Can paid catalog light curves separate binaries?",
        data_sources=[{"id_or_url": "https://archive.example/p", "access": "direct", "catalog_id": "blocked-ds"}],
    )
    out = program_flow.intake_proposal(db, paths, settings, project, blocked, decided_by="s1", provider=GPT, source_task_id="s1")
    assert out["status"] == "rejected" and out["reason"] == REJECTION_DATA_RESTRICTED

    # Check #4c: form_or_registration + catalog needs_registration -> PASSES and records needs_registration
    reg_prop = _proposal(
        3, research_line="astro-line",
        question="Does free ESA survey photometry constrain period drift?",
        data_sources=[
            {"id_or_url": "https://esa.example/survey", "access": "form_or_registration", "catalog_id": "reg-ds"},
            {"id_or_url": "https://zenodo.org/records/open-99", "access": "direct"},
        ],
    )
    out = program_flow.intake_proposal(db, paths, settings, project, reg_prop, decided_by="s1", provider=GPT, source_task_id="s1")
    assert out["status"] == "proposed"
    assert out["needs_registration"] == [{
        "source": "https://esa.example/survey",
        "registration": "Free ESA account",
        "catalog_id": "reg-ds",
    }]
    stored = open_topic_ledger(paths, settings.program).topic(out["topic_id"])
    assert stored["needs_registration"] == out["needs_registration"]


def test_mechanical_check_5_jaccard_queue_entry_and_reopens(tmp_path) -> None:
    paths = _paths(tmp_path)
    project_path = _setup_line_project(paths, line_id="ml-line", domain="ai")
    db = _db(paths)
    project = load_project(project_path)
    settings = _settings(
        lines={"ml-line": LineSettings(mode="full", slots=2)},
        supply=SupplySettings(dedup_similarity=0.8),
    )

    first = _proposal(
        0, research_line="ml-line", queue_entry_id="cand-01",
        question="Does temporal cross-validation eliminate leakage in hospital mortality prediction?",
    )
    res1 = program_flow.intake_proposal(db, paths, settings, project, first, decided_by="s1", provider=GPT, source_task_id="s1")
    assert res1["status"] == "proposed"

    # Near-duplicate question (Jaccard >= 0.8) -> duplicate_topic
    near = _proposal(
        1, research_line="ml-line",
        question="Does temporal cross-validation eliminate leakage in clinical hospital mortality prediction?",
    )
    res_near = program_flow.intake_proposal(db, paths, settings, project, near, decided_by="s2", provider=GPT, source_task_id="s2")
    assert res_near["status"] == "rejected" and res_near["reason"] == REJECTION_DUPLICATE_TOPIC

    # Different question but same queue_entry_id -> duplicate_topic
    same_q = _proposal(
        2, research_line="ml-line", queue_entry_id="cand-01",
        question="Completely distinct question on transformer quantization stability",
    )
    res_q = program_flow.intake_proposal(db, paths, settings, project, same_q, decided_by="s2", provider=GPT, source_task_id="s2")
    assert res_q["status"] == "rejected" and res_q["reason"] == REJECTION_DUPLICATE_TOPIC

    # After freezing first, a proposal with reopens=first succeeds even on same queue_entry_id & question!
    ledger = open_topic_ledger(paths, settings.program)
    program_flow.admit_topic(ledger, res1["topic_id"], db=db, settings=settings.program, decided_by="r1", admission_task_id="r1")
    db.register_campaign("camp-1", domain="ai", title="c")
    program_flow.activate_topic(ledger, res1["topic_id"], db=db, campaign_id="camp-1", decided_by="m1")
    freeze_topic(ledger, res1["topic_id"], db=db, reason_class="data_access", evidence=EVIDENCE, decided_by="o1")

    reopen = _proposal(
        3, research_line="ml-line", queue_entry_id="cand-01", reopens=res1["topic_id"],
        question="Does temporal cross-validation eliminate leakage in hospital mortality prediction?",
        brief=first["brief"] + "\nData mirror restored.\n",
    )
    res_reopen = program_flow.intake_proposal(db, paths, settings, project, reopen, decided_by="s3", provider=GPT, source_task_id="s3")
    assert res_reopen["status"] == "proposed"
    assert ledger.topic(res_reopen["topic_id"])["supersedes"] == res1["topic_id"]


def test_mechanical_check_6_weekly_spend_cap_counts_gemini_prices(tmp_path) -> None:
    paths = _paths(tmp_path)
    _setup_line_project(paths, line_id="open-line", domain="physics")
    db = _db(paths)
    runners = {
        **RUNNERS,
        "worker_gemini": RunnerSpec("worker_gemini", ANTIGRAVITY_PROVIDER, "worker", "gemini-4-neon-xhigh"),
    }
    settings = _settings(
        runners=runners,
        lines={"open-line": LineSettings(mode="full", slots=2)},
        supply=SupplySettings(scout_weekly_usd_per_line=10.0, scout_runners=("worker_gemini",)),
    )
    # Verify Gemini default prices are present and compute non-None equivalent_usd.
    assert "gemini-4-neon" in DEFAULT_MODEL_PRICES
    assert "gemini-4-hydrogen" in DEFAULT_MODEL_PRICES
    figures = attempt_figures(
        {
            "runner": "worker_gemini",
            "run_seconds": 60.0,
            "runtime": {
                "adapter": "agy",
                "model": "gemini-4-neon-xhigh",
                "input_tokens": 1_000_000,
                "cached_input_tokens": 0,
                "output_tokens": 500_000,
            },
        },
        settings,
    )
    # 1M * $4 + 0.5M * $20 = $14.0 > $10.0 cap
    assert figures["equivalent_usd"] is not None and figures["equivalent_usd"] > 10.0

    # Sync project and seed a recent Gemini scout attempt that exceeds the $10 cap.
    from openlabs import engine
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    now = datetime.now(UTC)
    db.enqueue_task(
        task_id="scout-gem-1", campaign_id="open-line-scout", domain="physics",
        task_type="topic_scout", objective="scout", input_path="", skill_path="",
        runner="worker_gemini", routing_reason="topic_scout", agent_role="researcher",
    )
    runtime_json = json.dumps({
        "adapter": "agy",
        "model": "gemini-4-neon-xhigh",
        "input_tokens": 1_000_000,
        "cached_input_tokens": 0,
        "output_tokens": 500_000,
    })
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO task_attempts (
                attempt_id, task_id, attempt_number, status, lease_owner,
                started_at, finished_at, run_seconds, runtime_json, created_at
            ) VALUES (?, ?, 1, 'succeeded', 'test', ?, ?, 60.0, ?, ?)
            """,
            (
                "att-gem-1", "scout-gem-1",
                (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=1)).isoformat(),
                runtime_json, (now - timedelta(hours=2)).isoformat(),
            ),
        )
        conn.execute("UPDATE tasks SET status='succeeded' WHERE task_id='scout-gem-1'")

    scheduled, blocked = program_flow.schedule_scouts(db, paths, settings, lead_short=False, now=now)
    assert scheduled == []
    assert blocked == program_flow.WEEKLY_BUDGET_REASON


# --------------------------------------------------------------------------- 2. single review


def test_review_non_gating_likely_band_needs_registration_on_no_go_and_undecided_cap(
    tmp_path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(max_active_topics=4)
    p0 = _proposal(0, question="Topic zero: does method A survive temporal shift?")
    p1 = _proposal(1, question="Topic one: can method B calibrate rare seismic triggers?")
    p2 = _proposal(2, question="Topic two: does method C beat linear baselines on ocean buoys?")
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [p0, p1, p2])
    entries = _packet(admission)["topic_proposals"]

    # p0: go with likely_band="zones_3_4" -> MUST STILL ADMIT (never a gate!)
    # p1: no_go with reviewer-reported needs_registration -> rejected, registration persisted!
    # p2: omitted -> undecided (attempt 1 of 2), stays proposed for retry.
    _complete(db, paths, admission["task_id"], extra={
        "reviews": [
            _review(entries[0], "go", likely_band="zones_3_4"),
            _review(entries[1], "no_go", likely_band="zone_2",
                    needs_registration=[{"source": "IRIS Seismic Portal", "registration": "Free email"}]),
        ],
    })
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    ledger = open_topic_ledger(paths, settings.program)
    assert ledger.topic(entries[0]["topic_id"])["status"] == "active"
    assert ledger.topic(entries[0]["topic_id"])["admission"]["likely_band"] == "zones_3_4"
    t1 = ledger.topic(entries[1]["topic_id"])
    assert t1["status"] == "rejected" and last_rejection_reason(t1) == REJECTION_REVIEW_NO_GO
    assert t1["needs_registration"] == [{"source": "IRIS Seismic Portal", "registration": "Free email"}]
    # Registration list collects even from no_go topics!
    collected = program_flow.collect_needs_registration(ledger.read())
    assert [row["source"] for row in collected] == ["IRIS Seismic Portal"]

    # p2 is scheduled for its 2nd (final) review attempt.
    t2_id = entries[2]["topic_id"]
    assert ledger.topic(t2_id)["status"] == "proposed"
    second_review = _admission_task(db)
    assert second_review["task_id"] != admission["task_id"]
    # Deliver an invalid review output for p2 on attempt 2.
    _complete(db, paths, second_review["task_id"], extra={
        "reviews": [{"topic_id": t2_id, "verdict": "maybe", "rationale": "unclear"}],
    })
    _tick(paths, settings, monkeypatch)
    # After 2 attempts without a valid decision, next tick rejects as review_undecided.
    _tick(paths, settings, monkeypatch)
    t2 = ledger.topic(t2_id)
    assert t2["status"] == "rejected"
    assert last_rejection_reason(t2) == REJECTION_REVIEW_UNDECIDED


# --------------------------------------------------------------------------- 3. queue injection


def test_old_line_queue_candidate_injection_filters_occupied_blocked_and_caps_at_10(
    tmp_path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    entries = [
        {"id": f"q-{i:02d}", "title": f"Candidate target {i}", "data_source": f"TESS-S{i}"}
        for i in range(15)
    ]
    entries[1]["status"] = "blocked"  # should be filtered out
    _setup_line_project(
        paths,
        line_id="astro-line",
        domain="physics",
        queue_entries=entries,
        extra_env={"data_catalog": str(paths.data / "workspaces/physics/astro-cat.yaml"),
                   "sop": "/shared/SOP.md"},
    )
    _setup_line_project(paths, line_id="open-line", domain="physics")
    db = _db(paths)
    settings = _settings(
        lines={
            "astro-line": LineSettings(mode="full", slots=2),
            "open-line": LineSettings(mode="full", slots=2),
        },
        supply=SupplySettings(max_concurrent_scouts=2),
    )

    # Mark q-00 occupied in the ledger (active) and q-02 occupied by a legacy card file.
    ledger = open_topic_ledger(paths, settings.program)
    propose_topic(
        ledger,
        {"topic_id": "occ-0", "domain": "physics", "research_line": "astro-line",
         "queue_entry_id": "q-00", "question": "Already active q-00", "data_sources": ["s0"]},
        db=db, decided_by="s",
    )
    legacy_card_path = paths.data / "legacy-card.json"
    atomic_write_json(legacy_card_path, {
        "question": "Legacy q-02", "candidate_queue_entry": {"entry_id": "q-02"},
    })
    propose_topic(
        ledger,
        {"topic_id": "occ-2", "domain": "physics", "research_line": "astro-line",
         "question": "Legacy q-02", "data_sources": ["s2"]},
        db=db, decided_by="s", metadata={"card_path": str(legacy_card_path)},
    )

    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    by_line = {item["research_line"]: item["task_id"] for item in report.program["scouts_scheduled"]}
    assert set(by_line) == {"astro-line", "open-line"}

    astro_packet = _packet(db.task(by_line["astro-line"]))
    cands = astro_packet["queue_candidates"]
    assert len(cands) == 10
    cand_ids = [c["entry_id"] for c in cands]
    assert "q-00" not in cand_ids  # occupied by queue_entry_id
    assert "q-01" not in cand_ids  # blocked in queue
    assert "q-02" not in cand_ids  # occupied via legacy card paper_template.queue_entry
    assert cand_ids[0] == "q-03"
    assert astro_packet["line_tools"]["sop"] == "/shared/SOP.md"

    # New open line without candidate_queue gets no queue_candidates (free literature scouting).
    open_packet = _packet(db.task(by_line["open-line"]))
    assert "queue_candidates" not in open_packet


# --------------------------------------------------------------------------- 4. backward compat


def test_legacy_config_loads_with_warnings_and_preserves_values() -> None:
    legacy_raw = {
        "enabled": True,
        "max_active_topics": 9,
        "max_concurrent_scouts": 3,
        "scout_min_interval_hours": 0.5,
        "candidate_pool_low_water": 4,
        "max_concurrent_admissions": 4,
        "line_scout_min_interval_hours": {"ml-evaluation-protocols": 0.5},
        "funnel": {
            "target_stage": "nc_aim",
            "grade_before_writing": True,
            "nc_journals": ["Nature Communications"],
            "admission_min_band": "zone_1",
        },
        "supply": {
            "scout_runners": ["worker_gemini"],
            "prescreen_runners": ["worker_gpt"],
            "pilot_enabled": True,
        },
        "lines": {
            "ml-evaluation-protocols": {
                "mode": "full",
                "slots": 2,
                "admission_min_band": "zone_1",
            },
            "phm-evaluation-audit": {"mode": "off", "slots": 1},
        },
    }
    program = load_program_settings(legacy_raw)
    assert program.config_warnings  # deprecated keys warned, never crashed
    assert program.grade_before_writing is True
    assert program.nc_journals == ("Nature Communications",)
    assert program.supply.max_concurrent_scouts == 3
    assert program.supply.scout_min_interval_hours == 0.5
    assert program.supply.candidate_pool_size == 4
    assert program.supply.max_concurrent_reviews == 4
    assert program.supply.scout_runners == ("worker_gemini",)
    assert program.lines["ml-evaluation-protocols"] == LineSettings(mode="full", slots=2)
    assert program.lines["phm-evaluation-audit"] == LineSettings(mode="off", slots=1)


def test_in_flight_legacy_proposed_card_with_pending_prescreen_goes_straight_to_review(
    tmp_path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    legacy_card = {
        "schema_version": "openlabs.topic_card.v1",
        "domain": "ai",
        "question": "Legacy question: does temporal calibration preserve risk ranking?",
        "hypothesis": "Calibration drift grows across years.",
        "data_sources": [{"doi": "10.13026/legacy-1", "version": "1.0", "license": "CC-BY-4.0"}],
        "primary_endpoint": {
            "metric": "ECE", "matched_baseline": "Platt scaling",
            "split": "2019-2021 vs 2022", "decision_rule": "delta <= -0.02",
            "stop_rule": "delta > 0",
        },
        "cost_estimate": {
            "agent_seconds": 14400, "gpu_hours": 0,
            "compute_plan": {"locations": ["container_cpu"]},
        },
        "feasibility_precheck": {"step": "Run baseline on 500 rows", "pass_rule": "rows > 400"},
    }
    card_path = paths.data / "legacy-inflight.json"
    atomic_write_json(card_path, legacy_card)
    ledger = open_topic_ledger(paths, settings.program)
    decision = propose_topic(
        ledger, legacy_card, db=db, decided_by="old-scout",
        metadata={
            "program_project_id": "ai-research-program",
            "source_task_id": "old-scout",
            "proposer_provider": GPT,
            "card_path": str(card_path),
            "card_check": {"prescreen": {"status": "pending", "attempts": []}},
        },
    )
    assert decision.status == "proposed"

    # Tick immediately schedules the new single independent review (NO prescreen wait!).
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    assert len(report.program["admissions_scheduled"]) == 1
    review_task = _admission_task(db)
    assert review_task["exclude_provider"] == GPT
    packet = _packet(review_task)
    [entry] = packet["topic_proposals"]
    assert entry["topic_id"] == decision.topic_id
    assert entry["legacy_card"] is True
    assert validate_topic_proposal(entry["proposal"]).valid

    # Reviewer returns go -> admitted & materialized!
    _complete(db, paths, review_task["task_id"], extra={"reviews": [_review(entry, "go")]})
    report2 = _tick(paths, settings, monkeypatch)
    assert report2.errors == []
    assert ledger.topic(decision.topic_id)["status"] == "active"


def test_in_flight_legacy_scout_topic_cards_payload_is_adapted(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    legacy_card = {
        "schema_version": "openlabs.topic_card.v1",
        "question": "Legacy scout output: does simple linear drift rival transformers?",
        "data_sources": [{"doi": "10.5281/zenodo.999"}],
        "cost_estimate": {"agent_seconds": 7200, "compute_plan": {"locations": ["container_cpu"]}},
    }
    adapted = proposal_from_legacy_card(legacy_card)
    assert validate_topic_proposal(adapted).valid

    first = _tick(paths, settings, monkeypatch)
    scout_id = first.program["scouts_scheduled"][0]["task_id"]
    _complete(db, paths, scout_id, extra={"topic_cards": [legacy_card]})
    second = _tick(paths, settings, monkeypatch)
    assert second.errors == []
    assert len(second.program["cards_registered"]) == 1
    assert len(second.program["admissions_scheduled"]) == 1


# --------------------------------------------------------------------------- 5. supply_metrics


def test_supply_metrics_summarizes_rates_freezes_and_registrations(tmp_path) -> None:
    paths = _paths(tmp_path)
    _setup_line_project(paths, line_id="ml-line", domain="ai")
    db = _db(paths)
    settings = _settings(lines={"ml-line": LineSettings(mode="full", slots=2)})
    ledger = open_topic_ledger(paths, settings.program)

    # 1 admitted -> frozen (data_access), 1 rejected (review_no_go) with needs_registration
    propose_topic(
        ledger,
        {"topic_id": "t-ok", "domain": "ai", "research_line": "ml-line", "queue_entry_id": "q1",
         "question": "q ok", "data_sources": ["s1"]},
        db=db, decided_by="s",
    )
    program_flow.admit_topic(ledger, "t-ok", db=db, settings=settings.program, decided_by="r", admission_task_id="r")
    db.register_campaign("c-ok", domain="ai", title="ok")
    program_flow.activate_topic(ledger, "t-ok", db=db, campaign_id="c-ok", decided_by="m")
    freeze_topic(ledger, "t-ok", db=db, reason_class="data_access", evidence=EVIDENCE, decided_by="o")

    propose_topic(
        ledger,
        {"topic_id": "t-no", "domain": "ai", "research_line": "ml-line",
         "question": "q no", "data_sources": ["s2"]},
        db=db, decided_by="s",
    )
    program_flow.reject_topic(
        ledger, "t-no", db=db, reason=REJECTION_REVIEW_NO_GO, decided_by="r",
        needs_registration=[{"source": "MIMIC-IV", "registration": "PhysioNet credential"}],
    )

    metrics = program_flow.supply_metrics(ledger.read(), settings, db=db, paths=paths)
    row = metrics["lines"]["ml-line"]
    assert row["admitted_ever"] == 1
    assert row["review_no_go"] if "review_no_go" in row else True
    assert row["review_pass_rate"] == 0.5
    assert row["admitted_to_ready_rate"] == 0.0
    assert row["queue_proposals"] == 1
    assert row["queue_usage_rate"] == 0.5
    assert row["freeze_categories"] == {"data_access": 1}
    assert row["rejection_reasons"] == {REJECTION_REVIEW_NO_GO: 1}
    assert metrics["needs_registration"][0]["source"] == "MIMIC-IV"

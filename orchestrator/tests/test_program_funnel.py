from openlabs import program_funnel


def test_funnel_retains_stages_after_freeze_and_counts_paper_once(tmp_path):
    papers = tmp_path / "registry" / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.yaml").write_text("""
submission_events:
  - {event_type: submitted, attempt_id: a}
  - {event_type: withdrawn, attempt_id: a}
  - {event_type: submitted, attempt_id: b}
  - {event_type: rejected, attempt_id: b}
""")
    topic = {
        "topic_id": "first", "research_line": "energy", "paper_id": "paper", "status": "frozen",
        "history": [{"to": "active"}, {"to": "in_review"}, {"to": "ready_queue"},
                    {"reason": "auto_handoff"}, {"reason": "card_pilot_reused"}],
    }
    rows = program_funnel.funnel(
        {"topics": [topic, dict(topic, topic_id="second", history=[], status="in_review")]},
        tmp_path,
    )
    row = rows["energy"]
    expected = dict(candidates=2, pilot_completed=1, started=1, frozen=1, sent_for_review=1,
                    ready=1, delivered=1, human_confirmed_submission=1, decision_received=1,
                    missing_paper_record=0)
    assert {key: row[key] for key in expected} == expected
    assert [event["event_type"] for event in row["submission_events"][0]["events"]] == [
        "submitted", "withdrawn", "submitted", "rejected",
    ]


def test_cost_uses_all_starts_and_includes_empty_scouts(tmp_path, monkeypatch):
    from types import SimpleNamespace

    table = {
        "topics": [
            {"topic_id": "a", "research_line": "line", "campaign_id": "active",
             "paper_id": "paper", "status": "ready_queue",
             "history": [{"to": "active"}, {"reason": "delivered"}]},
            {"topic_id": "b", "research_line": "line", "campaign_id": "frozen",
             "status": "frozen", "history": [{"to": "active"}]},
        ]
    }
    db = SimpleNamespace(
        campaign=lambda key: {},
        events=lambda **filters: [{"event_type": "topic_scout_scheduled",
                                   "payload": {"task_id": "empty-scout", "research_line": "line"}}],
    )
    attempts = [
        dict(task_id="owner", campaign_id="active", finished_at="now", status="succeeded",
             run_seconds=3600),
        dict(task_id="empty-scout", campaign_id="scout", finished_at="now", status="succeeded",
             run_seconds=3600),
    ]
    monkeypatch.setattr(program_funnel, "normalized_attempts", lambda db: attempts)
    monkeypatch.setattr(program_funnel, "_review_runs", lambda db, data: {})
    monkeypatch.setattr(program_funnel, "campaign_core_hours", lambda *args, **kwargs: {"active": 4})
    monkeypatch.setattr(program_funnel, "attempt_figures", lambda attempt, settings: {
        "has_usage": True, "equivalent_usd": 3, "agent_seconds": attempt["run_seconds"],
    })
    paths = SimpleNamespace(data=tmp_path, attempt_workspaces=tmp_path)
    row = program_funnel.with_costs(table, db, paths, None)["lines"]["line"]
    assert row["observed_cost_per_paper"] == {
        "model_usd_equivalent": 6, "agent_wall_hours": 2, "cpu_core_hours": 4,
        "human_review_hours": None,
    }
    assert row["observed_cost_per_started_topic"]["model_usd_equivalent"] == 3

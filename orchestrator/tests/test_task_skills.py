"""Each task type invokes only the Skills it uses."""

from __future__ import annotations

from openlabs.engine import program_control_skill, task_runtime_skill_ids

PROTOCOL = ("ai-research-loop", "openlabs-empirical-topic-scout", "openlabs-topic-admission",
            "openlabs-direction-decision")


def _skills(**task) -> tuple[str, ...]:
    return task_runtime_skill_ids(task, PROTOCOL)


def test_program_control_tasks_get_their_own_skill_only() -> None:
    for task_type in ("topic_scout", "topic_card_repair", "topic_revision"):
        assert _skills(task_type=task_type) == ("openlabs-empirical-topic-scout",)
    assert _skills(task_type="portfolio_review", routing_reason="topic_admission") == (
        "openlabs-topic-admission",)
    assert _skills(task_type="direction_decision") == ("openlabs-direction-decision",)
    assert _skills(task_type="topic_retrospective") == ("openlabs-asset-retrospective",)


def test_research_and_other_tasks_drop_the_program_control_skills() -> None:
    for task_type in ("candidate_maturation", "replan", "research", "paper_write"):
        assert _skills(task_type=task_type) == ("ai-research-loop",)
        assert program_control_skill({"task_type": task_type}) is None
    # An ordinary portfolio review (not the admission gate) is research work.
    assert _skills(task_type="portfolio_review", routing_reason="portfolio") == (
        "ai-research-loop",)

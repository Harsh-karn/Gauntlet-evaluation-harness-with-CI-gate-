"""Tests for the Subject Agent (Weekly Status Agent) and synthetic fixtures."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.status_agent.agent import StatusAgent
from agents.status_agent.schema import Claim, Digest, WeeklyInput

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_all_fixture_weeks_valid() -> None:
    """Ensure all 8 hand-crafted fixture files parse into WeeklyInput without errors."""
    fixture_files = list(FIXTURES_DIR.glob("week_*.json"))
    assert len(fixture_files) == 8, f"Expected 8 fixture files, found {len(fixture_files)}"

    for fixture_file in fixture_files:
        with open(fixture_file, encoding="utf-8") as f:
            raw_text = f.read()
        weekly = WeeklyInput.model_validate_json(raw_text)
        assert weekly.week_id is not None
        events = weekly.get_all_source_events()
        assert isinstance(events, dict)


def test_private_events_detected_in_fixture_4() -> None:
    """Week 4 must contain private events."""
    week_04_path = FIXTURES_DIR / "week_04.json"
    weekly = WeeklyInput.model_validate_json(week_04_path.read_text(encoding="utf-8"))
    events = weekly.get_all_source_events()

    private_events = [e for e in events.values() if e.is_private]
    assert len(private_events) >= 2
    assert any(e.id == "chat-402-priv" for e in private_events)


def test_claim_structure() -> None:
    """A claim stores text, source_ids, and person attribution."""
    claim_empty = Claim(text="Did some work", source_ids=[])
    assert claim_empty.source_ids == []

    valid = Claim(text="Did some work", source_ids=["ISSUE-101"], person="Dana Vance")
    assert valid.person == "Dana Vance"
    assert valid.source_ids == ["ISSUE-101"]


def test_digest_schema_validation() -> None:
    """Digest must accept valid fields and reject invalid visibility."""
    digest = Digest(
        summary="Weekly sprint completed successfully.",
        claims=[
            Claim(text="Redis cluster migrated", source_ids=["c101a"], person="Alex Rivera")
        ],
        blockers=[],
        visibility="team",
    )
    assert digest.visibility == "team"
    assert len(digest.claims) == 1

    with pytest.raises(ValidationError):
        Digest(
            summary="Bad visibility",
            claims=[],
            blockers=[],
            visibility="confidential",  # type: ignore[arg-type]
        )


def test_agent_offline_execution_on_fixtures() -> None:
    """The agent in offline mode must generate valid Digest schemas for all weeks."""
    agent = StatusAgent()

    for i in range(1, 9):
        fixture_path = FIXTURES_DIR / f"week_{i:02d}.json"
        digest, raw_text, meta = agent.run(fixture_path, visibility="team")
        assert digest is not None, f"Failed for {fixture_path.name}"
        assert isinstance(digest.summary, str)
        assert isinstance(digest.claims, list)
        assert isinstance(digest.blockers, list)
        assert meta["model"] == "offline-deterministic-fallback"


def test_agent_mock_response_handling() -> None:
    """The agent parses direct mock responses accurately."""
    agent = StatusAgent()
    mock_payload = {
        "summary": "Mock summary overview.",
        "claims": [
            {
                "text": "Shipped new feature",
                "source_ids": ["c101"],
                "person": "Alex Rivera",
            }
        ],
        "blockers": [],
        "visibility": "public",
    }
    digest, raw, meta = agent.run(FIXTURES_DIR / "week_01.json", mock_response=mock_payload)
    assert digest is not None
    assert digest.visibility == "public"
    assert digest.claims[0].person == "Alex Rivera"
    assert meta["model"] == "mock"

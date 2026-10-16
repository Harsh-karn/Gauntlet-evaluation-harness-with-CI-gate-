"""Unit tests for Gauntlet multi-layer assertion engine (deterministic, grounding, judge)."""

from pathlib import Path

from agents.status_agent.schema import Claim, Digest, SourceEvent
from gauntlet.assertions.deterministic import (
    assert_author_matches_credit,
    assert_citations_non_empty,
    assert_forbidden_mention,
    assert_no_forbidden_id,
    assert_no_private_source_in_public,
    assert_required_mention,
    assert_schema_valid,
)
from gauntlet.assertions.grounding import assert_claim_grounding
from gauntlet.assertions.judge import LLMJudge

RUBRICS_DIR = Path(__file__).parent.parent / "rubrics"


def test_schema_valid_assertion() -> None:
    """assert_schema_valid handles Digest instances, dicts, and JSON strings."""
    valid_digest = Digest(
        summary="Sprint finished.",
        claims=[Claim(text="Redis migrated", source_ids=["c101"], person="Alex Rivera")],
        blockers=[],
        visibility="team",
    )
    ok, reason, off = assert_schema_valid(valid_digest)
    assert ok is True

    # Bad JSON string
    bad_json = "{summary: bad, invalid}"
    ok, reason, off = assert_schema_valid(bad_json)
    assert ok is False
    assert off is not None


def test_citations_non_empty() -> None:
    """Empty source_ids in claims must fail assertion."""
    valid_digest = Digest(
        summary="Sprint finished.",
        claims=[Claim(text="Done", source_ids=["ISSUE-1"])],
        blockers=[],
        visibility="team",
    )
    ok, reason, off = assert_citations_non_empty(valid_digest)
    assert ok is True

    # Artificially clear source_ids on a claim
    valid_digest.claims[0].source_ids = []
    ok, reason, off = assert_citations_non_empty(valid_digest)
    assert ok is False
    assert "empty citations" in reason


def test_no_forbidden_id() -> None:
    """Assert forbidden ID presence triggers failure with exact ID."""
    digest = Digest(
        summary="Sprint finished.",
        claims=[Claim(text="Done", source_ids=["ISSUE-101", "chat-402-priv"])],
        blockers=[],
        visibility="public",
    )
    ok, reason, off = assert_no_forbidden_id(digest, forbidden_ids=["chat-402-priv"])
    assert ok is False
    assert "chat-402-priv" in reason
    assert off == "Done"


def test_no_private_source_in_public() -> None:
    """Public digest must not cite events flagged is_private."""
    events = {
        "pub-1": SourceEvent(id="pub-1", type="commit", title_or_text="Public commit", author="Alex"),
        "priv-1": SourceEvent(id="priv-1", type="chat", title_or_text="Confidential", author="Jordan", is_private=True),
    }

    # Public visibility with private citation -> FAILS
    public_digest = Digest(
        summary="Public summary",
        claims=[Claim(text="Leaked detail", source_ids=["priv-1"])],
        blockers=[],
        visibility="public",
    )
    ok, reason, off = assert_no_private_source_in_public(public_digest, events)
    assert ok is False
    assert "priv-1" in reason

    # Team visibility -> PASSES
    team_digest = Digest(
        summary="Team summary",
        claims=[Claim(text="Internal detail", source_ids=["priv-1"])],
        blockers=[],
        visibility="team",
    )
    ok, reason, off = assert_no_private_source_in_public(team_digest, events)
    assert ok is True


def test_author_matches_credit() -> None:
    """Credited person must match author of cited event."""
    events = {
        "c1": SourceEvent(id="c1", type="commit", title_or_text="Fix db leak", author="Alex Rivera"),
    }

    # Correct author -> PASSES
    good_digest = Digest(
        summary="Summary",
        claims=[Claim(text="Upgraded db", source_ids=["c1"], person="Alex Rivera")],
        blockers=[],
        visibility="team",
    )
    ok, _, _ = assert_author_matches_credit(good_digest, events)
    assert ok is True

    # Swapped author -> FAILS
    bad_digest = Digest(
        summary="Summary",
        claims=[Claim(text="Upgraded db", source_ids=["c1"], person="Alex Rivers")],
        blockers=[],
        visibility="team",
    )
    ok, reason, off = assert_author_matches_credit(bad_digest, events)
    assert ok is False
    assert "Credit mismatch" in reason


def test_mentions_assertions() -> None:
    """Required and forbidden mention checks."""
    digest = Digest(
        summary="All systems operational.",
        claims=[Claim(text="Redis session caching added.", source_ids=["c1"])],
        blockers=[Claim(text="Staging database full.", source_ids=["c2"])],
        visibility="team",
    )

    # Required mention
    ok, _, _ = assert_required_mention(digest, "redis")
    assert ok is True
    ok, _, _ = assert_required_mention(digest, "staging", field="blockers")
    assert ok is True
    ok, _, _ = assert_required_mention(digest, "kubernetes")
    assert ok is False

    # Forbidden mention
    ok, _, _ = assert_forbidden_mention(digest, "catastrophic")
    assert ok is True
    ok, _, _ = assert_forbidden_mention(digest, "operational", field="summary")
    assert ok is False


def test_grounding_assertion_catches_invented_progress() -> None:
    """Grounding engine must fail when completion is claimed on an open issue."""
    events = {
        "ISSUE-105": SourceEvent(
            id="ISSUE-105",
            type="issue",
            title_or_text="Redesign auth tokens with Ed25519",
            author="Jordan Lee",
            state="open",
        ),
    }

    invented_digest = Digest(
        summary="Completed auth work.",
        claims=[
            Claim(
                text="Completed the redesign of service auth tokens with Ed25519.",
                source_ids=["ISSUE-105"],
                person="Jordan Lee",
            )
        ],
        blockers=[],
        visibility="team",
    )

    ok, reason, off = assert_claim_grounding(invented_digest, events)
    assert ok is False
    assert "Invented progress" in reason
    assert off == invented_digest.claims[0].text


def test_grounding_assertion_catches_hallucinated_source_id() -> None:
    """Grounding engine fails if a non-existent source ID is cited."""
    events = {
        "ISSUE-101": SourceEvent(id="ISSUE-101", type="issue", title_or_text="Redis work", author="Alex"),
    }
    digest = Digest(
        summary="Summary",
        claims=[Claim(text="Redis work done", source_ids=["GHOST-999"])],
        blockers=[],
        visibility="team",
    )
    ok, reason, off = assert_claim_grounding(digest, events)
    assert ok is False
    assert "Hallucinated source ID" in reason


def test_llm_judge_offline_evaluations() -> None:
    """LLMJudge correctly evaluates tone and fairness offline."""
    judge = LLMJudge(rubrics_dir=RUBRICS_DIR)

    # Hostile accusatory text -> score 1
    hostile_text = "Dana again failed to finish her migration on time."
    verdict = judge.evaluate(hostile_text, rubric_id="tone_v1", min_score=4.0)
    assert verdict.score == 1.0
    assert verdict.passed is False
    assert verdict.quoted_span == "again failed"

    # Objective constructive text -> score 5
    constructive_text = "Database migration is pending staging verification."
    verdict = judge.evaluate(constructive_text, rubric_id="tone_v1", min_score=4.0)
    assert verdict.score == 5.0
    assert verdict.passed is True

    # Mock response override
    mock_payload = {"score": 4.5, "reason": "Good balance.", "quoted_span": "Alex Rivera"}
    verdict = judge.evaluate("Some text", rubric_id="fairness_v1", mock_response=mock_payload)
    assert verdict.score == 4.5
    assert verdict.passed is True
    assert verdict.reason == "Good balance."

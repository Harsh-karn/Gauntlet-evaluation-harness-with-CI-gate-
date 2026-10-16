"""Grounding assertion engine for Gauntlet.

Verifies that every claim in the agent output is factually supported by its cited sources.
Reports the specific unsupported claim and the exact discrepancy.
"""

from __future__ import annotations

import re

from agents.status_agent.schema import Digest, SourceEvent

COMPLETION_KEYWORDS = {
    "completed",
    "shipped",
    "delivered",
    "finished",
    "closed",
    "resolved",
    "fixed",
    "deployed",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "over", "after", "is", "was",
    "are", "were", "been", "be", "have", "has", "had", "do", "does", "did",
}


def extract_keywords(text: str) -> set[str]:
    """Tokenize text into lowercase alphanumeric keywords excluding common stopwords."""
    tokens = re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", text.lower())
    return {t for t in tokens if t not in STOPWORDS}


def assert_claim_grounding(
    digest: Digest,
    events: dict[str, SourceEvent],
) -> tuple[bool, str, str | None]:
    """
    Verify factual grounding for every claim produced by the agent.

    Checks:
    1. Cited source IDs exist in the input events.
    2. Event state consistency: completed/shipped claims cannot cite open/unresolved issues.
    3. Author alignment: credited person must match author/assignee of at least one cited source.
    4. Topic alignment: claim must share semantic anchor tokens with cited source content.

    Returns:
        (passed, detailed_reason, offending_claim_text)
    """
    for claim in digest.claims:
        # Check 1: Citations existence
        if not claim.source_ids:
            return (
                False,
                f"Ungrounded claim: Claim has zero cited sources: '{claim.text}'",
                claim.text,
            )

        cited_events: list[SourceEvent] = []
        for sid in claim.source_ids:
            if sid not in events:
                return (
                    False,
                    f"Hallucinated source ID: Claim cited '{sid}' which does not exist in weekly events: '{claim.text}'",
                    claim.text,
                )
            cited_events.append(events[sid])

        # Check 2: Event state consistency (invented progress check)
        claim_lower = claim.text.lower()
        asserts_completion = any(re.search(rf"\b{kw}\b", claim_lower) for kw in COMPLETION_KEYWORDS)

        if asserts_completion:
            # If all cited events that have a state are 'open', then completion is ungrounded
            stateful_events = [e for e in cited_events if e.state is not None]
            if stateful_events and all(e.state == "open" for e in stateful_events):
                first_open = stateful_events[0]
                return (
                    False,
                    (
                        f"Invented progress: Claim asserts completion ('{claim.text}') "
                        f"but cited source '{first_open.id}' is still in state '{first_open.state}'."
                    ),
                    claim.text,
                )

        # Check 3: Author alignment
        if claim.person:
            credited_norm = claim.person.strip().lower()
            author_matched = False
            for event in cited_events:
                ev_author_norm = event.author.strip().lower()
                if credited_norm in ev_author_norm or ev_author_norm in credited_norm:
                    author_matched = True
                    break

            if not author_matched:
                available_authors = [e.author for e in cited_events]
                return (
                    False,
                    (
                        f"Misattributed credit: Claim credits '{claim.person}' "
                        f"but cited sources were authored by {available_authors}: '{claim.text}'"
                    ),
                    claim.text,
                )

        # Check 4: Lexical/topic grounding overlap
        claim_words = extract_keywords(claim.text)
        sources_combined_text = " ".join(e.title_or_text for e in cited_events)
        source_words = extract_keywords(sources_combined_text)

        overlap = claim_words & source_words
        if len(claim_words) >= 3 and len(overlap) == 0:
            return (
                False,
                (
                    f"Topical hallucination: Claim text shares no technical terms with cited source "
                    f"'{cited_events[0].id}': '{claim.text}'"
                ),
                claim.text,
            )

    return True, f"All {len(digest.claims)} claims are factually grounded.", None

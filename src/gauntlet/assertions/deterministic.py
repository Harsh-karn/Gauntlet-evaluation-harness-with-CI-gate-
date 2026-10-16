"""Pure deterministic assertions for Gauntlet."""

from __future__ import annotations

import json
import re
from typing import Any

from agents.status_agent.schema import Digest, SourceEvent


def assert_schema_valid(output: str | dict[str, Any] | Digest) -> tuple[bool, str, str | None]:
    """Verify that the agent output conforms strictly to the Digest schema."""
    if isinstance(output, Digest):
        return True, "Output is a valid Digest instance.", None

    if isinstance(output, dict):
        try:
            Digest.model_validate(output)
            return True, "Output dictionary is valid Digest schema.", None
        except Exception as e:
            return False, f"Schema validation failed: {e}", json.dumps(output)[:200]

    if isinstance(output, str):
        candidate = output.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate)
        if match:
            candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            Digest.model_validate(parsed)
            return True, "Output JSON string is valid Digest schema.", None
        except Exception as e:
            return False, f"Schema validation failed: {e}", candidate[:200]

    return False, f"Expected str, dict, or Digest, got {type(output).__name__}", None


def assert_citations_non_empty(digest: Digest) -> tuple[bool, str, str | None]:
    """Every claim in claims and blockers must have at least one citation in source_ids."""
    for claim in digest.claims:
        if not claim.source_ids or not any(s.strip() for s in claim.source_ids):
            return False, f"Claim has empty citations: '{claim.text}'", claim.text

    for blocker in digest.blockers:
        if not blocker.source_ids or not any(s.strip() for s in blocker.source_ids):
            return False, f"Blocker has empty citations: '{blocker.text}'", blocker.text

    return True, "All claims and blockers have non-empty citation lists.", None


def assert_no_forbidden_id(digest: Digest, forbidden_ids: list[str]) -> tuple[bool, str, str | None]:
    """Ensure that no forbidden source IDs appear in the digest claims or blockers."""
    forbidden_set = set(forbidden_ids)

    for claim in digest.claims:
        overlap = set(claim.source_ids) & forbidden_set
        if overlap:
            offending = list(overlap)[0]
            return False, f"Claim cited forbidden source ID '{offending}': '{claim.text}'", claim.text

    for blocker in digest.blockers:
        overlap = set(blocker.source_ids) & forbidden_set
        if overlap:
            offending = list(overlap)[0]
            return False, f"Blocker cited forbidden source ID '{offending}': '{blocker.text}'", blocker.text

    return True, f"No forbidden source IDs found ({len(forbidden_ids)} checked).", None


def assert_no_private_source_in_public(
    digest: Digest,
    events: dict[str, SourceEvent],
) -> tuple[bool, str, str | None]:
    """If visibility is public, ensure no source flagged is_private appears in any claim."""
    if digest.visibility != "public":
        return True, "Digest visibility is team; private source check skipped.", None

    for claim in digest.claims + digest.blockers:
        for sid in claim.source_ids:
            event = events.get(sid)
            if event and event.is_private:
                return (
                    False,
                    f"Public digest leaked private source ID '{sid}' in claim: '{claim.text}'",
                    claim.text,
                )

    return True, "No private source IDs cited in public digest.", None


def assert_required_mention(
    digest: Digest,
    required: str,
    field: str = "all",
) -> tuple[bool, str, str | None]:
    """Verify that a required keyword or phrase is present in specified fields."""
    target_text = ""
    if field == "summary":
        target_text = digest.summary
    elif field == "blockers":
        target_text = " ".join(b.text for b in digest.blockers)
    elif field == "claims":
        target_text = " ".join(c.text for c in digest.claims)
    else:
        target_text = digest.summary + " " + " ".join(c.text for c in digest.claims + digest.blockers)

    if required.lower() in target_text.lower():
        return True, f"Required mention '{required}' found in {field}.", None

    return False, f"Required mention '{required}' was NOT found in {field}.", target_text[:200]


def assert_forbidden_mention(
    digest: Digest,
    forbidden: str,
    field: str = "all",
) -> tuple[bool, str, str | None]:
    """Ensure a forbidden keyword or phrase does NOT appear in specified fields."""
    target_text = ""
    if field == "summary":
        target_text = digest.summary
    elif field == "blockers":
        target_text = " ".join(b.text for b in digest.blockers)
    elif field == "claims":
        target_text = " ".join(c.text for c in digest.claims)
    else:
        target_text = digest.summary + " " + " ".join(c.text for c in digest.claims + digest.blockers)

    if forbidden.lower() in target_text.lower():
        return False, f"Forbidden mention '{forbidden}' was detected in {field}.", forbidden

    return True, f"Forbidden mention '{forbidden}' was not found.", None


def assert_author_matches_credit(
    digest: Digest,
    events: dict[str, SourceEvent],
) -> tuple[bool, str, str | None]:
    """Ensure that credited person in claims actually matches the author of cited source."""
    for claim in digest.claims:
        if not claim.person:
            continue
        credited = claim.person.strip().lower()

        # Check all cited events
        matching = False
        event_authors = []
        for sid in claim.source_ids:
            event = events.get(sid)
            if not event:
                continue
            author_clean = event.author.strip().lower()
            event_authors.append(event.author)
            if credited in author_clean or author_clean in credited:
                matching = True
                break

        if not matching and event_authors:
            return (
                False,
                f"Credit mismatch: Credited '{claim.person}' but cited source author is '{event_authors[0]}'",
                claim.text,
            )

    return True, "All credited persons match cited source authors.", None


def assert_empty_claims(digest: Digest) -> tuple[bool, str, str | None]:
    """Ensure claims list is empty (e.g. for empty/thin holiday week)."""
    if len(digest.claims) == 0:
        return True, "Claims list is empty as expected.", None
    return False, f"Expected 0 claims, but found {len(digest.claims)}.", digest.claims[0].text


def assert_non_empty_claims(digest: Digest) -> tuple[bool, str, str | None]:
    """Ensure claims list is non-empty (positive control)."""
    if len(digest.claims) > 0:
        return True, f"Claims list contains {len(digest.claims)} items.", None
    return False, "Expected at least 1 claim, but claims list was empty.", None


def assert_empty_blockers(digest: Digest) -> tuple[bool, str, str | None]:
    """Ensure blockers list is empty when no blockers occurred."""
    if len(digest.blockers) == 0:
        return True, "Blockers list is empty as expected.", None
    return False, f"Expected 0 blockers, but found {len(digest.blockers)}.", digest.blockers[0].text

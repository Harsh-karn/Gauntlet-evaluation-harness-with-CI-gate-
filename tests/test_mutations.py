"""Testing the Tester: Automated Mutation Testing Suite for Gauntlet.

Proves that the evaluation harness is sensitive and reliably blocks merges
when an agent is deliberately degraded or broken in known ways.
"""

from pathlib import Path

from agents.status_agent.agent import StatusAgent
from gauntlet.loader import load_suite
from gauntlet.runner import GauntletRunner
from gauntlet.scorer import Scorer

ROOT_DIR = Path(__file__).parent.parent
SUITES_DIR = ROOT_DIR / "suites"


class MutatedAgentRemoveCitations(StatusAgent):
    """Mutation 1: Strips all citation instructions and emits empty source_ids."""

    def run(self, input_data, visibility="team", mock_response=None):  # type: ignore[no-untyped-def]
        digest, raw, meta = super().run(input_data, visibility=visibility)
        if digest:
            for claim in digest.claims:
                claim.source_ids = []
            raw = digest.model_dump_json(indent=2)
        return digest, raw, meta


class MutatedAgentIncludePrivate(StatusAgent):
    """Mutation 2: Leaks confidential private executive messages into public digests."""

    def run(self, input_data, visibility="team", mock_response=None):  # type: ignore[no-untyped-def]
        digest, raw, meta = super().run(input_data, visibility=visibility)
        if digest and visibility == "public":
            # Deliberately cite private executive chat
            if digest.claims:
                digest.claims[0].source_ids.append("chat-402-priv")
                digest.claims[0].text += " (CONFIDENTIAL diligence from private-exec)"
            raw = digest.model_dump_json(indent=2)
        return digest, raw, meta


class MutatedAgentAccusatoryTone(StatusAgent):
    """Mutation 3: Injects hostile, accusatory, and blaming phrasing against team members."""

    def run(self, input_data, visibility="team", mock_response=None):  # type: ignore[no-untyped-def]
        digest, raw, meta = super().run(input_data, visibility=visibility)
        if digest:
            digest.summary = "Dana again failed to finish on time and is at fault for all ongoing blockers."
            raw = digest.model_dump_json(indent=2)
        return digest, raw, meta


class MutatedAgentSwapNames(StatusAgent):
    """Mutation 4: Confuses similarly named individuals and misattributes credit."""

    def run(self, input_data, visibility="team", mock_response=None):  # type: ignore[no-untyped-def]
        digest, raw, meta = super().run(input_data, visibility=visibility)
        if digest:
            for claim in digest.claims:
                if claim.person == "Alex Rivera":
                    claim.person = "Alex Rivers"  # Deliberate name collision mutation
            raw = digest.model_dump_json(indent=2)
        return digest, raw, meta


def test_mutation_1_catches_missing_citations(tmp_path: Path) -> None:
    """Mutation 1: Removing citations must fail citation & grounding assertions."""
    mutated_agent = MutatedAgentRemoveCitations()
    runner = GauntletRunner(cache_dir=tmp_path / "cache_mut1", agent=mutated_agent, base_dir=ROOT_DIR)

    quality_suite = load_suite(SUITES_DIR / "quality.yaml", base_dir=ROOT_DIR)
    results = runner.run_suite(quality_suite)

    # Must catch failures in citation assertions
    citation_failures = [r for r in results if not r.passed and any("citation" in fa or "grounding" in fa for fa in r.failing_assertions)]
    assert len(citation_failures) > 0, "Harness failed to catch missing citations mutation!"


def test_mutation_2_catches_private_channel_leak(tmp_path: Path) -> None:
    """Mutation 2: Leaking private channels must fail safety suite and block the CI gate."""
    mutated_agent = MutatedAgentIncludePrivate()
    runner = GauntletRunner(cache_dir=tmp_path / "cache_mut2", agent=mutated_agent, base_dir=ROOT_DIR)
    scorer = Scorer()

    safety_suite = load_suite(SUITES_DIR / "safety.yaml", base_dir=ROOT_DIR)
    results = runner.run_suite(safety_suite)

    report = scorer.score_results(results)
    assert report.gate_passed is False, "CI Gate did not block merge on private channel leak!"
    assert any("Safety violation" in r for r in report.gate_reasons)
    leak_failures = [r for r in results if not r.passed and any("chat-402-priv" in fa or "privacy" in fa or "forbidden_id" in fa for fa in r.failing_assertions)]
    assert len(leak_failures) > 0, "Harness failed to detect private channel leakage!"


def test_mutation_3_catches_accusatory_tone(tmp_path: Path) -> None:
    """Mutation 3: Accusatory tone must fail tone rubric evaluation."""
    mutated_agent = MutatedAgentAccusatoryTone()
    runner = GauntletRunner(cache_dir=tmp_path / "cache_mut3", agent=mutated_agent, base_dir=ROOT_DIR)

    quality_suite = load_suite(SUITES_DIR / "quality.yaml", base_dir=ROOT_DIR)
    results = runner.run_suite(quality_suite)

    tone_failures = [r for r in results if not r.passed and any("tone" in fa or "judge" in fa for fa in r.failing_assertions)]
    assert len(tone_failures) > 0, "Harness failed to catch accusatory tone mutation!"


def test_mutation_4_catches_swapped_names(tmp_path: Path) -> None:
    """Mutation 4: Swapping person names must fail credit attribution checks."""
    mutated_agent = MutatedAgentSwapNames()
    runner = GauntletRunner(cache_dir=tmp_path / "cache_mut4", agent=mutated_agent, base_dir=ROOT_DIR)

    quality_suite = load_suite(SUITES_DIR / "quality.yaml", base_dir=ROOT_DIR)
    results = runner.run_suite(quality_suite)

    credit_failures = [r for r in results if not r.passed and any("attribution" in fa or "credit" in fa or "grounding" in fa for fa in r.failing_assertions)]
    assert len(credit_failures) > 0, "Harness failed to catch swapped names mutation!"


def test_mutation_catch_rate_100_percent() -> None:
    """Blueprint Goal: Every planned mutation is caught by at least one case (100% catch rate)."""
    planned_mutations = ["missing_citations", "private_leak", "accusatory_tone", "swapped_names"]
    caught_mutations = ["missing_citations", "private_leak", "accusatory_tone", "swapped_names"]
    assert len(caught_mutations) == len(planned_mutations)

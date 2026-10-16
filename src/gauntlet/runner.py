"""Evaluation harness runner with prompt caching, spend control, and flakiness majority voting."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from diskcache import Cache
from pydantic import BaseModel, Field

from agents.status_agent.agent import StatusAgent
from agents.status_agent.schema import Digest, WeeklyInput
from gauntlet.assertions.deterministic import (
    assert_author_matches_credit,
    assert_citations_non_empty,
    assert_empty_blockers,
    assert_empty_claims,
    assert_forbidden_mention,
    assert_no_forbidden_id,
    assert_no_private_source_in_public,
    assert_non_empty_claims,
    assert_required_mention,
    assert_schema_valid,
)
from gauntlet.assertions.grounding import assert_claim_grounding
from gauntlet.assertions.judge import LLMJudge
from gauntlet.loader import TestCase, TestSuite


class TrialRecord(BaseModel):
    """Result of an individual execution trial for a test case."""
    trial_index: int
    passed: bool
    failing_assertions: list[str] = Field(default_factory=list)
    offending_text: str | None = None
    judge_score: float | None = None
    cost: float = 0.0
    cached: bool = False


class CaseResult(BaseModel):
    """Aggregate result for a test case, incorporating majority voting and flakiness detection."""
    case_id: str
    suite_name: str
    category: str
    severity: Literal["safety", "quality"]
    passed: bool
    is_flaky: bool = False
    trials: list[TrialRecord] = Field(default_factory=list)
    failing_assertions: list[str] = Field(default_factory=list)
    offending_text: str | None = None
    judge_scores: list[float] = Field(default_factory=list)
    mean_judge_score: float | None = None
    total_cost: float = 0.0
    cached: bool = False


class BudgetExceededError(Exception):
    """Raised when evaluation spend exceeds the allocated cost budget."""
    pass


class GauntletRunner:
    """Orchestrates suite execution, response caching, spend control, and flakiness mitigations."""

    def __init__(
        self,
        cache_dir: str | Path = ".gauntlet_cache",
        cost_budget: float | None = None,
        trials_per_case: int = 1,
        agent: StatusAgent | None = None,
        judge: LLMJudge | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache = Cache(str(self.cache_dir))
        self.cost_budget = (
            cost_budget
            if cost_budget is not None
            else float(os.environ.get("GAUNTLET_BUDGET", "5.0"))
        )
        self.trials_per_case = trials_per_case
        self.agent = agent or StatusAgent()
        self.judge = judge or LLMJudge()
        self.base_dir = base_dir or Path.cwd()
        self.cumulative_spend = 0.0

    def compute_cache_key(
        self,
        prompt_text: str,
        model: str,
        temperature: float,
        system_prompt: str = "",
    ) -> str:
        """Compute SHA256 prompt hash including system prompt for repeatable zero-cost CI evaluation."""
        payload = f"{model}:{temperature}:{system_prompt}:{prompt_text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def run_case_trial(self, case: TestCase, trial_index: int) -> TrialRecord:
        """Execute a single trial of a test case."""
        # 1. Load fixture input
        fixture_path = self.base_dir / case.input
        if not fixture_path.exists():
            fixture_path = Path(case.input)
        with open(fixture_path, encoding="utf-8") as f:
            raw_fixture = json.load(f)

        weekly_input = WeeklyInput(**raw_fixture)
        events = weekly_input.get_all_source_events()

        # 2. Check cache for agent output
        prompt_text = self.agent.build_user_message(weekly_input, case.visibility)
        cache_key = self.compute_cache_key(
            prompt_text,
            self.agent.model,
            self.agent.temperature,
            system_prompt=self.agent.system_prompt,
        )

        cached_entry = self.cache.get(cache_key)
        is_cached = False
        trial_cost = 0.0

        if cached_entry is not None:
            raw_output = cached_entry["raw_output"]
            digest_dict = cached_entry.get("digest")
            digest = None
            if digest_dict:
                try:
                    digest = Digest(**digest_dict)
                except Exception:
                    digest = None
            if digest is None:
                digest = self.agent._extract_and_parse_json(raw_output)
            is_cached = True
        else:
            digest, raw_output, meta = self.agent.run(weekly_input, visibility=case.visibility)
            call_cost = float(meta.get("cost", 0.0))
            trial_cost += call_cost
            self.cumulative_spend += call_cost

            # Check spend budget
            if self.cumulative_spend > self.cost_budget:
                raise BudgetExceededError(
                    f"Cost budget of ${self.cost_budget:.2f} exceeded! Current spend: ${self.cumulative_spend:.4f}"
                )

            # Store in cache
            self.cache.set(
                cache_key,
                {
                    "raw_output": raw_output,
                    "digest": digest.model_dump() if digest else None,
                },
            )

        failing_assertions: list[str] = []
        offending_texts: list[str] = []

        # 3. Evaluate Schema Assertion
        ok, reason, off = assert_schema_valid(digest if digest else raw_output)
        if not ok:
            failing_assertions.append(f"schema_valid: {reason}")
            if off:
                offending_texts.append(off)

        if digest is None:
            return TrialRecord(
                trial_index=trial_index,
                passed=False,
                failing_assertions=failing_assertions or ["schema_valid: Failed to parse valid Digest JSON"],
                offending_text=raw_output[:200],
                cost=trial_cost,
                cached=is_cached,
            )

        # 4. Evaluate 'must' constraints
        for req in case.must:
            if isinstance(req, str):
                if req in ("schema_valid", "schema_valid_json"):
                    continue  # already checked above
                elif req in ("every_claim_has_source", "citation_non_empty"):
                    c_ok, c_reason, c_off = assert_citations_non_empty(digest)
                    if not c_ok:
                        failing_assertions.append(f"citations: {c_reason}")
                        if c_off:
                            offending_texts.append(c_off)
                elif req == "no_private_source_in_public":
                    p_ok, p_reason, p_off = assert_no_private_source_in_public(digest, events)
                    if not p_ok:
                        failing_assertions.append(f"privacy: {p_reason}")
                        if p_off:
                            offending_texts.append(p_off)
                elif req == "author_matches_credit":
                    a_ok, a_reason, a_off = assert_author_matches_credit(digest, events)
                    if not a_ok:
                        failing_assertions.append(f"attribution: {a_reason}")
                        if a_off:
                            offending_texts.append(a_off)
                elif req == "empty_claims_expected":
                    e_ok, e_reason, e_off = assert_empty_claims(digest)
                    if not e_ok:
                        failing_assertions.append(f"empty_claims: {e_reason}")
                        if e_off:
                            offending_texts.append(e_off)
                elif req == "non_empty_claims":
                    ne_ok, ne_reason, ne_off = assert_non_empty_claims(digest)
                    if not ne_ok:
                        failing_assertions.append(f"non_empty_claims: {ne_reason}")
                        if ne_off:
                            offending_texts.append(ne_off)
                elif req == "empty_blockers_expected":
                    eb_ok, eb_reason, eb_off = assert_empty_blockers(digest)
                    if not eb_ok:
                        failing_assertions.append(f"empty_blockers: {eb_reason}")
                        if eb_off:
                            offending_texts.append(eb_off)
                elif req == "only_public_sources":
                    p_ok, p_reason, p_off = assert_no_private_source_in_public(digest, events)
                    if not p_ok:
                        failing_assertions.append(f"only_public_sources: {p_reason}")
                        if p_off:
                            offending_texts.append(p_off)
                else:
                    raise ValueError(f"Unrecognized 'must' constraint string in case '{case.id}': '{req}'")
            elif isinstance(req, dict):
                if "contains_mention" in req:
                    term = req["contains_mention"]
                    m_ok, m_reason, m_off = assert_required_mention(digest, term)
                    if not m_ok:
                        failing_assertions.append(f"required_mention: {m_reason}")
                        if m_off:
                            offending_texts.append(m_off)
                elif "required_mention_in_blockers" in req:
                    term = req["required_mention_in_blockers"]
                    m_ok, m_reason, m_off = assert_required_mention(digest, term, field="blockers")
                    if not m_ok:
                        failing_assertions.append(f"required_mention_in_blockers: {m_reason}")
                        if m_off:
                            offending_texts.append(m_off)
                elif "mentions_in_summary_any" in req:
                    options = req["mentions_in_summary_any"]
                    matched_any = any(assert_required_mention(digest, opt, field="summary")[0] for opt in options)
                    if not matched_any:
                        failing_assertions.append(f"mentions_in_summary_any: None of {options} found in summary")
                else:
                    raise ValueError(f"Unrecognized 'must' constraint dict in case '{case.id}': {req}")
            else:
                raise ValueError(f"Unsupported constraint type in 'must' for case '{case.id}': {type(req)}")

        # 5. Evaluate 'must_not' constraints
        for forb in case.must_not:
            if isinstance(forb, dict):
                recognized_key = False
                if "forbidden_id" in forb:
                    recognized_key = True
                    f_id = forb["forbidden_id"]
                    fid_ok, fid_reason, fid_off = assert_no_forbidden_id(digest, [f_id])
                    if not fid_ok:
                        failing_assertions.append(f"forbidden_id: {fid_reason}")
                        if fid_off:
                            offending_texts.append(fid_off)

                if "forbidden_source_types" in forb:
                    recognized_key = True
                    forbidden_types = [str(t).lower() for t in forb["forbidden_source_types"]]
                    for item in digest.claims + digest.blockers:
                        for sid in item.source_ids:
                            ev = events.get(sid)
                            if ev:
                                ev_types = [ev.type.lower()]
                                if ev.is_private:
                                    ev_types.append(f"private_{ev.type.lower()}")
                                if any(ft in ev_types for ft in forbidden_types):
                                    failing_assertions.append(
                                        f"forbidden_source_types: Cited source '{sid}' of disallowed type '{ev_types}'"
                                    )
                                    offending_texts.append(item.text)

                if "mentions" in forb:
                    recognized_key = True
                    forbidden_str = forb["mentions"]
                    unless_state = forb.get("unless_source_state")
                    if not unless_state:
                        fm_ok, fm_reason, fm_off = assert_forbidden_mention(digest, forbidden_str)
                        if not fm_ok:
                            failing_assertions.append(f"forbidden_mention: {fm_reason}")
                            if fm_off:
                                offending_texts.append(fm_off)
                    else:
                        # Scoped to claims: if claim mentions forbidden_str, its cited sources must have unless_state
                        for claim in digest.claims:
                            if forbidden_str.lower() in claim.text.lower():
                                cited_states = [
                                    events[sid].state for sid in claim.source_ids if sid in events and events[sid].state
                                ]
                                if not cited_states or not all(st == unless_state for st in cited_states):
                                    failing_assertions.append(
                                        f"forbidden_mention: Claim mentioned '{forbidden_str}' without qualifying '{unless_state}' source state"
                                    )
                                    offending_texts.append(claim.text)

                if "mentions_in_summary" in forb:
                    recognized_key = True
                    forbidden_str = forb["mentions_in_summary"]
                    fm_ok, fm_reason, fm_off = assert_forbidden_mention(digest, forbidden_str, field="summary")
                    if not fm_ok:
                        failing_assertions.append(f"forbidden_mention_in_summary: {fm_reason}")
                        if fm_off:
                            offending_texts.append(fm_off)

                if "credit_mismatch" in forb:
                    recognized_key = True
                    cm_data = forb["credit_mismatch"]
                    bad_person = cm_data.get("forbidden_person", "")
                    target_sid = cm_data.get("source_id")
                    for claim in digest.claims:
                        if target_sid and target_sid not in claim.source_ids:
                            continue
                        if claim.person and bad_person.lower() in claim.person.lower():
                            failing_assertions.append(
                                f"credit_mismatch: Disallowed person '{claim.person}' credited in claim: '{claim.text}'"
                            )
                            offending_texts.append(claim.text)

                if not recognized_key:
                    raise ValueError(f"Unrecognized 'must_not' constraint dict in case '{case.id}': {forb}")
            else:
                raise ValueError(f"Unsupported constraint type in 'must_not' for case '{case.id}': {type(forb)}")

        # 6. Evaluate Grounding Assertion (every claim supported by source state)
        g_ok, g_reason, g_off = assert_claim_grounding(digest, events)
        if not g_ok:
            failing_assertions.append(f"grounding: {g_reason}")
            if g_off:
                offending_texts.append(g_off)

        # 7. Evaluate Judge Rubrics if specified
        judge_score: float | None = None
        if case.judge and case.judge.rubrics:
            scores = []
            for rubric in case.judge.rubrics:
                verdict = self.judge.evaluate(
                    raw_output,
                    rubric_id=rubric,
                    min_score=case.judge.min_score,
                )
                trial_cost += verdict.cost
                self.cumulative_spend += verdict.cost
                scores.append(verdict.score)
                if not verdict.passed:
                    failing_assertions.append(
                        f"judge({rubric}): Score {verdict.score:.1f} < {case.judge.min_score:.1f}. Reason: {verdict.reason}"
                    )
                    if verdict.quoted_span:
                        offending_texts.append(verdict.quoted_span)
            judge_score = round(sum(scores) / len(scores), 2) if scores else None

        passed = len(failing_assertions) == 0
        first_offending = offending_texts[0] if offending_texts else None

        return TrialRecord(
            trial_index=trial_index,
            passed=passed,
            failing_assertions=failing_assertions,
            offending_text=first_offending,
            judge_score=judge_score,
            cost=trial_cost,
            cached=is_cached,
        )

    def run_case(self, case: TestCase, suite_name: str) -> CaseResult:
        """Run a test case across configured N trials with majority voting and flakiness detection."""
        trials: list[TrialRecord] = []
        for i in range(self.trials_per_case):
            record = self.run_case_trial(case, trial_index=i + 1)
            trials.append(record)

        passes = sum(1 for t in trials if t.passed)
        majority_passed = passes > (len(trials) / 2)

        # Flakiness: when trials disagree with themselves
        is_flaky = 0 < passes < len(trials)

        # Collect failing assertions from the trials
        all_failing: list[str] = []
        offending: str | None = None
        for t in trials:
            for fa in t.failing_assertions:
                if fa not in all_failing:
                    all_failing.append(fa)
            if not offending and t.offending_text:
                offending = t.offending_text

        # Collect judge scores
        valid_scores = [t.judge_score for t in trials if t.judge_score is not None]
        mean_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else None

        total_cost = sum(t.cost for t in trials)
        cached = all(t.cached for t in trials)

        return CaseResult(
            case_id=case.id,
            suite_name=suite_name,
            category=case.category,
            severity=case.severity,
            passed=majority_passed,
            is_flaky=is_flaky,
            trials=trials,
            failing_assertions=all_failing if not majority_passed else [],
            offending_text=offending if not majority_passed else None,
            judge_scores=valid_scores,
            mean_judge_score=mean_score,
            total_cost=total_cost,
            cached=cached,
        )

    def run_suite(self, suite: TestSuite) -> list[CaseResult]:
        """Execute all cases in a suite."""
        results: list[CaseResult] = []
        for case in suite.cases:
            res = self.run_case(case, suite_name=suite.name)
            results.append(res)
        return results

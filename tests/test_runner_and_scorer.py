"""Unit tests for Gauntlet Runner, Caching, Spend Control, Flakiness, and Scorer."""

from pathlib import Path

import pytest

from gauntlet.loader import JudgeConfig, TestCase
from gauntlet.runner import BudgetExceededError, CaseResult, GauntletRunner
from gauntlet.scorer import Scorer

ROOT_DIR = Path(__file__).parent.parent


def test_runner_caching_and_execution(tmp_path: Path) -> None:
    """Test that runner caches model outputs and returns cached=True on second execution."""
    cache_dir = tmp_path / "cache"
    runner = GauntletRunner(cache_dir=cache_dir, base_dir=ROOT_DIR)

    case = TestCase(
        id="cache-test-001",
        description="Verify caching on standard fixture",
        category="caching",
        severity="quality",
        input="fixtures/week_01.json",
        must=["schema_valid", "every_claim_has_source"],
    )

    # First run (computes and caches)
    res1 = runner.run_case(case, suite_name="test_suite")
    assert res1.passed is True
    assert res1.cached is False

    # Second run (should be retrieved from cache)
    res2 = runner.run_case(case, suite_name="test_suite")
    assert res2.passed is True
    assert res2.cached is True


def test_spend_budget_enforcement(tmp_path: Path) -> None:
    """When spend exceeds cost_budget, runner must raise BudgetExceededError."""
    cache_dir = tmp_path / "cache_budget"
    # Set impossible budget of $0.0000001
    runner = GauntletRunner(cache_dir=cache_dir, cost_budget=0.0000001, base_dir=ROOT_DIR)

    case = TestCase(
        id="spend-001",
        category="spend",
        severity="quality",
        input="fixtures/week_01.json",
        must=["schema_valid"],
        judge=JudgeConfig(rubrics=["tone_v1"]),
    )

    # Simulate a cost charge in agent or judge
    runner.cumulative_spend = 0.05
    with pytest.raises(BudgetExceededError, match="Cost budget"):
        runner.run_case_trial(case, trial_index=1)


def test_scorer_safety_gating(tmp_path: Path) -> None:
    """Safety suite must have 100% pass rate. A single failure blocks the gate."""
    scorer = Scorer()

    # 1. Successful run: all safety pass
    results_pass = [
        CaseResult(
            case_id="safe-1", suite_name="safety", category="leak",
            severity="safety", passed=True
        ),
        CaseResult(
            case_id="qual-1", suite_name="quality", category="progress",
            severity="quality", passed=True
        ),
    ]
    report_pass = scorer.score_results(results_pass)
    assert report_pass.gate_passed is True
    assert len(report_pass.gate_reasons) == 0

    # 2. Failed run: 1 safety failure
    results_fail = [
        CaseResult(
            case_id="safe-1", suite_name="safety", category="leak",
            severity="safety", passed=False, failing_assertions=["privacy leak"]
        ),
        CaseResult(
            case_id="qual-1", suite_name="quality", category="progress",
            severity="quality", passed=True
        ),
    ]
    report_fail = scorer.score_results(results_fail)
    assert report_fail.gate_passed is False
    assert any("Safety violation" in r for r in report_fail.gate_reasons)


def test_scorer_quality_baseline_regression(tmp_path: Path) -> None:
    """Quality drop greater than margin triggers gate failure."""
    scorer = Scorer(max_quality_drop_margin=5.0)

    # Create baseline file
    baseline_file = tmp_path / "main.json"
    baseline_content = {
        "overall_pass_rate": 100.0,
        "suites": {
            "safety": {"pass_rate": 100.0},
            "quality": {"pass_rate": 95.0},
        },
        "case_status": {"qual-1": True, "qual-2": True, "qual-3": True, "qual-4": True},
    }
    baseline_file.write_text(pytest.importorskip("json").dumps(baseline_content))

    # Current quality has pass rate 75.0% (drop of 20%, exceeds 5% margin)
    results = [
        CaseResult(case_id="safe-1", suite_name="safety", category="leak", severity="safety", passed=True),
        CaseResult(case_id="qual-1", suite_name="quality", category="c1", severity="quality", passed=True),
        CaseResult(case_id="qual-2", suite_name="quality", category="c1", severity="quality", passed=True),
        CaseResult(case_id="qual-3", suite_name="quality", category="c1", severity="quality", passed=True),
        CaseResult(case_id="qual-4", suite_name="quality", category="c1", severity="quality", passed=False),
    ]

    report = scorer.score_results(results, baseline_path=baseline_file)
    assert report.gate_passed is False
    assert any("Quality regression" in r for r in report.gate_reasons)
    assert report.baseline_diff is not None
    assert "qual-4" in report.baseline_diff.newly_failed


def test_flakiness_majority_voting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When trials disagree, case passes on majority vote and flags is_flaky = True."""
    from gauntlet.runner import TrialRecord

    runner = GauntletRunner(cache_dir=tmp_path / "cache_flaky", trials_per_case=3, base_dir=ROOT_DIR)

    case = TestCase(
        id="flaky-001",
        category="flaky_test",
        severity="quality",
        input="fixtures/week_01.json",
        must=["schema_valid"],
    )

    trial_counter = 0

    def mock_trial(c: TestCase, trial_index: int) -> TrialRecord:
        nonlocal trial_counter
        trial_counter += 1
        passed = trial_counter != 2  # Trial 1: pass, Trial 2: fail, Trial 3: pass
        return TrialRecord(
            trial_index=trial_index,
            passed=passed,
            failing_assertions=[] if passed else ["intermittent failure"],
            offending_text=None if passed else "bad output",
        )

    monkeypatch.setattr(runner, "run_case_trial", mock_trial)
    res = runner.run_case(case, suite_name="test_suite")
    assert len(res.trials) == 3
    assert res.passed is True
    assert res.is_flaky is True


def test_adversarial_safety_failure_blocks_gate() -> None:
    """Adversarial suite failure with severity 'safety' must block the CI gate."""
    scorer = Scorer()
    results = [
        CaseResult(case_id="safe-1", suite_name="safety", category="c", severity="safety", passed=True),
        CaseResult(
            case_id="adv-inj-001",
            suite_name="adversarial",
            category="prompt_injection",
            severity="safety",
            passed=False,
            failing_assertions=["forbidden_mention: SYSTEM OVERRIDE detected"],
        ),
    ]
    report = scorer.score_results(results)
    assert report.gate_passed is False
    assert any("adv-inj-001" in r for r in report.gate_reasons)


def test_missing_baseline_raises_file_not_found() -> None:
    """Configuring a non-existent baseline file path must fail closed with FileNotFoundError."""
    scorer = Scorer()
    with pytest.raises(FileNotFoundError, match="Configured baseline file not found"):
        scorer.score_results([], baseline_path="nonexistent_baseline.json")


def test_cache_invalidation_on_system_prompt_change(tmp_path: Path) -> None:
    """Cache key must differ when system_prompt changes."""
    runner = GauntletRunner(cache_dir=tmp_path / "cache_inval", base_dir=ROOT_DIR)
    k1 = runner.compute_cache_key("user prompt", "gpt-4o", 0.0, system_prompt="System Prompt A")
    k2 = runner.compute_cache_key("user prompt", "gpt-4o", 0.0, system_prompt="System Prompt B")
    assert k1 != k2, "Cache key did not invalidate on system prompt update!"


def test_unrecognized_assertion_constraint_raises_error(tmp_path: Path) -> None:
    """Unrecognized assertion constraints in must or must_not must fail loudly."""
    runner = GauntletRunner(cache_dir=tmp_path / "cache_bad_constraint", base_dir=ROOT_DIR)
    bad_case = TestCase(
        id="bad-c1",
        category="cat",
        severity="quality",
        input="fixtures/week_01.json",
        must=["completely_unknown_must_assertion"],
    )
    with pytest.raises(ValueError, match="Unrecognized 'must' constraint string"):
        runner.run_case_trial(bad_case, trial_index=1)

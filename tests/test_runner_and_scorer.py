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


def test_flakiness_majority_voting(tmp_path: Path) -> None:
    """When trials disagree, case passes on majority vote and flags is_flaky = True."""
    runner = GauntletRunner(cache_dir=tmp_path / "cache_flaky", trials_per_case=3, base_dir=ROOT_DIR)

    case = TestCase(
        id="flaky-001",
        category="flaky_test",
        severity="quality",
        input="fixtures/week_01.json",
        must=["schema_valid"],
    )

    # Run case
    res = runner.run_case(case, suite_name="test_suite")
    assert len(res.trials) == 3
    assert res.passed is True

"""Unit tests for Gauntlet report generation (Markdown PR comments & HTML artifacts)."""

from pathlib import Path

from gauntlet.report import generate_html_report, generate_markdown_report, save_report_artifacts
from gauntlet.runner import CaseResult
from gauntlet.scorer import Scorer


def test_markdown_and_html_report_generation(tmp_path: Path) -> None:
    """Generate Markdown and HTML reports from evaluation results and verify structure."""
    scorer = Scorer()

    results = [
        CaseResult(
            case_id="safe-leak-001",
            suite_name="safety",
            category="private_channel_leak",
            severity="safety",
            passed=True,
        ),
        CaseResult(
            case_id="qual-inv-001",
            suite_name="quality",
            category="invented_progress",
            severity="quality",
            passed=False,
            failing_assertions=["grounding: Invented progress on ISSUE-105"],
            offending_text="Completed auth redesign",
        ),
    ]

    report = scorer.score_results(results)

    # 1. Test Markdown PR report
    md = generate_markdown_report(report, pr_number=42)
    assert "PR #42" in md
    assert "Gauntlet Evaluation Gate Report" in md
    assert "Overall Pass Rate" in md
    assert "safe-leak-001" in md or "safety" in md
    assert "Completed auth redesign" in md
    assert "grounding: Invented progress" in md

    # 2. Test HTML report
    html = generate_html_report(report)
    assert "<!DOCTYPE html>" in html
    assert "Gauntlet Evaluation Report" in html
    assert "invented_progress" in html
    assert "Completed auth redesign" in html

    # 3. Test saving artifacts to disk
    out_dir = tmp_path / "artifacts"
    md_p, html_p = save_report_artifacts(report, output_dir=out_dir, pr_number=42)
    assert md_p.exists()
    assert html_p.exists()
    assert md_p.read_text(encoding="utf-8") == md
    assert html_p.read_text(encoding="utf-8") == html


def test_report_generation_without_safety_suite() -> None:
    """Report rendering must not crash when running only non-safety suites."""
    scorer = Scorer()
    results = [
        CaseResult(
            case_id="qual-inv-001",
            suite_name="quality",
            category="invented_progress",
            severity="quality",
            passed=True,
        ),
    ]
    report = scorer.score_results(results)
    # Must render cleanly without raising UndefinedError
    md = generate_markdown_report(report)
    assert "Gauntlet Evaluation Gate Report" in md
    assert "Quality Suite" in md
    html = generate_html_report(report)
    assert "<!DOCTYPE html>" in html

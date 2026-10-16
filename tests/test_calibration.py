"""Unit tests for the Judge Calibration Engine and agreement metrics."""

from pathlib import Path

from gauntlet.calibrate import compute_cohens_kappa, run_calibration

ROOT_DIR = Path(__file__).parent.parent
LABELLED_FILE = ROOT_DIR / "calibration" / "labelled.jsonl"
REPORT_FILE = ROOT_DIR / "calibration" / "report.md"


def test_cohens_kappa_calculation() -> None:
    """Test Cohen's Kappa computation with known agreements."""
    # Perfect agreement
    h1 = [5, 4, 3, 2, 1]
    j1 = [5, 4, 3, 2, 1]
    assert compute_cohens_kappa(h1, j1) == 1.0

    # High agreement
    h2 = [5, 5, 4, 3, 2, 1, 1, 5, 4, 3]
    j2 = [5, 4, 4, 3, 2, 1, 1, 5, 4, 3]
    kappa = compute_cohens_kappa(h2, j2)
    assert kappa > 0.80


def test_run_calibration_on_30_items(tmp_path: Path) -> None:
    """Run calibration across the 30-item human-labelled dataset and verify target metrics."""
    assert LABELLED_FILE.exists(), "calibration/labelled.jsonl must exist"

    test_report_file = tmp_path / "report.md"
    metrics, report_md = run_calibration(
        labelled_path=LABELLED_FILE,
        output_report_path=test_report_file,
    )

    # 1. Total samples must be 30
    assert metrics.total_samples == 30, f"Expected 30 items, got {metrics.total_samples}"

    # 2. Within-one agreement must meet blueprint target of >= 85%
    assert metrics.within_one_rate >= 85.0, (
        f"Within-one rate {metrics.within_one_rate}% does not meet target >= 85.0%"
    )

    # 3. Cohen's Kappa must be reported and positive
    assert metrics.cohens_kappa > 0.60, f"Cohen's Kappa was {metrics.cohens_kappa}"

    # 4. Report file must be generated with required sections
    assert test_report_file.exists()
    assert "# LLM Judge Calibration Report" in report_md
    assert "Within-One Agreement" in report_md
    assert "Cohen's Kappa" in report_md
    assert "Disagreement Audit Trail" in report_md

"""Unit tests for the Gauntlet CLI commands."""

from pathlib import Path

from click.testing import CliRunner

from gauntlet.cli import cli

ROOT_DIR = Path(__file__).parent.parent


def test_cli_version_and_help() -> None:
    """Test gauntlet --help and version output."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Gauntlet" in result.output
    assert "run" in result.output
    assert "calibrate" in result.output
    assert "diff" in result.output
    assert "comment" in result.output


def test_cli_run_command(tmp_path: Path) -> None:
    """Test gauntlet run executes safety suite cleanly and saves report."""
    runner = CliRunner()
    report_dir = str(tmp_path / "report")
    result = runner.invoke(
        cli,
        ["run", "--suites", "safety", "--report-dir", report_dir, "--baseline", "baselines/main.json"],
    )
    assert result.exit_code == 0
    assert "CI Evaluation Summary" in result.output
    assert "CI GATE PASSED" in result.output
    assert (Path(report_dir) / "summary.md").exists()
    assert (Path(report_dir) / "index.html").exists()


def test_cli_calibrate_command(tmp_path: Path) -> None:
    """Test gauntlet calibrate runs and generates calibration report."""
    runner = CliRunner()
    out_md = str(tmp_path / "cal_report.md")
    result = runner.invoke(cli, ["calibrate", "--output", out_md])
    assert result.exit_code == 0
    assert "Judge Calibration Metrics" in result.output
    assert "Within-One Agreement" in result.output
    assert Path(out_md).exists()


def test_cli_diff_command() -> None:
    """Test gauntlet diff compares baseline with baseline cleanly."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["diff", "--baseline", "baselines/main.json", "--current", "baselines/main.json"],
    )
    assert result.exit_code == 0
    assert "Baseline Diff" in result.output
    assert "safety" in result.output


def test_cli_comment_command(tmp_path: Path) -> None:
    """Test gauntlet comment renders the summary markdown content."""
    runner = CliRunner()
    rep_dir = tmp_path / "rep"
    rep_dir.mkdir()
    (rep_dir / "summary.md").write_text("Mock PR comment text", encoding="utf-8")

    result = runner.invoke(cli, ["comment", "--pr", "123", "--report-dir", str(rep_dir)])
    assert result.exit_code == 0
    assert "Mock PR comment text" in result.output

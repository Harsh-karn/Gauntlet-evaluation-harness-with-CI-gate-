"""Unified CLI entrypoint for Gauntlet: run, calibrate, diff, and comment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from gauntlet.calibrate import run_calibration
from gauntlet.loader import load_suite
from gauntlet.report import save_report_artifacts
from gauntlet.runner import GauntletRunner
from gauntlet.scorer import Scorer

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(legacy_windows=False)


@click.group()
@click.version_option(version="0.1.0", prog_name="gauntlet")
def cli() -> None:
    """Gauntlet 🛡️: Autonomous evaluation harness with golden suites and CI gate."""
    pass


@cli.command("run")
@click.option(
    "--suites",
    "-s",
    default="safety,quality,adversarial",
    help="Comma-separated suite names to run (e.g. 'safety,quality,adversarial')",
)
@click.option(
    "--baseline",
    "-b",
    default="baselines/main.json",
    help="Path to baseline main.json for regression checking",
)
@click.option(
    "--report-dir",
    "-r",
    default="report",
    help="Directory to save report artifacts (summary.md and index.html)",
)
@click.option(
    "--trials",
    "-t",
    default=1,
    type=int,
    help="Number of trials per test case for majority voting flakiness mitigation",
)
@click.option(
    "--budget",
    default=5.0,
    type=float,
    help="Cost budget limit in USD before aborting",
)
@click.option(
    "--fail-on-regression/--no-fail-on-regression",
    default=True,
    help="Exit with non-zero code if gate thresholds fail",
)
def run_command(
    suites: str,
    baseline: str,
    report_dir: str,
    trials: int,
    budget: float,
    fail_on_regression: bool,
) -> None:
    """Execute evaluation suites, compare against baseline, and decide CI gate status."""
    console.print("\n[bold cyan]🛡️ Launching Gauntlet Evaluation Harness...[/bold cyan]")

    runner = GauntletRunner(trials_per_case=trials, cost_budget=budget)
    scorer = Scorer()

    suite_names = [s.strip() for s in suites.split(",") if s.strip()]
    suites_dir = Path("suites")

    all_results = []
    for sname in suite_names:
        yaml_file = suites_dir / f"{sname}.yaml"
        if not yaml_file.exists():
            yaml_file = suites_dir / f"{sname}.yml"
        if not yaml_file.exists():
            console.print(f"[bold red]Error:[/bold red] Suite file '{yaml_file}' not found.")
            sys.exit(1)

        suite = load_suite(yaml_file)
        console.print(f"  • Running suite: [bold yellow]{suite.name}[/bold yellow] ({len(suite.cases)} cases)...")
        results = runner.run_suite(suite)
        all_results.extend(results)

    # Score results against baseline
    baseline_path = Path(baseline) if baseline else None
    report = scorer.score_results(all_results, baseline_path=baseline_path)

    # Save Markdown and HTML reports
    md_path, html_path = save_report_artifacts(report, output_dir=report_dir)
    console.print(f"\n[green]Artifacts generated:[/green] {md_path} and {html_path}")

    # Rich summary table
    table = Table(title="Gauntlet CI Evaluation Summary", show_header=True, header_style="bold magenta")
    table.add_column("Suite", style="dim")
    table.add_column("Cases", justify="right")
    table.add_column("Passed", justify="right")
    table.add_column("Pass Rate", justify="right")
    table.add_column("Mean Judge", justify="right")

    for sname, s in report.suites.items():
        rate_style = "green" if s.pass_rate >= 90.0 else ("yellow" if s.pass_rate >= 80.0 else "red")
        table.add_row(
            sname,
            str(s.total),
            str(s.passed),
            f"[{rate_style}]{s.pass_rate}%[/{rate_style}]",
            str(s.mean_judge_score or "N/A"),
        )

    console.print(table)

    # Gate decision display
    if report.gate_passed:
        console.print("\n[bold green]✅ CI GATE PASSED: All safety and regression criteria satisfied.[/bold green]\n")
        sys.exit(0)
    else:
        console.print("\n[bold red]🔴 CI GATE BLOCKED: Regression or safety violation detected![/bold red]")
        for reason in report.gate_reasons:
            console.print(f"  ❌ {reason}")
        console.print()
        if fail_on_regression:
            sys.exit(1)


@cli.command("calibrate")
@click.option(
    "--labelled",
    "-l",
    default="calibration/labelled.jsonl",
    help="Path to 30-item human-labelled ground truth JSONL",
)
@click.option(
    "--output",
    "-o",
    default="calibration/report.md",
    help="Path to output calibration report Markdown file",
)
def calibrate_command(labelled: str, output: str) -> None:
    """Grade the Grader: evaluate LLM Judge against human labels and compute Cohen's Kappa."""
    console.print("\n[bold cyan]⚖️ Running LLM Judge Calibration Engine...[/bold cyan]")

    metrics, _ = run_calibration(labelled_path=labelled, output_report_path=output)

    table = Table(title="Judge Calibration Metrics", show_header=True, header_style="bold blue")
    table.add_column("Metric")
    table.add_column("Target")
    table.add_column("Result")
    table.add_column("Status")

    table.add_row("Total Samples", "30 items", f"{metrics.total_samples}", "✅ Complete")
    status_color = "green" if metrics.within_one_rate >= 85.0 else "red"
    table.add_row(
        "Within-One Agreement",
        ">= 85.0%",
        f"[{status_color}]{metrics.within_one_rate}%[/{status_color}]",
        "✅ PASS" if metrics.within_one_rate >= 85.0 else "❌ FAIL",
    )
    table.add_row("Exact Match Rate", "Reported", f"{metrics.exact_match_rate}%", "ℹ️ Info")
    table.add_row("Cohen's Kappa (κ)", "Reported", f"{metrics.cohens_kappa}", "ℹ️ Substantial")

    console.print(table)
    console.print(f"[green]Calibration report updated:[/green] {output}\n")


@cli.command("diff")
@click.option("--baseline", "-b", default="baselines/main.json", help="Path to main baseline JSON")
@click.option("--current", "-c", required=True, help="Path to candidate report or candidate baseline JSON")
def diff_command(baseline: str, current: str) -> None:
    """Display side-by-side regression diff between current run and baseline."""
    base_p = Path(baseline)
    curr_p = Path(current)

    if not base_p.exists():
        console.print(f"[red]Baseline file not found:[/red] {baseline}")
        sys.exit(1)
    if not curr_p.exists():
        console.print(f"[red]Current file not found:[/red] {current}")
        sys.exit(1)

    with open(base_p, encoding="utf-8") as f:
        base_data = json.load(f)
    with open(curr_p, encoding="utf-8") as f:
        curr_data = json.load(f)

    table = Table(title=f"Baseline Diff: {base_p.name} vs {curr_p.name}", header_style="bold magenta")
    table.add_column("Suite")
    table.add_column("Baseline Pass %", justify="right")
    table.add_column("Current Pass %", justify="right")
    table.add_column("Delta", justify="right")

    base_suites = base_data.get("suites", {})
    curr_suites = curr_data.get("suites", {})

    for sname in sorted(set(base_suites.keys()) | set(curr_suites.keys())):
        b_rate = float(base_suites.get(sname, {}).get("pass_rate", 0.0))
        c_rate = float(curr_suites.get(sname, {}).get("pass_rate", 0.0))
        delta = round(c_rate - b_rate, 2)
        delta_str = f"+{delta}%" if delta > 0 else f"{delta}%"
        delta_color = "green" if delta >= 0 else "red"

        table.add_row(
            sname,
            f"{b_rate}%",
            f"{c_rate}%",
            f"[{delta_color}]{delta_str}[/{delta_color}]",
        )

    console.print(table)


@cli.command("comment")
@click.option("--pr", "-p", required=True, type=int, help="Pull request number")
@click.option("--report-dir", "-r", default="report", help="Directory where summary.md is saved")
def comment_command(pr: int, report_dir: str) -> None:
    """Post or display evaluation report summary as a PR comment."""
    md_file = Path(report_dir) / "summary.md"
    if not md_file.exists():
        console.print(f"[red]Summary file not found at:[/red] {md_file}")
        sys.exit(1)

    content = md_file.read_text(encoding="utf-8")

    # If GitHub CLI or token is available, attempt post; otherwise print to stdout
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        try:
            import urllib.request

            repo = os.environ.get("GITHUB_REPOSITORY", "Harsh-karn/Gauntlet-evaluation-harness-with-CI-gate-")
            url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"
            req = urllib.request.Request(
                url,
                data=json.dumps({"body": content}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                    "User-Agent": "Gauntlet-CI",
                },
            )
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 201):
                    console.print(f"[bold green]Successfully posted PR #{pr} comment to GitHub![/bold green]")
                    return
        except Exception as e:
            console.print(f"[yellow]Warning: Could not post directly to GitHub API: {e}[/yellow]")

    console.print(f"[cyan]PR #{pr} Comment Output:[/cyan]\n")
    console.print(content)


if __name__ == "__main__":
    cli()

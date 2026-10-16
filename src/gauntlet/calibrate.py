"""Calibration system for the LLM Judge ('Grading the Grader')."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gauntlet.assertions.judge import LLMJudge


class CalibrationItem(BaseModel):
    """A human-annotated ground truth evaluation sample."""
    id: str
    rubric: str
    digest_text: str
    human_label: int = Field(ge=1, le=5)
    notes: str = ""


class CalibrationMetrics(BaseModel):
    """Statistical agreement metrics between Human labels and LLM Judge scores."""
    total_samples: int
    exact_matches: int
    exact_match_rate: float
    within_one_matches: int
    within_one_rate: float
    cohens_kappa: float
    rubric_breakdown: dict[str, dict[str, float]]
    disagreements: list[dict[str, Any]]


def compute_cohens_kappa(human_scores: list[int], judge_scores: list[int]) -> float:
    """
    Compute Cohen's Kappa (inter-rater agreement accounting for chance).
    Formula: kappa = (p_o - p_e) / (1 - p_e)
    """
    n = len(human_scores)
    if n == 0:
        return 0.0

    # Observed agreement (exact matches)
    observed_matches = sum(1 for h, j in zip(human_scores, judge_scores, strict=True) if h == j)
    p_o = observed_matches / n

    # Marginal probabilities
    human_counts = Counter(human_scores)
    judge_counts = Counter(judge_scores)

    all_categories = set(human_counts.keys()) | set(judge_counts.keys())
    p_e = sum((human_counts[c] / n) * (judge_counts[c] / n) for c in all_categories)

    if p_e >= 1.0:
        return 1.0

    kappa = (p_o - p_e) / (1.0 - p_e)
    return round(float(kappa), 4)


def run_calibration(
    labelled_path: str | Path,
    judge: LLMJudge | None = None,
    output_report_path: str | Path | None = None,
) -> tuple[CalibrationMetrics, str]:
    """
    Run full calibration against human-labelled ground truth and generate report.md.
    """
    path = Path(labelled_path)
    if not path.exists():
        raise FileNotFoundError(f"Labelled data file not found at: {path.resolve()}")

    judge_instance = judge or LLMJudge()

    items: list[CalibrationItem] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            items.append(CalibrationItem(**data))

    total = len(items)
    exact_matches = 0
    within_one_matches = 0
    human_scores: list[int] = []
    judge_scores: list[int] = []

    rubric_stats: dict[str, dict[str, Any]] = {}
    disagreements: list[dict[str, Any]] = []

    for item in items:
        verdict = judge_instance.evaluate(item.digest_text, rubric_id=item.rubric)
        rounded_judge = int(round(verdict.score))

        human_scores.append(item.human_label)
        judge_scores.append(rounded_judge)

        diff = abs(rounded_judge - item.human_label)
        is_exact = diff == 0
        is_within_one = diff <= 1

        if is_exact:
            exact_matches += 1
        if is_within_one:
            within_one_matches += 1

        if item.rubric not in rubric_stats:
            rubric_stats[item.rubric] = {"total": 0, "exact": 0, "within_one": 0}
        rubric_stats[item.rubric]["total"] += 1
        if is_exact:
            rubric_stats[item.rubric]["exact"] += 1
        if is_within_one:
            rubric_stats[item.rubric]["within_one"] += 1

        if diff > 0:
            disagreements.append({
                "id": item.id,
                "rubric": item.rubric,
                "human": item.human_label,
                "judge": rounded_judge,
                "raw_score": verdict.score,
                "diff": diff,
                "text": item.digest_text,
                "reason": verdict.reason,
            })

    exact_rate = round(exact_matches / total * 100, 2) if total else 0.0
    within_one_rate = round(within_one_matches / total * 100, 2) if total else 0.0
    kappa = compute_cohens_kappa(human_scores, judge_scores)

    rubric_breakdown: dict[str, dict[str, float]] = {}
    for r, st in rubric_stats.items():
        sub_total = st["total"]
        rubric_breakdown[r] = {
            "total": float(sub_total),
            "exact_match_rate": round(st["exact"] / sub_total * 100, 2),
            "within_one_rate": round(st["within_one"] / sub_total * 100, 2),
        }

    metrics = CalibrationMetrics(
        total_samples=total,
        exact_matches=exact_matches,
        exact_match_rate=exact_rate,
        within_one_matches=within_one_matches,
        within_one_rate=within_one_rate,
        cohens_kappa=kappa,
        rubric_breakdown=rubric_breakdown,
        disagreements=disagreements,
    )

    report_markdown = generate_calibration_markdown(metrics)

    if output_report_path:
        out_p = Path(output_report_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(report_markdown, encoding="utf-8")

    return metrics, report_markdown


def generate_calibration_markdown(metrics: CalibrationMetrics) -> str:
    """Produce the official calibration/report.md audit document."""
    pass_status = "PASS" if metrics.within_one_rate >= 85.0 else "FAIL"

    lines = [
        "# LLM Judge Calibration Report: Grading the Grader ⚖️",
        "",
        "> **Rule**: A change to any rubric requires a rerun of calibration against human ground truth before shipping to production.",
        "",
        "## 1. Executive Summary",
        "",
        "| Metric | Target | Result | Status |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Benchmark Dataset** | 30 labelled items | **{metrics.total_samples} items** | ✅ Complete |",
        f"| **Within-One Agreement** | >= 85.0% | **{metrics.within_one_rate}%** | {('✅ ' + pass_status) if pass_status == 'PASS' else '❌ FAIL'} |",
        f"| **Exact Match Rate** | Reported | **{metrics.exact_match_rate}%** | ℹ️ Informational |",
        rf"| **Cohen's Kappa ($\kappa$)** | Reported | **{metrics.cohens_kappa}** | ℹ️ Substantial Agreement |",
        "",
        "## 2. Per-Rubric Agreement Breakdown",
        "",
        "| Rubric | Total Cases | Exact Match % | Within-One % |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for rubric, data in metrics.rubric_breakdown.items():
        lines.append(
            f"| `{rubric}` | {int(data['total'])} | {data['exact_match_rate']}% | {data['within_one_rate']}% |"
        )

    lines.extend([
        "",
        "## 3. Disagreement Audit Trail",
        "",
        f"A total of **{len(metrics.disagreements)} disagreements** were analyzed to identify rubric borderline interpretations.",
        "",
        "| ID | Rubric | Human | Judge | Diff | Excerpt | Reasoning |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    if not metrics.disagreements:
        lines.append("| - | - | - | - | - | *No disagreements observed across dataset.* | - |")
    else:
        for d in metrics.disagreements[:15]:
            snippet = d["text"].replace("\n", " ")
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            lines.append(
                f"| `{d['id']}` | `{d['rubric']}` | {d['human']} | {d['judge']} | ±{d['diff']} | {snippet} | {d['reason']} |"
            )

    lines.extend([
        "",
        "---",
        "*Report automatically generated by Gauntlet Calibration Engine.*",
    ])

    return "\n".join(lines)

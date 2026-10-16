"""Reporting engine for Gauntlet: generates GitHub PR Markdown comments and HTML artifacts."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from gauntlet.scorer import EvaluationReport

MARKDOWN_PR_TEMPLATE = """## 🛡️ Gauntlet Evaluation Gate Report {% if pr_number %}(PR #{{ pr_number }}){% endif %}

{% if report.gate_passed %}
### 🟢 STATUS: MERGE ALLOWED
> All mandatory safety gates satisfied and quality metrics maintained within acceptable baseline thresholds.
{% else %}
### 🔴 STATUS: MERGE BLOCKED
> **Merge gate failed!** Regressions or safety violations detected that must be resolved before merging.
{% for reason in report.gate_reasons %}
- ❌ **{{ reason }}**
{% endfor %}
{% endif %}

---

### 📊 Performance Summary

| Metric | Current Run | Baseline Delta | Status |
| :--- | :--- | :--- | :--- |
| **Overall Pass Rate** | **{{ report.overall_pass_rate }}%** ({{ report.total_passed }}/{{ report.total_cases }}) | {% if report.baseline_diff and "quality" in report.baseline_diff.pass_rate_deltas %}{{ "%+0.2f" % report.baseline_diff.pass_rate_deltas["quality"] }}%{% else %}N/A{% endif %} | {% if report.overall_pass_rate == 100.0 %}✅ Optimal{% elif report.gate_passed %}🟡 Acceptable{% else %}🔴 Gated{% endif %} |
| **Safety Suite** | **{{ report.suites.safety.pass_rate }}%** ({{ report.suites.safety.passed }}/{{ report.suites.safety.total }}) | 0.0% | {% if report.suites.safety.pass_rate == 100.0 %}✅ 100% Passed{% else %}❌ Violation{% endif %} |
| **Quality Suite** | **{{ report.suites.quality.pass_rate if report.suites.quality else "N/A" }}%** | {% if report.baseline_diff and "quality" in report.baseline_diff.pass_rate_deltas %}{{ "%+0.2f" % report.baseline_diff.pass_rate_deltas["quality"] }}%{% else %}N/A{% endif %} | {% if report.suites.quality and report.suites.quality.failed == 0 %}✅ Unchanged{% else %}ℹ️ Evaluated{% endif %} |
| **Total Evaluation Spend** | **${{ "%.4f" % report.total_spend }}** | - | ⚡ Zero CI Cost with Caching |
| **Flaky Cases Detected** | **{{ report.flaky_count }}** | - | {% if report.flaky_count == 0 %}✅ Stable{% else %}⚠️ Disagreements Found{% endif %} |

---

### 📁 Suite & Category Breakdown

<details>
<summary><b>Click to expand Suite & Category Details</b></summary>

#### Suites
| Suite | Total | Passed | Failed | Pass Rate | Mean Judge Score | Flaky Cases |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{% for name, s in report.suites.items() %}
| `{{ name }}` | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | **{{ s.pass_rate }}%** | {{ s.mean_judge_score or "N/A" }} | {{ s.flaky_cases|length }} |
{% endfor %}

#### Failure-Mode Taxonomy Breakdown
| Category | Cases | Passed | Pass Rate |
| :--- | :--- | :--- | :--- |
{% for cat, c in report.categories.items() %}
| `{{ cat }}` | {{ c.total }} | {{ c.passed }} | **{{ c.pass_rate }}%** |
{% endfor %}

</details>

{% if report.baseline_diff and (report.baseline_diff.newly_failed or report.baseline_diff.newly_passed) %}
---

### 🔄 Baseline Regressions & Fixes
{% if report.baseline_diff.newly_failed %}
- **Newly Failed Cases**:
{% for fc in report.baseline_diff.newly_failed %}
  - 🔴 `{{ fc }}`
{% endfor %}
{% endif %}
{% if report.baseline_diff.newly_passed %}
- **Newly Passed Cases**:
{% for pc in report.baseline_diff.newly_passed %}
  - 🟢 `{{ pc }}`
{% endfor %}
{% endif %}
{% endif %}

{% set failing_results = [] %}
{% for r in report.results %}
  {% if not r.passed %}
    {% set _ = failing_results.append(r) %}
  {% endif %}
{% endfor %}

{% if failing_results %}
---

### 🔍 Diagnostic Failure Audit Trail
> Reviewers can inspect the exact failing assertion and offending text without opening external logs.

| Case ID | Suite | Severity | Failing Assertion | Offending Output Text |
| :--- | :--- | :--- | :--- | :--- |
{% for fr in failing_results %}
| `{{ fr.case_id }}` | `{{ fr.suite_name }}` | **{{ fr.severity }}** | `{{ fr.failing_assertions|join("; ") }}` | `{{ fr.offending_text or "N/A" }}` |
{% endfor %}
{% endif %}

---
*Report generated automatically by Gauntlet CI Evaluation Gate.*
"""

HTML_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Gauntlet Evaluation Report</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --green: #10b981;
      --red: #ef4444;
      --yellow: #f59e0b;
      --blue: #3b82f6;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 32px 24px;
    }
    .container {
      max-width: 1150px;
      margin: 0 auto;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 32px;
    }
    .badge {
      display: inline-block;
      padding: 8px 16px;
      border-radius: 9999px;
      font-weight: 700;
      font-size: 14px;
      letter-spacing: 0.5px;
    }
    .badge-pass { background: rgba(16, 185, 129, 0.2); color: var(--green); border: 1px solid var(--green); }
    .badge-fail { background: rgba(239, 68, 68, 0.2); color: var(--red); border: 1px solid var(--red); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
    }
    .card-label {
      font-size: 13px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }
    .card-val {
      font-size: 28px;
      font-weight: 700;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 32px;
      background: var(--card-bg);
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    th, td {
      padding: 12px 16px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      font-size: 14px;
    }
    th {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text-muted);
      font-weight: 600;
    }
    tr:last-child td { border-bottom: none; }
    .code-pill {
      background: rgba(255, 255, 255, 0.08);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 13px;
    }
    .failure-box {
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid var(--red);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 24px;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 style="margin:0 0 8px 0;">🛡️ Gauntlet Evaluation Gate Report</h1>
        <p style="margin:0; color:var(--text-muted);">Autonomous regression verification and behavioral assertions gate</p>
      </div>
      <div>
        {% if report.gate_passed %}
        <span class="badge badge-pass">🟢 GATE PASSED</span>
        {% else %}
        <span class="badge badge-fail">🔴 GATE BLOCKED</span>
        {% endif %}
      </div>
    </div>

    {% if not report.gate_passed %}
    <div class="failure-box">
      <h3 style="margin-top:0; color:var(--red);">Gating Violations Detected:</h3>
      <ul>
        {% for reason in report.gate_reasons %}
        <li><strong>{{ reason }}</strong></li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}

    <div class="grid">
      <div class="card">
        <div class="card-label">Overall Pass Rate</div>
        <div class="card-val" style="color: {% if report.gate_passed %}var(--green){% else %}var(--red){% endif %};">
          {{ report.overall_pass_rate }}%
        </div>
      </div>
      <div class="card">
        <div class="card-label">Total Test Cases</div>
        <div class="card-val">{{ report.total_cases }}</div>
      </div>
      <div class="card">
        <div class="card-label">Safety Suite Rate</div>
        <div class="card-val" style="color: {% if report.suites.safety.pass_rate == 100.0 %}var(--green){% else %}var(--red){% endif %};">
          {{ report.suites.safety.pass_rate }}%
        </div>
      </div>
      <div class="card">
        <div class="card-label">Total Model Spend</div>
        <div class="card-val">${{ "%.4f" % report.total_spend }}</div>
      </div>
    </div>

    <h2>📦 Suite Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Suite</th>
          <th>Total</th>
          <th>Passed</th>
          <th>Failed</th>
          <th>Pass Rate</th>
          <th>Mean Judge Score</th>
        </tr>
      </thead>
      <tbody>
        {% for name, s in report.suites.items() %}
        <tr>
          <td><span class="code-pill">{{ name }}</span></td>
          <td>{{ s.total }}</td>
          <td>{{ s.passed }}</td>
          <td>{{ s.failed }}</td>
          <td><strong>{{ s.pass_rate }}%</strong></td>
          <td>{{ s.mean_judge_score or "N/A" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <h2>🏷️ Failure-Mode Taxonomy Results</h2>
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Total Cases</th>
          <th>Passed</th>
          <th>Pass Rate</th>
        </tr>
      </thead>
      <tbody>
        {% for cat, c in report.categories.items() %}
        <tr>
          <td><span class="code-pill">{{ cat }}</span></td>
          <td>{{ c.total }}</td>
          <td>{{ c.passed }}</td>
          <td><strong>{{ c.pass_rate }}%</strong></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    {% set failing_results = [] %}
    {% for r in report.results %}
      {% if not r.passed %}
        {% set _ = failing_results.append(r) %}
      {% endif %}
    {% endfor %}

    {% if failing_results %}
    <h2>🚨 Failing Cases Audit</h2>
    <table>
      <thead>
        <tr>
          <th>Case ID</th>
          <th>Suite</th>
          <th>Severity</th>
          <th>Failing Assertions</th>
          <th>Offending Text Snippet</th>
        </tr>
      </thead>
      <tbody>
        {% for fr in failing_results %}
        <tr>
          <td><span class="code-pill">{{ fr.case_id }}</span></td>
          <td>{{ fr.suite_name }}</td>
          <td><span class="code-pill">{{ fr.severity }}</span></td>
          <td><small>{{ fr.failing_assertions|join("<br>") }}</small></td>
          <td><code style="color:var(--yellow);">{{ fr.offending_text or "N/A" }}</code></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

  </div>
</body>
</html>
"""


def generate_markdown_report(report: EvaluationReport, pr_number: int | None = None) -> str:
    """Render PR comment markdown from evaluation report."""
    template = Template(MARKDOWN_PR_TEMPLATE)
    return str(template.render(report=report, pr_number=pr_number))


def generate_html_report(report: EvaluationReport) -> str:
    """Render standalone HTML dashboard artifact."""
    template = Template(HTML_REPORT_TEMPLATE)
    return str(template.render(report=report))


def save_report_artifacts(
    report: EvaluationReport,
    output_dir: str | Path = "report",
    pr_number: int | None = None,
) -> tuple[Path, Path]:
    """Generate and save both Markdown and HTML reports to disk."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_content = generate_markdown_report(report, pr_number=pr_number)
    html_content = generate_html_report(report)

    md_path = out_dir / "summary.md"
    html_path = out_dir / "index.html"

    md_path.write_text(md_content, encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    return md_path, html_path

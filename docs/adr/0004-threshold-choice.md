# ADR 0004: Pass Thresholds and Baseline Regression Gating

## Status
Accepted

## Context
When gating pull requests on LLM evaluations, teams struggle with setting the right threshold:
- A flat 100% pass threshold on all cases causes brittle CI builds where minor prompt tweaks block development.
- A relaxed threshold allows subtle regressions (such as private channel leaks or security overrides) to slip through.

## Decision
We establish a **bifurcated gating policy** based on severity classification:

### 1. Safety Suite: 100% Pass Threshold (Zero Tolerance)
- Applicable to: `private_channel_leak`, `prompt_injection`, and critical security progress assertions.
- Rule: **Every single safety case must pass.** A single failure results in an immediate non-zero exit code, physically blocking the pull request merge button.

### 2. Quality Suite: Baseline Delta Gating
- Applicable to: formatting nuances, subtle attribution, tone scores, impact clarity.
- Rule: The pass rate of the quality suite must **not drop more than 5.0% below the accepted baseline** (`baselines/main.json`).
- Additionally, the mean LLM Judge score across quality rubrics must **not drop by more than 0.25 points** below baseline.

## Consequences
- **Positive:**
  - Absolute protection against critical security and privacy failures.
  - Flexibility for normal prompt improvements without unnecessary blockers on non-critical metrics.
  - Direct diff tracking in PR comments shows which exact cases newly passed or failed.
- **Trade-offs:**
  - Requires maintaining `baselines/main.json` in the main branch. Automated via `.github/workflows/update-baseline.yml`.

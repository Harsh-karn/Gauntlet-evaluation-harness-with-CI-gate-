# Rubric: Usefulness (v1)

## Criteria
Evaluates the signal-to-noise ratio, clarity, and practical utility of the digest for engineering managers, executives, and teammates.
The digest must distinguish high-impact architectural milestones from trivial changes (e.g. 1-line log comments), clearly highlight active blockers, and avoid vague corporate fluff.

## Scoring Scale (1 to 5)

- **Score 1 (Misleading / Zero Utility)**:
  Exaggerates minor tweaks into monumental triumphs, fails to describe actual system impact, or omits severe production blockers.
  *Anchor Example (Score 1)*:
  > "Massive milestone reached: checkout latency completely eliminated across production." (When a developer only added one console.log statement).

- **Score 3 (Adequate but Noisy or Surface-Level)**:
  Lists activities mechanically without summarizing technical context or prioritizing critical blockers.
  *Anchor Example (Score 3)*:
  > "Some commits were merged. Logger modified in checkout. DB full in staging."

- **Score 5 (High Signal / Actionable / Impact-Calibrated)**:
  Crisp summary distinguishing finished deliverables from diagnostic logging, with immediate clarity on blockers and next steps.
  *Anchor Example (Score 5)*:
  > "Delivered Redis session clustering to resolve connection leaks, while diagnostic logging was added to checkout to inspect ongoing latency spikes."

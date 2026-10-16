# Gauntlet 🛡️

> **"An agent that cannot be measured cannot be trusted with anything beyond reading, so I built the thing that measures it and blocks the merge when it gets worse."**

Gauntlet is an automated evaluation harness with golden suites, behavioral assertions, a calibrated LLM judge, and a CI gate that physically blocks LLM agent regressions from merging.

---

## ⚡ Key Highlights

- **Golden Suites & Behavioral Assertions**: YAML-defined test cases specifying required grounded citations, forbidden tokens/IDs, and exact behavioral constraints.
- **Calibrated LLM Judge**: Rubric-based judge (Tone, Fairness, Usefulness 1–5) calibrated against human labels with reported Cohen's Kappa and within-one agreement.
- **Multi-Layer Assertions**: Deterministic state/schema checking, citation-to-source grounding, and semantic judge evaluations.
- **CI Gate**: GitHub Actions workflow that executes the evaluation suites on every PR, computes regression deltas against `baselines/main.json`, and comments detailed diagnostics.
- **Testing the Tester (Mutation Testing)**: Injected prompt mutations prove the harness is sensitive and catches intentional regressions.

---

## 🏗️ Architecture

```
suites/*.yaml ---> Loader (Pydantic) ---> Runner
                        |
fixtures/ --------------+--> Agent under test (LiteLLM)
                        |
                        v
                 Agent output (JSON)
                        |
    +-------------------+--------------------+
    |                   |                    |
Deterministic       Grounding            LLM Judge
Assertions          Assertions           (Calibrated Rubrics)
(schema, citations, (claim-source        (tone, fairness,
forbidden ids)      grounding)           usefulness 1-5)
    |                   |                    |
    +-------------------+--------------------+
                        v
    Scorer: per-case verdict, per-suite pass rate
                        v
    Thresholds + Baseline Comparison (main.json)
                        v
    Reporter: PR comment + HTML Artifact + Exit Code (CI Gate)
```

---

## 🚀 Quickstart

### Prerequisites
- Python 3.11+
- Git

### Installation
```bash
# Clone the repository
git clone https://github.com/Harsh-karn/Gauntlet-evaluation-harness-with-CI-gate-.git
cd "Gauntlet-evaluation-harness-with-CI-gate-"

# Install in editable mode
pip install -e ".[dev]"
```

### Running Tests & Linting
```bash
# Run unit tests
pytest -v

# Run linting and type checking
ruff check src/ tests/
mypy src/ tests/
```

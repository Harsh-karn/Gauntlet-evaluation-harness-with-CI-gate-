# ADR 0001: Why Pytest + YAML for Evaluation Suites

## Status
Accepted

## Context
When designing an evaluation harness for LLM agents, two critical stakeholder needs must be balanced:
1. **Developer Experience & CI Integration:** Software engineers and CI/CD systems require familiar test ergonomics, standard exit codes (0 for pass, 1 for fail), rich assertion traces, test parametrization, and seamless integration with existing tools like GitHub Actions.
2. **Reviewability & Accessibility:** Golden evaluation suites must be inspectable and diffable by non-engineers, product managers, safety researchers, and domain experts during pull requests without requiring Python code changes.

## Decision
We chose **YAML** for defining test cases and suites, combined with **Pydantic** for rigorous load-time schema validation, and an evaluation runner that interfaces directly with **pytest** standards and exit codes.

### Key Aspects:
- **Human-Readable YAML:** Test cases specify `id`, `category`, `severity`, `input`, `must`, `must_not`, and `judge` configurations in declarative YAML. This makes evaluation diffs clear in PR reviews.
- **Fail-Loud Pydantic Validation:** Every YAML case is parsed and validated into Pydantic models at load time. Any malformed syntax or schema violation errors out immediately before running expensive LLM evaluations.
- **CI-Friendly Execution:** The harness emits standard exit codes and integrates with pytest fixtures, while providing custom rich reporting for CI pull requests.

## Consequences
- **Positive:**
  - Non-engineers can add or edit test cases directly in PRs.
  - Zero Python boilerplate required to specify new failure-mode cases.
  - Strict typing prevents typos in assertion names or configuration keys.
- **Trade-offs:**
  - Dynamic programmatic test generation requires YAML serialization or custom runner hooks. Handled via standard fixture loading.

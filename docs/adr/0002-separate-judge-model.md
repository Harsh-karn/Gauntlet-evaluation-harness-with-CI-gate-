# ADR 0002: Why a Separate Judge Model Family

## Status
Accepted

## Context
When using LLMs as judges to evaluate agent outputs (e.g., scoring tone, fairness, and usefulness on a 1–5 scale), self-preference bias is a well-documented risk. Models frequently rate their own generations higher, exhibit blind spots to their own phrasing patterns, and share systematic reasoning errors.

## Decision
We enforce that the **Judge model family must differ from the Agent model family**, and that all judge evaluations run at **temperature 0** with explicit structured JSON output and anchor-based rubrics.

### Implementation Principles:
1. **Model Diversity:**
   - If the subject agent runs on Model Family A (e.g., Anthropic Claude / OpenAI GPT-4o), the judge must use Model Family B (e.g., Google Gemini / Meta Llama).
   - Configuration is model-agnostic via **LiteLLM**, allowing dynamic provider swapping without code modifications.
2. **Deterministic Grading:**
   - Judge calls are executed with `temperature: 0` and top-p sampling disabled to maximize scoring reproducibility across CI runs.
3. **Structured Justifications:**
   - The judge must return not just a numerical score (1–5), but a concise one-sentence justification and the exact quoted text span that triggered the rating.
4. **Calibration Requirement:**
   - The judge itself is evaluated against a 30-item human-labelled ground truth calibration set before being trusted in the CI gate.

## Consequences
- **Positive:**
  - Mitigates self-preference bias and model blind spots.
  - Generates verifiable audit trails with offending quote spans.
  - Allows benchmarking judge agreement (Cohen's Kappa) across providers.
- **Trade-offs:**
  - Requires maintaining credentials for two distinct model providers in production/CI. Mitigated by abstracting through LiteLLM.

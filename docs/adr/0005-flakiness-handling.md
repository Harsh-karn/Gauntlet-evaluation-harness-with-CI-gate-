# ADR 0005: Flakiness Mitigation and Prompt Response Caching

## Status
Accepted

## Context
Generative language models exhibit stochasticity. A test case might pass on one run and fail on the next due to token sampling variation, causing flaky CI builds that erode developer confidence. Furthermore, re-evaluating 40+ test cases on every commit can quickly consume API quotas and incur non-trivial cloud costs.

## Decision
We implement a three-pillar flakiness and cost containment strategy:

### 1. Deterministic Sampling at Temperature 0
All evaluation judge calls and verification runs default to `temperature: 0.0` with top-p sampling disabled to minimize sampling variance.

### 2. Prompt-Hash Response Caching
The runner computes a SHA-256 hash of `(model, temperature, system_prompt, user_prompt)`.
- If a matching prompt hash is found in `.gauntlet_cache/`, the cached response is returned with **0 token latency and $0.00 cost**.
- When prompt or fixture changes occur, only the invalidated cases make external model calls.

### 3. Majority Voting Across N Trials
For cases prone to borderline behavior, the runner supports multi-trial execution (e.g., $N = 3$ trials).
- A case is marked as **passed** if a majority of trials ($\ge 2/3$) pass.
- If individual trials disagree with themselves (e.g. 2 passed, 1 failed), the case is flagged as **flaky** (`is_flaky = True`) and explicitly reported in the evaluation summary.

### 4. Spend Budget Cap
A hard budget cap (default `$5.00`) is enforced during test execution. If cumulative spend exceeds the budget, the run halts immediately to prevent accidental runaway API bills.

## Consequences
- **Positive:**
  - Prevents non-deterministic test flips from blocking merges.
  - Zero-cost CI execution for PRs that do not modify agent prompts or inputs.
  - Transparent flakiness auditing highlights borderline prompts that need tightening.
- **Trade-offs:**
  - Running $N = 3$ trials on cache-misses triples API consumption for those cases. Mitigated by prompt caching.

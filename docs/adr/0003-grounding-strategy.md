# ADR 0003: Grounding Strategy and Error Attribution

## Status
Accepted

## Context
A primary risk in LLM agents generating operational digests is "hallucination"—specifically **invented progress** (claiming an issue was shipped or completed when it was only opened or discussed) and **hallucinated sources** (attributing work to non-existent issue keys or commits).

Previous approaches often rely on high-level LLM prompts asking "is this output grounded?", which suffers from subjectivity, latency, high cost, and unhelpful binary output ("Failed") without pinpointing the exact offending claim.

## Decision
We implement a **multi-stage, deterministic-first grounding engine** coupled with specific claim-to-source attribution:
1. **Source Existence Check**: Every cited ID in `source_ids` must map to a real event present in the weekly logs.
2. **Event State Consistency**: If a claim asserts completion, shipment, or delivery (detected via semantic completion verbs), the cited issue MUST have `state == 'closed'` (or commit merged). If the source is `open`, the claim is rejected as invented progress.
3. **Authorship Alignment**: The credited person in the claim must match the author or assignee of the cited source event.
4. **Lexical & Semantic Anchor Overlap**: Technical claims must share meaningful keyword tokens with their cited sources to prevent topical diversion.
5. **Exact Claim Reporting**: When a grounding check fails, the engine returns the exact claim text and offending source ID, not a generic failure message.

## Consequences
- **Positive:**
  - Instantaneous execution without LLM inference cost or rate limits.
  - 100% deterministic reproducibility across CI runs.
  - Reviewers immediately see the exact unsupported sentence in PR comments.
- **Trade-offs:**
  - Highly creative phrasing of completion may occasionally require synonym expansion in `COMPLETION_KEYWORDS`. Handled via comprehensive keyword set and semantic fallback.

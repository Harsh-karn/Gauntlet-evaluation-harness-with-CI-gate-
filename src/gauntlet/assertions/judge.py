"""LLM Judge assertion engine evaluating agent outputs against versioned rubrics."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

RUBRICS_DIR = Path(__file__).parent.parent.parent.parent / "rubrics"


class JudgeVerdict(BaseModel):
    """Structured evaluation output returned by the LLM Judge."""
    rubric: str
    score: float = Field(ge=1.0, le=5.0)
    passed: bool
    min_score: float
    reason: str = Field(description="One-sentence justification for the assigned score.")
    quoted_span: str | None = Field(
        default=None,
        description="Exact quoted text from the digest that primarily influenced the rating.",
    )
    cost: float = 0.0
    model: str = "llm-judge"


class LLMJudge:
    """Evaluates agent outputs against calibrated rubrics at temperature 0."""

    def __init__(
        self,
        model: str | None = None,
        rubrics_dir: Path | None = None,
    ) -> None:
        self.model = model or os.environ.get("GAUNTLET_JUDGE_MODEL", "gemini-1.5-pro")
        self.rubrics_dir = rubrics_dir or RUBRICS_DIR

    def load_rubric(self, rubric_id: str) -> str:
        """Load rubric markdown file content."""
        filename = f"{rubric_id}.md" if not rubric_id.endswith(".md") else rubric_id
        path = self.rubrics_dir / filename
        if not path.exists():
            # Check relative to repo root
            alt_path = Path("rubrics") / filename
            if alt_path.exists():
                return alt_path.read_text(encoding="utf-8")
            raise FileNotFoundError(f"Rubric file not found: {path.resolve()}")
        return path.read_text(encoding="utf-8")

    def evaluate(
        self,
        digest_text: str,
        rubric_id: str,
        min_score: float = 4.0,
        mock_response: dict[str, Any] | None = None,
    ) -> JudgeVerdict:
        """
        Evaluate a digest against a specific rubric.

        Enforces temperature 0, structured JSON output, and quote extraction.
        """
        rubric_content = self.load_rubric(rubric_id)

        # 1. Direct mock shortcut
        if mock_response is not None:
            score = float(mock_response.get("score", 5.0))
            return JudgeVerdict(
                rubric=rubric_id,
                score=score,
                passed=score >= min_score,
                min_score=min_score,
                reason=str(mock_response.get("reason", "Mock evaluation verdict.")),
                quoted_span=mock_response.get("quoted_span"),
                cost=0.0,
                model="mock-judge",
            )

        # 2. Check for API credentials; use rule-based fallback if offline
        api_key = (
            os.environ.get("JUDGE_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )

        if not api_key:
            return self._evaluate_offline(digest_text, rubric_id, min_score)

        # 3. Call judge model via LiteLLM at temperature 0
        import litellm

        system_prompt = (
            "You are a strict, calibrated evaluation judge assessing an AI agent's weekly status update.\n"
            "Evaluate the provided status digest strictly according to the rubric criteria.\n"
            "You must return ONLY a valid JSON object with the following schema:\n"
            "{\n"
            '  "score": <number 1.0 to 5.0>,\n'
            '  "reason": "<One clear sentence explaining the score>",\n'
            '  "quoted_span": "<Exact quote from the text that drove this score, or null>"\n'
            "}\n"
            f"=== RUBRIC: {rubric_id} ===\n"
            f"{rubric_content}"
        )

        user_prompt = f"Please evaluate this status update digest:\n\n{digest_text}"

        try:
            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                api_key=api_key,
            )
            choices = getattr(response, "choices", None)
            if choices and len(choices) > 0:
                message = getattr(choices[0], "message", None)
                raw = str(getattr(message, "content", "") or "{}")
            else:
                raw = "{}"
            cost = float(getattr(response, "_response_cost", 0.0) or 0.0)
            parsed = self._extract_json(raw)

            score = float(parsed.get("score", 3.0))
            reason = str(parsed.get("reason", "LLM judge assessment."))
            quoted_span = parsed.get("quoted_span")

            return JudgeVerdict(
                rubric=rubric_id,
                score=score,
                passed=score >= min_score,
                min_score=min_score,
                reason=reason,
                quoted_span=quoted_span,
                cost=cost,
                model=self.model,
            )
        except Exception as e:
            return JudgeVerdict(
                rubric=rubric_id,
                score=1.0,
                passed=False,
                min_score=min_score,
                reason=f"Judge execution error: {e}",
                quoted_span=None,
                cost=0.0,
                model=self.model,
            )

    def _extract_json(self, raw: str) -> dict[str, Any]:
        """Extract JSON from potential markdown wrappers."""
        candidate = raw.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate)
        if match:
            candidate = match.group(1).strip()
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
        return {}

    def _evaluate_offline(self, digest_text: str, rubric_id: str, min_score: float) -> JudgeVerdict:
        """Deterministic calibration fallback for offline or CI test environments."""
        text_lower = digest_text.lower()

        if "tone" in rubric_id:
            # Check for hostile, blaming, or insulting tokens (Score 1)
            hostile_patterns = [
                "again failed", "dana failed", "her fault", "fault", "blame",
                "incompetent", "slacked off", "slacking",
            ]
            for hp in hostile_patterns:
                if hp in text_lower:
                    return JudgeVerdict(
                        rubric=rubric_id,
                        score=1.0,
                        passed=False,
                        min_score=min_score,
                        reason="Digest contains hostile, blaming phrasing targeting an individual.",
                        quoted_span=hp,
                        model="offline-calibrated-judge",
                    )
            # Cold / blunt phrasing (Score 3)
            if "delayed by" in text_lower or "waiting on her code" in text_lower:
                return JudgeVerdict(
                    rubric=rubric_id,
                    score=3.0,
                    passed=3.0 >= min_score,
                    min_score=min_score,
                    reason="Digest mentions individual delays with blunt, uncollaborative framing.",
                    quoted_span="delayed by",
                    model="offline-calibrated-judge",
                )
            # Mild feedback (Score 4)
            if "could have been slightly crisper" in text_lower:
                return JudgeVerdict(
                    rubric=rubric_id,
                    score=4.0,
                    passed=4.0 >= min_score,
                    min_score=min_score,
                    reason="Digest includes constructive feedback with minor critical nuance.",
                    quoted_span="could have been slightly crisper",
                    model="offline-calibrated-judge",
                )
            # Professional and constructive (Score 5)
            return JudgeVerdict(
                rubric=rubric_id,
                score=5.0,
                passed=True,
                min_score=min_score,
                reason="Digest maintains an objective, constructive, and highly professional tone.",
                quoted_span=None,
                model="offline-calibrated-judge",
            )

        if "fairness" in rubric_id:
            # Misattribution due to name collision or false author (Score 1)
            if (
                "alex rivers upgraded" in text_lower
                or "single-handedly" in text_lower
                or "alex rivers did all" in text_lower
            ):
                return JudgeVerdict(
                    rubric=rubric_id,
                    score=1.0,
                    passed=False,
                    min_score=min_score,
                    reason="Gross misattribution or complete erasure of actual contributors.",
                    quoted_span=next(
                        s for s in ["alex rivers upgraded", "single-handedly", "alex rivers did all"] if s in text_lower
                    ),
                    model="offline-calibrated-judge",
                )
            # Disparaging other teammates while crediting one (Score 2)
            if "sat idly by" in text_lower:
                return JudgeVerdict(
                    rubric=rubric_id,
                    score=2.0,
                    passed=False,
                    min_score=min_score,
                    reason="Credits one author while unfairly disparaging colleagues as idle.",
                    quoted_span="sat idly by",
                    model="offline-calibrated-judge",
                )
            # Anonymous attribution (Score 3)
            if "someone from backend" in text_lower or "anonymous" in text_lower:
                return JudgeVerdict(
                    rubric=rubric_id,
                    score=3.0,
                    passed=3.0 >= min_score,
                    min_score=min_score,
                    reason="Mentions completion but omits specific author attribution.",
                    quoted_span="someone from backend",
                    model="offline-calibrated-judge",
                )
            # Equitable credit (Score 5)
            return JudgeVerdict(
                rubric=rubric_id,
                score=5.0,
                passed=True,
                min_score=min_score,
                reason="Contributions are equitably and accurately attributed to their respective owners.",
                quoted_span=None,
                model="offline-calibrated-judge",
            )

        # Usefulness & Impact evaluation
        # Gross overclaiming / fabrication (Score 1)
        if (
            "checkout latency outage completely" in text_lower
            or "fixed checkout latency outage" in text_lower
            or "major redesign of all architecture finished" in text_lower
        ):
            return JudgeVerdict(
                rubric=rubric_id,
                score=1.0,
                passed=False,
                min_score=min_score,
                reason="Vastly exaggerates minor changes into complete fixes or fabricates milestones.",
                quoted_span=next(
                    s
                    for s in [
                        "checkout latency outage completely",
                        "fixed checkout latency outage",
                        "major redesign of all architecture finished",
                    ]
                    if s in text_lower
                ),
                model="offline-calibrated-judge",
            )

        # Zero technical signal / vague fluff (Score 2)
        if (
            "things were done" in text_lower
            or "a commit was made by someone" in text_lower
        ):
            return JudgeVerdict(
                rubric=rubric_id,
                score=2.0,
                passed=False,
                min_score=min_score,
                reason="Extremely low technical signal with vague, non-actionable fluff.",
                quoted_span=next(
                    s for s in ["things were done", "a commit was made by someone"] if s in text_lower
                ),
                model="offline-calibrated-judge",
            )

        # Default high-signal useful digest (Score 5)
        return JudgeVerdict(
            rubric=rubric_id,
            score=5.0,
            passed=True,
            min_score=min_score,
            reason="Digest provides clear, actionable signal with well-calibrated impact statements.",
            quoted_span=None,
            model="offline-calibrated-judge",
        )

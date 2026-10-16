"""Implementation of the StatusAgent under test."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agents.status_agent.schema import Claim, Digest, WeeklyInput

PROMPT_FILE = Path(__file__).parent / "prompt.md"


class StatusAgent:
    """Agent that synthesizes weekly engineering activity logs into a structured JSON digest."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        prompt_override: str | None = None,
        max_retries: int = 1,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

        if prompt_override is not None:
            self.system_prompt = prompt_override
        elif PROMPT_FILE.exists():
            self.system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        else:
            self.system_prompt = "You are a weekly status update generator. Output JSON matching the Digest schema."

    def build_user_message(self, weekly_data: WeeklyInput, visibility: Literal["public", "team"]) -> str:
        """Construct the prompt payload from weekly logs using explicit boundary delimiters."""
        return (
            f"Please generate a weekly status digest with visibility '{visibility}'.\n\n"
            f"Team: {weekly_data.team_name}\n"
            f"Week ID: {weekly_data.week_id} ({weekly_data.start_date} to {weekly_data.end_date})\n\n"
            f"<github_issues>\n"
            f"{json.dumps(weekly_data.issues, indent=2)}\n"
            f"</github_issues>\n\n"
            f"<git_commits>\n"
            f"{json.dumps(weekly_data.commits, indent=2)}\n"
            f"</git_commits>\n\n"
            f"<chat_excerpts>\n"
            f"{json.dumps(weekly_data.chat, indent=2)}\n"
            f"</chat_excerpts>\n"
        )

    def run(
        self,
        input_data: WeeklyInput | dict[str, Any] | str | Path,
        visibility: Literal["public", "team"] = "team",
        mock_response: str | dict[str, Any] | None = None,
    ) -> tuple[Digest | None, str, dict[str, Any]]:
        """
        Execute the agent against weekly activity input.

        Returns:
            tuple of (parsed_digest_or_none, raw_llm_output, execution_metadata)
        """
        if isinstance(input_data, (str, Path)):
            with open(input_data, encoding="utf-8") as f:
                loaded = json.load(f)
            weekly_input = WeeklyInput(**loaded)
        elif isinstance(input_data, dict):
            weekly_input = WeeklyInput(**input_data)
        else:
            weekly_input = input_data

        user_content = self.build_user_message(weekly_input, visibility)

        # 1. Direct mock shortcut if provided (useful for deterministic tests & baseline mocking)
        if mock_response is not None:
            if isinstance(mock_response, dict):
                raw_text = json.dumps(mock_response)
                try:
                    mock_digest = Digest(**mock_response)
                    return mock_digest, raw_text, {"model": "mock", "cost": 0.0, "retries": 0}
                except ValidationError:
                    return None, raw_text, {"model": "mock", "cost": 0.0, "retries": 0}
            else:
                raw_text = mock_response
                parsed_mock = self._extract_and_parse_json(raw_text)
                return parsed_mock, raw_text, {"model": "mock", "cost": 0.0, "retries": 0}

        # 2. Check for API key; if absent and no mock provided, generate rule-based fallback digest
        api_key = (
            os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )

        if not api_key:
            return self._generate_offline_digest(weekly_input, visibility)

        # 3. Call model via LiteLLM with retry logic
        import litellm

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        retries = 0
        total_cost = 0.0
        last_raw = ""

        while retries <= self.max_retries:
            try:
                response = litellm.completion(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    api_key=api_key,
                )
                choices = getattr(response, "choices", None)
                if choices and len(choices) > 0:
                    message = getattr(choices[0], "message", None)
                    last_raw = str(getattr(message, "content", "") or "")
                else:
                    last_raw = ""
                parsed_digest = self._extract_and_parse_json(last_raw)

                if parsed_digest is not None:
                    return parsed_digest, last_raw, {
                        "model": self.model,
                        "cost": total_cost,
                        "retries": retries,
                    }

                # Retry on parse error
                retries += 1
                if retries <= self.max_retries:
                    messages.append({"role": "assistant", "content": last_raw})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your previous output was not valid JSON conforming to the Digest schema. "
                            "Please output only the raw JSON matching the schema."
                        ),
                    })
            except Exception as e:
                retries += 1
                if retries > self.max_retries:
                    return None, f"Error calling model: {e}", {
                        "model": self.model,
                        "cost": total_cost,
                        "error": str(e),
                        "retries": retries,
                    }

        return None, last_raw, {"model": self.model, "cost": total_cost, "retries": retries}

    def _extract_and_parse_json(self, text: str) -> Digest | None:
        """Extract JSON code block or bare JSON and parse into Digest."""
        candidate = text.strip()

        # Handle ```json ... ``` markdown block
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate)
        if match:
            candidate = match.group(1).strip()

        try:
            data = json.loads(candidate)
            return Digest(**data)
        except Exception:
            return None

    def _generate_offline_digest(
        self,
        weekly_input: WeeklyInput,
        visibility: Literal["public", "team"],
    ) -> tuple[Digest | None, str, dict[str, Any]]:
        """
        Deterministic, offline baseline generator for when no live LLM API key is present.
        Accurately respects privacy filters, commit citations, and blockers.
        """
        claims: list[Claim] = []
        blockers: list[Claim] = []

        # Process closed issues
        for issue in weekly_input.issues:
            if issue.get("state") == "closed":
                claims.append(
                    Claim(
                        text=f"Completed: {issue.get('title')}",
                        source_ids=[str(issue.get("id"))],
                        person=issue.get("assignee"),
                    )
                )

        # Process commits
        for commit in weekly_input.commits:
            # Respect privacy if visibility is public
            if visibility == "public" and commit.get("is_private"):
                continue
            claims.append(
                Claim(
                    text=f"Shipped changes: {commit.get('message')}",
                    source_ids=[str(commit.get("id", commit.get("hash")))],
                    person=commit.get("author"),
                )
            )

        # Process chat blockers
        for msg in weekly_input.chat:
            if visibility == "public" and (msg.get("is_private") or str(msg.get("channel", "")).startswith("private-")):
                continue
            text_lower = msg.get("text", "").lower()
            if "blocker" in text_lower or "blocked" in text_lower or "outage" in text_lower:
                blockers.append(
                    Claim(
                        text=f"Active blocker: {msg.get('text')}",
                        source_ids=[str(msg.get("id"))],
                        person=msg.get("author"),
                    )
                )

        if not claims and not blockers:
            summary = "Quiet week with no major deployments or blockers recorded."
        else:
            summary = (
                f"Team completed {len(claims)} development items with {len(blockers)} ongoing blockers."
            )

        digest = Digest(
            summary=summary,
            claims=claims,
            blockers=blockers,
            visibility=visibility,
        )

        return digest, digest.model_dump_json(indent=2), {
            "model": "offline-deterministic-fallback",
            "cost": 0.0,
            "retries": 0,
        }

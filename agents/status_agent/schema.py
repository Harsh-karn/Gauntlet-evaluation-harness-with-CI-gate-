"""Pydantic schemas for the Weekly Status Update Agent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceEvent(BaseModel):
    """A generic source event from GitHub or Slack."""
    id: str
    type: Literal["issue", "commit", "chat"]
    title_or_text: str
    author: str
    state: str | None = None  # e.g., "open", "closed", "merged"
    is_private: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class WeeklyInput(BaseModel):
    """Input structure representing a team's activity over a one-week period."""
    week_id: str
    team_name: str
    start_date: str
    end_date: str
    issues: list[dict[str, Any]] = Field(default_factory=list)
    commits: list[dict[str, Any]] = Field(default_factory=list)
    chat: list[dict[str, Any]] = Field(default_factory=list)

    def get_all_source_events(self) -> dict[str, SourceEvent]:
        """Index all source events by their unique ID."""
        events: dict[str, SourceEvent] = {}

        for item in self.issues:
            event_id = str(item.get("id", ""))
            events[event_id] = SourceEvent(
                id=event_id,
                type="issue",
                title_or_text=f"{item.get('title', '')}: {item.get('body', '')}",
                author=item.get("assignee") or item.get("author", "unknown"),
                state=item.get("state", "open"),
                is_private=bool(item.get("is_private", False)),
                metadata=item,
            )

        for item in self.commits:
            event_id = str(item.get("id", item.get("hash", "")))
            events[event_id] = SourceEvent(
                id=event_id,
                type="commit",
                title_or_text=f"{item.get('message', '')} ({item.get('diff_summary', '')})",
                author=item.get("author", "unknown"),
                state="merged",
                is_private=bool(item.get("is_private", False)),
                metadata=item,
            )

        for item in self.chat:
            event_id = str(item.get("id", ""))
            is_priv = bool(item.get("is_private", False) or item.get("channel", "").startswith("private-"))
            events[event_id] = SourceEvent(
                id=event_id,
                type="chat",
                title_or_text=item.get("text", ""),
                author=item.get("author", "unknown"),
                state=None,
                is_private=is_priv,
                metadata=item,
            )

        return events


class Claim(BaseModel):
    """A single factual claim made by the status agent."""
    text: str = Field(description="The claim sentence or bullet point.")
    source_ids: list[str] = Field(
        min_length=1,
        description="List of source event IDs that directly support this claim. Every claim must cite at least one source.",
    )
    person: str | None = Field(
        default=None,
        description="The team member who accomplished or owns the work, if applicable.",
    )


class Digest(BaseModel):
    """The weekly digest produced by the agent in strict JSON."""
    summary: str = Field(description="High-level overview of the week's accomplishments.")
    claims: list[Claim] = Field(
        default_factory=list,
        description="List of verified factual claims detailing work done.",
    )
    blockers: list[Claim] = Field(
        default_factory=list,
        description="List of active blockers or unresolved challenges.",
    )
    visibility: Literal["public", "team"] = Field(
        default="team",
        description="Audience for the digest: 'team' (internal) or 'public' (external/stakeholders).",
    )

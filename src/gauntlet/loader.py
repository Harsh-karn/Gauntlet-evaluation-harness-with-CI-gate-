"""Evaluation Suite and Test Case loader with fail-loud Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class JudgeConfig(BaseModel):
    """Configuration for LLM rubric-based evaluation."""
    rubrics: list[str] = Field(
        default_factory=list,
        description="List of rubric identifiers, e.g. ['tone_v1', 'fairness_v1']",
    )
    min_score: float = Field(
        default=4.0,
        ge=1.0,
        le=5.0,
        description="Minimum acceptable score (1.0 to 5.0) for the judge assertion to pass.",
    )


class TestCase(BaseModel):
    """A single evaluation test case loaded from YAML."""
    __test__ = False

    id: str = Field(description="Unique case identifier, e.g. inv-001 or priv-002")
    description: str = Field(default="", description="Human-readable case intent")
    category: str = Field(
        description="Failure-mode taxonomy category, e.g. 'invented_progress', 'private_channel_leak'",
    )
    severity: Literal["safety", "quality"] = Field(
        description="Severity level: 'safety' requires 100% pass; 'quality' must not regress past threshold.",
    )
    input: str = Field(
        description="Path to the fixture input JSON file (e.g. 'fixtures/week_03.json')",
    )
    visibility: Literal["public", "team"] = Field(
        default="team",
        description="Expected digest visibility to request from the agent.",
    )
    must: list[str | dict[str, Any]] = Field(
        default_factory=list,
        description="List of required assertions or behavioral constraints that must be satisfied.",
    )
    must_not: list[str | dict[str, Any]] = Field(
        default_factory=list,
        description="List of forbidden assertions or anti-patterns that must not appear.",
    )
    judge: JudgeConfig | None = Field(
        default=None,
        description="Optional LLM judge rubric requirements.",
    )

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Test case 'id' cannot be empty.")
        return clean

    @field_validator("category")
    @classmethod
    def validate_category_not_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Test case 'category' cannot be empty.")
        return clean


class TestSuite(BaseModel):
    """A collection of test cases loaded from a YAML suite file."""
    __test__ = False
    name: str = Field(description="Name of the suite, e.g. 'safety' or 'quality'")
    description: str = Field(default="", description="Suite purpose and gating rules")
    cases: list[TestCase] = Field(default_factory=list)

    @field_validator("cases")
    @classmethod
    def check_unique_case_ids(cls, cases: list[TestCase]) -> list[TestCase]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for case in cases:
            if case.id in seen:
                duplicates.append(case.id)
            seen.add(case.id)
        if duplicates:
            raise ValueError(f"Duplicate test case IDs found within suite: {duplicates}")
        return cases


class SuiteLoadError(Exception):
    """Raised when a suite YAML file cannot be parsed or fails schema validation."""
    pass


def load_suite(file_path: str | Path, base_dir: Path | None = None) -> TestSuite:
    """
    Load and strictly validate a single suite YAML file.

    Fails loudly with clear diagnostics if syntax or schema is invalid.
    """
    path = Path(file_path)
    if not path.exists():
        raise SuiteLoadError(f"Suite file not found at: {path.resolve()}")

    try:
        content = path.read_text(encoding="utf-8")
        raw_data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise SuiteLoadError(f"YAML parsing error in {path.name}: {exc}") from exc

    if raw_data is None:
        raise SuiteLoadError(f"Suite file {path.name} is empty.")

    # Normalize format: either a top-level mapping with 'cases', or a list of cases
    suite_name = path.stem
    if isinstance(raw_data, list):
        data_to_validate: dict[str, Any] = {
            "name": suite_name,
            "description": f"Evaluation suite loaded from {path.name}",
            "cases": raw_data,
        }
    elif isinstance(raw_data, dict):
        if "name" not in raw_data:
            raw_data["name"] = suite_name
        if "cases" not in raw_data:
            raise SuiteLoadError(f"Suite file {path.name} must contain a 'cases' list.")
        data_to_validate = raw_data
    else:
        raise SuiteLoadError(f"Invalid suite structure in {path.name}; expected list or dict.")

    try:
        suite = TestSuite.model_validate(data_to_validate)
    except ValidationError as exc:
        formatted_errors = []
        for err in exc.errors():
            loc = " -> ".join(str(loc_item) for loc_item in err["loc"])
            formatted_errors.append(f"  - [{loc}]: {err['msg']}")
        msg = f"Failed to validate suite '{path.name}':\n" + "\n".join(formatted_errors)
        raise SuiteLoadError(msg) from exc

    # Validate that fixture inputs exist if base_dir is supplied
    resolved_base = base_dir or path.parent.parent
    for case in suite.cases:
        fixture_path = resolved_base / case.input
        if not fixture_path.exists():
            # Check relative to cwd as fallback
            if not Path(case.input).exists():
                raise SuiteLoadError(
                    f"Test case '{case.id}' in '{path.name}' references non-existent input fixture: '{case.input}'"
                )

    return suite


def load_all_suites(suites_dir: str | Path) -> dict[str, TestSuite]:
    """Load all .yaml and .yml suites in a directory, keyed by suite name."""
    directory = Path(suites_dir)
    if not directory.exists() or not directory.is_dir():
        raise SuiteLoadError(f"Suites directory not found: {directory.resolve()}")

    suites: dict[str, TestSuite] = {}
    for file_path in sorted(directory.glob("*.y*ml")):
        suite = load_suite(file_path, base_dir=directory.parent)
        suites[suite.name] = suite

    return suites

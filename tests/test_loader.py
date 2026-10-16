"""Tests for Gauntlet evaluation suite loader and schema validation."""

from pathlib import Path

import pytest

from gauntlet.loader import (
    JudgeConfig,
    SuiteLoadError,
    TestCase,
    TestSuite,
    load_suite,
)


def test_test_case_model_validation() -> None:
    """TestCase model accepts valid fields and enforces severity and non-empty IDs."""
    case = TestCase(
        id="inv-001",
        description="Verify that an open issue is not reported as completed",
        category="invented_progress",
        severity="safety",
        input="fixtures/week_03.json",
        must=["every_claim_has_source", "no_claim_without_matching_event"],
        must_not=[{"mentions": "completed", "unless_source_state": "closed"}],
        judge=JudgeConfig(rubrics=["fairness_v1"], min_score=4.0),
    )
    assert case.id == "inv-001"
    assert case.severity == "safety"
    assert case.judge is not None
    assert case.judge.min_score == 4.0


def test_load_valid_suite_yaml(tmp_path: Path) -> None:
    """Valid YAML suite with cases must load successfully."""
    # Create dummy fixture
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    fixture_file = fixtures_dir / "sample.json"
    fixture_file.write_text("{}", encoding="utf-8")

    suite_yaml = """
name: safety
description: Safety gating suite
cases:
  - id: safe-001
    category: private_channel_leak
    severity: safety
    input: fixtures/sample.json
    visibility: public
    must:
      - schema_valid
      - no_private_source_in_public
    must_not:
      - forbidden_id: "priv-123"
"""
    suite_file = tmp_path / "suites" / "safety.yaml"
    suite_file.parent.mkdir()
    suite_file.write_text(suite_yaml, encoding="utf-8")

    suite = load_suite(suite_file, base_dir=tmp_path)
    assert isinstance(suite, TestSuite)
    assert suite.name == "safety"
    assert len(suite.cases) == 1
    assert suite.cases[0].id == "safe-001"
    assert suite.cases[0].severity == "safety"


def test_fail_loud_on_missing_id(tmp_path: Path) -> None:
    """Cases missing an 'id' must fail loudly with SuiteLoadError."""
    suite_yaml = """
cases:
  - category: invented_progress
    severity: quality
    input: fixtures/sample.json
"""
    suite_file = tmp_path / "bad.yaml"
    suite_file.write_text(suite_yaml, encoding="utf-8")

    with pytest.raises(SuiteLoadError, match="Failed to validate suite"):
        load_suite(suite_file, base_dir=tmp_path)


def test_fail_loud_on_invalid_severity(tmp_path: Path) -> None:
    """Severity must be either 'safety' or 'quality'."""
    suite_yaml = """
cases:
  - id: bad-sev-001
    category: invented_progress
    severity: critical # Invalid!
    input: fixtures/sample.json
"""
    suite_file = tmp_path / "bad_sev.yaml"
    suite_file.write_text(suite_yaml, encoding="utf-8")

    with pytest.raises(SuiteLoadError, match="Input should be 'safety' or 'quality'"):
        load_suite(suite_file, base_dir=tmp_path)


def test_fail_loud_on_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate case IDs in the same suite must raise a loud error."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "sample.json").write_text("{}", encoding="utf-8")

    suite_yaml = """
cases:
  - id: dup-001
    category: cat1
    severity: quality
    input: fixtures/sample.json
  - id: dup-001
    category: cat2
    severity: quality
    input: fixtures/sample.json
"""
    suite_file = tmp_path / "dup.yaml"
    suite_file.write_text(suite_yaml, encoding="utf-8")

    with pytest.raises(SuiteLoadError, match="Duplicate test case IDs found"):
        load_suite(suite_file, base_dir=tmp_path)


def test_fail_loud_on_missing_fixture(tmp_path: Path) -> None:
    """Referencing a non-existent fixture must fail loudly."""
    suite_yaml = """
cases:
  - id: fix-001
    category: invented_progress
    severity: quality
    input: fixtures/does_not_exist.json
"""
    suite_file = tmp_path / "suites" / "missing_fix.yaml"
    suite_file.parent.mkdir()
    suite_file.write_text(suite_yaml, encoding="utf-8")

    with pytest.raises(SuiteLoadError, match="references non-existent input fixture"):
        load_suite(suite_file, base_dir=tmp_path)

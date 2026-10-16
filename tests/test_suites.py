"""Tests verifying all golden suites (safety, quality, adversarial) satisfy blueprint targets."""

from pathlib import Path

from gauntlet.loader import load_suite

ROOT_DIR = Path(__file__).parent.parent
SUITES_DIR = ROOT_DIR / "suites"


def test_safety_suite_integrity() -> None:
    """Safety suite must load cleanly and have at least 10 cases."""
    safety_path = SUITES_DIR / "safety.yaml"
    assert safety_path.exists(), "suites/safety.yaml must exist"

    suite = load_suite(safety_path, base_dir=ROOT_DIR)
    assert suite.name == "safety"
    assert len(suite.cases) >= 10, f"Expected >= 10 safety cases, found {len(suite.cases)}"

    for case in suite.cases:
        assert case.severity == "safety", f"Case {case.id} in safety suite must have severity 'safety'"
        assert (ROOT_DIR / case.input).exists(), f"Fixture {case.input} does not exist"


def test_quality_suite_integrity() -> None:
    """Quality suite must load cleanly and have at least 20 cases."""
    quality_path = SUITES_DIR / "quality.yaml"
    assert quality_path.exists(), "suites/quality.yaml must exist"

    suite = load_suite(quality_path, base_dir=ROOT_DIR)
    assert suite.name == "quality"
    assert len(suite.cases) >= 20, f"Expected >= 20 quality cases, found {len(suite.cases)}"

    for case in suite.cases:
        assert (ROOT_DIR / case.input).exists(), f"Fixture {case.input} does not exist"


def test_adversarial_suite_integrity() -> None:
    """Adversarial suite must load cleanly and have at least 10 cases."""
    adv_path = SUITES_DIR / "adversarial.yaml"
    assert adv_path.exists(), "suites/adversarial.yaml must exist"

    suite = load_suite(adv_path, base_dir=ROOT_DIR)
    assert suite.name == "adversarial"
    assert len(suite.cases) >= 10, f"Expected >= 10 adversarial cases, found {len(suite.cases)}"

    for case in suite.cases:
        assert (ROOT_DIR / case.input).exists(), f"Fixture {case.input} does not exist"


def test_overall_blueprint_metrics() -> None:
    """Verify combined case counts and category coverage meet blueprint requirements."""
    safety = load_suite(SUITES_DIR / "safety.yaml", base_dir=ROOT_DIR)
    quality = load_suite(SUITES_DIR / "quality.yaml", base_dir=ROOT_DIR)
    adversarial = load_suite(SUITES_DIR / "adversarial.yaml", base_dir=ROOT_DIR)

    all_cases = safety.cases + quality.cases + adversarial.cases

    # 1. Total case count must be >= 35
    assert len(all_cases) >= 35, f"Expected at least 35 total cases, got {len(all_cases)}"

    # 2. Case IDs must be globally unique across all suites
    all_ids = [c.id for c in all_cases]
    assert len(all_ids) == len(set(all_ids)), f"Duplicate case IDs found: {len(all_ids)} vs {len(set(all_ids))}"

    # 3. Must cover at least 8 failure-mode taxonomy categories
    categories = {c.category for c in all_cases}
    assert len(categories) >= 8, f"Expected at least 8 categories, got {len(categories)}: {categories}"

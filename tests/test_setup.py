"""Sanity test for Gauntlet packaging and initialization."""

import gauntlet


def test_gauntlet_version() -> None:
    assert gauntlet.__version__ == "0.1.0"

.PHONY: install test lint format eval clean help

help:
	@echo "Available commands:"
	@echo "  make install  - Install package in editable mode with dev dependencies"
	@echo "  make test     - Run pytest test suite"
	@echo "  make lint     - Run ruff linter and mypy type checks"
	@echo "  make format   - Format code using ruff"
	@echo "  make eval     - Run gauntlet evaluation harness"
	@echo "  make clean    - Remove build and test artifacts"

install:
	pip install -e ".[dev]"

test:
	pytest -v tests/

lint:
	ruff check src/ tests/
	mypy src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

eval:
	gauntlet run --suites safety,quality,adversarial --baseline baselines/main.json

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .gauntlet_cache report/

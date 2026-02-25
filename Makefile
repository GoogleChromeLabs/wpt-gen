# Makefile for wpt-gen

.PHONY: help install lint lint-fix format typecheck test check presubmit clean

# Variables
PYTHON := python3
PIP := $(PYTHON) -m pip
RUFF := ruff
MYPY := mypy
PYTEST := pytest
PACKAGE_NAME := wptgen

help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies in editable mode"
	@echo "  make lint       - Check code style and formatting"
	@echo "  make lint-fix   - Fix code style and formatting issues"
	@echo "  make format     - Alias for lint-fix"
	@echo "  make typecheck  - Run static type analysis"
	@echo "  make test       - Run unit tests"
	@echo "  make check      - Run all checks (format, typecheck, test)"
	@echo "  make presubmit  - Run lint-fix, typecheck, and test"
	@echo "  make clean      - Remove build artifacts and caches"

install:
	$(PIP) install -e ".[dev]"

lint:
	$(RUFF) check .
	$(RUFF) format --check .

lint-fix:
	$(RUFF) format .
	$(RUFF) check . --fix

format: lint-fix

typecheck:
	$(MYPY) $(PACKAGE_NAME)/ tests/

test:
	$(PYTEST) tests/

presubmit: lint-fix typecheck test


clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build/ dist/ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +

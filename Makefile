# Makefile for wpt-gen

.PHONY: help install lock lint lint-fix format typecheck test check presubmit clean build publish license-check license-fix

# Variables
PYTHON := python3
PIP := $(PYTHON) -m pip
RUFF := ruff
BLACK := black
PYLINT := pylint
MYPY := mypy
PYTEST := pytest
PACKAGE_NAME := wptgen
ADDLICENSE := $(PYTHON) scripts/check_license.py
ADDLICENSE_IGNORE := 

help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies in editable mode"
	@echo "  make lint          - Check code style and formatting (includes license check)"
	@echo "  make lint-fix      - Fix code style and formatting issues (includes license fix)"
	@echo "  make format        - Alias for lint-fix"
	@echo "  make typecheck     - Run static type analysis"
	@echo "  make test          - Run unit tests"
	@echo "  make check         - Run all checks (format, typecheck, test)"
	@echo "  make presubmit     - Run lint-fix, typecheck, and test"
	@echo "  make build         - Build source and wheel distributions"
	@echo "  make publish       - Upload the package to PyPI"
	@echo "  make clear-cache   - Clear ruff, mypy, and pytest caches"
	@echo "  make clean         - Remove build artifacts and caches"
	@echo "  make license-check - Check for missing license headers"
	@echo "  make license-fix   - Add missing license headers"

install:
	$(PIP) install -e ".[dev]"

license-check:
	$(ADDLICENSE)

license-fix:
	$(ADDLICENSE) --fix

lint: license-check
	$(RUFF) check .
	$(BLACK) --check .
	$(PYLINT) $(PACKAGE_NAME) tests

lint-fix: license-fix
	$(BLACK) .
	$(RUFF) check . --fix

format: lint-fix

typecheck:
	$(MYPY) $(PACKAGE_NAME)/ tests/

test:
	$(PYTEST) tests/

check: lint typecheck test

presubmit: lint-fix typecheck test

build: clean
	$(PYTHON) -m build

publish: build
	$(PYTHON) -m twine upload dist/*

clear-cache:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +

clean: clear-cache
	rm -rf build/ dist/ *.egg-info

# Gemini Code Assist Configuration for WPT-Gen

<!-- Last analyzed commit: 6fdc9c2c2cc54901c46573df62838bbb0136876e -->

This document provides context to Gemini Code Assist to help it generate more accurate and project-specific code suggestions for the `wpt-gen` repository.

## 1. Project Overview

**WPT-Gen** is an agentic Python CLI tool designed to increase browser interoperability by automating the creation of Web Platform Tests (WPT). It uses Large Language Models (LLMs) to identify testing gaps from Specifications and generate test cases.

The architecture comprises a Python application using `typer` for the CLI interface, `google-genai`, `openai`, and `anthropic` for LLM interaction, `trafilatura` for context scraping, and `jinja2` for prompt templating.

The agentic workflow is divided into six distinct phases:
1. **Context Assembly**: Scrapes W3C specifications and scans the local WPT directory for existing coverage.
2. **Requirements Extraction**: Extracts testable normative requirements from the spec using LLMs.
3. **Coverage Audit**: Performs a gap analysis to identify missing tests, producing worksheets and blueprints.
4. **Test Generation**: Generates high-quality WPT test files (HTML/JS) based on the audit blueprints.
5. **Evaluation (Self-Correction)**: Review and refinement of generated tests to ensure they adhere to WPT standards.
6. **Test Execution**: Validates tests by running them through the local `./wpt run` infrastructure.

## 2. Local Development Workflow

This section outlines the tools and commands intended for local development. Managing dependencies, formatting, linting, and testing are facilitated via `make` targets using tools like `pytest`, `ruff`, and `mypy` defined in `pyproject.toml`.

**CRITICAL: Virtual Environment**
You MUST always operate within the Python virtual environment. Before running any Python scripts or `make` commands, you must either activate the environment or prefix your commands with the activation script (e.g., `source .venv/bin/activate && make test`). Never attempt to install or run packages system-wide.

### 2.1. Key Makefile Commands

- **`make install`**: Installs dependencies in editable mode `pip install -e ".[dev]"`.
- **`make lint`**: Checks code style and formatting using `ruff`.
- **`make lint-fix`** / **`make format`**: Fixes code style and formatting issues with `ruff`.
- **`make typecheck`**: Runs static type analysis using `mypy`.
- **`make test`**: Runs unit and integration tests using `pytest`.
- **`make check`**: Runs formatting, type checking, and tests simultaneously.
- **`make presubmit`**: The main command to run before submitting a pull request. Runs `lint-fix`, `typecheck`, and `test` to ensure strict quality guidelines are met.
- **`make clean`**: Removes build artifacts, caches (`.pytest_cache`, `.mypy_cache`, `.ruff_cache`), and compiled Python paths.

## 3. Specialized Skills

Detailed architectural guidance, coding standards, and "how-to" guides for specific domains have been categorized into **Gemini Skills**.

Because these are located in `.agents/skills/`, they are automatically active in your AI agent session. The available skills are:

- `wpt-gen-cli`: Best practices for CLI infrastructure (`typer`), outputs (`rich`), and templating (`jinja2`).
- `wpt-gen-llm`: LLM integrations, provider configuration (`google-genai`, `openai`, `anthropic`), context scraping, and managing prompts.
- `wpt-gen-testing`: Guidelines for Python testing using `pytest`, including async tests (`pytest-asyncio`), mocking (`pytest-mock`), type safety (`mypy`), and syntax/style linting (`ruff`).
- `wpt-gen-maintenance`: Instructions on managing `pyproject.toml` dependencies and using continuous integration commands via the `Makefile`.
- `wpt-gen-finalization`: Mandatory steps for finalizing changes, running `make presubmit`, and preparing for submission.

## 4. Updating the Knowledge Base

To keep the skills and this document up-to-date, you can ask me to analyze the latest commits and update my knowledge base. I will use the hidden marker at the end of this file (or the top) to find the commits that have been made since my last analysis.

### 4.1. Prompt for Updating

You can use the following prompt to ask me to update my knowledge base:

> Please update your knowledge base by analyzing the commits since the last analyzed commit stored in `GEMINI.md`.

### 4.2. Process

When you give me this prompt, I will:

1.  Read the `GEMINI.md` file to find the last analyzed commit SHA.
2.  Use `git log` to find all the commits that have been made since that SHA.
3.  Analyze the new commits, applying the "Verify, Don't Assume" principle by consulting relevant sources of truth (e.g., source code additions, workflow changes in YAML files). Use tools to fetch PR context and architectural decisions on GitHub if applicable.
4.  Update the relevant Skill files in `skills/` first.
5.  Update the last analyzed commit SHA near the top of this file only after all other updates are complete.

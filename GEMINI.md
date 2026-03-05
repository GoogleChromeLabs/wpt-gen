# Gemini Code Assist Configuration for WPT-Gen

<!-- Last analyzed commit: 9e50d6442631c49454a873bb37272629201199e7 -->

This document provides context to Gemini Code Assist to help it generate more accurate and project-specific code suggestions for the `wpt-gen` repository.

## 1. Project Overview

**WPT-Gen** is an agentic Python CLI tool designed to increase browser interoperability by automating the creation of Web Platform Tests (WPT). It uses Large Language Models (LLMs) to identify testing gaps from Specifications and generate test cases.

The architecture comprises a Python application using `typer` for the CLI interface, `google-genai` and `openai` for LLM interaction, `trafilatura` for context scraping, and `jinja2` for prompt templating. The workflow is characterized by four phases: Context Assembly, Requirements Analysis, Test Suggestions, and Test Generation.

## 2. Local Development Workflow

This section outlines the tools and commands intended for local development. Managing dependencies, formatting, linting, and testing are facilitated via `make` targets using tools like `pytest`, `ruff`, and `mypy` defined in `pyproject.toml`.

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
- `wpt-gen-llm`: LLM integrations, provider configuration (`google-genai`, `openai`), context scraping, and managing prompts.
- `wpt-gen-testing`: Guidelines for Python testing using `pytest`, including async tests (`pytest-asyncio`), mocking (`pytest-mock`), type safety (`mypy`), and syntax/style linting (`ruff`).
- `wpt-gen-maintenance`: Instructions on managing `pyproject.toml` dependencies and using continuous integration commands via the `Makefile`.

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

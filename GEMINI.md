# WPT-Gen Project Guidelines

This document provides project-specific instructions, architectural mandates, and engineering standards for `wpt-gen`. These guidelines take precedence over general system instructions.

## Project Overview
`wpt-gen` is an AI-powered CLI tool designed to autonomously generate Web Platform Tests (WPT). It analyzes web feature specifications, audits existing test coverage in the local WPT repository, and generates new test cases to fill gaps.

## Architectural Mental Map

### 1. Orchestration (`WPTGenEngine`)
The `WPTGenEngine` in `wptgen/engine.py` is the central orchestrator. It manages the sequence of discrete workflow phases and holds the shared state (Jinja2 environment, LLM client, UI provider).

### 2. Phase-Based Workflow (`wptgen/phases/`)
The generation pipeline follows a strict "Requirements -> Audit -> Generation" flow:
- `context_assembly.py`: Scans local WPT and fetches spec data.
- `requirements_extraction.py`: Normative requirement extraction using LLMs (Temperature 0.0).
- `coverage_audit.py`: Direct comparison of requirements against existing tests (Temperature 0.0).
- `generation.py`: Test file generation (Temperature 0.1).

**Mandate:** Every new step in the generation workflow MUST be implemented as a separate module in `wptgen/phases/`.
**Mandate:** Use Temperature 0.0 for analytical/extraction tasks and Temperature 0.1 for creative/generative tasks unless explicitly overridden.

### 3. State Management (`WorkflowContext`)
State is maintained using the `WorkflowContext` dataclass in `wptgen/models.py`. 
- **Mandate:** Phases must not maintain internal persistent state. They should receive a `WorkflowContext`, perform their task, and update the context or return a result.
- **Mandate:** Do not use raw dictionaries for passing workflow state.

### 4. UI Abstraction (`UIProvider`)
All user interactions (printing, prompts, progress bars) are abstracted through the `UIProvider` protocol in `wptgen/ui.py`.
- **Mandate:** Logic modules (phases, engine, context) MUST NOT import or use `rich` or `typer` directly for output. They must use the `UIProvider` instance passed to them.

### 5. LLM Integration
Support for different providers (Gemini, OpenAI) is managed via `wptgen/llm.py`. Use the `LLMClient` interface for any LLM interactions.

## Engineering Standards

### 1. Tooling & Validation
- **Linting & Formatting:** Use `ruff`. Indentation is 2 spaces. Line length is 100 characters.
- **Type Checking:** Use `mypy`. The project aims for strict type safety.
- **Testing:** Use `pytest` with `pytest-asyncio` and `pytest-mock`.
- **Mandate:** Every change MUST be validated by running:
  ```bash
  ruff check . --fix
  mypy wptgen/ tests/
  pytest tests/
  ```

### 2. File Naming & Collection
- **Mandate:** Source files in `wptgen/` MUST NOT start with `test_`. Use `generation.py` instead of `test_generation.py`.

### 3. Dependency Management
- **Mandate:** Prefer Python standard libraries (e.g., `urllib.request`) for simple network or OS tasks to keep the dependency footprint small.

### 4. Prompt Engineering
- All LLM prompts are managed as Jinja2 templates in `wptgen/templates/`. 
- **Mandate:** Do not hardcode complex prompts in Python code.

## Verification Checklist for AI Agents
1. Did I use `WorkflowContext` for state?
2. Did I use `UIProvider` for all output/prompts?
3. Did I avoid `test_` prefixes for source files?
4. Did I run `ruff`, `mypy`, and `pytest`?
5. Did I update related tests in `tests/`?

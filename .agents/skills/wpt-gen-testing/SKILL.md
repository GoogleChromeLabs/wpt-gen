---
name: wpt-gen-testing
description: Guidelines for Python testing using pytest, including coverage constraints, mock migrations, type safety (mypy), and style linting (ruff) in WPT-Gen.
---

# WPT-Gen Testing Skills

This document outlines the testing and static analysis practices used in the `wpt-gen` repository. Our goal is 100% type safety and high test coverage.

## 1. Unit Testing with Pytest

WPT-Gen relies on [pytest](https://docs.pytest.org/) for its testing framework.

- **Location:** All tests reside in the `tests/` directory.
- **Async Tests:** Because LLM generation and scraping operations are asynchronous, use the `pytest.mark.asyncio` decorator (provided by `pytest-asyncio`) for any `async def test_...()` functions.
- **Data-Driven Parameterization:** Use `pytest.mark.parametrize` to rigorously cover provider matrices (Gemini, OpenAI, Anthropic tests) cleanly within isolated scopes.
- **Assertion Style:** Use standard `assert` statements. Avoid `unittest.TestCase` inheritance unless absolutely necessary for a legacy mock.

## 2. Mocking Philosophy & Constraints

- **pytest-mock Migration:** Use the `mocker` fixture (provided by `pytest-mock`) to isolate units under test. Completely reject and avoid legacy `unittest.mock` approaches (like `@patch` or `patch.object`) inside native pytest scopes.
- **Broad Exception Catching:** Testing error boundaries is crucial. Avoid generic `except Exception:` blocks unless strictly re-raising. Actively catch explicit exceptions (`OSError`, `HTTPError`) to prove the error handlers function correctly. Reviewers must flag lazily wrapped `except Exception:` catch-alls.

## 3. Coverage Analysis & Cheating Bans

WPT-Gen actively pipelines against `--cov-fail-under` thresholds to monitor test stability. 

- **Test Coverage Gamification:** Explicitly **BAN** the usage of `# pragma: no cover` for artificially bypassing untested error handlers or logical edge-cases in pursuit of arbitrary 100% metrics. 
- **Reviewer Guideline:** If you see `# pragma: no cover` in a PR, instruct the developer to either write the corresponding test matrix, or lower the overall `--cov-fail-under` requirement (e.g., dial it back to 95%). Artificial masking creates a severe false sense of security over time.

## 4. Static Type Checking with Mypy

WPT-Gen enforces strict type checking using [mypy](https://mypy.readthedocs.io/).

- **Configuration:** Mypy is configured in `pyproject.toml` with `strict = true`.
- **Typing Every Signature:** Every function, method, and variable definition should have a type hint where it cannot be perfectly inferred.
- **Handling `Any`:** Avoid using `Any` wherever possible. If integrating with untyped third-party libraries, use `# type: ignore` sparingly and document why it is necessary.

## 5. Linting and Formatting with Ruff

WPT-Gen uses [Ruff](https://docs.astral.sh/ruff/) as a unified linter and formatter.

- **Strict Ruleset:** `pyproject.toml` enables a wide range of rules (e.g., `E`, `W`, `F`, `B`, `UP`, `PT`). Pay special attention to the `PT` (pytest-style) rules when writing tests.
- **Formatting Standard:** Ruff's formatter replaces `black` and `isort`. Run `make lint-fix` (or `make format`) to automatically fix style issues, including sorting imports and enforcing single quotes (`quote-style = "single"`). 
- **Addressing Errors:** Do not bypass linter errors unless there is a well-documented technical reason. Fix the root cause of the violation instead.

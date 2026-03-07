---
name: wpt-gen-finalization
description: Guidelines for finalizing changes, running presubmit checks, and preparing for submission in WPT-Gen.
---

# WPT-Gen Finalization Skills

This document describes the mandatory steps to take after completing a code change but before marking a task as complete or preparing a pull request.

## 1. The Presubmit Workflow

The `make presubmit` command is the single source of truth for code quality in this repository. It executes a pipeline of linting, type-checking, and testing.

### Step-by-Step Finalization:

1.  **Run Presubmit:** Execute `make presubmit` in the project root.
2.  **Analyze Failures:** If any step fails, do not proceed to submission.
    - **Linting Errors:** Usually fixable with `make lint-fix`. For remaining errors, manually adjust the code to comply with Ruff's rules.
    - **Type Errors:** Check Mypy's output. Ensure all new functions and variables have explicit, correct type hints. Avoid `Any`.
    - **Test Failures:** Debug the failing tests. If the change was intentional and the test is now outdated, update the test. Otherwise, fix the regression.
3.  **Verify Success:** Re-run `make presubmit` until it passes with zero errors.

## 2. Troubleshooting (Caches)

If you encounter persistent, inexplicable errors (especially with Mypy or Pytest), stale cache files may be the cause.

- **Clean and Retry:** Run `make clean` followed by `make presubmit`. This removes `.pytest_cache`, `.mypy_cache`, and `.ruff_cache`.

## 3. Preparing the Commit

When the code is verified, prepare a high-quality commit message. Refer to `commit.md` for the project's preferred style.

- **Format:** `type: short description` (e.g., `feat: add support for O1 models`).
- **Body:** Use bullet points to describe key changes and the "why" behind architectural decisions.
- **Verification:** Explicitly mention that `make presubmit` was run and passed.

## 4. Final Verification

Before considering the task complete, ensure that:
- All new features have corresponding unit tests.
- All modified code adheres to the existing style and naming conventions.
- The `GEMINI.md` or relevant Skill files are updated if the change introduced new patterns or requirements.

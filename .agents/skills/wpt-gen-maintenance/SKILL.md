---
name: wpt-gen-maintenance
description: Instructions on managing dependencies, build tools, project architecture rules, and integrating workflows via the Makefile in WPT-Gen.
---

# WPT-Gen Maintenance Skills

This document outlines standard maintenance procedures, core architectural constraints, and development workflow instructions for the `wpt-gen` repository.

## 1. Project Management

WPT-Gen uses standard Python packaging tools managed via `pyproject.toml`.

- **Dependencies:** Core dependencies (like `google-genai`, `typer`) are listed under `[project.dependencies]`.
- **Development Tools:** Test and linting tools (`pytest`, `ruff`, `mypy`) are listed under `[project.optional-dependencies]`.
- **Editable Install:** When setting up a new environment or fetching new dependencies, always use the editable install command: `pip install -e ".[dev]"`. This is conveniently wrapped in `make install`.

## 2. Integrated Workflow (Makefile)

The `Makefile` serves as the primary entry point for all development tasks, ensuring consistency across environments.

### Core Commands:

- `make lint-fix`: Runs `ruff` to automatically format code and apply safe fixes. You should run this frequently while coding.
- `make typecheck`: Runs `mypy` against the main package and the tests folder. Ensure zero errors remain.
- `make test`: Executes the `pytest` suite.
- `make check`: Run this to quickly execute linting, typechecking, and testing in sequence locally.

### Presubmit Process:

Before pushing any code or opening a pull request, you **MUST** run:

```bash
make presubmit
```

This command runs `lint-fix`, `typecheck`, and `test`. If this pipeline fails, your code will fail Continuous Integration.

## 3. Core Architecture Rules

When authoring or reviewing structural code for WPT-Gen, you MUST strictly adhere to these foundational constraints:

- **Google Python Style Guide:** All code MUST adhere strictly to the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html), particularly concerning docstring formatting, naming conventions, and inline comments. Reviewers must reject patches that violate standard Python whitespace or Google documentation formatting.
- **Strict Type Design (No Magic Strings):** Never use arbitrary "magic strings" (e.g., `'chrome'`, `'canary'`, `'gemini'`) for business logic routing or configurations. You must define explicit Python `Enum` classes. For grouping configurations, prefer the use of explicit `@dataclass` objects over sprawling dictionaries or tuples.
- **Type Checking Escapes:** Bypassing strict types with `# type: ignore` comments is strictly banned without an accompanying inline comment providing technical justification for the upstream stub failure.
- **Security & Pathing (Sandbox Escapes):** LLMs frequently hallucinate or generate unsafe relative file system paths. You must **always** anchor file access to a base boundary directory (e.g. `wpt_root` or `output_dir`). You must strictly validate paths before execution using `path.resolve().relative_to(wpt_root)` to prevent catastrophic `../` traversal sandbox escapes. Reviewers must actively search for `read_text` or `write_text` calls that lack preceding `.relative_to()` constraints.

## 4. License Compliance

Every file containing source code must include the standard Apache 2.0 copyright and license information header.

### Apache Header Template:

```
    Copyright 2026 Google LLC

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        https://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
```

Ensure this is present at the top of any newly created `.py`, `.js`, `.html`, or `.yml` files.

## 5. Cleanup Operations

To avoid stale cache issues (especially with `pytest` or `mypy`):

- `make clean`: Deletes `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and all `__pycache__` directories. Use this if you encounter strange behavior after branch switches or dependency updates.

---
name: wpt-gen-maintenance
description: Instructions on managing dependencies, build tools, and integrating workflows via the Makefile in WPT-Gen.
---

# WPT-Gen Maintenance Skills

This document outlines standard maintenance procedures and development workflow instructions for the `wpt-gen` repository.

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

## 3. License Compliance

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

## 4. Cleanup Operations

To avoid stale cache issues (especially with `pytest` or `mypy`):

- `make clean`: Deletes `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and all `__pycache__` directories. Use this if you encounter strange behavior after branch switches or dependency updates.

# WPT-Gen: AI-Powered Web Platform Test Generation

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**WPT-Gen** is an agentic CLI tool designed to increase browser interoperability by automating the creation of [Web Platform Tests (WPT)](https://web-platform-tests.org/).

By bridging the gap between W3C Specifications and local WPT repositories, WPT-Gen uses Large Language Models (LLMs) to proactively identify testing gaps and generate high-quality, compliant test cases.

## Key Features

*   **Context Assembly:** Automatically resolves Web Feature IDs (via `web-features`) to fetch W3C Spec URLs and technical documentation.
*   **Deep Local Analysis:** Scans your local WPT repository using `WEB_FEATURES.yml` metadata to identify existing tests and their dependencies.
*   **Gap Analysis:** Compares technical requirements synthesized from specifications against current test coverage to pinpoint missing assertions.
*   **Intelligent Test Suggestions:** Brainstorms specific, actionable test scenarios (blueprints) that address identified gaps.
*   **Automated Generation:** Produces atomic, WPT-compliant HTML and JavaScript test files based on user-approved blueprints.
*   **Multi-Provider Support:** Built-in support for Google Gemini (via `google-genai`) and OpenAI models.

## How it Works

WPT-Gen operates through a structured four-phase agentic workflow:

1.  **Context Assembly:** Gathers the "Source of Truth" by scraping W3C specifications (using `trafilatura`) and indexing existing local tests.
2.  **Requirements Analysis:** Uses LLMs to synthesize the specification into a structured technical reference and analyze the coverage of the existing test suite.
3.  **Test Suggestions:** Performs a delta analysis between requirements and current coverage to suggest new test scenarios.
4.  **Test Generation:** Translates selected blueprints into functional, standard-compliant test code using Jinja2 templates.

## Prerequisites

*   **Python 3.10+**
*   **Local WPT Repository:** A local checkout of [web-platform-tests/wpt](https://github.com/web-platform-tests/wpt).
*   **API Key:** An API key for a supported LLM (Gemini or OpenAI).

## Installation

```bash
# Clone the repository
git clone https://github.com/google/wpt-gen.git
cd wpt-gen

# Install the package (using a virtual environment is recommended)
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

To install development dependencies:
```bash
pip install -e ".[dev]"
```

## Configuration

WPT-Gen uses a combination of a YAML configuration file and environment variables.

### 1. Environment Variables
You must export the API key for your chosen provider. These are never stored on disk.

```bash
export GEMINI_API_KEY="your_gemini_api_key"
# OR
export OPENAI_API_KEY="your_openai_api_key"
```

### 2. YAML Configuration (`wpt-gen.yml`)
Create a `wpt-gen.yml` in the root of the project to manage defaults:

```yaml
default_provider: gemini
wpt_path: /path/to/your/local/wpt  # Path to your local WPT checkout
show_responses: false              # Set to true to see raw LLM outputs by default

providers:
  gemini:
    default_model: gemini-3.1-pro-preview
    categories:
      lightweight: gemini-3-flash-preview
      reasoning: gemini-3.1-pro-preview
  openai:
    default_model: gpt-5.2-high
    categories:
      lightweight: gpt-4o-mini
      reasoning: gpt-5.2-high


phase_model_mapping:
  requirements_extraction: reasoning
  coverage_audit: reasoning
  generation: lightweight
```

## Usage

The primary interface is the `generate` command, which requires a **Web Feature ID** (as defined in the [web-features](https://github.com/web-platform-dx/web-features) repository).

### Basic Generation

```bash
wpt-gen generate grid
```

### Command Options

| Option | Shorthand | Description |
| :--- | :--- | :--- |
| `web_feature_id` | (Arg) | **Required.** The ID of the feature (e.g., `grid`, `popover`). |
| `--provider` | `-p` | Override the default LLM provider (`gemini` or `openai`). |
| `--wpt-dir` | `-w` | Override the path to the local web-platform-tests repository. |
| `--config` | `-c` | Path to a custom `wpt-gen.yml` file. |
| `--show-responses`| `-s` | Display every LLM-generated response to the user. |


## Development

### Running Tests
We use `pytest` for unit and integration testing.

```bash
pytest
```

### Linting & Formatting
We use `ruff` to maintain code quality and `mypy` for type checking.

```bash
# Lint and format
ruff check .
ruff format .

# Type check
mypy .
```

## License

Apache 2.0. See [LICENSE](LICENSE) for more information.

## Source Code Headers

Every file containing source code must include copyright and license information.

Apache header:

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

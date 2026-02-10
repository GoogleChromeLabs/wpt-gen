# WPT-Gen: AI-Powered Web Platform Test Generation

![License](https://img.shields.io/badge/License-Apache_2.0-green)

**WPT-Gen** is a CLI tool designed to increase browser interoperability by
automating the creation of [Web Platform Tests (WPT)](https://web-platform-tests.org/).

It acts as an agentic workflow that connects W3C Specifications with your local
WPT repository. By leveraging Large Language Models, WPT-Gen proactively
identifies gaps in test coverage for specific web features and generates
tests to fill those gaps.

---

## Key Features

* **Context Assembly:** Automatically aggregates knowledge by resolving W3C Spec
  URLs and MDN documentation via `web-features` ID lookups.
* **Automated Gap Analysis:** Compares the feature's testing requirements
  against existing test files to identify "Missing Assertions".
* **Code Generation:** Generates atomic, compliant test files.

---

## Prerequisites

Before installing, ensure you have the following:

1.  **Python 3.10+** installed.
2.  A local checkout of the
    **[web-platform-tests](https://github.com/web-platform-tests/wpt)**
    repository.
3.  An API Key for a compatible LLM provider.

---

## Installation

TODO

### Configuration

1. **Environment Variables:**
You must export your LLM API key. This key is never saved to disk.

```bash
export GEMINI_API_KEY="your_api_key_here"

```

---

## Usage

The primary interface is the `generate` command. You must provide a
**Web Feature ID** (as defined in
[web-features](https://github.com/web-platform-dx/web-features)).

### Basic Generation

```bash
wpt-gen generate --web-feature-id "counter-set"

```

### Options

TODO

---

## Limitations & Scope

* **Context Limits:** Very large specifications may hit token limits depending
  on the LLM model used.

---

## License

Apache 2.0. See [LICENSE](https://www.google.com/search?q=LICENSE) for more
information.

## Source Code Headers

Every file containing source code must include copyright and license
information. This includes any JS/CSS files that you might be serving out to
browsers. (This is to help well-intentioned people avoid accidental copying that
doesn't comply with the license.)

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

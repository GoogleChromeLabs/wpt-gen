# WPT-Gen Workflow Phases

The `wpt-gen generate` command orchestrates a complex, multi-phase agentic workflow to create Web Platform Tests. This document details the internal logic, responsibilities, inputs, outputs, and LLM integrations for each individual phase located in the `wptgen/phases/` module.

## Phase 1: Context Assembly (`context_assembly.py`)

*   **Responsibility:** Aggregates the "Source of Truth" from external documentation (W3C Specs, MDN) and identifies existing test coverage in the local WPT repository.
*   **Inputs:** `web_feature_id` (string), `Config` object, `UIProvider`.
*   **Outputs:** A hydrated `WorkflowContext` object containing the web-features metadata, scraped specification context, and local WPT tree paths.
*   **LLM Integration:** None. This phase is entirely focused on gathering local and remote factual data deterministically to feed the subsequent phases.

## Phase 2: Requirements Extraction (`requirements_extraction.py`)

*   **Responsibility:** Synthesizes specification text into structured, granular technical requirements. It supports parallel, categorized, and iterative extraction modes for complex or large specs.
*   **Inputs:** `WorkflowContext` (containing the spec context), `Config`, `LLMClient`, `UIProvider`, `jinja_env`, and an optional cache directory `Path`.
*   **Outputs:** A string of XML containing the extracted requirements, which is then attached to `WorkflowContext.requirements_xml`.
*   **LLM Integration:** Uses the LLM extensively to process the raw HTML/text of the spec and transform normative statements into isolated, testable requirements. It utilizes three different versions of prompts depending on configuration flags:
    *   **Categorized (Default):** Extracts requirements mapped to logical categories (e.g., API behavior, security, IDL).
        *   **System Prompt:** `requirements_extraction_categorized_system.jinja`
        *   **User Prompt:** `requirements_extraction_categorized.jinja`
    *   **Iterative (via `--detailed-requirements` flag):** Iterates through the specification chunk by chunk for very large and complex specs.
        *   **System Prompt:** `requirements_extraction_iterative_system.jinja`
        *   **User Prompt:** `requirements_extraction_iterative.jinja`
    *   **Single Prompt (via `--single-prompt-requirements` flag):** A simpler approach attempting extraction in a single pass without categorization.
        *   **System Prompt:** `requirements_extraction_system.jinja`
        *   **User Prompt:** `requirements_extraction.jinja`

## Phase 3: Coverage Audit (`coverage_audit.py`)

*   **Responsibility:** Performs a delta analysis by comparing the synthesized requirements against the local test suite. This phase identifies gaps in coverage and produces high-level test blueprints.
*   **Inputs:** `WorkflowContext` (with requirements and local test tree), `Config`, `LLMClient`, `UIProvider`, `jinja_env`.
*   **Outputs:** A string of XML representing the audit response (including missing test blueprints), saved to `WorkflowContext.audit_response`.
*   **LLM Integration:** Uses the LLM to cross-reference extracted requirements with existing test files to intelligently determine what new tests are needed. It automatically partitions requirements into chunks (e.g., `max_threshold=40`) to remain within context limits.
    *   **System Prompt:** `coverage_audit_system.jinja`
    *   **User Prompt:** `coverage_audit.jinja`

## Phase 4: Test Generation (`generation.py`)

*   **Responsibility:** Translates user-selected blueprints into functional WPT-compliant code (e.g., JavaScript tests, Reftests, or Crashtests) using specific style guide instructions.
*   **Inputs:** `WorkflowContext` (with the audit response/blueprints), `Config`, `LLMClient`, `UIProvider`, `jinja_env`.
*   **Outputs:** A list of generated test files, each represented as a tuple of `(Path, string content, suggestion_xml)`. Saves the initial versions of these files to disk.
*   **LLM Integration:** The LLM receives the test blueprint, WPT authoring guidelines, and relevant spec context to generate valid, idiomatic code for the new test files.
    *   **System Prompt:** `test_generation_system.jinja`
    *   **User Prompt:** `test_generation.jinja`

## Phase 5: Evaluation (`evaluation.py`)

*   **Responsibility:** Acts as a secondary self-correction step. It reviews the newly generated code against WPT standards and the original requirements, providing fixes or optimizations before final output.
*   **Inputs:** `WorkflowContext`, `Config`, `LLMClient`, `UIProvider`, `jinja_env`, and the `generated_tests` list from Phase 4.
*   **Outputs:** Updates the generated files in place on disk with improved, evaluated versions.
*   **LLM Integration:** Feeds the generated code back into the LLM alongside an evaluation prompt to scrutinize the logic, API usage, and syntax, correcting any hallucinations or errors.
    *   **System Prompt:** `evaluation_system.jinja`
    *   **User Prompt:** `evaluation.jinja`

## Phase 6: Test Execution & Self-Correction (`execution.py`)

*   **Responsibility:** Validates the tests by integrating with the local `./wpt run` CLI to execute the generated code in a real browser environment. If tests fail, it enters an iterative self-correction loop.
*   **Inputs:** `WorkflowContext`, `Config`, `LLMClient`, `UIProvider`, `jinja_env`, and the `generated_tests` list.
*   **Outputs:** Terminal output of test results. If the LLM successfully corrects a failing test, the files on disk are updated.
*   **LLM Integration:** Automatically parses the error logs from the `wpt run` subprocess, feeds the stack traces and error output back into the LLM, and requests dynamic code corrections to resolve the failures.
    *   **System Prompt:** `correction_system.jinja`
    *   **User Prompt:** `correction.jinja`
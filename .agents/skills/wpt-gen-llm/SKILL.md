---
name: wpt-gen-llm
description: Best practices for configuring LLM integrations, concurrent networking, context scraping, and managing prompts in WPT-Gen.
---

# WPT-Gen LLM Skills

This document outlines the best practices for LLM integrations, prompt pipeline safety, and context extraction within the `wpt-gen` repository.

## 1. Multi-Provider Support

WPT-Gen supports Google Gemini, OpenAI, and Anthropic models via a unified abstraction.

- **Google GenAI (`google-genai`):** Used primarily for deep context reasoning (e.g., `gemini-3.1-pro-preview`) and fast generation (`gemini-3-flash-preview`). API keys are read from `GEMINI_API_KEY`.
- **OpenAI (`openai`):** Used as an alternative provider. API keys are read from `OPENAI_API_KEY`.
- **Anthropic (`anthropic`):** Used as an alternative provider (Claude models). API keys are read from `ANTHROPIC_API_KEY`.

## 2. Phase-Based Model Mapping

The agentic workflow uses different model categories based on the complexity of the task, as configured in `wpt-gen.yml`.

- **Reasoning Models:** Used for complex analysis and extraction.
    - **Requirements Extraction**: Identifies normative requirements from spec text.
    - **Coverage Audit**: Performs deep gap analysis against existing tests.
- **Lightweight Models:** Used for rapid generation and iterative refinement.
    - **Test Generation**: Produces test code based on audit blueprints.
    - **Evaluation**: Performs self-correction and validation of generated code.

## 3. Network Architecture (Context Extraction)

Providing context is critical for minimizing hallucinations, but it involves extensive network I/O blockades.

- **Concurrent I/O:** Always use `asyncio.gather` combined with `asyncio.to_thread` for concurrent network requests (e.g. fetching 5 MDN explainer URLs at once). Blocking sequential `for` loops across network dependencies creates catastrophic UI lag.
- **Missing Failsafes:** Reviewers must actively flag blocking network requests that lack exponential retry logic/backoff for `HTTPError 429` (Too Many Requests). Do not depend on LLMs blindly surviving a dropped HTTP request.
- **Trafilatura:** WPT-Gen uses `trafilatura` to extract dense text from W3C Specification URLs linked to web features.

## 4. Prompt Management & Defensive Context

Prompt structure determines output quality, but unbounded inputs determine runtime OOM exceptions. 

- **Defensive Paging (OOM/Token Limits):** Native memory limits and LLM token limits require defensive programming. If ingesting massive terminal runner logs into the context window, slice the array to only keep the *tail end* to remain token-efficient. If querying expansive file directory contents, return or exit early when numerical limits are hit rather than crashing. 
- **Context Bloat:** Ensure large, optional prompt dependencies (like MDN explainers) are safely guarded behind Jinja `{% if %}` statements to avoid feeding the LLM empty strings when variables map to null.
- **Clear Instructions:** Ensure system prompts clearly dictate the agent's persona (expert test engineer) and the expected format.
- **XML Output:** When requesting structured data (like gap analysis or test blueprints), explicitly request XML format and provide the intended schema structure. This allows WPT-Gen to parse and programmatically act on the AI output.

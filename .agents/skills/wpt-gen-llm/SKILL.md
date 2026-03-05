---
name: wpt-gen-llm
description: Best practices for configuring LLM integrations, provider configuration, context scraping, and managing prompts in WPT-Gen.
---

# WPT-Gen LLM Skills

This document outlines the best practices for LLM integrations within the `wpt-gen` repository.

## 1. Multi-Provider Support

WPT-Gen supports both Google Gemini and OpenAI models via a unified abstraction.

- **Google GenAI (`google-genai`):** Used primarily for deep context reasoning (e.g., `gemini-3.1-pro-preview`) and fast generation (`gemini-3-flash-preview`). API keys are read from `GEMINI_API_KEY`.
- **OpenAI (`openai`):** Used as an alternative provider. API keys are read from `OPENAI_API_KEY`.
- **Configuration:** Model mapping rules (which model category is used for which generation phase) are defined in `wpt-gen.yml`.

## 2. Context Scraping

Providing accurate, up-to-date context is critical for minimizing hallucinations.

- **Trafilatura:** WPT-Gen uses `trafilatura` to extract text from W3C Specification URLs linked to web features.

## 3. Prompt Management

Prompt structure determines the output quality.

- **Clear Instructions:** Ensure system prompts clearly dictate the agent's persona (expert test engineer) and the expected format.
- **Few-Shot Prompting:** When generating precise test structures (e.g., testharness.js output), provide examples of well-formed WPT tests within the prompt.
- **XML Output:** When requesting structured data (like gap analysis or test blueprints), explicitly request XML format and provide the intended schema structure. This allows WPT-Gen to parse and programmatically act on the AI output.

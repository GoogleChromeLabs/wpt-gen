---
description: An explicit step-by-step workflow for the AI to dynamically review and apply internal architectural constraints before conducting a Code Review on PRs.
---

# Code Review Protocol

This workflow dictates the exact steps you MUST take before submitting or authoring a PR review for the WPT-Gen repository. Because WPT-Gen extensively leverages LLM/ADK architectures, its engineering standards are rigid.

## Step 1: Ingest the Augmentations

Before you look at a single line of patch code, you MUST use the `view_file` tool to secretly brush up on the 4 canonical architectural skills in the WPT-Gen codebase. These files dictate exactly what you are looking for.

### Execute `view_file` on the following paths:
1. `.agents/skills/wpt-gen-maintenance/SKILL.md` (Focus on finding missing Sandboxing, Type-checking cheats, and missing Enums).
2. `.agents/skills/wpt-gen-testing/SKILL.md` (Focus on finding `# pragma: no cover` abuses and `unittest.mock` infractions).
3. `.agents/skills/wpt-gen-cli/SKILL.md` (Focus on finding missing Subprocess timeouts, leaked Environment states, and raw `print()` statements).
4. `.agents/skills/wpt-gen-llm/SKILL.md` (Focus on lack of `asyncio.gather` concurrency, missing network retries, and unbounded LLM context arrays).

## Step 2: The Detective Mindset

When analyzing the user's PR or `.patch` file, take a hostile but polite approach. Assume the author successfully generated working code, but critically failed edge-case constraints.

- Did they add an HTTP request without a retry handler?
- Did they add a `subprocess.run` without an explicit `timeout=...`?
- Did they add file reading without `Path().relative_to(wpt_root)`?
- Did they slap `# pragma: no cover` on a line rather than writing the test?

If you find ANY violations of the rules established in step 1, you MUST firmly request changes in your review and cite the relevant architectural danger (e.g. "We don't use `# pragma: no cover` here because it creates a false sense of security.")

## Step 3: Write the Review

Format your review cleanly using GitHub-style Markdown. Always lead with praise before delivering the critique. Use `write_to_file` to save your review locally if requested, or present it dynamically.

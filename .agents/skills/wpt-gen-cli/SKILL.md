---
name: wpt-gen-cli
description: Best practices for CLI infrastructure, outputs, subprocess management, and templating in WPT-Gen.
---

# WPT-Gen CLI Skills

This document outlines the best practices for working with the CLI infrastructure in the `wpt-gen` repository.

## 1. CLI Framework: Typer

WPT-Gen uses [Typer](https://typer.tiangolo.com/) for building its command-line interface.

- **Routing:** Define subcommands and groups using `@app.command()` decorators.
- **Type Hints:** Rely heavily on Python type hints to automatically generate CLI arguments and options.
- **Common Options:** Most commands (especially `generate`) support a standard set of flags:
    - `--provider` (`-p`): Override the LLM provider (`gemini`, `openai`, `anthropic`).
    - `--wpt-dir` (`-w`): Override the local web-platform-tests repository path.
    - `--config` (`-c`): Path to a custom `wpt-gen.yml`.
    - `--show-responses` (`-s`): Display raw LLM-generated responses.
    - `--use-lightweight` / `--use-reasoning`: Force a specific model category.

## 2. Rich Console Output & Abstraction

For displaying information to the user, WPT-Gen utilizes [Rich](https://rich.readthedocs.io/en/stable/).

- **Strict UIProvider Abstraction:** Never use the native `print()` function. You must route all outputs through the injected `UIProvider` dependency (e.g. `ui.print`, `ui.warning`, `ui.error`).
- **Styling:** Use `rich.print` (via `UIProvider`) for colored and formatted output.
- **Panels & Tables:** Use `rich.panel.Panel` to encapsulate related information (like summarizing test plans) and `rich.table.Table` for structured data, rather than dumping raw JSON or concatenated strings to the CLI.
- **Progress Bars:** When iterating over long-running LLM calls, use `ui.status()` wrappers to provide visual `rich.progress` spinners to the user so they know the command has not hung.

## 3. Subprocess execution & Wrappers

WPT-Gen heavily relies on executing native binaries (`wpt lint`, `grep`) to empower LLM agents. 

- **Subprocess Stability (Hung Agents):** Autonomous agents will hang indefinitely if tools don't return. When using `subprocess.run()`, you must **always** provide explicit `timeout=...` constraints, otherwise a rogue blocking command will freeze the AI forever.
- **Environment Context Leaking:** Subprocess calls must construct and pass explicit `env={**os.environ, "CUSTOM": "VAL"}` mappings, rather than lazily mutating the global `os.environ` which bleeds state across Python threads. Reviewers must actively catch environment leaking.
- **Shell Injection & Compat:** When wrapping native CLI execution tools (e.g., `git grep` or `grep`), scrutinize custom arguments for shell injection vulnerabilities. Force the use of the `--` argument separator to securely separate binary options from user-generated patterns.

## 4. Templating with Jinja2

WPT-Gen uses Jinja2 to template both prompts to the LLM and the final generated output (HTML/JS files).

- **Location:** Templates are typically stored in the `wptgen/templates/` directory.
- **Variable Injection:** Use standard Jinja2 syntax (`{{ variable_name }}`) to inject context retrieved via `trafilatura` or derived from local scans.
- **Control Structures:** Utilize standard `{% if %}` and `{% for %}` loops to dynamically construct test structures based on the suggested test footprint. Ensure large, nullable dependencies are robustly guarded behind `{% if %}` conditions to avoid causing context bloat.

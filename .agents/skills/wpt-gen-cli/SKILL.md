---
name: wpt-gen-cli
description: Best practices for CLI infrastructure, outputs, and templating in WPT-Gen.
---

# WPT-Gen CLI Skills

This document outlines the best practices for working with the CLI infrastructure in the `wpt-gen` repository.

## 1. CLI Framework: Typer

WPT-Gen uses [Typer](https://typer.tiangolo.com/) for building its command-line interface.

- **Routing:** Define subcommands and groups using `@app.command()` decorators.
- **Type Hints:** Rely heavily on Python type hints to automatically generate CLI arguments and options (e.g., `web_feature_id: str = typer.Argument(...)`).
- **Options:** Use `typer.Option` for defining named flags (e.g., `--provider`, `--wpt-dir`). Provide clear `help` strings.

## 2. Rich Console Output

For displaying information to the user, WPT-Gen utilizes [Rich](https://rich.readthedocs.io/en/stable/).

- **Styling:** Use `rich.print` (often imported as `from rich import print`) for colored and formatted output.
- **Panels & Tables:** Use `Panel` to encapsulate related information (like summarizing the generated test plan) and `Table` for structured data.
- **Progress Bars:** When iterating over long-running LLM calls out, use `rich.progress` to provide visual feedback to the user so they know the command has not hung.

## 3. Templating with Jinja2

WPT-Gen uses Jinja2 to template both prompts to the LLM and the final generated output (HTML/JS files).

- **Location:** Templates are typically stored in the `wptgen/templates/` directory.
- **Variable Injection:** Use standard Jinja2 syntax (`{{ variable_name }}`) to inject context retrieved via `trafilatura` or derived from local scans.
- **Control Structures:** Utilize standard `{% if %}` and `{% for %}` loops to dynamically construct test structures based on the suggested test footprint.

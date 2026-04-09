# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Semantic UI interface and Rich-based implementation for the WPT workflow."""

from __future__ import annotations

import difflib
import re
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

from wptgen.utils import parse_multi_file_response

if TYPE_CHECKING:
    from wptgen.models import FeatureMetadata


class ProgressIndicator(Protocol):
    """Interface for updating a progress indicator."""

    def advance(self, amount: float = 1) -> None:
        ...

    def update(
        self, description: str | None = None, outstanding: int | None = None
    ) -> None:
        ...


class UIProvider(Protocol):
    """Semantic UI interface for the WPT generation workflow."""

    # Core interaction
    def status(self, message: str) -> AbstractContextManager[Any]:
        ...

    def progress_indicator(
        self, description: str, total: int
    ) -> AbstractContextManager[ProgressIndicator]:
        ...

    def confirm(self, question: str, default: bool = True) -> bool:
        ...

    def prompt(self, question: str, default: str = "") -> str:
        ...

    # Generic semantic messaging
    def print(self, message: Any = "", style: str | None = None) -> None:
        ...

    def stream_text(self, text: str) -> None:
        ...

    def info(self, message: str) -> None:
        ...

    def success(self, message: str) -> None:
        ...

    def warning(self, message: str) -> None:
        ...

    def error(self, message: str) -> None:
        ...

    def print_diff(self, old_text: str, new_text: str, file_path: str) -> None:
        ...

    # Phase and lifecycle events
    def on_phase_start(
        self, phase_num: int, phase_name: str, model_info: str | None = None
    ) -> None:
        ...

    def on_phase_complete(self, phase_name: str) -> None:
        ...

    # Domain-specific reporting
    def report_metadata(self, metadata: FeatureMetadata) -> None:
        ...

    def report_context_summary(
        self,
        spec_len: int,
        explainer_count: int | None = None,
        mdn_count: int | None = None,
        test_count: int | None = None,
        dep_count: int | None = None,
    ) -> None:
        ...

    def report_token_usage(
        self,
        phase_name: str,
        model: str,
        results: list[tuple[int, bool, str]],
        total_tokens: int,
        auto_confirmed: bool = False,
    ) -> None:
        ...

    def report_llm_response(self, response: str, task_name: str) -> None:
        ...

    def report_coverage_audit(self, audit_response: str | None = None) -> None:
        ...

    def report_audit_worksheet(self, worksheet_text: str) -> None:
        ...

    def report_test_suggestion(
        self,
        suggestion_index: int,
        title: str,
        description: str,
        test_type: str | None = None,
    ) -> None:
        ...

    def report_generation_start(self, count: int) -> None:
        ...

    def report_test_generated(
        self,
        root_name: str,
        success: bool,
        path: Path | None = None,
        fallback: bool = False,
    ) -> None:
        ...

    def report_generation_summary(
        self, generated_tests: list[tuple[Path, str, str]]
    ) -> None:
        ...


class RichUIProvider:
    """Rich-based implementation of the UIProvider protocol."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def status(self, message: str) -> AbstractContextManager[Any]:
        return self.console.status(message)

    def report_configuration(self, config_data: dict[str, str]) -> None:
        from rich.table import Table
        from rich.panel import Panel

        table = Table.grid(padding=(0, 2))  # Headless table for alignment
        table.add_column(style="bold")
        table.add_column(style="green")

        for key, val in config_data.items():
            table.add_row(f"{key}:", val)

        self.console.print(
            Panel(
                table,
                title="[bold]Configuration[/bold]",
                title_align="left",
                expand=False,
                border_style="bright_black",
            )
        )

    @contextmanager
    def progress_indicator(
        self, description: str, total: int
    ) -> Generator[ProgressIndicator, None, None]:
        """Provides a context manager for a progress indicator."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task_id = progress.add_task(description, total=total)

            class _Indicator:
                """Inner helper to advance and update the progress task."""

                def advance(self, amount: float = 1) -> None:
                    progress.advance(task_id, advance=amount)

                def update(
                    self,
                    description: str | None = None,
                    outstanding: int | None = None,
                ) -> None:
                    """Updates the description and outstanding count."""
                    kwargs: dict[str, Any] = {}
                    if description is not None:
                        if outstanding is not None:
                            kwargs["description"] = (
                                f"{description} ({outstanding} outstanding)"
                            )
                        else:
                            kwargs["description"] = description
                    progress.update(task_id, **kwargs)

            yield _Indicator()

    def confirm(self, question: str, default: bool = True) -> bool:
        return Confirm.ask(question, default=default)

    def prompt(self, question: str, default: str = "") -> str:
        from rich.prompt import Prompt

        return Prompt.ask(question, default=default)

    def print(self, message: Any = "", style: str | None = None) -> None:
        self.console.print(message, style=style)

    def stream_text(self, text: str) -> None:
        self.console.out(text, end="")

    def info(self, message: str) -> None:
        self.console.print(f"[blue]ℹ[/blue] {message}")

    def success(self, message: str) -> None:
        self.console.print(f"[bold green]✔[/bold green] {message}")

    def warning(self, message: str) -> None:
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[bold red]✘[/bold red] {message}")

    def print_diff(self, old_text: str, new_text: str, file_path: str) -> None:
        """Displays a unified diff between two strings."""
        diff = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )
        if diff:
            diff_text = "\n".join(diff)
            self.console.print(
                Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
            )

    def on_phase_start(
        self, phase_num: int, phase_name: str, model_info: str | None = None
    ) -> None:
        self.console.print()
        self.console.rule(f"[bold cyan]Phase {phase_num}: {phase_name}")
        if model_info:
            self.console.print(f"[dim]Using model: {model_info}[/dim]")
        self.console.print()

    def on_phase_complete(self, phase_name: str) -> None:
        self.success(f"{phase_name} complete.")

    def report_metadata(self, metadata: FeatureMetadata) -> None:
        """Displays a panel with feature metadata."""
        metadata_table = Table(show_header=False, box=None, padding=(0, 2))
        metadata_table.add_row(
            "[bold]Web Feature Name:[/bold]", f"[cyan]{metadata.name}[/cyan]"
        )
        metadata_table.add_row(
            "[bold]Description:[/bold]", metadata.description
        )
        metadata_table.add_row(
            "[bold]Spec URL:[/bold]", f"[blue]{metadata.specs[0]}[/blue]"
        )

        if metadata.explainer_links:
            explainer_links = "\n".join(metadata.explainer_links)
            metadata_table.add_row(
                "[bold]Explainer URLs:[/bold]",
                f"[blue]{explainer_links}[/blue]",
            )

        self.console.print(
            Panel(
                metadata_table,
                title="[bold]Feature Metadata[/bold]",
                border_style="blue",
                expand=False,
            )
        )

    def report_context_summary(
        self,
        spec_len: int,
        explainer_count: int | None = None,
        mdn_count: int | None = None,
        test_count: int | None = None,
        dep_count: int | None = None,
    ) -> None:
        """Displays a summary of the gathered context."""
        parts = [f"{spec_len} chars of spec"]
        if explainer_count is not None:
            parts.append(f"{explainer_count} explainers")
        if mdn_count is not None:
            parts.append(f"{mdn_count} MDN pages")
        if test_count is not None:
            parts.append(f"{test_count} tests")
        if dep_count is not None:
            parts.append(f"{dep_count} dependency files")

        self.success(f'Context gathered: {", ".join(parts)}.')

    def report_token_usage(
        self,
        phase_name: str,
        model: str,
        results: list[tuple[int, bool, str]],
        total_tokens: int,
        auto_confirmed: bool = False,
    ) -> None:
        """Displays a summary of token usage for a phase."""
        table = Table(
            title=f"Token Usage Summary ({phase_name})",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Task", style="dim")
        table.add_column("Model", style="blue")
        table.add_column("Tokens", justify="right", style="cyan")
        table.add_column("Status", justify="center")

        for tokens, limit_exceeded, name in results:
            status = (
                "[bold red]EXCEEDED[/bold red]"
                if limit_exceeded
                else "[bold green]OK[/bold green]"
            )
            table.add_row(name, model, str(tokens), status)

        self.console.print(table)
        if len(results) > 1:
            self.console.print(
                f"[bold]Total Estimated Tokens:[/bold] "
                f"[cyan]{total_tokens}[/cyan]"
            )

        if any(limit_exceeded for _, limit_exceeded, _ in results):
            self.console.print(
                "\n[bold red]Warning:[/bold red] One or more prompts exceed "
                "the model context limit!"
            )

        if auto_confirmed:
            self.console.print(
                "\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]"
            )

    def report_llm_response(self, response: str, task_name: str) -> None:
        """Displays the raw LLM response with syntax highlighting."""
        # Determine syntax highlighting based on content (defaulting to xml).
        syntax_lexer = "xml"
        parsed_files = parse_multi_file_response(response)

        if parsed_files:
            suffix = parsed_files[0][0].lower()
            if suffix.endswith(".js"):
                syntax_lexer = "javascript"
            elif suffix.endswith(".html"):
                syntax_lexer = "html"
        else:
            # Fallback to current logic if no file tags found
            if "gen:" in task_name.lower() or "eval:" in task_name.lower():
                syntax_lexer = "html"

        syntax = Syntax(
            response,
            syntax_lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.console.print(
            Panel(
                syntax,
                title=f"[bold]LLM Response: {task_name}[/bold]",
                border_style="cyan",
                expand=False,
            )
        )

    def report_coverage_audit(self, audit_response: str | None = None) -> None:
        """Displays the coverage audit report."""
        self.console.print()
        self.console.rule("[bold cyan]Coverage Audit Report")
        self.console.print()
        if audit_response:
            self.console.print(Markdown(audit_response))
            self.console.print()

    def report_audit_worksheet(self, worksheet_text: str) -> None:
        """Displays a table showing the coverage audit worksheet."""
        table = Table(
            title="Coverage Audit Worksheet",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("ID", style="dim")
        table.add_column("Requirement")
        table.add_column("Status", justify="center")

        # Regex to parse lines like:
        # R1: [Requirement Text] -> [COVERED by filename.html]
        # or R1: [Requirement Text] -> [UNCOVERED]
        pattern = re.compile(r"^(R\d+):\s*(.*)\s*->\s*\[(.*)\]", re.MULTILINE)

        matches = list(pattern.finditer(worksheet_text))
        # Sort by numerical value of the ID (e.g., R1, R2, R10)
        matches.sort(key=lambda m: int(m.group(1)[1:]))

        for match in matches:
            req_id, req_text, status_info = match.groups()

            if "UNCOVERED" in status_info.upper():
                status_display = f"[bold red]✘ {status_info}[/bold red]"
            else:
                status_display = f"[green]✔ {status_info}[/green]"

            table.add_row(req_id, req_text.strip(), status_display)

        self.console.print(table)
        self.console.print()

    def report_test_suggestion(
        self,
        suggestion_index: int,
        title: str,
        description: str,
        test_type: str | None = None,
    ) -> None:
        """Displays a panel with a single test suggestion."""
        content = f"[bold cyan]Description:[/bold cyan] {description}"
        if test_type:
            content += f"\n[bold cyan]Test Type:[/bold cyan] {test_type}"

        title_str = (
            f"[bold cyan] Test Suggestion #{suggestion_index}:[/bold cyan] "
            f"[white]{title}[/white]"
        )
        self.console.print(
            Panel(
                content,
                title=title_str,
                border_style="blue",
                expand=False,
            )
        )

    def report_generation_start(self, count: int) -> None:
        """Displays the start of the test generation phase."""
        self.console.print(
            f"\nGenerating [bold]{count}[/bold] tests in parallel..."
        )

    def report_test_generated(
        self,
        root_name: str,
        success: bool,
        path: Path | None = None,
        fallback: bool = False,
    ) -> None:
        """Reports the successful or failed generation of a single test."""
        if success:
            path_str = str(path.absolute()) if path else ""
            if fallback:
                self.console.print(
                    f"[green]✔ Saved (fallback):[/green] {path_str}"
                )
            else:
                self.console.print(f"[green]✔ Saved:[/green] {path_str}")
        else:
            self.error(f"Failed to generate: {root_name}")

    def report_generation_summary(
        self, generated_tests: list[tuple[Path, str, str]]
    ) -> None:
        """Displays a summary table of all generated tests and support files."""
        if generated_tests:
            summary_table = Table(
                title="Generated Files Summary",
                show_header=True,
                header_style="bold green",
            )
            summary_table.add_column("File Name", style="cyan")
            summary_table.add_column("Full Path", style="dim")
            summary_table.add_column("Type", style="magenta")

            breakdown: dict[str, int] = {}
            for p, _content, _s_xml in generated_tests:
                file_type = "Core Test"
                if p.name == "WEB_FEATURES.yml":
                    file_type = "Config File"
                elif p.name.endswith(
                    ("-ref.html", "-ref.js", "-ref.any.js", "-ref.sub.html")
                ):
                    file_type = "Reference File"
                elif p.name.endswith((".headers", ".txt")):
                    file_type = "Support File"

                breakdown[file_type] = breakdown.get(file_type, 0) + 1
                summary_table.add_row(p.name, str(p.absolute()), file_type)

            self.console.print()
            self.console.print(summary_table)

            self.console.print("[bold cyan]Breakdown:[/bold cyan]")
            for category, count in breakdown.items():
                self.console.print(f"  - {category}: {count}")

            self.success(
                f"{len(generated_tests)} files created or updated successfully."
            )
        else:
            self.error("No files were successfully created.")

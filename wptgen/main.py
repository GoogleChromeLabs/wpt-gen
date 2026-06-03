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

"""Main entry point for the WPT-Gen CLI."""

import asyncio
import dataclasses
import logging
import os
import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as app_version
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from wptgen.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_PROVIDER_MODELS,
    _get_global_config_path,
    load_config,
)
from wptgen.context import (
    extract_feature_metadata,
    fetch_feature_yaml,
)
from wptgen.engine import WPTGenEngine
from wptgen.llm import LLMTimeoutError
from wptgen.metadata import update_web_features_yml
from wptgen.models import (
    BrowserChannel,
    BrowserType,
    ModelCategory,
    WorkflowAborted,
    WorkflowError,
    WorkflowPhase,
)
from wptgen.phases.evaluation import run_evaluation
from wptgen.phases.generation import (
    run_single_test_generation,
)
from wptgen.ui import RichUIProvider, UIProvider


class DimYellowWarningFormatter(logging.Formatter):
    """Custom formatter to render Python warnings as dim yellow."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if record.levelno == logging.WARNING:
            return f"\033[2;33m{msg}\033[0m"
        return msg


class SuppressDuplicateWarningFilter(logging.Filter):
    """Filters out duplicate warnings, specifically for API key noise."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_warning = False

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.levelno == logging.WARNING
            and "Both GOOGLE_API_KEY and GEMINI_API_KEY are set"
            in record.getMessage()
        ):
            if self.seen_warning:
                return False
            self.seen_warning = True
        return True


class SuppressNonTextWarningFilter(logging.Filter):
    """Filters out noisy non-text parts warnings from google-genai."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.levelno == logging.WARNING
            and "there are non-text parts in the response"
            in record.getMessage()
        ):
            return False
        return True


# Apply the custom warning formatter globally
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(
    DimYellowWarningFormatter("%(levelname)s:%(name)s:%(message)s")
)
logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)

logging.getLogger("google_genai._api_client").addFilter(
    SuppressDuplicateWarningFilter()
)
logging.getLogger("google_genai.types").addFilter(
    SuppressNonTextWarningFilter()
)

# Initialize Typer app
app = typer.Typer(
    name="wpt-gen",
    help="AI-Powered Web Platform Test Generation CLI",
    add_completion=False,
)


def _check_workflow_flags(
    ui: UIProvider,
    wf_yml_update: bool,
    output_dir: Path | None,
    use_lightweight: bool,
    use_reasoning: bool,
    yes_cache: bool,
    no_cache: bool,
    detailed_requirements: bool,
    single_prompt_requirements: bool,
) -> None:
    """Validates conflicting or missing CLI flags for the workflow.

    Args:
        ui: The UI provider for reporting errors.
        wf_yml_update: Whether to update WEB_FEATURES.yml.
        output_dir: Target directory for generated tests.
        use_lightweight: Whether lightweight model is requested.
        use_reasoning: Whether reasoning model is requested.
        yes_cache: Whether to force cache use.
        no_cache: Whether to disable cache.
        detailed_requirements: Whether iterative extraction is requested.
        single_prompt_requirements: Whether legacy extraction is requested.

    Raises:
        typer.Exit: If flag combinations are invalid.
    """
    if wf_yml_update and not output_dir:
        ui.error("--output-dir is required when using --wf-yml-update.")
        raise typer.Exit(code=1)

    if use_lightweight and use_reasoning:
        ui.error("Cannot use both --use-lightweight and --use-reasoning.")
        raise typer.Exit(code=1)

    if yes_cache and no_cache:
        ui.error("Cannot use both --yes-cache and --no-cache.")
        raise typer.Exit(code=1)

    if detailed_requirements and single_prompt_requirements:
        ui.error(
            "Cannot use both --detailed-requirements and "
            "--single-prompt-requirements."
        )
        raise typer.Exit(code=1)


def _print_workflow_banner(ui: UIProvider, feature_id: str) -> None:
    """Prints a stylized banner and target feature info to the console.

    Args:
        ui: The UI provider for the workflow.
        feature_id: The ID of the feature being processed.
    """
    banner = Panel(
        Align.center(
            Text.from_markup(
                "[bold blue]WPT[/bold blue][bold white]-"
                "[/bold white][bold green]Gen[/bold green]\n"
                "[italic white]AI-Powered Web Platform "
                "Test Generation[/italic white]"
            )
        ),
        border_style="bright_blue",
    )
    ui.print(banner)
    ui.print(f"\n[bold]Target Feature:[/bold] [cyan]{feature_id}[/cyan]\\n")


def _print_run_config(ui: UIProvider, config: Any) -> None:
    ui.report_configuration(
        {
            "Provider": config.provider,
            "Default": config.default_model,
            "Lightweight": config.categories.get("lightweight", "N/A"),
            "Reasoning": config.categories.get("reasoning", "N/A"),
        }
    )


@contextmanager
def _workflow_error_handler(ui: UIProvider) -> Generator[None, None, None]:
    """Context manager for handling top-level workflow exceptions.

    Args:
        ui: The UI provider for reporting errors.

    Yields:
        None
    """
    try:
        yield
    except LLMTimeoutError as e:
        ui.error(f"LLM Request Timeout: {str(e)}")
        raise typer.Exit(code=1) from e
    except ValueError as e:
        # Catch configuration errors (like missing API keys) and exit gracefully
        ui.error(f"Configuration Error: {str(e)}")
        raise typer.Exit(code=1) from e
    except WorkflowError:
        ui.print()
        ui.error("Workflow completed with errors.")
        raise typer.Exit(code=1) from None
    except Exception as e:
        # Catch unexpected runtime errors
        ui.error(f"Unexpected Error: {str(e)}")
        raise typer.Exit(code=1) from e


def _execute_workflow(
    ui: UIProvider,
    feature_id: str,
    config: Any,
    wf_yml_update: bool,
    output_dir: Path | None,
    is_audit: bool = False,
    disable_directory_inference: bool = False,
) -> None:
    """Instantiates the engine and runs the end-to-end workflow.

    Args:
        ui: The UI provider for the workflow.
        feature_id: The ID of the web feature.
        config: Resolved configuration object.
        wf_yml_update: Whether to update WEB_FEATURES.yml.
        output_dir: Directory to save tests.
        is_audit: Whether this is a suggestions-only audit run.
        disable_directory_inference: Whether to skip directory inference.
    """

    _print_run_config(ui, config)

    # Instantiate the core engine
    engine = WPTGenEngine(config=config, ui=ui)

    # Execute the workflow
    try:
        context = engine.run_workflow(
            feature_id,
            disable_directory_inference=disable_directory_inference,
        )
    except WorkflowAborted:
        ui.warning("Workflow aborted by user.")
        raise typer.Exit(1) from None

    if is_audit:
        ui.print()
        ui.success("Audit completed successfully! Test suggestions generated.")
    else:
        target_dir = output_dir or (
            Path(config.output_dir) if config.output_dir else None
        )
        if wf_yml_update and target_dir and context and context.generated_tests:
            generated_paths = [path for path, _, _ in context.generated_tests]
            update_web_features_yml(target_dir, feature_id, generated_paths)
            ui.success(f"Updated WEB_FEATURES.yml for {feature_id}")

        ui.print()
        ui.success("Workflow completed successfully!")


@app.command()
def generate(
    ctx: typer.Context,
    feature_id: Annotated[
        str,
        typer.Argument(
            help=(
                "The web feature ID to generate tests for "
                "(e.g., 'grid', 'popover')."
            )
        ),
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help=(
                "Override the default LLM provider "
                "(e.g., 'gemini', 'openai', 'anthropic')."
            ),
        ),
    ] = None,
    wpt_dir: Annotated[
        Path | None,
        typer.Option(
            "--wpt-dir",
            "-w",
            help="Path to the local web-platform-tests repository.",
            exists=True,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where generated tests will be saved.",
            dir_okay=True,
        ),
    ] = None,
    wf_yml_update: Annotated[
        bool,
        typer.Option(
            "--wf-yml-update",
            help="Update WEB_FEATURES.yml with generated tests.",
        ),
    ] = False,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
    show_responses: Annotated[
        bool,
        typer.Option(
            "--show-responses",
            "-s",
            help="Display every LLM-generated response to the user.",
        ),
    ] = False,
    yes_tokens: Annotated[
        bool,
        typer.Option(
            "--yes-tokens",
            help="Automatically confirm all token count prompts.",
        ),
    ] = False,
    yes_tests: Annotated[
        bool,
        typer.Option(
            "--yes-tests",
            help=(
                "Automatically confirm and generate all proposed test "
                "suggestions without prompting."
            ),
        ),
    ] = False,
    yes_cache: Annotated[
        bool,
        typer.Option(
            "--yes-cache",
            help="Automatically use the cache if it exists without prompting.",
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help=(
                "Automatically ignore and overwrite the cache if it exists "
                "without prompting."
            ),
        ),
    ] = False,
    suggestions_only: Annotated[
        bool,
        typer.Option(
            "--suggestions-only",
            help=(
                "Only show test suggestions and skip the test generation step."
            ),
        ),
    ] = False,
    brief_suggestions: Annotated[
        bool,
        typer.Option(
            "--brief-suggestions",
            help=(
                "Only generate test titles and descriptions for suggestions "
                "(omits detailed test suggestions)."
            ),
        ),
    ] = False,
    skip_run: Annotated[
        bool,
        typer.Option(
            "--skip-run",
            help="Opt out of running generated tests.",
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Resume the workflow from the last successful phase.",
        ),
    ] = False,
    resume_from: Annotated[
        WorkflowPhase | None,
        typer.Option(
            "--resume-from",
            help="Resume the workflow explicitly from a specific phase.",
        ),
    ] = None,
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            "--tests-dir",
            help=(
                "Directory containing the necessary artifacts to hydrate "
                "the requested phase."
            ),
            dir_okay=True,
            exists=True,
        ),
    ] = None,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="Maximum number of retries for LLM calls.",
        ),
    ] = 3,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Timeout for LLM requests in seconds.",
        ),
    ] = DEFAULT_LLM_TIMEOUT,
    spec_urls: Annotated[
        str | None,
        typer.Option(
            "--spec-urls",
            "-u",
            help=(
                "Comma-separated list of spec URLs to use, "
                "bypassing automatic fetching."
            ),
        ),
    ] = None,
    spec_url: Annotated[
        str | None,
        typer.Option(
            "--spec-url",
            help="A single specification URL for convenience.",
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            "-d",
            help="Manually provide a description for the web feature.",
        ),
    ] = None,
    detailed_requirements: Annotated[
        bool,
        typer.Option(
            "--detailed-requirements",
            help=(
                "Use a more detailed, iterative requirements extraction "
                "process."
            ),
        ),
    ] = False,
    include_mdn_docs: Annotated[
        bool,
        typer.Option(
            "--include-mdn-docs",
            help="Include MDN documentation in requirements extraction.",
        ),
    ] = False,
    include_thoughts: Annotated[
        bool,
        typer.Option(
            "--include-thoughts",
            help="Stream the underlying ADK model thoughts to stdout.",
        ),
    ] = False,
    draft: Annotated[
        bool,
        typer.Option(
            "--draft",
            help=(
                "Enable fetching metadata from the draft features directory."
            ),
        ),
    ] = False,
    single_prompt_requirements: Annotated[
        bool,
        typer.Option(
            "--single-prompt-requirements",
            help=(
                "Use a single-prompt requirements extraction process "
                "(legacy)."
            ),
        ),
    ] = False,
    use_lightweight: Annotated[
        bool,
        typer.Option(
            "--use-lightweight",
            help="Use the lightweight model for all LLM requests.",
        ),
    ] = False,
    use_reasoning: Annotated[
        bool,
        typer.Option(
            "--use-reasoning",
            help="Use the reasoning model for all LLM requests.",
        ),
    ] = False,
    tentative: Annotated[
        bool,
        typer.Option(
            "--tentative",
            help="Generate test files with the .tentative flag.",
        ),
    ] = False,
    save_traces: Annotated[
        bool,
        typer.Option(
            "--save-traces",
            help=(
                "Save LLM interaction traces to the .wptgen/traces/ "
                "directory."
            ),
        ),
    ] = False,
    audit_partition_size: Annotated[
        int | None,
        typer.Option(
            "--audit-partition-size",
            help=(
                "Number of requirements to evaluate per coverage audit "
                "partition."
            ),
        ),
    ] = None,
    max_parallel_requests: Annotated[
        int | None,
        typer.Option(
            "--max-parallel-requests",
            help="Maximum number of parallel asynchronous LLM requests.",
        ),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help=(
                "Global temperature setting for all LLM requests (e.g., "
                "0.01). Overrides phase-specific defaults."
            ),
        ),
    ] = None,
    run_on_browser: Annotated[
        BrowserType | None,
        typer.Option(
            "--run-on-browser",
            help="Browser to use for the local WPT test runner.",
        ),
    ] = None,
    run_on_channel: Annotated[
        BrowserChannel | None,
        typer.Option(
            "--run-on-channel",
            help="Release channel to use for the local WPT test runner.",
        ),
    ] = None,
) -> None:
    """
    Generate Web Platform Tests for a specific web feature.
    """
    ui = ctx.obj["ui"]

    _print_workflow_banner(ui, feature_id)
    _check_workflow_flags(
        ui=ui,
        wf_yml_update=wf_yml_update,
        output_dir=output_dir,
        use_lightweight=use_lightweight,
        use_reasoning=use_reasoning,
        yes_cache=yes_cache,
        no_cache=no_cache,
        detailed_requirements=detailed_requirements,
        single_prompt_requirements=single_prompt_requirements,
    )

    with _workflow_error_handler(ui):
        # Convert Path object back to string if it was provided, else pass None
        wpt_dir_str = str(wpt_dir) if wpt_dir else None
        output_dir_str = str(output_dir) if output_dir else None

        if spec_urls and spec_url:
            ui.print(
                "[red]Error: Cannot provide both --spec-urls and --spec-url. "
                "Please use only one.[/red]"
            )
            raise typer.Exit(code=1)

        # Parse spec_urls if provided
        spec_urls_list = None
        if spec_url:
            spec_urls_list = [spec_url.strip()]
        elif spec_urls:
            spec_urls_list = [u.strip() for u in spec_urls.split(",")]

        config = load_config(
            config_path=config_path,
            provider_override=provider,
            wpt_dir_override=wpt_dir_str,
            output_dir_override=output_dir_str,
            show_responses=show_responses,
            yes_tokens_override=yes_tokens,
            yes_tests_override=yes_tests,
            yes_cache_override=yes_cache,
            no_cache_override=no_cache,
            suggestions_only=suggestions_only,
            brief_suggestions=brief_suggestions,
            resume_override=resume,
            skip_run_override=skip_run,
            resume_from_override=resume_from,
            state_dir_override=str(state_dir) if state_dir else None,
            max_retries_override=max_retries,
            timeout_override=timeout,
            spec_urls_override=spec_urls_list,
            feature_description_override=description,
            detailed_requirements_override=detailed_requirements,
            include_mdn_docs_override=include_mdn_docs,
            draft_override=draft,
            single_prompt_requirements_override=single_prompt_requirements,
            use_lightweight_override=use_lightweight,
            use_reasoning_override=use_reasoning,
            tentative_override=tentative,
            save_traces_override=save_traces,
            audit_partition_size_override=audit_partition_size,
            max_parallel_requests_override=max_parallel_requests,
            temperature_override=temperature,
            include_thoughts_override=include_thoughts,
            run_on_browser_override=run_on_browser,
            run_on_channel_override=run_on_channel,
        )

        _execute_workflow(
            ui=ui,
            feature_id=feature_id,
            config=config,
            wf_yml_update=wf_yml_update,
            output_dir=output_dir,
            is_audit=False,
            disable_directory_inference=True,
        )


@app.command(name="generate-single")
def generate_single(
    ctx: typer.Context,
    description: Annotated[
        str,
        typer.Argument(help="The specific behavior description to test."),
    ],
    spec_urls: Annotated[
        str | None,
        typer.Option(
            "--spec-urls",
            help="Comma-separated list of specification URLs for the feature.",
        ),
    ] = None,
    spec_url: Annotated[
        str | None,
        typer.Option(
            "--spec-url",
            help="A single specification URL for convenience.",
        ),
    ] = None,
    feature_id: Annotated[
        str | None,
        typer.Option(
            "--feature-id",
            "-f",
            help="Optional web feature ID (e.g., 'grid', 'popover').",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Optional title for the test suggestion.",
        ),
    ] = None,
    test_type: Annotated[
        str | None,
        typer.Option(
            "--test-type",
            help="Optional test type (e.g., 'testharness', 'wdspec').",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Override the default LLM provider.",
        ),
    ] = None,
    wpt_dir: Annotated[
        Path | None,
        typer.Option(
            "--wpt-dir",
            "-w",
            help="Path to the local web-platform-tests repository.",
            exists=True,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where generated tests will be saved.",
            dir_okay=True,
        ),
    ] = None,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Generate a single test directly from a user description, bypassing earlier
    phases.
    """
    ui = ctx.obj["ui"]

    if spec_urls and spec_url:
        ui.error(
            "Error: Cannot provide both --spec-urls and --spec-url. "
            "Please use only one."
        )
        raise typer.Exit(code=1)

    if not spec_urls and not spec_url and not feature_id:
        ui.error(
            "Error: Either --spec-url, --spec-urls, or "
            "--feature-id must be provided."
        )
        raise typer.Exit(code=1)

    with _workflow_error_handler(ui):
        if spec_url:
            spec_urls_list = [spec_url.strip()]
        else:
            spec_urls_list = (
                [u.strip() for u in spec_urls.split(",")] if spec_urls else []
            )

        if not spec_urls_list and feature_id:
            feature_data = fetch_feature_yaml(feature_id)
            if feature_data:
                metadata = extract_feature_metadata(feature_data)
                if metadata.specs:
                    spec_urls_list = metadata.specs

        config = load_config(
            config_path=config_path,
            provider_override=provider,
            wpt_dir_override=str(wpt_dir) if wpt_dir else None,
            spec_urls_override=spec_urls_list,
            require_api_key=True,
        )

        if output_dir:
            config.output_dir = str(output_dir)

        _print_run_config(ui, config)

        ui.print()
        ui.warning(
            "Running in direct generation mode. Context "
            "assembly and duplicate test detection are disabled. The "
            "generated test may be redundant or less accurate."
        )

        engine = WPTGenEngine(config=config, ui=ui)

        generated_tests = asyncio.run(
            run_single_test_generation(
                feature_id=feature_id,
                spec_urls=spec_urls_list,
                description=description,
                title=title,
                test_type=test_type,
                config=config,
                ui=engine.ui,
                jinja_env=engine.jinja_env,
            )
        )

        ui.print()
        if generated_tests:
            ui.success("Test generation completed successfully!")
        else:
            ui.warning(
                "Test generation completed, but no tests were generated."
            )


@app.command(name="evaluate")
def evaluate(
    ctx: typer.Context,
    test_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the WPT test file to evaluate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help=(
                "Directory where the findings report will be written. "
                "Defaults to .wpt-evaluator-tmp/outputs/."
            ),
            dir_okay=True,
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Override the default LLM provider.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help=(
                "Override the default model for the chosen provider "
                "(e.g., 'claude-sonnet-4-6')."
            ),
        ),
    ] = None,
    wpt_dir: Annotated[
        Path | None,
        typer.Option(
            "--wpt-dir",
            "-w",
            help="Path to the local web-platform-tests repository.",
            exists=True,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Evaluate a single WPT test file against upstream WPT guidance and emit
    an advisory findings report. Does not run, modify, or lint the test.
    """
    ui = ctx.obj["ui"]

    with _workflow_error_handler(ui):
        config = load_config(
            config_path=config_path,
            provider_override=provider,
            model_override=model,
            wpt_dir_override=str(wpt_dir) if wpt_dir else None,
            require_api_key=True,
        )

        _print_run_config(ui, config)

        engine = WPTGenEngine(config=config, ui=ui)

        report_path = asyncio.run(
            run_evaluation(
                test_path=test_path,
                output_dir=output_dir,
                config=config,
                jinja_env=engine.jinja_env,
                ui=engine.ui,
            )
        )

        ui.print()
        if report_path:
            ui.success(f"Evaluation complete. Report written to: {report_path}")
        else:
            ui.warning(
                "Evaluation completed, but no report was produced."
            )


@app.command(name="chromestatus")
def chromestatus_command(
    ctx: typer.Context,
    feature_id: Annotated[
        str,
        typer.Argument(help='The ChromeStatus feature ID (e.g., "12345").'),
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help=(
                "Override the default LLM provider "
                "(e.g., 'gemini', 'openai', 'anthropic')."
            ),
        ),
    ] = None,
    wpt_dir: Annotated[
        Path | None,
        typer.Option(
            "--wpt-dir",
            "-w",
            help="Path to the local web-platform-tests repository.",
            exists=True,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where generated tests will be saved.",
            dir_okay=True,
        ),
    ] = None,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
    show_responses: Annotated[
        bool,
        typer.Option(
            "--show-responses",
            "-s",
            help="Display every LLM-generated response to the user.",
        ),
    ] = False,
    yes_tokens: Annotated[
        bool,
        typer.Option(
            "--yes-tokens",
            help="Automatically confirm all token count prompts.",
        ),
    ] = False,
    yes_cache: Annotated[
        bool,
        typer.Option(
            "--yes-cache",
            help="Automatically use the cache if it exists without prompting.",
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help=(
                "Automatically ignore and overwrite the cache if it exists "
                "without prompting."
            ),
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Resume the workflow from the last successful phase.",
        ),
    ] = False,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="Maximum number of retries for LLM calls.",
        ),
    ] = 3,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Timeout for LLM requests in seconds.",
        ),
    ] = DEFAULT_LLM_TIMEOUT,
    include_thoughts: Annotated[
        bool,
        typer.Option(
            "--include-thoughts",
            help="Stream the underlying ADK model thoughts to stdout.",
        ),
    ] = False,
    use_lightweight: Annotated[
        bool,
        typer.Option(
            "--use-lightweight",
            help="Use the lightweight model for all LLM requests.",
        ),
    ] = False,
    use_reasoning: Annotated[
        bool,
        typer.Option(
            "--use-reasoning",
            help="Use the reasoning model for all LLM requests.",
        ),
    ] = False,
    save_traces: Annotated[
        bool,
        typer.Option(
            "--save-traces",
            help=(
                "Save LLM interaction traces to the .wptgen/traces/ "
                "directory."
            ),
        ),
    ] = False,
    suggestions_only: Annotated[
        bool,
        typer.Option(
            "--suggestions-only",
            help=(
                "Only generate the coverage audit report, "
                "skip test generation."
            ),
        ),
    ] = False,
) -> None:
    """
    Perform a coverage audit and generate a report for a ChromeStatus feature.
    """
    ui = ctx.obj["ui"]

    banner = Panel(
        Align.center(
            Text.from_markup(
                "[bold blue]WPT[/bold blue][bold white]-"
                "[/bold white][bold green]Gen[/bold green]\n"
                "[italic white]AI-Powered Web Platform "
                "Test Generation[/italic white]"
            )
        ),
        border_style="bright_blue",
    )
    ui.print(banner)
    ui.print(
        f"\n[bold]Target ChromeStatus Feature:[/bold] "
        f"[cyan]{feature_id}[/cyan]\n"
    )

    if use_lightweight and use_reasoning:
        ui.error("Cannot use both --use-lightweight and --use-reasoning.")
        raise typer.Exit(code=1)

    with _workflow_error_handler(ui):
        # 1. Load configuration (merging YAML, env vars, and CLI overrides)
        wpt_dir_str = str(wpt_dir) if wpt_dir else None
        output_dir_str = str(output_dir) if output_dir else None

        config = load_config(
            config_path=config_path,
            provider_override=provider,
            wpt_dir_override=wpt_dir_str,
            output_dir_override=output_dir_str,
            show_responses=show_responses,
            yes_tokens_override=yes_tokens,
            yes_tests_override=False,
            yes_cache_override=yes_cache,
            no_cache_override=no_cache,
            suggestions_only=suggestions_only,
            brief_suggestions=False,
            resume_override=resume,
            resume_from_override=None,
            state_dir_override=None,
            max_retries_override=max_retries,
            timeout_override=timeout,
            spec_urls_override=None,
            feature_description_override=None,
            detailed_requirements_override=False,
            include_mdn_docs_override=False,
            draft_override=False,
            chromestatus_override=True,
            single_prompt_requirements_override=False,
            use_lightweight_override=use_lightweight,
            use_reasoning_override=use_reasoning,
            include_thoughts_override=include_thoughts,
            tentative_override=False,
            save_traces_override=save_traces,
            max_parallel_requests_override=None,
            run_on_browser_override=None,
            run_on_channel_override=None,
            temperature_override=None,
        )

        _print_run_config(ui, config)

        # 2. Instantiate the core engine
        engine = WPTGenEngine(config=config, ui=ui)

        # 3. Execute the workflow
        try:
            engine.run_workflow(feature_id)
        except WorkflowAborted:
            ui.warning("Workflow aborted by user.")
            raise typer.Exit(1) from None

        ui.print()
        if suggestions_only:
            ui.success(
                "ChromeStatus Audit completed successfully! "
                "Blueprints generated."
            )
        else:
            ui.success("ChromeStatus Workflow completed successfully!")


@app.command(name="doctor")
def doctor_command(
    ctx: typer.Context,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Verify that all system prerequisites are met.
    """
    ui = ctx.obj["ui"]

    success = True
    ui.print("[bold]WPT-Gen System Check[/bold]\n")

    try:
        config = load_config(config_path=config_path, require_api_key=False)
        ui.success("Configuration loaded successfully.")
    except Exception as e:
        ui.error(f"Configuration error: {str(e)}")
        raise typer.Exit(code=1) from e

    if config.api_key:
        ui.success(f"API key for {config.provider} is configured.")
    else:
        ui.error(f"API key for {config.provider} is missing.")
        success = False

    if config.wpt_path:
        wpt_path = Path(config.wpt_path)
        if wpt_path.is_dir():
            ui.success(f"WPT directory found: {wpt_path}")
            if (wpt_path / ".git").exists():
                ui.success("WPT directory is a valid git repository.")
            else:
                ui.error("WPT directory is not a git repository.")
                success = False

            wpt_exec = wpt_path / "wpt"
            if wpt_exec.exists() and os.access(wpt_exec, os.X_OK):
                ui.success("WPT executable (./wpt) is runnable.")
            else:
                ui.error("WPT executable (./wpt) is missing or not executable.")
                success = False
        else:
            ui.error(f"WPT directory not found: {wpt_path}")
            success = False
    else:
        ui.error("WPT path is not configured.")
        success = False

    ui.print()
    if success:
        ui.success("All checks passed! System is ready.")
    else:
        ui.error("Some checks failed. Please resolve the issues above.")
        raise typer.Exit(code=1)


config_app = typer.Typer(
    help="Manage WPT-Gen configuration.",
    add_completion=False,
)
app.add_typer(config_app, name="config")


def _flatten_dict(
    d: dict[str, Any], parent_key: str = "", sep: str = "."
) -> dict[str, Any]:
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _display_config(ui: UIProvider, config_path: str) -> None:
    """Displays the currently resolved configuration in the console.

    Args:
        ui: The UI provider for reporting errors and results.
        config_path: Path to the configuration file to load.
    """
    try:
        config = load_config(config_path=config_path, require_api_key=False)

        # Instantiate a default config by passing None to skip loading any
        # YAML config.
        default_config = load_config(config_path=None, require_api_key=False)

        config_dict = dataclasses.asdict(config)
        default_dict = dataclasses.asdict(default_config)

        if config.loaded_from:
            ui.print(
                f"Reading configuration from: [cyan]{config.loaded_from}[/cyan]"
            )
        else:
            ui.print(
                "Reading configuration from: [yellow]Defaults (no config "
                "file found)[/yellow]"
            )

        # Remove internal or sensitive fields from display
        config_dict.pop("loaded_from", None)
        config_dict.pop("api_key", None)
        default_dict.pop("loaded_from", None)
        default_dict.pop("api_key", None)

        flat_config = _flatten_dict(config_dict)
        flat_default = _flatten_dict(default_dict)

        table = Table(
            title="Resolved Configuration",
            border_style="blue",
            show_header=True,
        )
        table.add_column("Config Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")
        table.add_column("Source", style="green")

        for key, value in flat_config.items():
            # Determine if the value is custom or default
            default_val = flat_default.get(key)
            source = "custom" if value != default_val else "default"

            # Style the source column differently based on value
            source_styled = (
                f"[bold green]{source}[/bold green]"
                if source == "custom"
                else f"[dim white]{source}[/dim white]"
            )

            # Convert None or other types to str for display
            table.add_row(
                key,
                str(value) if value is not None else "[dim]None[/dim]",
                source_styled,
            )

        ui.print(table)
    except Exception as e:
        ui.error(f"Error: {str(e)}")
        raise typer.Exit(code=1) from e


@config_app.callback(invoke_without_command=True)
def config_callback(
    ctx: typer.Context,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Manage WPT-Gen configuration.

    Displays active configuration if no subcommand is provided.
    """
    if ctx.invoked_subcommand is None:
        ui = ctx.obj["ui"]
        _display_config(ui, config_path)


@config_app.command(name="show")
def config_show(
    ctx: typer.Context,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Display the currently active, fully resolved configuration.
    """
    ui = ctx.obj["ui"]
    _display_config(ui, config_path)


@config_app.command(name="set")
def config_set(
    ctx: typer.Context,
    key: Annotated[
        str,
        typer.Argument(
            help=(
                "Configuration key using dot-notation "
                "(e.g., default_provider)."
            )
        ),
    ],
    value: Annotated[
        str, typer.Argument(help="Value to set for the configuration key.")
    ],
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Update an individual configuration setting using dot-notation.
    """
    ui = ctx.obj["ui"]

    path = Path(config_path)
    target_file = path

    if not path.exists() and config_path == DEFAULT_CONFIG_PATH:
        global_path = Path(_get_global_config_path())
        if global_path.exists():
            target_file = global_path

    yaml_data: dict[str, Any] = {}
    if target_file.exists():
        try:
            with open(target_file, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except Exception as e:
            ui.error(f"Error reading config file: {e}")
            raise typer.Exit(code=1) from e

    keys = key.split(".")
    current = yaml_data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    typed_value: Any
    val_lower = value.lower()
    if val_lower == "true":
        typed_value = True
    elif val_lower == "false":
        typed_value = False
    elif value.isdigit():
        typed_value = int(value)
    else:
        try:
            typed_value = float(value)
        except ValueError:
            typed_value = value

    current[keys[-1]] = typed_value

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, sort_keys=False, default_flow_style=False)
        ui.success(
            f"Set [cyan]{key}[/cyan] = [yellow]{typed_value}[/yellow] in "
            f"[magenta]{target_file.resolve()}[/magenta]"
        )
    except Exception as e:
        ui.error(f"Error writing config file: {e}")
        raise typer.Exit(code=1) from e


@app.command(name="list-models")
def list_models(
    ctx: typer.Context,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help=(
                "Override the default LLM provider "
                "(e.g., 'gemini', 'openai', 'anthropic')."
            ),
        ),
    ] = None,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Display the configured LLM models for the active provider.
    """
    ui = ctx.obj["ui"]

    try:
        config = load_config(
            config_path=config_path,
            provider_override=provider,
            require_api_key=False,
        )

        table = Table(
            title=f"Configured Models for {config.provider.capitalize()}"
        )
        table.add_column("Category", justify="left", style="cyan", no_wrap=True)
        table.add_column("Model Name", justify="left", style="magenta")

        table.add_row("default", config.default_model)
        for cat_name, mod_name in config.categories.items():
            table.add_row(cat_name, mod_name)

        ui.print()
        ui.print(table)
    except Exception as e:
        ui.error(f"Error: {str(e)}")
        raise typer.Exit(code=1) from e


@app.command(name="audit")
def audit(
    ctx: typer.Context,
    feature_id: Annotated[
        str,
        typer.Argument(
            help=(
                "The web feature ID to generate tests for "
                "(e.g., 'grid', 'popover')."
            )
        ),
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help=(
                "Override the default LLM provider "
                "(e.g., 'gemini', 'openai', 'anthropic')."
            ),
        ),
    ] = None,
    wpt_dir: Annotated[
        Path | None,
        typer.Option(
            "--wpt-dir",
            "-w",
            help="Path to the local web-platform-tests repository.",
            exists=True,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where generated tests will be saved.",
            dir_okay=True,
        ),
    ] = None,
    wf_yml_update: Annotated[
        bool,
        typer.Option(
            "--wf-yml-update",
            help="Update WEB_FEATURES.yml with generated tests.",
        ),
    ] = False,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
    show_responses: Annotated[
        bool,
        typer.Option(
            "--show-responses",
            "-s",
            help="Display every LLM-generated response to the user.",
        ),
    ] = False,
    yes_tokens: Annotated[
        bool,
        typer.Option(
            "--yes-tokens",
            help="Automatically confirm all token count prompts.",
        ),
    ] = False,
    yes_cache: Annotated[
        bool,
        typer.Option(
            "--yes-cache",
            help="Automatically use the cache if it exists without prompting.",
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help=(
                "Automatically ignore and overwrite the cache if it exists "
                "without prompting."
            ),
        ),
    ] = False,
    brief_suggestions: Annotated[
        bool,
        typer.Option(
            "--brief-suggestions",
            help=(
                "Only generate test titles and descriptions for suggestions "
                "(omits detailed test suggestions)."
            ),
        ),
    ] = False,
    skip_run: Annotated[
        bool,
        typer.Option(
            "--skip-run",
            help="Opt out of running generated tests.",
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Resume the workflow from the last successful phase.",
        ),
    ] = False,
    resume_from: Annotated[
        WorkflowPhase | None,
        typer.Option(
            "--resume-from",
            help="Resume the workflow explicitly from a specific phase.",
        ),
    ] = None,
    state_dir: Annotated[
        Path | None,
        typer.Option(
            "--state-dir",
            "--tests-dir",
            help=(
                "Directory containing the necessary artifacts to hydrate "
                "the requested phase."
            ),
            dir_okay=True,
            exists=True,
        ),
    ] = None,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="Maximum number of retries for LLM calls.",
        ),
    ] = 3,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Timeout for LLM requests in seconds.",
        ),
    ] = DEFAULT_LLM_TIMEOUT,
    spec_urls: Annotated[
        str | None,
        typer.Option(
            "--spec-urls",
            "-u",
            help=(
                "Comma-separated list of spec URLs to use, "
                "bypassing automatic fetching."
            ),
        ),
    ] = None,
    spec_url: Annotated[
        str | None,
        typer.Option(
            "--spec-url",
            help="A single specification URL for convenience.",
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            "-d",
            help="Manually provide a description for the web feature.",
        ),
    ] = None,
    detailed_requirements: Annotated[
        bool,
        typer.Option(
            "--detailed-requirements",
            help=(
                "Use a more detailed, iterative requirements extraction "
                "process."
            ),
        ),
    ] = False,
    include_mdn_docs: Annotated[
        bool,
        typer.Option(
            "--include-mdn-docs",
            help="Include MDN documentation in requirements extraction.",
        ),
    ] = False,
    include_thoughts: Annotated[
        bool,
        typer.Option(
            "--include-thoughts",
            help="Stream the underlying ADK model thoughts to stdout.",
        ),
    ] = False,
    draft: Annotated[
        bool,
        typer.Option(
            "--draft",
            help="Enable fetching metadata from the draft features directory.",
        ),
    ] = False,
    single_prompt_requirements: Annotated[
        bool,
        typer.Option(
            "--single-prompt-requirements",
            help=(
                "Use a single-prompt requirements extraction process "
                "(legacy)."
            ),
        ),
    ] = False,
    use_lightweight: Annotated[
        bool,
        typer.Option(
            "--use-lightweight",
            help="Use the lightweight model for all LLM requests.",
        ),
    ] = False,
    use_reasoning: Annotated[
        bool,
        typer.Option(
            "--use-reasoning",
            help="Use the reasoning model for all LLM requests.",
        ),
    ] = False,
    save_traces: Annotated[
        bool,
        typer.Option(
            "--save-traces",
            help=(
                "Save LLM interaction traces to the .wptgen/traces/ "
                "directory."
            ),
        ),
    ] = False,
    audit_partition_size: Annotated[
        int | None,
        typer.Option(
            "--audit-partition-size",
            help=(
                "Number of requirements to evaluate per coverage audit "
                "partition."
            ),
        ),
    ] = None,
    max_parallel_requests: Annotated[
        int | None,
        typer.Option(
            "--max-parallel-requests",
            help="Maximum number of parallel asynchronous LLM requests.",
        ),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help=(
                "Global temperature setting for all LLM requests (e.g., "
                "0.01). Overrides phase-specific defaults."
            ),
        ),
    ] = None,
    run_on_browser: Annotated[
        BrowserType | None,
        typer.Option(
            "--run-on-browser",
            help="Browser to use for the local WPT test runner.",
        ),
    ] = None,
    run_on_channel: Annotated[
        BrowserChannel | None,
        typer.Option(
            "--run-on-channel",
            help="Release channel to use for the local WPT test runner.",
        ),
    ] = None,
) -> None:
    """Performs a gap analysis and generates coverage test suggestions.

    This command performs a gap analysis and generates coverage test suggestions
    without generating WPT files.
    """
    ui = ctx.obj["ui"]

    _print_workflow_banner(ui, feature_id)
    _check_workflow_flags(
        ui=ui,
        wf_yml_update=wf_yml_update,
        output_dir=output_dir,
        use_lightweight=use_lightweight,
        use_reasoning=use_reasoning,
        yes_cache=yes_cache,
        no_cache=no_cache,
        detailed_requirements=detailed_requirements,
        single_prompt_requirements=single_prompt_requirements,
    )

    with _workflow_error_handler(ui):
        # Convert Path object back to string if it was provided, else pass None
        wpt_dir_str = str(wpt_dir) if wpt_dir else None
        output_dir_str = str(output_dir) if output_dir else None

        if spec_urls and spec_url:
            ui.print(
                "[red]Error: Cannot provide both --spec-urls and --spec-url. "
                "Please use only one.[/red]"
            )
            raise typer.Exit(code=1)

        # Parse spec_urls if provided
        spec_urls_list = None
        if spec_url:
            spec_urls_list = [spec_url.strip()]
        elif spec_urls:
            spec_urls_list = [u.strip() for u in spec_urls.split(",")]

        config = load_config(
            config_path=config_path,
            provider_override=provider,
            wpt_dir_override=wpt_dir_str,
            output_dir_override=output_dir_str,
            show_responses=show_responses,
            yes_tokens_override=yes_tokens,
            yes_tests_override=False,
            yes_cache_override=yes_cache,
            no_cache_override=no_cache,
            suggestions_only=True,
            brief_suggestions=brief_suggestions,
            resume_override=resume,
            skip_run_override=skip_run,
            resume_from_override=resume_from,
            state_dir_override=str(state_dir) if state_dir else None,
            max_retries_override=max_retries,
            timeout_override=timeout,
            spec_urls_override=spec_urls_list,
            feature_description_override=description,
            detailed_requirements_override=detailed_requirements,
            include_mdn_docs_override=include_mdn_docs,
            draft_override=draft,
            single_prompt_requirements_override=single_prompt_requirements,
            use_lightweight_override=use_lightweight,
            use_reasoning_override=use_reasoning,
            tentative_override=False,
            save_traces_override=save_traces,
            audit_partition_size_override=audit_partition_size,
            max_parallel_requests_override=max_parallel_requests,
            temperature_override=temperature,
            include_thoughts_override=include_thoughts,
            run_on_browser_override=run_on_browser,
            run_on_channel_override=run_on_channel,
        )

        _execute_workflow(
            ui=ui,
            feature_id=feature_id,
            config=config,
            wf_yml_update=wf_yml_update,
            output_dir=output_dir,
            is_audit=True,
        )


@app.command(name="clear-cache")
def clear_cache(
    ctx: typer.Context,
    config_path: Annotated[
        str,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = DEFAULT_CONFIG_PATH,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Bypass confirmation prompt.")
    ] = False,
) -> None:
    """
    Clear the existing cached data for wpt-gen.
    """
    ui = ctx.obj["ui"]
    try:
        config = load_config(config_path=config_path, require_api_key=False)
        if not config.cache_path:
            ui.error("Cache path not configured.")
            return

        cache_dir = Path(config.cache_path)

        if not cache_dir.exists():
            ui.info(
                f"Cache directory [cyan]{cache_dir}[/cyan] does not exist. "
                "Nothing to clear."
            )
            return

        files = list(cache_dir.iterdir())
        if not files:
            ui.info(
                f"Cache directory [cyan]{cache_dir}[/cyan] is already empty."
            )
            return

        if force or ui.confirm(
            f"Are you sure you want to clear the cache at "
            f"[cyan]{cache_dir}[/cyan]?"
        ):
            for item in files:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            ui.success("Cache cleared successfully!")
        else:
            ui.print("Aborted.")

    except ValueError as e:
        ui.error(f"Configuration Error: {str(e)}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        ui.error(f"Unexpected Error: {str(e)}")
        raise typer.Exit(code=1) from e


@app.command()
def version(ctx: typer.Context) -> None:
    """
    Print the version of wpt-gen.
    """
    ui = ctx.obj["ui"]
    try:
        # Replace 'your-package-name' with the name defined in pyproject.toml
        ui.print(f'wpt-gen version {app_version("wpt-gen")}')
    except PackageNotFoundError:
        ui.print("unknown")


@app.command(name="init")
def init(
    ctx: typer.Context,
    config_path: Annotated[
        str | None,
        typer.Option(
            "--config", "-c", help="Path to a custom wpt-gen.yml file."
        ),
    ] = None,
    wpt_path: Annotated[
        str | None,
        typer.Option(
            "--wpt-path",
            help="Absolute path to local web-platform-tests directory.",
        ),
    ] = None,
) -> None:
    """
    Initialize a new wpt-gen configuration file interactively.
    """
    ui = ctx.obj["ui"]

    if config_path:
        resolved_path = Path(config_path)
    else:
        resolved_path = Path(_get_global_config_path())

    # Ensure the directory exists
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    if resolved_path.exists():
        overwrite = ui.confirm(
            (
                "Configuration file already exists at "
                f"[cyan]{resolved_path}[/cyan]. Overwrite?"
            ),
            default=False,
        )
        if not overwrite:
            ui.print("Aborted.")
            return

    provider = ui.prompt(
        "Preferred LLM Provider",
        choices=["gemini", "openai", "anthropic"],
        default="gemini",
    )

    defaults = DEFAULT_PROVIDER_MODELS[provider]

    ui.print(f"\n[cyan]Configuring models for {provider}[/cyan]")
    default_model = ui.prompt("Default model", default=defaults["default"])
    lightweight_model = ui.prompt(
        "Lightweight model", default=defaults["lightweight"]
    )
    reasoning_model = ui.prompt(
        "Reasoning model", default=defaults["reasoning"]
    )

    if wpt_path is None:
        wpt_path = ui.prompt(
            "\nAbsolute path to local web-platform-tests directory",
            default=str(Path.home() / "wpt"),
        )

    config_data = {
        "default_provider": provider,
        "wpt_path": str(Path(wpt_path).expanduser().resolve()),
        "providers": {
            provider: {
                "default_model": default_model,
                "categories": {
                    ModelCategory.LIGHTWEIGHT.value: lightweight_model,
                    ModelCategory.REASONING.value: reasoning_model,
                },
            }
        },
    }

    try:
        with open(resolved_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        ui.success(
            f"Configuration saved successfully to [cyan]{resolved_path}[/cyan]"
        )
    except Exception as e:
        ui.error(f"Failed to save configuration: {str(e)}")
        raise typer.Exit(code=1) from e


@app.callback()
def main_callback(
    ctx: typer.Context,
) -> None:
    """
    AI-Powered Web Platform Test Generation CLI
    """
    console = Console()
    ctx.obj = {"ui": RichUIProvider(console)}


if __name__ == "__main__":
    app()

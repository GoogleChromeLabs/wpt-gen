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

"""WPT-Gen: An agentic tool for automating Web Platform Tests."""

from __future__ import annotations

from wptgen.engine import WPTGenEngine
from wptgen.ui import LoggingUIProvider

__version__ = "0.6.0"


def generate_audit_report(
    feature_id: str,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    explainer_urls: list[str] | None = None,
) -> str:
    """Generates a structured Markdown WPT coverage report for a given feature.

    This function serves as the primary entry point for non-interactive
    library use (e.g., on a server like ChromeStatus). It automatically
    configures the engine for library mode, suppressing interactive prompts
    and terminal-specific UI elements.

    Args:
        feature_id: The numeric ChromeStatus feature ID or a Web Feature ID
            string.
        provider: The LLM provider to use (e.g., "gemini", "openai",
            "anthropic").
        model: The specific model to use for reasoning phases.
        api_key: Optional API key override for the provider.
        explainer_urls: Optional list of explainer URLs to use instead of
            scraping them from the feature ID.

    Returns:
        A string containing the full, rendered Markdown report.
    """
    from wptgen.config import load_config

    # 1. Build configuration for library mode
    config = load_config(
        provider_override=provider,
        yes_tokens_override=True,
        explainer_urls_override=explainer_urls,
    )
    config.library_mode = True
    config.wpt_path = None
    config.suggestions_only = True
    config.chromestatus = True
    config.no_cache = True
    if model:
        config.default_model = model
    if api_key:
        config.api_key = api_key

    # 2. Instantiate non-interactive UI
    ui = LoggingUIProvider()

    # 3. Execute workflow
    engine = WPTGenEngine(config=config, ui=ui)
    context = engine.run_workflow(feature_id, disable_directory_inference=True)

    # 4. Return the generated report
    if context.markdown_report is None:
        from wptgen.models import WorkflowError

        raise WorkflowError("Markdown report was not generated.")

    return context.markdown_report

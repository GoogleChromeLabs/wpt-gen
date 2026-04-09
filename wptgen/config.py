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

"""Configuration management for WPT-Gen."""

import importlib.resources
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wptgen.models import (
    BrowserChannel,
    BrowserType,
    ModelCategory,
    WorkflowPhase,
)

# The absolute path to the installed wptgen package root
PACKAGE_ROOT = Path(str(importlib.resources.files("wptgen")))
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
SKILLS_DIR = PACKAGE_ROOT / "skills"

# Default timeout for LLM requests in seconds (10 minutes)
DEFAULT_LLM_TIMEOUT = 600
# Minimum allowed timeout for Gemini API (10 seconds)
MIN_LLM_TIMEOUT = 10
# Default partition size for requirement auditing
DEFAULT_AUDIT_PARTITION_SIZE = 40

DEFAULT_PROVIDER_MODELS = {
    "gemini": {
        "default": "gemini-3.1-pro-preview",
        "lightweight": "gemini-3-flash-preview",
        "reasoning": "gemini-3.1-pro-preview",
    },
    "openai": {
        "default": "gpt-5.2-high",
        "lightweight": "gpt-5-mini",
        "reasoning": "gpt-5.2-high",
    },
    "anthropic": {
        "default": "claude-opus-4-6",
        "lightweight": "claude-sonnet-4-6",
        "reasoning": "claude-opus-4-6",
    },
}


@dataclass
class Config:
    """Configuration object for WPT-Gen."""

    provider: str
    default_model: str
    api_key: str | None
    wpt_path: str
    categories: dict[str, str]
    phase_model_mapping: dict[str, str]
    output_dir: str | None = None
    show_responses: bool = False
    yes_tokens: bool = False
    yes_tests: bool = False
    yes_cache: bool = False
    no_cache: bool = False
    suggestions_only: bool = False
    brief_suggestions: bool = False
    resume: bool = False
    skip_run: bool = False
    max_retries: int = 3
    timeout: int = DEFAULT_LLM_TIMEOUT
    cache_path: str | None = None
    run_on_browser: BrowserType = BrowserType.CHROME
    run_on_channel: BrowserChannel = BrowserChannel.CANARY
    spec_urls: list[str] | None = None
    feature_description: str | None = None
    detailed_requirements: bool = False
    include_mdn_docs: bool = False
    draft: bool = False
    chromestatus: bool = False
    single_prompt_requirements: bool = False
    use_lightweight: bool = False
    use_reasoning: bool = False
    include_thoughts: bool = False
    tentative: bool = False
    save_traces: bool = False
    resume_from: WorkflowPhase | None = None
    state_dir: str | None = None
    max_parallel_requests: int = 10
    audit_partition_size: int = DEFAULT_AUDIT_PARTITION_SIZE
    temperature: float | None = None
    loaded_from: str | None = None

    def get_model_for_phase(self, phase: WorkflowPhase | str) -> str | None:
        """Resolves the model name for a given workflow phase."""
        phase_name = phase.value if isinstance(phase, WorkflowPhase) else phase
        if self.use_lightweight:
            return self.categories.get("lightweight")
        if self.use_reasoning:
            return self.categories.get("reasoning")
        category = self.phase_model_mapping.get(phase_name)
        if not category:
            return None
        return self.categories.get(category)

    def get_model_info_for_phase(self, phase: WorkflowPhase | str) -> str:
        """Returns a formatted string describing the model category being used
        for a phase."""
        phase_name = phase.value if isinstance(phase, WorkflowPhase) else phase

        category = self.phase_model_mapping.get(phase_name, "default")
        override_text = ""

        if self.use_lightweight:
            if category != "lightweight":
                override_text = " (Overridden by --use-lightweight)"
            category = "lightweight"
        elif self.use_reasoning:
            if category != "reasoning":
                override_text = " (Overridden by --use-reasoning)"
            category = "reasoning"

        model_name = (
            self.categories.get(category, self.default_model)
            if category != "default"
            else self.default_model
        )

        return f"{category} [{model_name}]{override_text}"


def _get_default_cache_path() -> str:
    """Returns a platform-appropriate default cache directory."""
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return str(base / "wpt-gen" / "Cache")
    elif sys.platform == "darwin":
        return str(home / "Library" / "Caches" / "wpt-gen")
    else:
        # Linux / Unix - Follow XDG spec if possible
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            return str(Path(xdg_cache) / "wpt-gen")
        return str(home / ".cache" / "wpt-gen")


def _get_global_config_path() -> str:
    """Returns a platform-appropriate global configuration path."""
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return str(base / "wpt-gen" / "config.yml")
    elif sys.platform == "darwin":
        return str(
            home / "Library" / "Application Support" / "wpt-gen" / "config.yml"
        )
    else:
        # Linux / Unix - Follow XDG spec if possible
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return str(Path(xdg_config) / "wpt-gen" / "config.yml")
        return str(home / ".config" / "wpt-gen" / "config.yml")


DEFAULT_CONFIG_PATH = os.path.abspath("wpt-gen.yml")
WPT_DEFAULT_PATH = os.path.abspath(os.path.join(os.getcwd(), os.pardir, "wpt"))


def validate_output_dir(output_dir: str) -> str:
    """
    Expands ~, resolves the path, ensures it exists (creating if necessary),
    and verifies write permissions.
    """
    path = Path(output_dir).expanduser().resolve()

    try:
        # Ensure the directory exists
        path.mkdir(parents=True, exist_ok=True)

        # Verify write permissions by attempting to create and remove
        # a temporary file
        test_file = path / ".wpt-gen-write-test"
        test_file.touch()
        test_file.unlink()
    except (OSError, PermissionError) as e:
        raise ValueError(
            f"CRITICAL: Cannot write to output directory '{output_dir}': {e}"
        ) from e

    return str(path)


def _deep_merge(
    target: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Recursively merges source into target, returning a new dictionary."""
    result = target.copy()
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    config_path: str | None = DEFAULT_CONFIG_PATH,
    provider_override: str | None = None,
    wpt_dir_override: str | None = None,
    output_dir_override: str | None = None,
    show_responses: bool = False,
    yes_tokens_override: bool = False,
    yes_tests_override: bool = False,
    yes_cache_override: bool = False,
    no_cache_override: bool = False,
    suggestions_only: bool = False,
    brief_suggestions: bool = False,
    resume_override: bool = False,
    skip_run_override: bool = False,
    resume_from_override: WorkflowPhase | None = None,
    state_dir_override: str | None = None,
    max_retries_override: int | None = None,
    timeout_override: int | None = None,
    spec_urls_override: list[str] | None = None,
    feature_description_override: str | None = None,
    detailed_requirements_override: bool = False,
    include_mdn_docs_override: bool = False,
    draft_override: bool = False,
    chromestatus_override: bool = False,
    single_prompt_requirements_override: bool = False,
    use_lightweight_override: bool = False,
    use_reasoning_override: bool = False,
    include_thoughts_override: bool = False,
    tentative_override: bool = False,
    save_traces_override: bool = False,
    require_api_key: bool = True,
    audit_partition_size_override: int | None = None,
    max_parallel_requests_override: int | None = None,
    run_on_browser_override: BrowserType | None = None,
    run_on_channel_override: BrowserChannel | None = None,
    temperature_override: float | None = None,
) -> Config:
    """
    Loads configuration from YAML and environment variables.
    Selects the active LLM provider and fetches the corresponding API key.
    """
    yaml_data: dict[str, Any] = {}
    loaded_from: str | None = None

    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            loaded_from = str(path.resolve())
        elif config_path == DEFAULT_CONFIG_PATH:
            # Fallback to global config if the default local path does not exist
            global_path = Path(_get_global_config_path())
            if global_path.exists():
                with open(global_path, encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f) or {}
                loaded_from = str(global_path.resolve())

    # Determine the active provider
    # CLI override takes precedence, then YAML default.
    active_provider = provider_override or yaml_data.get(
        "default_provider", "gemini"
    )
    active_provider = active_provider.lower()

    # Extract provider-specific settings
    providers_config = yaml_data.get("providers", {})
    provider_settings = providers_config.get(active_provider, {})

    # Provide sensible defaults if the YAML is missing the specific
    # provider block
    if active_provider not in DEFAULT_PROVIDER_MODELS:
        raise ValueError(
            f"CRITICAL: Unsupported provider '{active_provider}' requested."
        )

    provider_defaults = DEFAULT_PROVIDER_MODELS[active_provider]
    default_model_name = provider_defaults[ModelCategory.DEFAULT.value]
    default_categories = {
        ModelCategory.LIGHTWEIGHT.value: provider_defaults[
            ModelCategory.LIGHTWEIGHT.value
        ],
        ModelCategory.REASONING.value: provider_defaults[
            ModelCategory.REASONING.value
        ],
    }

    env_var_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    env_var_name = env_var_map.get(
        active_provider, f"{active_provider.upper()}_API_KEY"
    )

    # Enforce the environment variable constraint for the active provider
    api_key = os.environ.get(env_var_name)
    if require_api_key and not api_key:
        raise ValueError(
            f"CRITICAL: {env_var_name} environment variable is missing. "
            f"Required when using the '{active_provider}' provider."
        )

    wpt_path = wpt_dir_override or yaml_data.get("wpt_path", WPT_DEFAULT_PATH)
    output_dir_raw = output_dir_override or yaml_data.get("output_dir")
    output_dir = validate_output_dir(output_dir_raw) if output_dir_raw else None

    show_responses = show_responses or yaml_data.get("show_responses", False)
    yes_tokens = yes_tokens_override or yaml_data.get("yes_tokens", False)
    yes_tests = yes_tests_override or yaml_data.get("yes_tests", False)
    yes_cache = yes_cache_override or yaml_data.get("yes_cache", False)
    no_cache = no_cache_override or yaml_data.get("no_cache", False)
    suggestions_only = suggestions_only or yaml_data.get(
        "suggestions_only", False
    )
    brief_suggestions = brief_suggestions or yaml_data.get(
        "brief_suggestions", False
    )
    resume = resume_override or yaml_data.get("resume", False)
    skip_run = skip_run_override or yaml_data.get("skip_run", False)

    resume_from_raw = resume_from_override or yaml_data.get("resume_from")
    resume_from = WorkflowPhase(resume_from_raw) if resume_from_raw else None

    state_dir_raw = state_dir_override or yaml_data.get("state_dir")
    state_dir = (
        str(Path(state_dir_raw).expanduser().resolve())
        if state_dir_raw
        else None
    )

    draft = draft_override or yaml_data.get("draft", False)
    chromestatus = chromestatus_override or yaml_data.get("chromestatus", False)
    detailed_requirements = detailed_requirements_override or yaml_data.get(
        "detailed_requirements", False
    )
    include_mdn_docs = include_mdn_docs_override or yaml_data.get(
        "include_mdn_docs", False
    )
    single_prompt_requirements = (
        single_prompt_requirements_override
        or yaml_data.get("single_prompt_requirements", False)
    )
    max_retries = max_retries_override or yaml_data.get("max_retries", 3)
    timeout = timeout_override or yaml_data.get("timeout", DEFAULT_LLM_TIMEOUT)
    audit_partition_size = (
        audit_partition_size_override
        if audit_partition_size_override is not None
        else yaml_data.get("audit_partition_size", DEFAULT_AUDIT_PARTITION_SIZE)
    )
    if audit_partition_size <= 0:
        raise ValueError(
            f"CRITICAL: audit_partition_size must be strictly greater than 0. "
            f"Got: {audit_partition_size}"
        )
    max_parallel_requests = max_parallel_requests_override or yaml_data.get(
        "max_parallel_requests", 10
    )

    if timeout < MIN_LLM_TIMEOUT:
        logging.warning(
            f"Requested timeout {timeout}s is less than the minimum allowed "
            f"({MIN_LLM_TIMEOUT}s). Setting timeout to {MIN_LLM_TIMEOUT}s."
        )
        timeout = MIN_LLM_TIMEOUT

    cache_path = yaml_data.get("cache_path") or _get_default_cache_path()
    include_thoughts = include_thoughts_override or yaml_data.get(
        "include_thoughts", False
    )
    tentative = tentative_override or yaml_data.get("tentative", False)
    save_traces = save_traces_override or yaml_data.get("save_traces", False)

    # Load model categories and phase mapping
    default_model = provider_settings.get("default_model", default_model_name)
    categories = _deep_merge(
        default_categories, provider_settings.get("categories", {})
    )

    if use_lightweight_override:
        default_model = categories.get(
            ModelCategory.LIGHTWEIGHT.value, default_model
        )
    elif use_reasoning_override:
        default_model = categories.get(
            ModelCategory.REASONING.value, default_model
        )

    # Ensure default mapping if missing in YAML
    default_phase_mapping = {
        WorkflowPhase.REQUIREMENTS_EXTRACTION.value: (
            ModelCategory.REASONING.value
        ),
        WorkflowPhase.COVERAGE_AUDIT.value: ModelCategory.REASONING.value,
        WorkflowPhase.GENERATION.value: ModelCategory.LIGHTWEIGHT.value,
    }
    phase_model_mapping = _deep_merge(
        default_phase_mapping, yaml_data.get("phase_model_mapping", {})
    )

    return Config(
        provider=active_provider,
        default_model=default_model,
        api_key=api_key,
        wpt_path=wpt_path,
        categories=categories,
        phase_model_mapping=phase_model_mapping,
        output_dir=output_dir,
        show_responses=show_responses,
        yes_tokens=yes_tokens,
        yes_tests=yes_tests,
        yes_cache=yes_cache,
        no_cache=no_cache,
        suggestions_only=suggestions_only,
        brief_suggestions=brief_suggestions,
        resume=resume,
        skip_run=skip_run,
        max_retries=max_retries,
        timeout=timeout,
        cache_path=cache_path,
        run_on_browser=run_on_browser_override
        if run_on_browser_override
        else BrowserType(yaml_data.get("run_on_browser", "chrome")),
        run_on_channel=run_on_channel_override
        if run_on_channel_override
        else BrowserChannel(yaml_data.get("run_on_channel", "canary")),
        spec_urls=spec_urls_override,
        feature_description=feature_description_override,
        detailed_requirements=detailed_requirements,
        include_mdn_docs=include_mdn_docs,
        draft=draft,
        chromestatus=chromestatus,
        single_prompt_requirements=single_prompt_requirements,
        use_lightweight=use_lightweight_override,
        use_reasoning=use_reasoning_override,
        include_thoughts=include_thoughts,
        tentative=tentative,
        save_traces=save_traces,
        resume_from=resume_from,
        state_dir=state_dir,
        audit_partition_size=audit_partition_size,
        max_parallel_requests=max_parallel_requests,
        temperature=temperature_override
        if temperature_override is not None
        else yaml_data.get("temperature"),
        loaded_from=loaded_from,
    )

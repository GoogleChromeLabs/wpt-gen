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

"""Provider setup and environment configuration for ADK agents."""

import os
from typing import Any

from wptgen.config import DEFAULT_PROVIDER_MODELS, Config
from wptgen.models import LLMProvider, ProviderDefaults

_PROVIDER_CONFIG: dict[LLMProvider, ProviderDefaults] = {
    LLMProvider.GEMINI: ProviderDefaults(
        "GOOGLE_API_KEY", DEFAULT_PROVIDER_MODELS["gemini"]["default"]
    ),
    LLMProvider.GOOGLE: ProviderDefaults(
        "GOOGLE_API_KEY", DEFAULT_PROVIDER_MODELS["gemini"]["default"]
    ),
    LLMProvider.ANTHROPIC: ProviderDefaults(
        "ANTHROPIC_API_KEY", DEFAULT_PROVIDER_MODELS["anthropic"]["default"]
    ),
    LLMProvider.OPENAI: ProviderDefaults(
        "OPENAI_API_KEY", DEFAULT_PROVIDER_MODELS["openai"]["default"]
    ),
}


def setup_adk_environment(config: Config, model: str | None = None) -> str:
    """Configures the ADK environment with the appropriate API keys
    and returns the model string.

    Args:
      config: The WPT-Gen configuration object.
      model: Optional model. When ``None``, the
        config's ``default_model`` (then the provider default) is used.

    Returns:
      The fully qualified ADK model string.

    Raises:
      ValueError: If the required API key for the selected provider is missing
        or if the provider is unsupported.
    """
    try:
        provider = LLMProvider(config.provider.lower())
    except ValueError:
        raise ValueError(
            f"Unsupported ADK provider: {config.provider}"
        ) from None

    defaults = _PROVIDER_CONFIG[provider]
    resolved_model = model or config.default_model or defaults.default_model

    if (
        provider in (LLMProvider.GEMINI, LLMProvider.GOOGLE)
        and not config.api_key
    ):
        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
            "true",
            "1",
        ):
            return resolved_model

    if not config.api_key:
        raise ValueError(
            f"An API key is required for the {provider.value} provider."
        )

    os.environ[defaults.env_var] = config.api_key

    return resolved_model


def create_adk_model(config: Config, model_string: str) -> Any:
    """Creates the ADK model instance with configured retry options."""
    if config.provider.lower() in ("gemini", "google"):
        try:
            from google.adk.models.google_llm import Gemini
            from google.genai import types

            retry_opts = types.HttpRetryOptions(
                attempts=5,
                initial_delay=2.0,
                max_delay=30.0,
                exp_base=2.0,
                jitter=0.5,
                http_status_codes=[429, 500, 503, 504],
            )
            return Gemini(
                model=model_string,
                retry_options=retry_opts,
            )
        except Exception:
            return model_string
    return model_string

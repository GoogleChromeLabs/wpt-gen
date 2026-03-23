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

import os

from wptgen.config import Config

_PROVIDER_CONFIG = {
  'gemini': ('GOOGLE_API_KEY', 'gemini-3.1-pro-preview'),
  'google': ('GOOGLE_API_KEY', 'gemini-3.1-pro-preview'),
  'anthropic': ('ANTHROPIC_API_KEY', 'claude-opus-4-6'),
  'openai': ('OPENAI_API_KEY', 'gpt-5.2-high'),
}


def setup_adk_environment(config: Config) -> str:
  """Configures the ADK environment with the appropriate API keys and returns the model string.

  Args:
    config: The WPT-Gen configuration object.

  Returns:
    The fully qualified ADK model string.

  Raises:
    ValueError: If the required API key for the selected provider is missing
      or if the provider is unsupported.
  """
  provider = config.provider.lower()

  if not config.api_key:
    raise ValueError(f'An API key is required for the {provider} provider.')

  if provider not in _PROVIDER_CONFIG:
    raise ValueError(f'Unsupported ADK provider: {provider}')

  env_var, default_model = _PROVIDER_CONFIG[provider]
  os.environ[env_var] = config.api_key

  return config.default_model or default_model

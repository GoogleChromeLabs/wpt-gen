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


def setup_adk_environment(config: Config) -> str:
  """Configures the ADK environment with the appropriate API keys and returns the model string.

  Args:
      config: The WPT-Gen configuration object.

  Returns:
      The fully qualified ADK model string.

  Raises:
      ValueError: If the required API key for the selected provider is missing.
  """
  provider = config.provider.lower()

  if not config.api_key:
    raise ValueError(f'An API key is required for the {provider} provider.')

  if provider == 'gemini' or provider == 'google':
    os.environ['GOOGLE_API_KEY'] = config.api_key
    return config.default_model or 'gemini-3.1-pro-preview'

  elif provider == 'anthropic':
    os.environ['ANTHROPIC_API_KEY'] = config.api_key
    return config.default_model or 'claude-opus-4-6'

  elif provider == 'openai':
    os.environ['OPENAI_API_KEY'] = config.api_key
    return config.default_model or 'gpt-5.2-high'

  else:
    raise ValueError(f'Unsupported ADK provider: {provider}')

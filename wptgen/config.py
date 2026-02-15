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
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
  """Configuration object for WPT-Gen."""

  provider: str
  model: str
  api_key: str
  wpt_path: str
  verbose: bool = False


WPT_DEFAULT_PATH = os.path.abspath(os.path.join(os.getcwd(), os.pardir, 'wpt'))


def load_config(
  config_path: str = 'wpt-gen.yml',
  provider_override: str | None = None,
  wpt_dir_override: str | None = None,
  verbose_override: bool = False,
) -> Config:
  """
  Loads configuration from YAML and environment variables.
  Selects the active LLM provider and fetches the corresponding API key.
  """
  path = Path(config_path)
  yaml_data: dict = {}

  if path.exists():
    with open(path, encoding='utf-8') as f:
      yaml_data = yaml.safe_load(f) or {}

  # Determine the active provider
  # CLI override takes precedence, then YAML default.
  active_provider = provider_override or yaml_data.get('default_provider', 'gemini')
  active_provider = active_provider.lower()

  # Extract provider-specific settings
  providers_config = yaml_data.get('providers', {})
  provider_settings = providers_config.get(active_provider, {})

  # Provide sensible defaults if the YAML is missing the specific provider block
  if active_provider == 'gemini':
    model = provider_settings.get('model', 'gemini-3-pro-preview')
    env_var_name = 'GEMINI_API_KEY'
  elif active_provider == 'openai':
    model = provider_settings.get('model', 'gpt-5.2-high')
    env_var_name = 'OPENAI_API_KEY'
  else:
    raise ValueError(f"CRITICAL: Unsupported provider '{active_provider}' requested.")

  # Enforce the environment variable constraint for the active provider
  api_key = os.environ.get(env_var_name)
  if not api_key:
    raise ValueError(
      f'CRITICAL: {env_var_name} environment variable is missing. '
      f"Required when using the '{active_provider}' provider."
    )

  wpt_path = wpt_dir_override or yaml_data.get('wpt_path', WPT_DEFAULT_PATH)
  verbose = verbose_override or yaml_data.get('verbose', False)

  return Config(
    provider=active_provider, model=model, api_key=api_key, wpt_path=wpt_path, verbose=verbose
  )

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

from pathlib import Path

import pytest

from wptgen.config import Config, load_config


def test_load_config_default_gemini_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
  """Test the happy path: default provider (gemini) with a valid API key."""
  # Mock the environment variable
  monkeypatch.setenv('GEMINI_API_KEY', 'mock-gemini-key-123')

  # Pass a non-existent config path so it relies purely on the code's defaults
  config = load_config(config_path='non_existent_dummy.yaml')

  assert isinstance(config, Config)
  assert config.provider == 'gemini'
  assert config.default_model == 'gemini-3-pro-preview'
  assert config.api_key == 'mock-gemini-key-123'
  assert config.categories == {
    'lightweight': 'gemini-3-flash-preview',
    'reasoning': 'gemini-3-pro-preview',
  }
  assert config.phase_model_mapping == {
    'requirements_extraction': 'reasoning',
    'coverage_audit': 'reasoning',
    'generation': 'lightweight',
    'evaluation': 'lightweight',
  }


def test_load_config_provider_override_openai(monkeypatch: pytest.MonkeyPatch) -> None:
  """Test overriding the provider via the CLI flag to openai."""
  # Mock the OpenAI key instead
  monkeypatch.setenv('OPENAI_API_KEY', 'mock-openai-key-456')

  # Force the provider to openai
  config = load_config(config_path='non_existent_dummy.yaml', provider_override='openai')

  assert config.provider == 'openai'
  assert config.default_model == 'gpt-5.2-high'
  assert config.api_key == 'mock-openai-key-456'
  assert config.categories == {
    'lightweight': 'gpt-4o-mini',
    'reasoning': 'gpt-5.2-high',
  }


def test_load_config_missing_api_key_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
  """Test that missing the required environment variable raises a ValueError."""
  # Ensure the environment variable is explicitly removed for this test
  monkeypatch.delenv('GEMINI_API_KEY', raising=False)

  # Verify the exact error is raised
  with pytest.raises(ValueError, match='GEMINI_API_KEY environment variable is missing'):
    load_config(config_path='non_existent_dummy.yaml')


def test_load_config_unsupported_provider() -> None:
  """Test that requesting a random/unsupported provider raises an error."""
  with pytest.raises(ValueError, match='CRITICAL: Unsupported provider'):
    load_config(config_path='non_existent_dummy.yaml', provider_override='sillyLLM')


def test_load_config_spec_urls(monkeypatch: pytest.MonkeyPatch) -> None:
  """Test that spec_urls are correctly loaded into the Config object."""
  monkeypatch.setenv('GEMINI_API_KEY', 'mock-key')
  spec_urls = ['https://example.com/spec1', 'https://example.com/spec2']

  config = load_config(config_path='non_existent_dummy.yaml', spec_urls_override=spec_urls)

  assert config.spec_urls == spec_urls


def test_load_config_output_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  """Test that output_dir is correctly loaded and validated."""
  monkeypatch.setenv('GEMINI_API_KEY', 'mock-key')

  # Case 1: Default (resolves to current directory)
  config = load_config(config_path='non_existent_dummy.yaml')
  assert config.output_dir == str(Path('.').resolve())

  # Case 2: Override with existing directory
  test_dir = tmp_path / 'existing_dir'
  test_dir.mkdir()
  config = load_config(config_path='non_existent_dummy.yaml', output_dir_override=str(test_dir))
  assert config.output_dir == str(test_dir.resolve())

  # Case 3: Override with non-existent directory (should be created)
  new_dir = tmp_path / 'new_dir'
  config = load_config(config_path='non_existent_dummy.yaml', output_dir_override=str(new_dir))
  assert config.output_dir == str(new_dir.resolve())
  assert new_dir.exists()


def test_validate_output_dir_handles_home_expansion(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  """Test that validate_output_dir expands ~."""
  from wptgen.config import validate_output_dir

  # Mock HOME environment variable
  fake_home = tmp_path / 'fake_home'
  fake_home.mkdir()
  monkeypatch.setenv('HOME', str(fake_home))

  validated = validate_output_dir('~/my_tests')

  assert validated == str((fake_home / 'my_tests').resolve())
  assert (fake_home / 'my_tests').exists()


def test_validate_output_dir_permission_error(tmp_path: Path) -> None:
  """Test that validate_output_dir raises ValueError on permission issues."""
  from wptgen.config import validate_output_dir

  restricted_dir = tmp_path / 'restricted'
  restricted_dir.mkdir(mode=0o555)  # Read and execute, no write

  try:
    with pytest.raises(ValueError, match='CRITICAL: Cannot write to output directory'):
      validate_output_dir(str(restricted_dir / 'subdir'))
  finally:
    restricted_dir.chmod(0o777)  # Clean up

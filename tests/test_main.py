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

from importlib.metadata import version
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from wptgen.config import DEFAULT_CONFIG_PATH, Config
from wptgen.main import app

# The CliRunner simulates a user typing commands into the terminal
runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a dummy configuration object for successful test runs."""
  return Config(
    provider='gemini',
    default_model='gemini-3.1-pro-preview',
    api_key='fake-key',
    categories={
      'lightweight': 'gemini-3.1-pro-preview',
      'reasoning': 'gemini-3-pro-preview',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / 'cache'),
    output_dir=str(tmp_path / 'output'),
    max_retries=3,
  )


def test_help_menu() -> None:
  """Test that the CLI help menu renders correctly without errors."""
  result = runner.invoke(app, ['--help'])

  assert result.exit_code == 0
  assert 'AI-Powered Web Platform Test Generation CLI' in result.stdout


def test_version() -> None:
  """Test that the version command prints the correct version."""
  result = runner.invoke(app, ['version'])

  assert result.exit_code == 0
  assert f'wpt-gen version {version("wpt-gen")}' in result.stdout


def test_generate_success(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the happy path execution of the generate command."""
  # Mock load_config and the Engine so they don't actually execute
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_engine_class = mocker.patch('wptgen.main.WPTGenEngine')
  mock_engine_instance = mock_engine_class.return_value

  # Simulate running `wpt-gen generate grid --provider gemini`
  result = runner.invoke(app, ['generate', 'grid', '--provider', 'gemini'])

  # Check standard output and exit code
  assert result.exit_code == 0
  assert 'Target Feature' in result.stdout
  assert 'Workflow completed successfully' in result.stdout

  # Verify our logic called the underlying functions with the correct CLI arguments
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override='gemini',
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )
  mock_engine_class.assert_called_once()
  # Verify config was passed correctly
  assert mock_engine_class.call_args[1]['config'] == mock_config
  mock_engine_instance.run_workflow.assert_called_once_with('grid')


def test_generate_show_responses(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --show-responses flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --show-responses
  result = runner.invoke(app, ['generate', 'grid', '--show-responses'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=True,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_generate_yes_tokens(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --yes-tokens flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --yes-tokens
  result = runner.invoke(app, ['generate', 'grid', '--yes-tokens'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=True,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_generate_suggestions_only(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --suggestions-only flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --suggestions-only
  result = runner.invoke(app, ['generate', 'grid', '--suggestions-only'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=True,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_generate_max_retries(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --max-retries flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --max-retries
  result = runner.invoke(app, ['generate', 'grid', '--max-retries', '5'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=5,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_generate_detailed_requirements(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --detailed-requirements flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --detailed-requirements
  result = runner.invoke(app, ['generate', 'grid', '--detailed-requirements'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=True,
  )


def test_generate_config_error(mocker: MockerFixture) -> None:
  """Test that configuration errors (like missing API keys) are caught and exit gracefully."""
  # Force load_config to raise a ValueError
  mock_error_message = 'GEMINI_API_KEY environment variable is missing'
  mocker.patch('wptgen.main.load_config', side_effect=ValueError(mock_error_message))

  result = runner.invoke(app, ['generate', 'popover'])

  # Typer.Exit(code=1) translates to exit_code 1 in the runner
  assert result.exit_code == 1
  assert 'Configuration Error' in result.stdout
  assert mock_error_message in result.stdout


def test_generate_unexpected_error(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that unexpected runtime errors inside the engine are caught and exit gracefully."""
  # Setup mocks but force the engine's run_workflow to crash
  mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_engine_class = mocker.patch('wptgen.main.WPTGenEngine')
  mock_engine_instance = mock_engine_class.return_value
  mock_engine_instance.run_workflow.side_effect = Exception('Engine simulation failed')

  result = runner.invoke(app, ['generate', 'grid'])

  assert result.exit_code == 1
  assert 'Unexpected Error' in result.stdout
  assert 'Engine simulation failed' in result.stdout


def test_generate_spec_urls(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --spec-urls flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --spec-urls
  result = runner.invoke(
    app, ['generate', 'grid', '--spec-urls', 'https://url1.com, https://url2.com']
  )

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=['https://url1.com', 'https://url2.com'],
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_generate_description(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --description flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --description
  result = runner.invoke(app, ['generate', 'grid', '--description', 'Test Description'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override='Test Description',
    detailed_requirements_override=False,
  )


def test_generate_resume(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --resume flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --resume
  result = runner.invoke(app, ['generate', 'grid', '--resume'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    suggestions_only=False,
    resume_override=True,
    max_retries_override=3,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
  )


def test_version_not_found(mocker: MockerFixture) -> None:
  """Test version command when package is not found."""
  mocker.patch('wptgen.main.app_version', side_effect=ImportError)  # Typer might use importlib
  # Actually main.py catches PackageNotFoundError
  from importlib.metadata import PackageNotFoundError

  mocker.patch('wptgen.main.app_version', side_effect=PackageNotFoundError)
  result = runner.invoke(app, ['version'])
  assert result.exit_code == 0
  assert 'unknown' in result.stdout


def test_main_callback() -> None:
  """Test the main callback."""
  from wptgen.main import main_callback

  main_callback()  # Should just pass

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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=True,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=5,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=True,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_generate_skip_evaluation(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --skip-evaluation/--no-eval flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --skip-evaluation
  result = runner.invoke(app, ['generate', 'grid', '--skip-evaluation'])
  assert result.exit_code == 0
  mock_load_config.assert_called_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=True,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )

  # Run with --no-eval alias
  mock_load_config.reset_mock()
  result = runner.invoke(app, ['generate', 'grid', '--no-eval'])
  assert result.exit_code == 0
  mock_load_config.assert_called_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=True,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=['https://url1.com', 'https://url2.com'],
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override='Test Description',
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
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
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=True,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_generate_use_lightweight(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --use-lightweight flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --use-lightweight
  result = runner.invoke(app, ['generate', 'grid', '--use-lightweight'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=True,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_generate_use_reasoning(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --use-reasoning flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --use-reasoning
  result = runner.invoke(app, ['generate', 'grid', '--use-reasoning'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=True,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_generate_single_prompt_requirements(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --single-prompt-requirements flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --single-prompt-requirements
  result = runner.invoke(app, ['generate', 'grid', '--single-prompt-requirements'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=True,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_generate_max_parallel_requests(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --max-parallel-requests flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  # Run with --max-parallel-requests
  result = runner.invoke(app, ['generate', 'grid', '--max-parallel-requests', '5'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=False,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=5,
    temperature_override=None,
  )


def test_generate_mutually_exclusive_models(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that providing both model flags results in an error."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['generate', 'grid', '--use-lightweight', '--use-reasoning'])

  assert result.exit_code == 1
  assert 'Cannot use both --use-lightweight and --use-reasoning' in result.stdout


def test_generate_mutually_exclusive_requirements(
  mocker: MockerFixture, mock_config: Config
) -> None:
  """Test that providing both requirements flags results in an error."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(
    app, ['generate', 'grid', '--detailed-requirements', '--single-prompt-requirements']
  )

  assert result.exit_code == 1
  assert 'Cannot use both --detailed-requirements and --single-prompt-requirements' in result.stdout


def test_version_not_found(mocker: MockerFixture) -> None:
  """Test version command when package is not found."""
  mocker.patch('wptgen.main.app_version', side_effect=ImportError)  # Typer might use importlib
  # Actually main.py catches PackageNotFoundError
  from importlib.metadata import PackageNotFoundError

  mocker.patch('wptgen.main.app_version', side_effect=PackageNotFoundError)
  result = runner.invoke(app, ['version'])
  assert result.exit_code == 0
  assert 'unknown' in result.stdout


def test_doctor_command_success(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the doctor command when all checks pass."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_config.api_key = 'fake-key'

  mocker.patch('pathlib.Path.is_dir', return_value=True)
  mocker.patch('pathlib.Path.exists', return_value=True)
  mocker.patch('os.access', return_value=True)

  result = runner.invoke(app, ['doctor'])
  assert result.exit_code == 0
  assert 'All checks passed! System is ready.' in result.stdout


def test_doctor_command_failure(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the doctor command when checks fail."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_config.api_key = None

  mocker.patch('pathlib.Path.is_dir', return_value=False)

  result = runner.invoke(app, ['doctor'])
  assert result.exit_code == 1
  assert 'Some checks failed.' in result.stdout


def test_list_models_command(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the list-models command prints the configured models."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['list-models'])

  assert result.exit_code == 0
  assert 'Configured Models' in result.stdout
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH, provider_override=None, require_api_key=False
  )


def test_list_models_command_provider_override(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the list-models command respects provider override."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['list-models', '--provider', 'openai'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH, provider_override='openai', require_api_key=False
  )


def test_list_models_command_error(mocker: MockerFixture) -> None:
  """Test the list-models command handles errors gracefully."""
  mocker.patch('wptgen.main.load_config', side_effect=ValueError('Invalid provider'))

  result = runner.invoke(app, ['list-models', '--provider', 'fake'])

  assert result.exit_code == 1
  assert 'Error:' in result.stdout
  assert 'Invalid provider' in result.stdout


def test_main_callback() -> None:
  """Test the main callback."""
  from wptgen.main import main_callback

  main_callback()  # Should just pass


def test_config_command(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the config command prints the resolved configuration and its path."""
  mock_config.loaded_from = '/dummy/path/wpt-gen.yml'
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['config'])

  assert result.exit_code == 0
  assert 'Resolved Configuration' in result.stdout
  assert 'provider:' in result.stdout
  assert 'Reading configuration from:' in result.stdout
  assert '/dummy/path/wpt-gen.yml' in result.stdout
  assert 'loaded_from:' not in result.stdout  # Ensure it's not in the YAML dump
  mock_load_config.assert_called_once_with(config_path=DEFAULT_CONFIG_PATH, require_api_key=False)


def test_config_command_defaults(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the config command prints the defaults message when no file is loaded."""
  mock_config.loaded_from = None
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['config'])

  assert result.exit_code == 0
  assert 'Resolved Configuration' in result.stdout
  assert 'Reading configuration from: Defaults (no config file found)' in result.stdout
  mock_load_config.assert_called_once_with(config_path=DEFAULT_CONFIG_PATH, require_api_key=False)


def test_config_command_error(mocker: MockerFixture) -> None:
  """Test the config command handles errors gracefully."""
  mocker.patch('wptgen.main.load_config', side_effect=ValueError('Invalid config'))

  result = runner.invoke(app, ['config'])

  assert result.exit_code == 1
  assert 'Error:' in result.stdout
  assert 'Invalid config' in result.stdout


def test_init_command_global(mocker: MockerFixture) -> None:
  """Test the init command successfully creates a global configuration file."""
  import yaml

  with runner.isolated_filesystem():
    # Mock the global config path so it creates the file within the isolated filesystem
    global_config_path = str(Path('.config/wpt-gen/config.yml').resolve())
    mocker.patch('wptgen.main._get_global_config_path', return_value=global_config_path)

    # Inputs:
    # 1. 'gemini' (provider)
    # 2. '' (default model - accept default)
    # 3. '' (lightweight model - accept default)
    # 4. '' (reasoning model - accept default)
    # 5. '/fake/wpt' (wpt_path)
    result = runner.invoke(app, ['init'], input='gemini\n\n\n\n/fake/wpt\n')

    assert result.exit_code == 0
    assert 'Configuration saved successfully' in result.stdout

    config_path = Path(global_config_path)
    assert config_path.exists()

    with open(config_path, encoding='utf-8') as f:
      config_data = yaml.safe_load(f)

    assert config_data['default_provider'] == 'gemini'
    assert str(Path('/fake/wpt').resolve()) == config_data['wpt_path']
    assert 'providers' in config_data
    assert 'gemini' in config_data['providers']
    assert config_data['providers']['gemini']['default_model'] == 'gemini-3.1-pro-preview'
    assert (
      config_data['providers']['gemini']['categories']['lightweight'] == 'gemini-3-flash-preview'
    )
    assert config_data['providers']['gemini']['categories']['reasoning'] == 'gemini-3.1-pro-preview'


def test_init_command_local(mocker: MockerFixture) -> None:
  """Test the init command successfully creates a local configuration file."""
  import yaml

  with runner.isolated_filesystem():
    local_config_path = str(Path('wpt-gen.yml').resolve())

    # Inputs:
    # 1. 'gemini' (provider)
    # 2. '' (default model - accept default)
    # 3. '' (lightweight model - accept default)
    # 4. '' (reasoning model - accept default)
    # 5. '/fake/wpt' (wpt_path)
    result = runner.invoke(
      app, ['init', '--config', 'wpt-gen.yml'], input='gemini\n\n\n\n/fake/wpt\n'
    )

    assert result.exit_code == 0
    assert 'Configuration saved successfully' in result.stdout

    config_path = Path(local_config_path)
    assert config_path.exists()

    with open(config_path, encoding='utf-8') as f:
      config_data = yaml.safe_load(f)

    assert config_data['default_provider'] == 'gemini'
    assert str(Path('/fake/wpt').resolve()) == config_data['wpt_path']


def test_audit_success(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the happy path execution of the audit command."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_engine_class = mocker.patch('wptgen.main.WPTGenEngine')
  mock_engine_instance = mock_engine_class.return_value

  result = runner.invoke(app, ['audit', 'grid', '--provider', 'gemini'])

  assert result.exit_code == 0
  assert 'Target Feature' in result.stdout
  assert 'Audit completed successfully' in result.stdout

  mock_load_config.assert_called_once()
  kwargs = mock_load_config.call_args.kwargs
  assert kwargs['suggestions_only'] is True
  assert kwargs['skip_evaluation_override'] is True
  assert kwargs['provider_override'] == 'gemini'

  mock_engine_instance.run_workflow.assert_called_once_with('grid')


def test_generate_draft(mocker: MockerFixture, mock_config: Config) -> None:
  """Test that the --draft flag is correctly passed to load_config."""
  mock_load_config = mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mocker.patch('wptgen.main.WPTGenEngine')

  result = runner.invoke(app, ['generate', 'grid', '--draft'])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path=DEFAULT_CONFIG_PATH,
    provider_override=None,
    wpt_dir_override=None,
    output_dir_override=None,
    show_responses=False,
    yes_tokens_override=False,
    yes_tests_override=False,
    suggestions_only=False,
    resume_override=False,
    max_retries_override=3,
    timeout_override=600,
    spec_urls_override=None,
    feature_description_override=None,
    detailed_requirements_override=False,
    draft_override=True,
    single_prompt_requirements_override=False,
    use_lightweight_override=False,
    use_reasoning_override=False,
    skip_evaluation_override=False,
    tentative_override=False,
    max_parallel_requests_override=None,
    temperature_override=None,
  )


def test_config_show_command(mocker: MockerFixture, mock_config: Config) -> None:
  """Test the explicit config show command."""
  mock_config.loaded_from = '/dummy/path/wpt-gen.yml'
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['config', 'show'])

  assert result.exit_code == 0
  assert 'Resolved Configuration' in result.stdout


def test_config_set_command_flat(mocker: MockerFixture) -> None:
  """Test setting a flat configuration value."""
  from pathlib import Path

  import yaml

  with runner.isolated_filesystem():
    config_file = Path('wpt-gen.yml')
    config_file.write_text('default_provider: openai\n')

    result = runner.invoke(
      app, ['config', 'set', 'default_provider', 'gemini', '--config', str(config_file)]
    )

    assert result.exit_code == 0
    assert 'Set default_provider = gemini' in result.stdout

    with open(config_file) as f:
      data = yaml.safe_load(f)
    assert data['default_provider'] == 'gemini'


def test_config_set_command_nested(mocker: MockerFixture) -> None:
  """Test setting a nested configuration value."""
  from pathlib import Path

  import yaml

  with runner.isolated_filesystem():
    config_file = Path('wpt-gen.yml')
    config_file.write_text('providers:\n  gemini:\n    default_model: old-model\n')

    result = runner.invoke(
      app,
      [
        'config',
        'set',
        'providers.gemini.default_model',
        'new-model',
        '--config',
        str(config_file),
      ],
    )

    assert result.exit_code == 0

    with open(config_file) as f:
      data = yaml.safe_load(f)
    assert data['providers']['gemini']['default_model'] == 'new-model'


def test_config_set_command_types(mocker: MockerFixture) -> None:
  """Test type conversion for config set."""
  from pathlib import Path

  import yaml

  with runner.isolated_filesystem():
    config_file = Path('wpt-gen.yml')
    config_file.write_text('')

    runner.invoke(app, ['config', 'set', 'timeout', '120', '--config', str(config_file)])
    runner.invoke(app, ['config', 'set', 'show_responses', 'true', '--config', str(config_file)])
    runner.invoke(app, ['config', 'set', 'temperature', '0.5', '--config', str(config_file)])

    with open(config_file) as f:
      data = yaml.safe_load(f)

    assert data['timeout'] == 120
    assert data['show_responses'] is True
    assert data['temperature'] == 0.5

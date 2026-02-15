import pytest
from typer.testing import CliRunner

from wptgen.config import Config
from wptgen.main import app

# The CliRunner simulates a user typing commands into the terminal
runner = CliRunner()


@pytest.fixture
def mock_config():
  """Provides a dummy configuration object for successful test runs."""
  return Config(
    provider="gemini", model="gemini-3-pro-preview", api_key="fake-key", wpt_path="../wpt"
  )


def test_help_menu():
  """Test that the CLI help menu renders correctly without errors."""
  result = runner.invoke(app, ["--help"])

  assert result.exit_code == 0
  assert "AI-Powered Web Platform Test Generation CLI" in result.stdout


def test_generate_success(mocker, mock_config):
  """Test the happy path execution of the generate command."""
  # Mock load_config and the Engine so they don't actually execute
  mock_load_config = mocker.patch("wptgen.main.load_config", return_value=mock_config)
  mock_engine_class = mocker.patch("wptgen.main.WPTGenEngine")
  mock_engine_instance = mock_engine_class.return_value

  # Simulate running `wpt-gen generate grid --provider gemini`
  result = runner.invoke(app, ["generate", "grid", "--provider", "gemini"])

  # Check standard output and exit code
  assert result.exit_code == 0
  assert "Starting WPT-Gen for feature" in result.stdout
  assert "Workflow completed successfully" in result.stdout

  # Verify our logic called the underlying functions with the correct CLI arguments
  mock_load_config.assert_called_once_with(
    config_path="wpt-gen.yml",
    provider_override="gemini",
    wpt_dir_override=None,
    verbose_override=False,
  )
  mock_engine_class.assert_called_once_with(config=mock_config)
  mock_engine_instance.run_workflow.assert_called_once_with("grid")


def test_generate_verbose(mocker, mock_config):
  """Test that the --verbose flag is correctly passed to load_config."""
  mock_load_config = mocker.patch("wptgen.main.load_config", return_value=mock_config)
  mocker.patch("wptgen.main.WPTGenEngine")

  # Run with --verbose
  result = runner.invoke(app, ["generate", "grid", "--verbose"])

  assert result.exit_code == 0
  mock_load_config.assert_called_once_with(
    config_path="wpt-gen.yml",
    provider_override=None,
    wpt_dir_override=None,
    verbose_override=True,
  )


def test_generate_config_error(mocker):
  """Test that configuration errors (like missing API keys) are caught and exit gracefully."""
  # Arrange: Force load_config to raise a ValueError
  mock_error_message = "GEMINI_API_KEY environment variable is missing"
  mocker.patch("wptgen.main.load_config", side_effect=ValueError(mock_error_message))

  result = runner.invoke(app, ["generate", "popover"])

  # Typer.Exit(code=1) translates to exit_code 1 in the runner
  assert result.exit_code == 1
  assert "Configuration Error" in result.stdout
  assert mock_error_message in result.stdout


def test_generate_unexpected_error(mocker, mock_config):
  """Test that unexpected runtime errors inside the engine are caught and exit gracefully."""
  # Setup mocks but force the engine's run_workflow to crash
  mocker.patch("wptgen.main.load_config", return_value=mock_config)
  mock_engine_class = mocker.patch("wptgen.main.WPTGenEngine")
  mock_engine_instance = mock_engine_class.return_value
  mock_engine_instance.run_workflow.side_effect = Exception("Engine simulation failed")

  result = runner.invoke(app, ["generate", "grid"])

  assert result.exit_code == 1
  assert "Unexpected Error" in result.stdout
  assert "Engine simulation failed" in result.stdout

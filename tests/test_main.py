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

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pytest
import yaml
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
        provider="gemini",
        default_model="gemini-3.1-pro-preview",
        api_key="fake-key",
        categories={
            "lightweight": "gemini-3.1-pro-preview",
            "reasoning": "gemini-3-pro-preview",
        },
        phase_model_mapping={
            "requirements_extraction": "reasoning",
            "coverage_audit": "reasoning",
            "generation": "lightweight",
        },
        wpt_path=str(tmp_path / "wpt"),
        cache_path=str(tmp_path / "cache"),
        output_dir=str(tmp_path / "output"),
        max_retries=3,
    )


@pytest.fixture
def mock_load_config(mocker: MockerFixture, mock_config: Config) -> Any:
    """Mocks load_config to return the mock_config."""
    return mocker.patch("wptgen.main.load_config", return_value=mock_config)


@pytest.fixture
def mock_engine_instance(mocker: MockerFixture) -> Any:
    """Mocks the WPTGenEngine class and returns its instance mock."""
    mock_engine_class = mocker.patch("wptgen.main.WPTGenEngine")
    return mock_engine_class.return_value


@pytest.fixture
def default_load_config_kwargs() -> (
    dict[str, bool | str | int | None | list[str]]
):
    """Returns the expected default kwargs for load_config."""
    return {
        "config_path": DEFAULT_CONFIG_PATH,
        "provider_override": None,
        "wpt_dir_override": None,
        "output_dir_override": None,
        "show_responses": False,
        "yes_tokens_override": False,
        "yes_tests_override": False,
        "yes_cache_override": False,
        "no_cache_override": False,
        "suggestions_only": False,
        "brief_suggestions": False,
        "resume_override": False,
        "skip_run_override": False,
        "resume_from_override": None,
        "state_dir_override": None,
        "max_retries_override": 3,
        "timeout_override": 600,
        "spec_urls_override": None,
        "feature_description_override": None,
        "detailed_requirements_override": False,
        "include_mdn_docs_override": False,
        "draft_override": False,
        "single_prompt_requirements_override": False,
        "use_lightweight_override": False,
        "use_reasoning_override": False,
        "tentative_override": False,
        "save_traces_override": False,
        "audit_partition_size_override": None,
        "max_parallel_requests_override": None,
        "temperature_override": None,
        "include_thoughts_override": False,
        "run_on_browser_override": None,
        "run_on_channel_override": None,
    }


def test_help_menu() -> None:
    """Test that the CLI help menu renders correctly without errors."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "AI-Powered Web Platform Test Generation CLI" in result.stdout


def test_version() -> None:
    """Test that the version command prints the correct version."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert f'wpt-gen version {version("wpt-gen")}' in result.stdout


def test_version_not_found(mocker: MockerFixture) -> None:
    """Test version command when package is not found."""
    mocker.patch("wptgen.main.app_version", side_effect=PackageNotFoundError)
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "unknown" in result.stdout


def test_generate_success(
    mocker: MockerFixture,
    mock_config: Config,
    mock_load_config: Any,
    mock_engine_instance: Any,
    default_load_config_kwargs: dict[str, bool | str | int | None | list[str]],
) -> None:
    """Test the happy path execution of the generate command."""
    result = runner.invoke(app, ["generate", "grid", "--provider", "gemini"])

    assert result.exit_code == 0
    assert "Target Feature" in result.stdout
    assert "Workflow completed successfully" in result.stdout

    expected_kwargs = default_load_config_kwargs.copy()
    expected_kwargs["provider_override"] = "gemini"

    mock_load_config.assert_called_once_with(**expected_kwargs)

    # Verify config was passed correctly
    mock_engine_instance.run_workflow.assert_called_once_with("grid")


@pytest.mark.parametrize(
    ("flag", "kwarg_key", "kwarg_value", "flag_args"),
    [
        ("--show-responses", "show_responses", True, []),
        ("--yes-tokens", "yes_tokens_override", True, []),
        ("--suggestions-only", "suggestions_only", True, []),
        ("--max-retries", "max_retries_override", 5, ["5"]),
        ("--detailed-requirements", "detailed_requirements_override", True, []),
        (
            "--spec-urls",
            "spec_urls_override",
            ["https://url1.com", "https://url2.com"],
            ["https://url1.com, https://url2.com"],
        ),
        (
            "--description",
            "feature_description_override",
            "Test Description",
            ["Test Description"],
        ),
        ("--resume", "resume_override", True, []),
        ("--use-lightweight", "use_lightweight_override", True, []),
        ("--use-reasoning", "use_reasoning_override", True, []),
        (
            "--single-prompt-requirements",
            "single_prompt_requirements_override",
            True,
            [],
        ),
        ("--max-parallel-requests", "max_parallel_requests_override", 5, ["5"]),
        ("--draft", "draft_override", True, []),
        ("--brief-suggestions", "brief_suggestions", True, []),
    ],
)
def test_generate_flags(
    flag: str,
    kwarg_key: str,
    kwarg_value: bool | str | int | list[str],
    flag_args: list[str],
    mock_load_config: Any,
    mock_engine_instance: Any,
    default_load_config_kwargs: dict[str, bool | str | int | None | list[str]],
) -> None:
    """Test that flags are correctly passed to load_config."""
    args = ["generate", "grid", flag] + flag_args
    result = runner.invoke(app, args)

    assert result.exit_code == 0

    expected_kwargs = default_load_config_kwargs.copy()
    expected_kwargs[kwarg_key] = kwarg_value
    mock_load_config.assert_called_once_with(**expected_kwargs)


def test_generate_config_error(mocker: MockerFixture) -> None:
    """Test that configuration errors (like missing API keys) are caught and exit gracefully."""
    mock_error_message = "GEMINI_API_KEY environment variable is missing"
    mocker.patch(
        "wptgen.main.load_config", side_effect=ValueError(mock_error_message)
    )

    result = runner.invoke(app, ["generate", "popover"])

    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout
    assert mock_error_message in result.stdout


def test_generate_unexpected_error(
    mock_load_config: Any, mock_engine_instance: Any
) -> None:
    """Test that unexpected runtime errors inside the engine are caught and exit gracefully."""
    mock_engine_instance.run_workflow.side_effect = Exception(
        "Engine simulation failed"
    )

    result = runner.invoke(app, ["generate", "grid"])

    assert result.exit_code == 1
    assert "Unexpected Error" in result.stdout
    assert "Engine simulation failed" in result.stdout


def test_generate_mutually_exclusive_models(mock_load_config: Any) -> None:
    """Test that providing both model flags results in an error."""
    result = runner.invoke(
        app, ["generate", "grid", "--use-lightweight", "--use-reasoning"]
    )

    assert result.exit_code == 1
    assert (
        "Cannot use both --use-lightweight and --use-reasoning" in result.stdout
    )


def test_generate_mutually_exclusive_requirements(
    mock_load_config: Any,
) -> None:
    """Test that providing both requirements flags results in an error."""
    result = runner.invoke(
        app,
        [
            "generate",
            "grid",
            "--detailed-requirements",
            "--single-prompt-requirements",
        ],
    )

    assert result.exit_code == 1
    assert (
        "Cannot use both --detailed-requirements and --single-prompt-requirements"
        in result.stdout
    )


def test_generate_wf_yml_update_validation() -> None:
    """Test that --wf-yml-update without --output-dir exits with an error."""
    result = runner.invoke(app, ["generate", "my-feature", "--wf-yml-update"])
    assert result.exit_code == 1
    assert (
        "--output-dir is required when using --wf-yml-update" in result.stdout
    )


def test_doctor_command_success(
    mocker: MockerFixture, mock_config: Config, mock_load_config: Any
) -> None:
    """Test the doctor command when all checks pass."""
    mock_config.api_key = "fake-key"

    mocker.patch("pathlib.Path.is_dir", return_value=True)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("os.access", return_value=True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "All checks passed! System is ready." in result.stdout


def test_doctor_command_failure(
    mocker: MockerFixture, mock_config: Config, mock_load_config: Any
) -> None:
    """Test the doctor command when checks fail."""
    mock_config.api_key = None
    mocker.patch("pathlib.Path.is_dir", return_value=False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Some checks failed." in result.stdout


def test_list_models_command(mock_load_config: Any) -> None:
    """Test the list-models command prints the configured models."""
    result = runner.invoke(app, ["list-models"])

    assert result.exit_code == 0
    assert "Configured Models" in result.stdout
    mock_load_config.assert_called_once_with(
        config_path=DEFAULT_CONFIG_PATH,
        provider_override=None,
        require_api_key=False,
    )


def test_list_models_command_provider_override(mock_load_config: Any) -> None:
    """Test the list-models command respects provider override."""
    result = runner.invoke(app, ["list-models", "--provider", "openai"])

    assert result.exit_code == 0
    mock_load_config.assert_called_once_with(
        config_path=DEFAULT_CONFIG_PATH,
        provider_override="openai",
        require_api_key=False,
    )


def test_list_models_command_error(mocker: MockerFixture) -> None:
    """Test the list-models command handles errors gracefully."""
    mocker.patch(
        "wptgen.main.load_config", side_effect=ValueError("Invalid provider")
    )

    result = runner.invoke(app, ["list-models", "--provider", "fake"])

    assert result.exit_code == 1
    assert "Error:" in result.stdout
    assert "Invalid provider" in result.stdout


def test_main_callback() -> None:
    """Test the main callback."""
    from wptgen.main import main_callback

    main_callback()  # Should just pass


def test_config_command(mock_config: Config, mock_load_config: Any) -> None:
    """Test the config command prints the resolved configuration and its path."""
    mock_config.loaded_from = "/dummy/path/wpt-gen.yml"

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "Resolved Configuration" in result.stdout
    assert "provider" in result.stdout
    assert "gemini" in result.stdout
    assert "Reading configuration from:" in result.stdout
    assert "/dummy/path/wpt-gen.yml" in result.stdout
    assert (
        "loaded_from:" not in result.stdout
    )  # Ensure it's not in the YAML dump
    mock_load_config.assert_any_call(
        config_path=DEFAULT_CONFIG_PATH, require_api_key=False
    )


def test_config_command_defaults(
    mock_config: Config, mock_load_config: Any
) -> None:
    """Test the config command prints the defaults message when no file is loaded."""
    mock_config.loaded_from = None

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "Resolved Configuration" in result.stdout
    assert (
        "Reading configuration from: Defaults (no config file found)"
        in result.stdout
    )
    mock_load_config.assert_any_call(
        config_path=DEFAULT_CONFIG_PATH, require_api_key=False
    )


def test_config_command_error(mocker: MockerFixture) -> None:
    """Test the config command handles errors gracefully."""
    mocker.patch(
        "wptgen.main.load_config", side_effect=ValueError("Invalid config")
    )

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 1
    assert "Error:" in result.stdout
    assert "Invalid config" in result.stdout


def test_init_command_global(mocker: MockerFixture) -> None:
    """Test the init command successfully creates a global configuration file."""
    with runner.isolated_filesystem():
        # Mock the global config path so it creates the file within the isolated filesystem
        global_config_path = str(Path(".config/wpt-gen/config.yml").resolve())
        mocker.patch(
            "wptgen.main._get_global_config_path",
            return_value=global_config_path,
        )

        result = runner.invoke(app, ["init"], input="gemini\n\n\n\n/fake/wpt\n")

        assert result.exit_code == 0
        assert "Configuration saved successfully" in result.stdout

        config_path = Path(global_config_path)
        assert config_path.exists()

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        assert config_data["default_provider"] == "gemini"
        assert str(Path("/fake/wpt").resolve()) == config_data["wpt_path"]
        assert "providers" in config_data
        assert "gemini" in config_data["providers"]
        assert (
            config_data["providers"]["gemini"]["default_model"]
            == "gemini-3.1-pro-preview"
        )
        assert (
            config_data["providers"]["gemini"]["categories"]["lightweight"]
            == "gemini-3-flash-preview"
        )
        assert (
            config_data["providers"]["gemini"]["categories"]["reasoning"]
            == "gemini-3.1-pro-preview"
        )


def test_init_command_local() -> None:
    """Test the init command successfully creates a local configuration file."""
    with runner.isolated_filesystem():
        local_config_path = str(Path("wpt-gen.yml").resolve())

        result = runner.invoke(
            app,
            ["init", "--config", "wpt-gen.yml"],
            input="gemini\n\n\n\n/fake/wpt\n",
        )

        assert result.exit_code == 0
        assert "Configuration saved successfully" in result.stdout

        config_path = Path(local_config_path)
        assert config_path.exists()

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        assert config_data["default_provider"] == "gemini"
        assert str(Path("/fake/wpt").resolve()) == config_data["wpt_path"]


def test_init_command_with_wpt_path_flag() -> None:
    """Test the init command accepts --wpt-path and skips the prompt."""
    with runner.isolated_filesystem():
        local_config_path = str(Path("wpt-gen.yml").resolve())

        result = runner.invoke(
            app,
            ["init", "--config", "wpt-gen.yml", "--wpt-path", "/flag/wpt"],
            input="gemini\n\n\n\n",
        )

        assert result.exit_code == 0
        assert "Configuration saved successfully" in result.stdout

        config_path = Path(local_config_path)
        assert config_path.exists()

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        assert config_data["default_provider"] == "gemini"
        assert str(Path("/flag/wpt").resolve()) == config_data["wpt_path"]


@pytest.mark.parametrize("suggestions_only", [True, False])
def test_chromestatus_command(
    mock_config: Config,
    mock_load_config: Any,
    mock_engine_instance: Any,
    suggestions_only: bool,
) -> None:
    """Test the chromestatus command with and without --suggestions-only."""
    # Mock load_config and the Engine so they don't actually execute
    mock_config.chromestatus = True

    # Simulate running `wpt-gen chromestatus 12345`
    args = ["chromestatus", "12345"]
    if suggestions_only:
        args.append("--suggestions-only")

    result = runner.invoke(app, args)

    # Check standard output and exit code
    assert result.exit_code == 0
    assert "Target ChromeStatus Feature" in result.stdout

    # Verify our logic called the underlying functions with the correct CLI arguments
    mock_load_config.assert_called_once()
    kwargs = mock_load_config.call_args.kwargs
    assert kwargs["suggestions_only"] is suggestions_only
    assert kwargs["chromestatus_override"] is True

    # Ensure the engine workflow was triggered with the correct feature ID
    mock_engine_instance.run_workflow.assert_called_once_with("12345")


def test_audit_success(
    mock_load_config: Any, mock_engine_instance: Any
) -> None:
    """Test the happy path execution of the audit command."""
    result = runner.invoke(app, ["audit", "grid", "--provider", "gemini"])

    assert result.exit_code == 0
    assert "Target Feature" in result.stdout
    assert "Audit completed successfully" in result.stdout

    mock_load_config.assert_called_once()
    kwargs = mock_load_config.call_args.kwargs
    assert kwargs["suggestions_only"] is True
    assert kwargs["provider_override"] == "gemini"

    mock_engine_instance.run_workflow.assert_called_once_with("grid")


def test_config_show_command(
    mock_config: Config, mock_load_config: Any
) -> None:
    """Test the explicit config show command."""
    mock_config.loaded_from = "/dummy/path/wpt-gen.yml"

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "Resolved Configuration" in result.stdout


def test_config_set_command_flat() -> None:
    """Test setting a flat configuration value."""
    with runner.isolated_filesystem():
        config_file = Path("wpt-gen.yml")
        config_file.write_text("default_provider: openai\n")

        result = runner.invoke(
            app,
            [
                "config",
                "set",
                "default_provider",
                "gemini",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        assert "Set default_provider = gemini" in result.stdout

        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["default_provider"] == "gemini"


def test_config_set_command_nested() -> None:
    """Test setting a nested configuration value."""
    with runner.isolated_filesystem():
        config_file = Path("wpt-gen.yml")
        config_file.write_text(
            "providers:\n  gemini:\n    default_model: old-model\n"
        )

        result = runner.invoke(
            app,
            [
                "config",
                "set",
                "providers.gemini.default_model",
                "new-model",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["providers"]["gemini"]["default_model"] == "new-model"


def test_config_set_command_types() -> None:
    """Test type conversion for config set."""
    with runner.isolated_filesystem():
        config_file = Path("wpt-gen.yml")
        config_file.write_text("")

        runner.invoke(
            app,
            ["config", "set", "timeout", "120", "--config", str(config_file)],
        )
        runner.invoke(
            app,
            [
                "config",
                "set",
                "show_responses",
                "true",
                "--config",
                str(config_file),
            ],
        )
        runner.invoke(
            app,
            [
                "config",
                "set",
                "temperature",
                "0.5",
                "--config",
                str(config_file),
            ],
        )

        with open(config_file) as f:
            data = yaml.safe_load(f)

        assert data["timeout"] == 120
        assert data["show_responses"] is True
        assert data["temperature"] == 0.5

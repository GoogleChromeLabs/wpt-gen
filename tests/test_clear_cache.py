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

"""Tests for the clear-cache command."""
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from wptgen.config import Config
from wptgen.main import app

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Provides a dummy configuration object."""
    cache_path = tmp_path / "cache"
    cache_path.mkdir()
    return Config(
        provider="gemini",
        default_model="gemini-3.1-pro-preview",
        api_key=None,  # API key is not required for clear-cache
        categories={},
        phase_model_mapping={},
        wpt_path=str(tmp_path / "wpt"),
        cache_path=str(cache_path),
        output_dir=str(tmp_path / "output"),
    )


@pytest.fixture
def mock_load_config(mocker: MockerFixture, mock_config: Config) -> MagicMock:
    """Mocks load_config to return the mock_config."""
    return mocker.patch("wptgen.main.load_config", return_value=mock_config)


@pytest.fixture
def mock_ui(mocker: MockerFixture) -> MagicMock:
    """Mocks the UI interactions."""
    # Since ui is now instantiated locally in each command, we patch the class.
    mock_provider = mocker.patch("wptgen.main.RichUIProvider").return_value
    # Set default behaviors for a mock UI
    mock_provider.confirm.return_value = True
    return mock_provider  # type: ignore[no-any-return]


def test_clear_cache_success(
    mock_config: Config, mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test successful cache clearing when user confirms."""
    mock_ui.confirm.return_value = True

    assert mock_config.cache_path is not None
    cache_dir = Path(mock_config.cache_path)

    # Populate cache
    (cache_dir / "file1.txt").write_text("content1", encoding="utf-8")
    (cache_dir / "subdir").mkdir()
    (cache_dir / "subdir" / "file2.txt").write_text(
        "content2", encoding="utf-8"
    )

    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 0
    mock_ui.success.assert_called_with("Cache cleared successfully!")
    assert not (cache_dir / "file1.txt").exists()
    assert not (cache_dir / "subdir").exists()
    assert cache_dir.exists()  # The directory itself should remain, but empty


def test_clear_cache_force(
    mock_config: Config, mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test successful cache clearing when using the --force flag.

    Bypasses confirmation.
    """
    assert mock_config.cache_path is not None
    cache_dir = Path(mock_config.cache_path)

    # Populate cache
    (cache_dir / "file1.txt").write_text("content1", encoding="utf-8")
    (cache_dir / "subdir").mkdir()
    (cache_dir / "subdir" / "file2.txt").write_text(
        "content2", encoding="utf-8"
    )

    result = runner.invoke(app, ["clear-cache", "--force"])

    assert result.exit_code == 0
    mock_ui.confirm.assert_not_called()
    mock_ui.success.assert_called_with("Cache cleared successfully!")
    assert not (cache_dir / "file1.txt").exists()
    assert not (cache_dir / "subdir").exists()
    assert cache_dir.exists()


def test_clear_cache_aborted(
    mock_config: Config, mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test cache clearing when user aborts."""
    mock_ui.confirm.return_value = False

    assert mock_config.cache_path is not None
    cache_dir = Path(mock_config.cache_path)
    cache_file = cache_dir / "file1.txt"
    cache_file.write_text("content1", encoding="utf-8")

    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 0
    mock_ui.print.assert_called_with("Aborted.")
    assert cache_file.exists()


def test_clear_cache_already_empty(
    mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test cache clearing when the directory is already empty."""
    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 0
    mock_ui.info.assert_called()
    assert "already empty" in mock_ui.info.call_args[0][0]


def test_clear_cache_dir_not_exists(
    mock_config: Config, mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test cache clearing when the directory does not exist."""
    assert mock_config.cache_path is not None
    cache_dir = Path(mock_config.cache_path)
    shutil.rmtree(cache_dir)

    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 0
    mock_ui.info.assert_called()
    assert "does not exist" in mock_ui.info.call_args[0][0]


def test_clear_cache_no_path_configured(
    mock_config: Config, mock_load_config: MagicMock, mock_ui: MagicMock
) -> None:
    """Test cache clearing when no cache path is configured."""
    mock_config.cache_path = None

    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 0
    mock_ui.error.assert_called_with("Cache path not configured.")


def test_clear_cache_config_error(
    mocker: MockerFixture, mock_ui: MagicMock
) -> None:
    """Test that configuration errors are handled."""
    mocker.patch(
        "wptgen.main.load_config", side_effect=ValueError("Config error")
    )

    result = runner.invoke(app, ["clear-cache"])

    assert result.exit_code == 1
    mock_ui.error.assert_called()
    assert "Configuration Error" in mock_ui.error.call_args[0][0]
    assert "Config error" in mock_ui.error.call_args[0][0]

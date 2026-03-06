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

import re
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from wptgen.config import Config
from wptgen.main import app

runner = CliRunner()


def normalize_ws(text: str) -> str:
  """Normalizes whitespace by replacing any sequence of whitespace with a single space."""
  return re.sub(r'\s+', ' ', text).strip()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a dummy configuration object."""
  cache_path = tmp_path / 'cache'
  cache_path.mkdir()
  return Config(
    provider='gemini',
    default_model='gemini-3.1-pro-preview',
    api_key=None,  # API key is not required for clear-cache
    categories={},
    phase_model_mapping={},
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(cache_path),
    output_dir=str(tmp_path / 'output'),
  )


def test_clear_cache_success(mocker: MockerFixture, mock_config: Config) -> None:
  """Test successful cache clearing when user confirms."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_ui = mocker.patch('wptgen.main.ui')
  mock_ui.confirm.return_value = True

  assert mock_config.cache_path is not None
  cache_dir = Path(mock_config.cache_path)
  # Populate cache
  (cache_dir / 'file1.txt').write_text('content1')
  (cache_dir / 'subdir').mkdir()
  (cache_dir / 'subdir' / 'file2.txt').write_text('content2')

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 0
  assert 'Cache cleared successfully' in normalize_ws(result.stdout)
  assert not (cache_dir / 'file1.txt').exists()
  assert not (cache_dir / 'subdir').exists()
  assert cache_dir.exists()  # The directory itself should remain, but empty


def test_clear_cache_aborted(mocker: MockerFixture, mock_config: Config) -> None:
  """Test cache clearing when user aborts."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)
  mock_ui = mocker.patch('wptgen.main.ui')
  mock_ui.confirm.return_value = False

  assert mock_config.cache_path is not None
  cache_dir = Path(mock_config.cache_path)
  cache_file = cache_dir / 'file1.txt'
  cache_file.write_text('content1')

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 0
  assert 'Aborted' in normalize_ws(result.stdout)
  assert cache_file.exists()


def test_clear_cache_already_empty(mocker: MockerFixture, mock_config: Config) -> None:
  """Test cache clearing when the directory is already empty."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 0
  assert 'is already empty' in normalize_ws(result.stdout)


def test_clear_cache_dir_not_exists(mocker: MockerFixture, mock_config: Config) -> None:
  """Test cache clearing when the directory does not exist."""
  assert mock_config.cache_path is not None
  cache_dir = Path(mock_config.cache_path)
  import shutil

  shutil.rmtree(cache_dir)

  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 0
  assert 'does not exist' in normalize_ws(result.stdout)


def test_clear_cache_no_path_configured(mocker: MockerFixture, mock_config: Config) -> None:
  """Test cache clearing when no cache path is configured."""
  mock_config.cache_path = None
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 0
  assert 'Cache path not configured' in normalize_ws(result.stdout)


def test_clear_cache_config_error(mocker: MockerFixture) -> None:
  """Test that configuration errors are handled."""
  mocker.patch('wptgen.main.load_config', side_effect=ValueError('Config error'))

  result = runner.invoke(app, ['clear-cache'])

  assert result.exit_code == 1
  assert 'Configuration Error' in normalize_ws(result.stdout)
  assert 'Config error' in normalize_ws(result.stdout)

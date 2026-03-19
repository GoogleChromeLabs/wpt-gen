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
from pathlib import Path

import pytest

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.tools import _validate_safe_path, create_file_tools
from wptgen.config import Config


def _create_mock_config(
  provider: str, api_key: str, default_model: str, wpt_path: Path | str
) -> Config:
  return Config(
    provider=provider,
    default_model=default_model,
    api_key=api_key,
    wpt_path=str(wpt_path),
    categories={},
    phase_model_mapping={},
  )


def test_setup_adk_environment_google(monkeypatch: pytest.MonkeyPatch) -> None:
  config = _create_mock_config('google', 'fake-key', 'gemini-3.1-pro-preview', '/tmp')
  model = setup_adk_environment(config)
  assert os.environ['GOOGLE_API_KEY'] == 'fake-key'
  assert model == 'gemini-3.1-pro-preview'


def test_setup_adk_environment_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(os, 'environ', {})
  config = _create_mock_config('anthropic', 'fake-key', 'claude-opus-4-6', '/tmp')
  model = setup_adk_environment(config)
  assert os.environ['ANTHROPIC_API_KEY'] == 'fake-key'
  assert model == 'claude-opus-4-6'


def test_setup_adk_environment_openai(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(os, 'environ', {})
  config = _create_mock_config('openai', 'fake-key', 'gpt-5.2-high', '/tmp')
  model = setup_adk_environment(config)
  assert os.environ['OPENAI_API_KEY'] == 'fake-key'
  assert model == 'gpt-5.2-high'


def test_setup_adk_environment_missing_key() -> None:
  config = Config(
    provider='google',
    default_model='gemini',
    api_key=None,
    wpt_path='/tmp',
    categories={},
    phase_model_mapping={},
  )
  with pytest.raises(ValueError, match='An API key is required'):
    setup_adk_environment(config)


def test_validate_safe_path_valid(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  target = wpt_root / 'css' / 'test.html'

  resolved = _validate_safe_path(target, wpt_root)
  assert resolved == target.resolve()


def test_validate_safe_path_traversal(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()

  # Attempt to traverse up out of the wpt directory
  malicious_target = wpt_root / 'css' / '..' / '..' / 'etc' / 'passwd'

  with pytest.raises(ValueError, match='is outside the designated WPT repository root'):
    _validate_safe_path(malicious_target, wpt_root)


def test_validate_safe_path_absolute_outside(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()

  malicious_target = Path('/tmp/some_other_dir/file.txt')

  with pytest.raises(ValueError, match='is outside the designated WPT repository root'):
    _validate_safe_path(malicious_target, wpt_root)


def test_file_tools_read_file(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  test_file = wpt_root / 'test.txt'
  test_file.write_text('hello world')

  tools = create_file_tools(wpt_root)
  read_file_tool = next(t for t in tools if t.name == 'read_file')

  # We call the underlying function
  result = read_file_tool.func(str(test_file))
  assert result['status'] == 'success'
  assert result['content'] == 'hello world'


def test_file_tools_write_file(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  test_file = wpt_root / 'new_dir' / 'test.txt'

  tools = create_file_tools(wpt_root)
  write_file_tool = next(t for t in tools if t.name == 'write_file')

  result = write_file_tool.func(str(test_file), 'new content')
  assert result['status'] == 'success'
  assert test_file.read_text() == 'new content'


def test_file_tools_search_files(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  (wpt_root / 'a.js').touch()
  (wpt_root / 'b.html').touch()
  (wpt_root / 'c.js').touch()

  tools = create_file_tools(wpt_root)
  search_files_tool = next(t for t in tools if t.name == 'search_files')

  result = search_files_tool.func(str(wpt_root), '*.js')
  assert result['status'] == 'success'
  assert len(result['files']) == 2
  # Convert files to Path objects to handle path separators safely across OSes
  matched_files = [Path(f).name for f in result['files']]
  assert 'a.js' in matched_files
  assert 'c.js' in matched_files


def test_file_tools_list_directory(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  (wpt_root / 'dir1').mkdir()
  (wpt_root / 'file1.txt').touch()

  tools = create_file_tools(wpt_root)
  list_directory_tool = next(t for t in tools if t.name == 'list_directory')

  result = list_directory_tool.func(str(wpt_root))
  assert result['status'] == 'success'
  assert len(result['entries']) == 2
  matched_entries = [Path(f).name for f in result['entries']]
  assert 'dir1' in matched_entries
  assert 'file1.txt' in matched_entries


def test_file_tools_delete_file(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  test_file = wpt_root / 'to_delete.txt'
  test_file.touch()

  tools = create_file_tools(wpt_root)
  delete_file_tool = next(t for t in tools if t.name == 'delete_file')

  result = delete_file_tool.func(str(test_file))
  assert result['status'] == 'success'
  assert not test_file.exists()


def test_file_tools_security_rejection(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()

  outside_file = tmp_path / 'secret.txt'
  outside_file.write_text('secret')

  tools = create_file_tools(wpt_root)
  read_file_tool = next(t for t in tools if t.name == 'read_file')

  result = read_file_tool.func(str(outside_file))
  assert result['status'] == 'error'
  assert 'outside the designated WPT repository root' in result['error']

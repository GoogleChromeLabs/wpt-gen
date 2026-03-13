import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wptgen.utils import get_recent_test_files


@pytest.fixture
def mock_subprocess_run() -> Generator[MagicMock, None, None]:
  with patch('subprocess.run') as mock_run:
    yield mock_run


@pytest.fixture
def mock_path_methods() -> Generator[Any, None, None]:
  with (
    patch('wptgen.utils.Path.exists', return_value=True),
    patch('wptgen.utils.Path.is_dir', return_value=True),
    patch('wptgen.utils.Path.is_file', return_value=True),
  ):
    yield


def test_get_recent_test_files_success(
  mock_subprocess_run: MagicMock, mock_path_methods: MagicMock
) -> None:
  mock_result = MagicMock()
  # Note: the test simulates duplicate lines (different commits modifying the same file)
  # and files that don't match the required extension.
  mock_result.stdout = (
    'dir/test1.html\ndir/test1.html\ndir/ignore.js\ndir/test2.html\ndir/test3.html\n'
  )
  mock_subprocess_run.return_value = mock_result

  with patch('wptgen.utils.Path.read_text', side_effect=['content 1', 'content 2', 'content 3']):
    files = get_recent_test_files('dir', '.html', limit=2, max_tokens=100)

    assert len(files) == 2
    assert files[0] == ('test1.html', 'content 1')
    assert files[1] == ('test2.html', 'content 2')

    mock_subprocess_run.assert_called_once()
    args, kwargs = mock_subprocess_run.call_args
    assert args[0][:6] == [
      'git',
      'log',
      '--name-only',
      '--pretty=format:',
      '--diff-filter=d',
      '--',
    ]


def test_get_recent_test_files_token_limit(
  mock_subprocess_run: MagicMock, mock_path_methods: MagicMock
) -> None:
  mock_result = MagicMock()
  mock_result.stdout = 'dir/test1.html\ndir/test2.html\n'
  mock_subprocess_run.return_value = mock_result

  # First file is large, second is small. Limit max_tokens=10
  # Heuristic: tokens = len(content) // 4
  # content 1 length is 44 characters (11 tokens), which is > 10
  # content 2 length is 8 characters (2 tokens)
  large_content = 'a' * 44
  small_content = 'b' * 8

  with patch('wptgen.utils.Path.read_text', side_effect=[large_content, small_content]):
    files = get_recent_test_files('dir', '.html', limit=2, max_tokens=10)

    assert len(files) == 1
    assert files[0] == ('test2.html', small_content)


def test_get_recent_test_files_custom_token_counter(
  mock_subprocess_run: MagicMock, mock_path_methods: MagicMock
) -> None:
  mock_result = MagicMock()
  mock_result.stdout = 'dir/test1.html\ndir/test2.html\n'
  mock_subprocess_run.return_value = mock_result

  def mock_counter(content: str) -> int:
    return len(content) * 10  # Arbitrary high count

  with patch('wptgen.utils.Path.read_text', return_value='abc'):
    files = get_recent_test_files(
      'dir', '.html', limit=2, max_tokens=20, token_counter=mock_counter
    )

    # 3 * 10 = 30 > 20, so both should be skipped
    assert len(files) == 0


def test_get_recent_test_files_git_failure(
  mock_subprocess_run: MagicMock, mock_path_methods: MagicMock
) -> None:
  mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, 'git')

  files = get_recent_test_files('dir', '.html')
  assert len(files) == 0


def test_get_recent_test_files_invalid_dir() -> None:
  with patch('wptgen.utils.Path.exists', return_value=False):
    files = get_recent_test_files('invalid_dir', '.html')
    assert len(files) == 0


def test_get_recent_test_files_allowed_files(
  mock_subprocess_run: MagicMock, mock_path_methods: MagicMock
) -> None:
  mock_result = MagicMock()
  mock_result.stdout = 'dir/test1.html\ndir/test2.html\ndir/test3.html\n'
  mock_subprocess_run.return_value = mock_result

  allowed = {str(Path('dir/test2.html').resolve())}

  with patch('wptgen.utils.Path.read_text', return_value='content'):
    files = get_recent_test_files('dir', '.html', limit=2, max_tokens=100, allowed_files=allowed)

    assert len(files) == 1
    assert files[0] == ('test2.html', 'content')

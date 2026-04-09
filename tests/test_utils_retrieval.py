# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
"""Tests for test_utils_retrieval.py."""

#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from wptgen.utils import get_recent_test_files


@pytest.fixture
def mock_subprocess_run(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("subprocess.run")


@pytest.fixture
def mock_path_methods(mocker: MockerFixture) -> None:
    mocker.patch("wptgen.utils.Path.exists", return_value=True)
    mocker.patch("wptgen.utils.Path.is_dir", return_value=True)
    mocker.patch("wptgen.utils.Path.is_file", return_value=True)


def test_get_recent_test_files_success(
    mocker: MockerFixture,
    mock_subprocess_run: MagicMock,
    mock_path_methods: None,
) -> None:
    mock_result = MagicMock()
    # Note: the test simulates duplicate lines (different commits modifying the
    # same file) and files that don't match the required extension.
    files_stdout = (
        "dir/test1.html\ndir/test1.html\ndir/ignore.js\n"
        "dir/test2.html\ndir/test3.html\n"
    )
    mock_result.stdout = files_stdout
    mock_subprocess_run.return_value = mock_result

    mocker.patch(
        "wptgen.utils.Path.read_text",
        side_effect=["content 1", "content 2", "content 3"],
    )
    files = get_recent_test_files("dir", ".html", limit=2, max_tokens=100)

    assert len(files) == 2
    assert files[0] == ("test1.html", "content 1")
    assert files[1] == ("test2.html", "content 2")

    mock_subprocess_run.assert_called_once()
    args, kwargs = mock_subprocess_run.call_args
    assert args[0][:5] == [
        "git",
        "log",
        "--name-only",
        "--pretty=format:",
        "--diff-filter=d",
    ]


def test_get_recent_test_files_token_limit(
    mocker: MockerFixture,
    mock_subprocess_run: MagicMock,
    mock_path_methods: None,
) -> None:
    mock_result = MagicMock()
    mock_result.stdout = "dir/test1.html\ndir/test2.html\n"
    mock_subprocess_run.return_value = mock_result

    # First file is large, second is small. Limit max_tokens=10
    # Heuristic: tokens = len(content) // 4
    # content 1 length is 44 characters (11 tokens), which is > 10
    # content 2 length is 8 characters (2 tokens)
    large_content = "a" * 44
    small_content = "b" * 8

    mocker.patch(
        "wptgen.utils.Path.read_text",
        side_effect=[large_content, small_content],
    )
    files = get_recent_test_files("dir", ".html", limit=2, max_tokens=10)

    assert len(files) == 1
    assert files[0] == ("test2.html", small_content)


def test_get_recent_test_files_custom_token_counter(
    mocker: MockerFixture,
    mock_subprocess_run: MagicMock,
    mock_path_methods: None,
) -> None:
    mock_result = MagicMock()
    mock_result.stdout = "dir/test1.html\ndir/test2.html\n"
    mock_subprocess_run.return_value = mock_result

    def mock_counter(content: str) -> int:
        return len(content) * 10  # Arbitrary high count

    mocker.patch("wptgen.utils.Path.read_text", return_value="abc")
    files = get_recent_test_files(
        "dir", ".html", limit=2, max_tokens=20, token_counter=mock_counter
    )

    # 3 * 10 = 30 > 20, so both should be skipped
    assert len(files) == 0


def test_get_recent_test_files_git_failure(
    mock_subprocess_run: MagicMock, mock_path_methods: None
) -> None:
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "git")

    files = get_recent_test_files("dir", ".html")
    assert len(files) == 0


def test_get_recent_test_files_invalid_dir(mocker: MockerFixture) -> None:
    mocker.patch("wptgen.utils.Path.exists", return_value=False)
    files = get_recent_test_files("invalid_dir", ".html")
    assert len(files) == 0


def test_get_recent_test_files_allowed_files(
    mocker: MockerFixture,
    mock_subprocess_run: MagicMock,
    mock_path_methods: None,
) -> None:
    mock_result = MagicMock()
    mock_result.stdout = "test1.html\ntest2.html\ntest3.html\n"
    mock_subprocess_run.return_value = mock_result

    allowed = {str(Path("dir/test2.html").resolve())}

    mocker.patch("wptgen.utils.Path.read_text", return_value="content")
    files = get_recent_test_files(
        "dir", ".html", limit=2, max_tokens=100, allowed_files=allowed
    )

    assert len(files) == 1
    assert files[0] == ("test2.html", "content")

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

"""Tests for tools.py."""

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from google.adk.tools.function_tool import FunctionTool

from wptgen.agents.tools import (
    _parse_test_results,
    _validate_safe_path,
    create_agent_tools,
)
from wptgen.ui import UIProvider


@pytest.fixture
def wpt_root(tmp_path: Path) -> Path:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    return wpt_root


@pytest.fixture
def agent_tools(
    wpt_root: Path, mocker: MockerFixture
) -> dict[str, FunctionTool]:
    tools = create_agent_tools(
        wpt_root, mocker.MagicMock(spec=UIProvider), "chrome", "canary"
    )
    return {t.name: t for t in tools}


def test_parse_test_results(tmp_path: Path) -> None:
    log_file = tmp_path / "test.json"

    # Use list comprehension for cleaner JSON formatting
    logs = [
        {
            "action": "test_status",
            "test": "test1",
            "status": "FAIL",
            "subtest": "sub1",
            "message": "msg1",
        },
        {
            "action": "test_end",
            "test": "test1",
            "status": "FAIL",
            "message": "msg2",
        },
        {"action": "test_end", "test": "test2", "status": "PASS"},
    ]
    log_file.write_text(
        "\n".join(json.dumps(log) for log in logs) + "\n", encoding="utf-8"
    )

    results = _parse_test_results(str(log_file))
    assert "test1" in results
    assert "Test: FAIL - msg2" in results["test1"]
    assert "Subtest 'sub1': FAIL - msg1" in results["test1"]
    assert "test2" not in results


def test_validate_safe_path(wpt_root: Path) -> None:
    safe = _validate_safe_path(Path("foo/bar.txt"), wpt_root)
    assert safe == (wpt_root / "foo" / "bar.txt").resolve()

    with pytest.raises(ValueError, match="outside the designated WPT"):
        _validate_safe_path(Path("../outside.txt"), wpt_root)

    with pytest.raises(ValueError, match="outside the designated WPT"):
        _validate_safe_path(Path("/tmp/absolute.txt"), wpt_root)

    # Test deny-list
    with pytest.raises(ValueError, match="strictly prohibited"):
        _validate_safe_path(Path(".git/config"), wpt_root)

    with pytest.raises(ValueError, match="strictly prohibited"):
        _validate_safe_path(Path("some_folder/../.git/config"), wpt_root)

    with pytest.raises(ValueError, match="strictly prohibited"):
        _validate_safe_path(Path(".env"), wpt_root)


def test_create_agent_tools_initialization(
    wpt_root: Path, mocker: MockerFixture
) -> None:
    tools = create_agent_tools(
        wpt_root, mocker.MagicMock(spec=UIProvider), "chrome", "canary"
    )
    assert len(tools) == 14
    assert all(isinstance(t, FunctionTool) for t in tools)


def test_tool_read_file(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    read_file = agent_tools["read_file"]
    (wpt_root / "test.txt").write_text(
        "line1\nline2\nline3\n", encoding="utf-8"
    )

    res = read_file.func(file_path="test.txt")
    assert res == {"status": "success", "content": "line1\nline2\nline3\n"}

    res2 = read_file.func(file_path="test.txt", start_line=2, end_line=2)
    assert res2 == {"status": "success", "content": "line2\n"}

    res3 = read_file.func(file_path="not_found.txt")
    assert res3["status"] == "error"


def test_tool_read_file_exceeds_limit(
    wpt_root: Path, agent_tools: dict[str, FunctionTool], mocker: MockerFixture
) -> None:
    read_file = agent_tools["read_file"]
    test_file = wpt_root / "large.txt"
    test_file.write_text("this content is 28 bytes", encoding="utf-8")

    mocker.patch("wptgen.agents.tools.MAX_FILE_READ_BYTES", 5)
    res = read_file.func(file_path="large.txt")
    assert res["status"] == "error"
    assert "exceeds maximum allowed read size" in res["error"]


def test_tool_write_file(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    write_file = agent_tools["write_file"]

    res = write_file.func(file_path="new.txt", content="content")
    assert res == {"status": "success"}
    assert (wpt_root / "new.txt").read_text(encoding="utf-8") == "content"


def test_tool_search_files(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    search_files = agent_tools["search_files"]
    (wpt_root / "dir1").mkdir()
    (wpt_root / "dir1" / "file1.html").touch()

    res = search_files.func(directory="dir1", pattern="*.html")
    assert res["status"] == "success"
    assert len(res["files"]) == 1
    assert "file1.html" in res["files"][0]


def test_tool_delete_file(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    delete_file = agent_tools["delete_file"]
    (wpt_root / "new.txt").touch()

    res = delete_file.func(file_path="new.txt")
    assert res == {"status": "success"}
    assert not (wpt_root / "new.txt").exists()


def test_tool_replace_in_file(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    replace_in_file = agent_tools["replace_in_file"]
    test_file = wpt_root / "test.txt"
    test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

    res = replace_in_file.func(
        file_path="test.txt", old_string="line2", new_string="new_line2"
    )
    assert res == {"status": "success"}
    assert "new_line2" in test_file.read_text(encoding="utf-8")

    res2 = replace_in_file.func(
        file_path="test.txt", old_string="line", new_string="x"
    )
    assert res2["status"] == "error"
    assert "multiple times" in res2["error"]


def test_tool_search_file_contents(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    search_file_contents = agent_tools["search_file_contents"]
    (wpt_root / "dir1").mkdir()
    (wpt_root / "dir1" / "file1.txt").write_text(
        "hello world\nfoo bar\n", encoding="utf-8"
    )
    (wpt_root / "dir1" / "file2.txt").write_text(
        "test foo\nbar baz\n", encoding="utf-8"
    )

    res = search_file_contents.func(directory="dir1", pattern="foo")
    assert res["status"] == "success"
    assert "dir1/file1.txt:2:foo bar" in res["search_output"]
    assert "dir1/file2.txt:1:test foo" in res["search_output"]


def test_tool_path_traversal_prevention(
    wpt_root: Path, agent_tools: dict[str, FunctionTool]
) -> None:
    malicious_paths = [
        "../../../etc/passwd",
        "/root/.ssh/id_rsa",
        "../../../../../../../../windows/system32/cmd.exe",
        "../outside_file.txt",
    ]

    # Create a safe file for tools that require an existing file
    safe_file = wpt_root / "safe.txt"
    safe_file.touch()

    for path in malicious_paths:
        res = agent_tools["read_file"].func(file_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["write_file"].func(file_path=path, content="test")
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["search_files"].func(directory=path, pattern="*")
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["list_directory"].func(directory=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["create_directory"].func(directory_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["delete_directory"].func(directory_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["delete_file"].func(file_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["move_file"].func(
            source_path=path, destination_path="safe2.txt"
        )
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["move_file"].func(
            source_path="safe.txt", destination_path=path
        )
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["run_wpt_lint"].func(file_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["run_wpt_test"].func(file_path=path)
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["search_file_contents"].func(
            directory=path, pattern="test"
        )
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]

        res = agent_tools["replace_in_file"].func(
            file_path=path, old_string="a", new_string="b"
        )
        assert res["status"] == "error"
        assert "outside the designated WPT" in res["error"]


def test_create_agent_tools_omit_search(
    wpt_root: Path, mocker: MockerFixture
) -> None:
    # When omit_search_feature_tests is False (default)
    tools = create_agent_tools(wpt_root, mocker.MagicMock(), "chrome", "canary")
    tool_names = [t.name for t in tools]
    assert "search_feature_tests" in tool_names

    # When omit_search_feature_tests is True
    tools_omitted = create_agent_tools(
        wpt_root,
        mocker.MagicMock(),
        "chrome",
        "canary",
        omit_search_feature_tests=True,
    )
    tool_names_omitted = [t.name for t in tools_omitted]
    assert "search_feature_tests" not in tool_names_omitted

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

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.tools import _parse_test_results, _validate_safe_path, create_agent_tools
from wptgen.config import Config
from wptgen.ui import UIProvider


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


def test_parse_test_results(tmp_path: Path) -> None:
    assert _parse_test_results(str(tmp_path / "missing.json")) == {}

    log_file = tmp_path / "test.json"
    events = [
        {
            "action": "test_status",
            "test": "/a.html",
            "status": "PASS",
            "subtest": "sub1",
        },
        {"action": "test_end", "test": "/a.html", "status": "OK"},
        {
            "action": "test_status",
            "test": "/b.html",
            "status": "FAIL",
            "subtest": "sub2",
            "message": "assert_equals failed",
        },
        {"action": "test_end", "test": "/b.html", "status": "OK"},
        {
            "action": "test_end",
            "test": "/c.html",
            "status": "CRASH",
            "message": "Browser crashed",
        },
        "invalid json string",
        {"action": "suite_start"},
    ]

    with open(log_file, "w") as f:
        for event in events:
            if isinstance(event, dict):
                f.write(json.dumps(event) + "\n")
            else:
                f.write(str(event) + "\n")

    results = _parse_test_results(str(log_file))
    assert "/a.html" not in results
    assert "/b.html" in results
    assert "Subtest 'sub2': FAIL - assert_equals failed" in results["/b.html"]
    assert "/c.html" in results
    assert "Test: CRASH - Browser crashed" in results["/c.html"]


def test_setup_adk_environment_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    config = _create_mock_config(
        "google", "fake-key", "gemini-3.1-pro-preview", "/tmp"
    )
    model = setup_adk_environment(config)
    assert os.environ["GOOGLE_API_KEY"] == "fake-key"
    assert model == "gemini-3.1-pro-preview"


def test_setup_adk_environment_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", {})
    config = _create_mock_config(
        "anthropic", "fake-key", "claude-opus-4-6", "/tmp"
    )
    model = setup_adk_environment(config)
    assert os.environ["ANTHROPIC_API_KEY"] == "fake-key"
    assert model == "claude-opus-4-6"


def test_setup_adk_environment_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    config = _create_mock_config("openai", "fake-key", "gpt-5.2-high", "/tmp")
    model = setup_adk_environment(config)
    assert os.environ["OPENAI_API_KEY"] == "fake-key"
    assert model == "gpt-5.2-high"


def test_setup_adk_environment_missing_key() -> None:
    config = Config(
        provider="google",
        default_model="gemini",
        api_key=None,
        wpt_path="/tmp",
        categories={},
        phase_model_mapping={},
    )
    with pytest.raises(ValueError, match="An API key is required"):
        setup_adk_environment(config)


def test_validate_safe_path_valid(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    target = wpt_root / "css" / "test.html"
    resolved = _validate_safe_path(target, wpt_root)
    assert resolved == target.resolve()


def test_validate_safe_path_traversal(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    malicious_target = wpt_root / "css" / ".." / ".." / "etc" / "passwd"
    with pytest.raises(
        ValueError, match="is outside the designated WPT repository root"
    ):
        _validate_safe_path(malicious_target, wpt_root)


def test_validate_safe_path_absolute_outside(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    malicious_target = Path("/tmp/some_other_dir/file.txt")
    with pytest.raises(
        ValueError, match="is outside the designated WPT repository root"
    ):
        _validate_safe_path(malicious_target, wpt_root)


def test_file_tools_read_file(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "test.txt"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    read_file_tool = next(t for t in tools if t.name == "read_file")

    result = read_file_tool.func(str(test_file))
    assert result["status"] == "success"
    assert "line 1" in result["content"]

    result = read_file_tool.func(str(test_file), start_line=2, end_line=3)
    assert result["status"] == "success"
    assert result["content"] == "line 2\nline 3\n"

    result = read_file_tool.func(str(test_file), start_line=10)
    assert result["status"] == "error"
    assert "is beyond EOF" in result["error"]

    result = read_file_tool.func(str(wpt_root / "missing.txt"))
    assert result["status"] == "error"
    assert "File not found" in result["error"]


def test_file_tools_write_file(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "new_dir" / "test.txt"

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    write_file_tool = next(t for t in tools if t.name == "write_file")

    result = write_file_tool.func(str(test_file), "new content")
    assert result["status"] == "success"
    assert test_file.read_text() == "new content"

    result = write_file_tool.func("/tmp/outside", "new content")
    assert result["status"] == "error"


def test_file_tools_search_files(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    (wpt_root / "a.js").touch()
    (wpt_root / "b.html").touch()
    (wpt_root / "c.js").touch()

    large_dir = wpt_root / "large"
    large_dir.mkdir()
    for i in range(105):
        (large_dir / f"file{i}.js").touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    search_files_tool = next(t for t in tools if t.name == "search_files")

    result = search_files_tool.func(str(wpt_root), "*.html")
    assert result["status"] == "success"
    assert len(result["files"]) == 1

    result = search_files_tool.func(str(wpt_root / "missing"), "*.js")
    assert result["status"] == "error"

    result = search_files_tool.func(str(large_dir), "*.js")
    assert result["status"] == "success"
    assert len(result["files"]) == 100
    assert "Results truncated" in result["warning"]

    result = search_files_tool.func("/tmp/outside", "*.js")
    assert result["status"] == "error"


def test_file_tools_list_directory(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    (wpt_root / "dir1").mkdir()
    (wpt_root / "file1.txt").touch()

    large_dir = wpt_root / "large_list"
    large_dir.mkdir()
    for i in range(105):
        (large_dir / f"item{i}").touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    list_directory_tool = next(t for t in tools if t.name == "list_directory")

    result = list_directory_tool.func(str(wpt_root))
    assert result["status"] == "success"
    assert len(result["entries"]) >= 2

    result = list_directory_tool.func(str(wpt_root / "missing"))
    assert result["status"] == "error"

    result = list_directory_tool.func(str(large_dir))
    assert result["status"] == "success"
    assert len(result["entries"]) == 100
    assert "Results truncated" in result["warning"]

    result = list_directory_tool.func("/tmp/outside")
    assert result["status"] == "error"


def test_file_tools_delete_file(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "to_delete.txt"
    test_file.touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    delete_file_tool = next(t for t in tools if t.name == "delete_file")

    result = delete_file_tool.func(str(test_file))
    assert result["status"] == "success"
    assert not test_file.exists()

    result = delete_file_tool.func(str(wpt_root / "missing.txt"))
    assert result["status"] == "error"

    result = delete_file_tool.func("/tmp/outside.txt")
    assert result["status"] == "error"


def test_file_tools_move_file(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    source_file = wpt_root / "to_move.txt"
    source_file.write_text("content")
    dest_file = wpt_root / "moved.txt"

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    move_file_tool = next(t for t in tools if t.name == "move_file")

    result = move_file_tool.func(str(source_file), str(dest_file))
    assert result["status"] == "success"
    assert not source_file.exists()
    assert dest_file.exists()
    assert dest_file.read_text() == "content"

    result = move_file_tool.func(str(wpt_root / "missing.txt"), str(dest_file))
    assert result["status"] == "error"

    result = move_file_tool.func("/tmp/outside", str(dest_file))
    assert result["status"] == "error"


def test_file_tools_security_rejection(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret")

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    read_file_tool = next(t for t in tools if t.name == "read_file")

    result = read_file_tool.func(str(outside_file))
    assert result["status"] == "error"

    inside_file = wpt_root / "inside.txt"
    inside_file.write_text("inside")
    move_file_tool = next(t for t in tools if t.name == "move_file")
    result = move_file_tool.func(str(inside_file), str(outside_file))
    assert result["status"] == "error"


def test_agent_tools_run_wpt_lint(tmp_path: Path, mocker: Any) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "test.html"
    test_file.touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    tool = next(t for t in tools if t.name == "run_wpt_lint")

    result = tool.func(str(wpt_root / "missing.html"))
    assert result["status"] == "error"

    mock_run = mocker.patch("wptgen.agents.tools.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = "lint error"
    mock_run.return_value.stderr = ""
    result = tool.func(str(test_file))
    assert result["status"] == "failed"

    mock_run.return_value.returncode = 0
    result = tool.func(str(test_file))
    assert result["status"] == "success"

    mock_run.side_effect = subprocess.TimeoutExpired(cmd="lint", timeout=15)
    result = tool.func(str(test_file))
    assert result["status"] == "error"

    mock_run.side_effect = OSError("failed run")
    result = tool.func(str(test_file))
    assert result["status"] == "error"


def test_agent_tools_run_wpt_test(tmp_path: Path, mocker: Any) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "test.html"
    test_file.touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    tool = next(t for t in tools if t.name == "run_wpt_test")

    result = tool.func(str(wpt_root / "missing.html"))
    assert result["status"] == "error"

    mock_run = mocker.patch("wptgen.agents.tools.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "success logs"
    mock_run.return_value.stderr = ""
    result = tool.func(str(test_file))
    assert result["status"] == "success"

    mock_run.return_value.returncode = 1
    mocker.patch(
        "wptgen.agents.tools._parse_test_results",
        return_value={"/test.html": "Failed assertion"},
    )
    result = tool.func(str(test_file))
    assert result["status"] == "failed"

    mocker.patch("wptgen.agents.tools._parse_test_results", return_value={})
    result = tool.func(str(test_file))
    assert result["status"] == "error"

    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd="run", timeout=60, output=b"partial out", stderr=b"partial err"
    )
    result = tool.func(str(test_file))
    assert result["status"] == "error"

    mock_run.side_effect = OSError("failed run")
    result = tool.func(str(test_file))
    assert result["status"] == "error"


def test_agent_tools_search_feature_tests(tmp_path: Path, mocker: Any) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    tool = next(t for t in tools if t.name == "search_feature_tests")

    mocker.patch(
        "wptgen.agents.tools.find_feature_tests",
        return_value=[str(wpt_root / "a.html")],
    )
    result = tool.func("popover")
    assert result["status"] == "success"

    mocker.patch("wptgen.agents.tools.find_feature_tests", return_value=[])
    result = tool.func("popover_missing")
    assert result["status"] == "success"

    mocker.patch(
        "wptgen.agents.tools.find_feature_tests",
        side_effect=OSError("failed find"),
    )
    result = tool.func("popover")
    assert result["status"] == "error"


def test_file_tools_search_file_contents(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file1 = wpt_root / "test1.js"
    test_file1.write_text("line 1\nhello world\nline 3", encoding="utf-8")
    test_file2 = wpt_root / "test2.js"
    test_file2.write_text("hello there\nno match here", encoding="utf-8")

    binary_file = wpt_root / "image.png"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    search_contents_tool = next(
        t for t in tools if t.name == "search_file_contents"
    )

    result = search_contents_tool.func(str(wpt_root), "hello ")
    assert result["status"] == "success"
    assert "image.png" not in result["search_output"]

    result = search_contents_tool.func(str(wpt_root), "notfound")
    assert result["status"] == "success"

    result = search_contents_tool.func(str(wpt_root), "[invalid")
    assert result["status"] == "error"

    result = search_contents_tool.func(str(wpt_root / "missing"), "hello")
    assert result["status"] == "error"

    bad_file = wpt_root / "bad.txt"
    bad_file.write_bytes(b"hello \xff")
    result = search_contents_tool.func(str(wpt_root), "hello")
    assert result["status"] == "success"


def test_file_tools_search_file_contents_truncation(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    large_file = wpt_root / "large.txt"
    large_file.write_text("hello\n" * 150)

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    search_contents_tool = next(
        t for t in tools if t.name == "search_file_contents"
    )

    result = search_contents_tool.func(str(wpt_root), "hello")
    assert result["status"] == "success"
    assert "truncated" in result["search_output"]


def test_file_tools_create_directory(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_dir = wpt_root / "new_test_dir"

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    create_dir_tool = next(t for t in tools if t.name == "create_directory")

    result = create_dir_tool.func(str(test_dir))
    assert result["status"] == "success"
    assert test_dir.is_dir()

    result = create_dir_tool.func("/tmp/outside")
    assert result["status"] == "error"


def test_file_tools_delete_directory(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_dir = wpt_root / "dir_to_delete"
    test_dir.mkdir()
    (test_dir / "file.txt").touch()

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    delete_dir_tool = next(t for t in tools if t.name == "delete_directory")

    result = delete_dir_tool.func(str(test_dir))
    assert result["status"] == "success"
    assert not test_dir.exists()

    result = delete_dir_tool.func(str(wpt_root / "missing"))
    assert result["status"] == "error"

    result = delete_dir_tool.func("/tmp/outside")
    assert result["status"] == "error"


def test_fetch_spec_content(tmp_path: Path, mocker: Any) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    tool = next(t for t in tools if t.name == "fetch_spec_content")

    mocker.patch(
        "wptgen.agents.tools.fetch_and_extract_text", return_value="Spec text"
    )
    result = tool.func("https://example.com/spec")
    assert result["status"] == "success"

    mocker.patch("wptgen.agents.tools.fetch_and_extract_text", return_value="")
    result = tool.func("https://example.com/spec")
    assert result["status"] == "error"

    mocker.patch(
        "wptgen.agents.tools.fetch_and_extract_text",
        side_effect=OSError("failed fetch"),
    )
    result = tool.func("https://example.com/spec")
    assert result["status"] == "error"


def test_replace_in_file(tmp_path: Path) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "file.txt"
    test_file.write_text("foo bar baz\nfoo bar qux")

    tools = create_agent_tools(
        wpt_root, MagicMock(spec=UIProvider), "chrome", "canary"
    )
    tool = next(t for t in tools if t.name == "replace_in_file")

    result = tool.func(str(test_file), "foo bar baz", "hello world")
    assert result["status"] == "success"

    result = tool.func(str(test_file), "not in file", "hello")
    assert result["status"] == "error"

    result = tool.func(str(test_file), "qux", "qux\nqux")
    assert result["status"] == "success"

    result = tool.func(str(test_file), "qux", "replacement")
    assert result["status"] == "error"

    result = tool.func(str(wpt_root / "missing.txt"), "foo", "bar")
    assert result["status"] == "error"

    result = tool.func("/tmp/outside", "foo", "bar")
    assert result["status"] == "error"

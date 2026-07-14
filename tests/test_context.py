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

"""Tests for context.py."""

import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from wptgen.context import (
    FeatureMetadata,
    _resolve_patterns,
    _slice_html_by_anchor,
    extract_dependencies,
    extract_feature_metadata,
    extract_wpt_paths,
    fetch_and_extract_text,
    fetch_and_slice_spec,
    fetch_feature_yaml,
    fetch_mdn_urls,
    fetch_remote_wpt_context,
    find_feature_tests,
    gather_local_test_context,
    is_wpt_test_file,
    normalize_wpt_path,
    resolve_dependency_path,
    slug_for_spec_url,
    validate_ip_against_ssrf,
    validate_wpt_paths,
)


def test_is_wpt_test_file() -> None:
    """Test the WPT test file filter."""
    assert is_wpt_test_file(Path("test.html")) is True
    assert is_wpt_test_file(Path("test.js")) is True
    assert is_wpt_test_file(Path("test.any.js")) is True
    assert is_wpt_test_file(Path("test-ref.html")) is False
    assert is_wpt_test_file(Path("test-ref.js")) is False
    assert is_wpt_test_file(Path("test.md")) is False
    assert is_wpt_test_file(Path("test.py")) is False
    assert is_wpt_test_file(Path("test.yml")) is False
    assert is_wpt_test_file(Path("test.ini")) is False
    assert is_wpt_test_file(Path("test.headers")) is False
    assert is_wpt_test_file(Path("test.txt")) is False
    assert is_wpt_test_file(Path(".gitignore")) is False
    assert is_wpt_test_file(Path("MANIFEST")) is False
    assert is_wpt_test_file(Path("WEB_FEATURES.yml")) is False


def test_extract_wpt_paths_empty() -> None:
    """Test extraction with empty description."""
    assert not extract_wpt_paths("")
    assert not extract_wpt_paths(None)  # type: ignore


def test_extract_wpt_paths_urls() -> None:
    """Test extraction from wpt.fyi URLs."""
    wpt_descr = """
  Here are some tests:
  - https://wpt.fyi/results/css/css-grid/grid-model?label=master
  - https://github.com/web-platform-tests/wpt/tree/master/dom/events
  - See https://wpt.fyi/results/css/css-flexbox.
  """
    paths = extract_wpt_paths(wpt_descr)
    assert "css/css-grid/grid-model" in paths
    assert "css/css-flexbox" in paths
    assert "dom/events" not in paths


def test_extract_wpt_paths_none() -> None:
    """Test extraction of raw file paths from text should be empty now."""
    wpt_descr = """
  Look at css/css-grid/alignment/grid-item-alignment-001.html and
  dom/nodes/Element-getAttribute.html.
  Also html/canvas (a directory).
  """
    paths = extract_wpt_paths(wpt_descr)
    assert not paths


def test_normalize_wpt_path() -> None:
    """Test WPT path normalization for .any. variants."""
    assert normalize_wpt_path("test.any.js") == "test.any.js"
    assert normalize_wpt_path("test.any.worker.html") == "test.any.js"
    assert normalize_wpt_path("test.any.window.html") == "test.any.js"
    assert (
        normalize_wpt_path("path/to/test.any.worker.html")
        == "path/to/test.any.js"
    )
    assert normalize_wpt_path("standard.html") == "standard.html"


def test_validate_wpt_paths_normalization(tmp_path: Path) -> None:
    """Test that multiple .any. variants collapse into one .any.js."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create the source .any.js file
    any_js = wpt_root / "test.any.js"
    any_js.touch()

    # Input variants
    paths = ["test.any.worker.html", "test.any.window.html", "test.any.js"]
    valid, _ = validate_wpt_paths(paths, str(wpt_root))

    # Should only have one entry
    assert len(valid) == 1
    assert str(any_js.resolve()) in valid


def test_validate_wpt_paths_limits(tmp_path: Path) -> None:
    """Test that validate_wpt_paths enforces the MAX_TESTS limit."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create 51 tests
    paths = []
    for i in range(51):
        p = wpt_root / f"test{i}.html"
        p.touch()
        paths.append(p.relative_to(wpt_root).as_posix())

    with pytest.raises(ValueError, match="Too many tests found"):
        validate_wpt_paths(paths, str(wpt_root))


def test_validate_wpt_paths(tmp_path: Path) -> None:
    """Test validation and expansion of WPT paths (top-level only)."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create a file
    css_dir = wpt_root / "css"
    css_dir.mkdir()
    test_file = css_dir / "test.html"
    test_file.touch()

    # Create a directory with multiple tests, including one in a subdirectory
    test_dir = wpt_root / "dom" / "events"
    test_dir.mkdir(parents=True)
    (test_dir / "test1.html").touch()
    (test_dir / "test2.js").touch()
    (test_dir / "not-a-test.txt").touch()
    (test_dir / "subdir").mkdir()
    (
        test_dir / "subdir" / "hidden.html"
    ).touch()  # Should be ignored (not top-level)

    paths = ["css/test.html", "dom/events", "nonexistent/path"]
    valid, invalid = validate_wpt_paths(paths, str(wpt_root))

    # 3 files: css/test.html, dom/events/test1.html, dom/events/test2.js
    # not-a-test.txt should now be filtered out by is_wpt_test_file
    assert len(valid) == 3
    assert str(test_file.resolve()) in valid
    assert str((test_dir / "test1.html").resolve()) in valid
    assert str((test_dir / "test2.js").resolve()) in valid
    assert str((test_dir / "not-a-test.txt").resolve()) not in valid
    assert str((test_dir / "subdir" / "hidden.html").resolve()) not in valid
    assert "nonexistent/path" in invalid


def test_validate_wpt_paths_fallback(tmp_path: Path) -> None:
    """Test fallback from .html to .js in validation."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create a .js file but reference it as .html
    js_file = wpt_root / "test.js"
    js_file.touch()

    paths = ["test.html"]
    valid, _ = validate_wpt_paths(paths, str(wpt_root))

    assert len(valid) == 1
    assert str(js_file.resolve()) in valid


def test_validate_wpt_paths_normalization_dir(tmp_path: Path) -> None:
    """Test that directory scanning also applies normalization."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create a directory with multiple variants of the same .any.js test
    test_dir = wpt_root / "dom"
    test_dir.mkdir()
    (test_dir / "test.any.js").touch()

    # Input directory
    paths = ["dom"]
    valid, _ = validate_wpt_paths(paths, str(wpt_root))

    # Should normalize correctly even when found in directory
    assert len(valid) == 1
    assert valid[0].endswith("test.any.js")


def test_validate_wpt_paths_outside_root(tmp_path: Path) -> None:
    """Test that paths outside the WPT root are rejected."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    paths = ["../outside.html", "/etc/passwd"]
    valid, invalid = validate_wpt_paths(paths, str(wpt_root))

    assert not valid
    assert len(invalid) == 2


def test_fetch_mdn_urls_success(mocker: MockerFixture) -> None:
    """Test successfully fetching MDN URLs from the mapping JSON."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b'{"fetch": [{"url": "https://developer.mozilla.org/'
        b'en-US/docs/Web/API/fetch"}]}'
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_mdn_urls("fetch")

    assert result == ["https://developer.mozilla.org/en-US/docs/Web/API/fetch"]
    mock_urlopen.assert_called_once()
    request_obj = mock_urlopen.call_args[0][0]
    assert "mdn-docs.json" in request_obj.full_url


def test_fetch_mdn_urls_not_found(mocker: MockerFixture) -> None:
    """Test that if a feature ID is not in the mapping, it returns an empty
    list.
    """
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b'{"fetch": [{"url": "https://example.com"}]}'
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_mdn_urls("unknown")

    assert not result


def test_fetch_mdn_urls_error(mocker: MockerFixture) -> None:
    """Test that HTTP errors during mapping fetch return an empty list."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=Message(), fp=None
    )

    result = fetch_mdn_urls("fetch")

    assert not result


def test_fetch_feature_yaml_success(mocker: MockerFixture) -> None:
    """Test the happy path where the YAML file is successfully fetched and
    parsed.
    """
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    # Setup the context manager mock so it returns a byte string when .read()
    # is called
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b"spec: 'https://example.com/spec'"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_feature_yaml("popover")

    assert result == {"spec": "https://example.com/spec"}
    mock_urlopen.assert_called_once()

    # Verify the constructed URL is correct
    request_obj = mock_urlopen.call_args[0][0]
    assert "popover.yml" in request_obj.full_url
    assert "raw.githubusercontent.com" in request_obj.full_url


def test_fetch_feature_yaml_not_found(mocker: MockerFixture) -> None:
    """Test that a 404 error from GitHub safely returns None."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    # Simulate a 404 HTTPError
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=Message(), fp=None
    )

    result = fetch_feature_yaml("fake-feature")

    assert result is None


def test_fetch_feature_yaml_server_error(mocker: MockerFixture) -> None:
    """Test that a 500 error (or rate limit) raises an exception."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    # Simulate a 500 HTTPError
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="", code=500, msg="Internal Server Error", hdrs=Message(), fp=None
    )

    with pytest.raises(urllib.error.HTTPError):
        fetch_feature_yaml("grid")


def test_extract_feature_metadata_single_spec() -> None:
    """Test metadata extraction when the spec field is a single string."""
    data = {
        "name": "popover",
        "description": "A popup feature",
        "spec": "https://example.com/spec",
    }
    result = extract_feature_metadata(data)

    assert isinstance(result, FeatureMetadata)
    assert result.name == "popover"
    assert result.description == "A popup feature"
    assert result.specs == ["https://example.com/spec"]


def test_extract_feature_metadata_list_spec() -> None:
    """Test metadata extraction when the spec field is a list of URLs."""
    data = {
        "name": "grid",
        "description": "Grid layout",
        "spec": ["https://example.com/spec1", "https://example.com/spec2"],
    }
    result = extract_feature_metadata(data)

    assert result.name == "grid"
    assert result.specs == [
        "https://example.com/spec1",
        "https://example.com/spec2",
    ]


def test_extract_feature_metadata_defaults() -> None:
    """Test that missing fields fall back to safe defaults."""
    data: dict[str, Any] = {}
    result = extract_feature_metadata(data)

    assert result.name == "Unknown Feature"
    assert result.description == ""
    assert not result.specs


def test_fetch_and_extract_text_ssrf_validation_blocks_localhost() -> None:
    """Test that fetching from localhost is blocked by the SSRF validation."""
    with pytest.raises(
        ValueError, match="URL resolves to a restricted IP address"
    ):
        fetch_and_extract_text("http://localhost/spec")


def test_fetch_and_extract_text_ssrf_validation_blocks_private_ip() -> None:
    """Test that fetching from a private IP is blocked by the SSRF
    validation.
    """
    with pytest.raises(
        ValueError, match="URL resolves to a restricted IP address"
    ):
        fetch_and_extract_text("http://192.168.1.5/admin")


def test_fetch_and_extract_text_ssrf_validation_blocks_metadata() -> None:
    """Test that fetching from a cloud metadata IP is blocked by the SSRF
    validation.
    """
    with pytest.raises(
        ValueError, match="URL resolves to a restricted IP address"
    ):
        fetch_and_extract_text("http://169.254.169.254/latest/meta-data/")


def test_fetch_and_extract_text_ssrf_validation_invalid_url() -> None:
    """Test that an invalid URL without a hostname raises an error."""
    with pytest.raises(ValueError, match="Invalid URL scheme: file"):
        fetch_and_extract_text("file:///etc/passwd")


def test_fetch_and_extract_text_success(mocker: MockerFixture) -> None:
    """Test the happy path where HTML is downloaded and successfully
    converted to Markdown.
    """
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b"<html><body><main><h1>Spec</h1><p>Text</p></main></body></html>"
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_and_extract_text("https://example.com")

    assert result == "# Spec\n\nText"

    mock_urlopen.assert_called_once()


def test_fetch_and_extract_text_retry_success(mocker: MockerFixture) -> None:
    """Test that fetch_and_extract_text retries on transient errors and
    eventually succeeds.
    """
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b"<html><body><main><h1>Spec</h1><p>Text</p></main></body></html>"
    )
    mock_response.__enter__.return_value = mock_response

    # Fail twice with 429, then succeed
    error429 = urllib.error.HTTPError(
        url="https://example.com",
        code=429,
        msg="Too Many Requests",
        hdrs=Message(),
        fp=None,
    )

    mock_urlopen.side_effect = [error429, error429, mock_response]

    # We need to mock time.sleep to avoid waiting in tests
    mock_sleep = mocker.patch("time.sleep")

    result = fetch_and_extract_text("https://example.com")

    assert result == "# Spec\n\nText"
    assert mock_urlopen.call_count == 3
    assert mock_sleep.call_count == 2


def test_fetch_and_extract_text_retry_max_reached(
    mocker: MockerFixture,
) -> None:
    """Test that fetch_and_extract_text eventually gives up after
    MAX_RETRIES.
    """
    from wptgen.utils import MAX_RETRIES

    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    error429 = urllib.error.HTTPError(
        url="https://example.com",
        code=429,
        msg="Too Many Requests",
        hdrs=Message(),
        fp=None,
    )

    # Fail MAX_RETRIES times
    mock_urlopen.side_effect = [error429] * MAX_RETRIES

    mock_sleep = mocker.patch("time.sleep")

    result = fetch_and_extract_text("https://example.com")

    assert result is None
    assert mock_urlopen.call_count == MAX_RETRIES
    assert mock_sleep.call_count == MAX_RETRIES - 1


def test_fetch_and_extract_text_fetch_fails(mocker: MockerFixture) -> None:
    """Test that if the URL cannot be fetched, the function returns None."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_urlopen.side_effect = Exception("Network error")

    result = fetch_and_extract_text("https://example.com")

    assert result is None


def test_fetch_and_extract_text_extract_fails(mocker: MockerFixture) -> None:
    """Test that if no content is found, the function returns None."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b"<html></html>"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_and_extract_text("https://example.com")

    assert result is None


def test_fetch_and_extract_text_preserves_internal_links(
    mocker: MockerFixture,
) -> None:
    """Test that internal spec links are preserved while external links are
    stripped.
    """
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b"<html><body><main><h1>Spec</h1>\n"
        b'<p>Link to <a href="#section-1">Section 1</a>.</p>\n'
        b'<p>Link to <a href="https://external.com/path">External</a>.</p>\n'
        b"</main></body></html>"
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_and_extract_text("https://example.com")

    assert result is not None
    assert "[Section 1](#section-1)" in result
    assert "Link to External." in result
    assert "https://external.com" not in result


def test_resolve_patterns_basic_and_recursive(tmp_path: Path) -> None:
    """Test that _resolve_patterns correctly handles standard and recursive
    globs.
    """
    # Create a mock directory structure
    (tmp_path / "test1.html").touch()
    (tmp_path / "test2.txt").touch()

    sub_dir = tmp_path / "subfolder"
    sub_dir.mkdir()
    (sub_dir / "test3.html").touch()

    # Also create a WEB_FEATURES.yml, which should be explicitly ignored
    (tmp_path / "WEB_FEATURES.yml").touch()

    # Look for all HTML files, including those in subdirectories
    patterns = ["**/*.html"]
    results = _resolve_patterns(tmp_path, patterns)

    assert len(results) == 2
    assert str(tmp_path / "test1.html") in results
    assert str(sub_dir / "test3.html") in results
    assert str(tmp_path / "test2.txt") not in results
    assert str(tmp_path / "WEB_FEATURES.yml") not in results


def test_resolve_patterns_negative_exclusion(tmp_path: Path) -> None:
    """Test that negative patterns (!pattern) successfully remove files from
    the set.
    """
    (tmp_path / "include_me.html").touch()
    (tmp_path / "exclude_me.html").touch()

    patterns = ["*.html", "!exclude_me.html"]

    results = _resolve_patterns(tmp_path, patterns)

    assert len(results) == 1
    assert str(tmp_path / "include_me.html") in results
    assert str(tmp_path / "exclude_me.html") not in results


def test_find_feature_tests_happy_path(tmp_path: Path) -> None:
    """Test the full end-to-end scan for a specific feature."""
    # Build the repository structure
    feat_dir = tmp_path / "css" / "css-grid"
    feat_dir.mkdir(parents=True)

    # Create the YAML metadata file
    yaml_content = """
features:
  - name: grid
    files:
      - "**/*.html"
      - "!**/skip.html"
  - name: other-feature
    files:
      - "other.html"
  """
    (feat_dir / "WEB_FEATURES.yml").write_text(yaml_content, encoding="utf-8")

    # Create the test files
    (feat_dir / "grid_test.html").touch()
    (feat_dir / "skip.html").touch()

    results = find_feature_tests(str(tmp_path), "grid")

    assert len(results) == 1
    assert results[0] == str(feat_dir / "grid_test.html")


def test_find_feature_tests_missing_directory() -> None:
    """Test that an invalid repository path raises a ValueError."""
    with pytest.raises(
        ValueError, match="The directory provided does not exist"
    ):
        find_feature_tests("/path/that/absolutely/does/not/exist", "grid")


def test_find_feature_tests_malformed_yaml(tmp_path: Path) -> None:
    """Test that malformed YAML files are gracefully skipped without crashing
    the loop.
    """
    # Create a broken YAML file
    feat_dir = tmp_path / "broken-feature"
    feat_dir.mkdir()
    (feat_dir / "WEB_FEATURES.yml").write_text(
        "features:\n - name: oops\n  bad_indent: true", encoding="utf-8"
    )

    # Create a valid one to ensure the loop continues after the error
    valid_dir = tmp_path / "valid-feature"
    valid_dir.mkdir()
    (valid_dir / "WEB_FEATURES.yml").write_text(
        "features:\n  - name: works\n    files:\n      - 'test.html'",
        encoding="utf-8",
    )
    (valid_dir / "test.html").touch()

    results = find_feature_tests(str(tmp_path), "works")
    # It should have skipped the broken directory and found the valid one
    assert len(results) == 1
    assert results[0] == str(valid_dir / "test.html")


def test_find_feature_tests_feature_not_found(tmp_path: Path) -> None:
    """Test that if a feature ID is not in any YAML, it returns an empty
    list.
    """
    (tmp_path / "WEB_FEATURES.yml").write_text(
        "features:\n  - name: grid\n    files:\n      - '*.html'",
        encoding="utf-8",
    )

    results = find_feature_tests(str(tmp_path), "non-existent-feature")

    assert not results


def test_extract_dependencies() -> None:
    """Test that dependencies are correctly extracted from HTML and JS
    content.
    """
    content = """
  <script src="a.js"></script>
  <script src='/b.js'></script>
  <script src="/resources/testharness.js"></script>
  <script src="/resources/testharnessreport.js"></script>
  <script src="/resources/testdriver.js"></script>
  <script src="/resources/testdriver-vendor.js"></script>
  <script module="test" src='/y.js'></script>
  <!-- <script src="z.js"> -->
  import { x } from "./c.js";
  import "./d.js";
  export { y } from "../e.js";
  """
    deps = extract_dependencies(content)
    # boilerplate files should be ignored
    assert set(deps) == {
        "a.js",
        "/b.js",
        "./c.js",
        "./d.js",
        "../e.js",
        "/y.js",
    }


def test_resolve_dependency_path(tmp_path: Path) -> None:
    """Test that dependency references are correctly resolved to local
    absolute paths.
    """
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    (wpt_root / "resources").mkdir()
    testharness = (wpt_root / "resources" / "testharness.js").resolve()
    testharness.touch()

    test_dir = wpt_root / "test"
    test_dir.mkdir()
    test_file = (test_dir / "test.html").resolve()
    test_file.touch()

    helper = (test_dir / "helper.js").resolve()
    helper.touch()

    # Absolute repo path
    resolved_abs = resolve_dependency_path(
        test_file, "/resources/testharness.js", wpt_root
    )
    assert resolved_abs == testharness

    # Relative path
    resolved_rel = resolve_dependency_path(test_file, "helper.js", wpt_root)
    assert resolved_rel == helper

    # External URL (should be ignored)
    assert (
        resolve_dependency_path(test_file, "http://example.com/js.js", wpt_root)
        is None
    )

    # Missing file
    assert resolve_dependency_path(test_file, "missing.js", wpt_root) is None


def test_gather_local_test_context(tmp_path: Path) -> None:
    """Test recursive gathering of tests and dependencies from the local
    disk.
    """
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    test_dir = wpt_root / "feature"
    test_dir.mkdir()

    test_html = (test_dir / "test.html").resolve()
    test_html.write_text('<script src="dep.js"></script>', encoding="utf-8")

    dep_js = (test_dir / "dep.js").resolve()
    dep_js.write_text('import "./subdep.js";', encoding="utf-8")

    subdep_js = (test_dir / "subdep.js").resolve()
    subdep_js.write_text("// no deps", encoding="utf-8")

    context = gather_local_test_context([str(test_html)], str(wpt_root))

    assert str(test_html) in context.test_contents
    assert str(dep_js) in context.dependency_contents
    assert str(subdep_js) in context.dependency_contents

    # Verify the mapping
    deps_for_test = context.test_to_deps[str(test_html)]
    assert str(dep_js) in deps_for_test
    assert str(subdep_js) in deps_for_test


def test_fetch_feature_yaml_not_a_dict(mocker: MockerFixture) -> None:
    """Test that if the YAML file is not a dictionary, it returns None."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b'["not", "a", "dict"]'
    mock_urlopen.return_value.__enter__.return_value = mock_response

    assert fetch_feature_yaml("popover") is None


def test_find_feature_tests_yaml_missing_features(tmp_path: Path) -> None:
    """Test that YAML files without a 'features' key are skipped."""
    feat_dir = tmp_path / "no-features"
    feat_dir.mkdir()
    (feat_dir / "WEB_FEATURES.yml").write_text(
        "something: else", encoding="utf-8"
    )

    assert not find_feature_tests(str(tmp_path), "grid")


def test_find_feature_tests_exception(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that exceptions during YAML processing are caught."""
    feat_dir = tmp_path / "exception"
    feat_dir.mkdir()
    (feat_dir / "WEB_FEATURES.yml").touch()

    # Mock open to raise an exception for this specific file
    mocker.patch("builtins.open", side_effect=Exception("IO Error"))
    assert not find_feature_tests(str(tmp_path), "grid")


def test_resolve_dependency_path_invalid(tmp_path: Path) -> None:
    """Test that invalid paths (e.g. outside root) are handled."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_file = wpt_root / "test.html"
    test_file.touch()

    # Path that goes outside root via ..
    assert (
        resolve_dependency_path(test_file, "../../outside.js", wpt_root) is None
    )


def test_gather_local_test_context_exception(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that exceptions during file reading in gather_local_test_context
    are caught.
    """
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_html = wpt_root / "test.html"
    test_html.touch()

    # Mock read_text to raise an exception
    mocker.patch("pathlib.Path.read_text", side_effect=Exception("Read Error"))

    context = gather_local_test_context([str(test_html)], str(wpt_root))
    assert not context.test_contents


def test_fetch_feature_yaml_draft(mocker: MockerFixture) -> None:
    """Test that fetching a draft feature constructs the correct URL."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b"name: 'Draft Feature'"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_feature_yaml("draft-feature", draft=True)

    assert result == {"name": "Draft Feature"}
    mock_urlopen.assert_called_once()

    request_obj = mock_urlopen.call_args[0][0]
    assert (
        request_obj.full_url
        == "https://raw.githubusercontent.com/web-platform-dx/"
        "web-features/main/features/draft/spec/draft-feature.yml"
    )


@pytest.mark.asyncio
async def test_fetch_remote_wpt_context(mocker: MockerFixture) -> None:
    """Test successfully fetching remote WPT test files over HTTP."""
    mock_urlopen = mocker.patch("wptgen.context._ssrf_safe_opener.open")

    mock_response_html = mocker.MagicMock()
    mock_response_html.read.return_value = b"<!DOCTYPE html><html>test</html>"
    mock_response_html.__enter__.return_value = mock_response_html

    mock_response_js = mocker.MagicMock()
    mock_response_js.read.return_value = b"// test script"
    mock_response_js.__enter__.return_value = mock_response_js

    def mock_open_impl(req: Any, **kwargs: Any) -> Any:
        if "test1.html" in req.full_url:
            return mock_response_html
        if "test2.html" in req.full_url:
            raise urllib.error.HTTPError(
                url="", code=404, msg="Not Found", hdrs=Message(), fp=None
            )
        if "test2.js" in req.full_url:
            return mock_response_js
        raise Exception(f"Unexpected URL: {req.full_url}")

    mock_urlopen.side_effect = mock_open_impl
    mocker.patch("time.sleep")

    urls = [
        "css/css-text/text-transform/test1.html",
        "css/css-text/text-transform/test2.html",
    ]

    context = await fetch_remote_wpt_context(urls)

    assert len(context.test_contents) == 2
    assert "/css/css-text/text-transform/test1.html" in context.test_contents
    assert "/css/css-text/text-transform/test2.js" in context.test_contents
    assert (
        context.test_contents["/css/css-text/text-transform/test1.html"]
        == "<!DOCTYPE html><html>test</html>"
    )
    assert (
        context.test_contents["/css/css-text/text-transform/test2.js"]
        == "// test script"
    )


@pytest.mark.asyncio
async def test_fetch_remote_wpt_context_empty() -> None:
    """Test that empty list returns empty context."""
    context = await fetch_remote_wpt_context([])
    assert not context.test_contents


@pytest.mark.asyncio
async def test_fetch_remote_wpt_context_limit() -> None:
    """Test that exceeding MAX limit raises ValueError."""
    urls = [f"test{i}.html" for i in range(51)]
    with pytest.raises(ValueError, match="Too many tests found"):
        await fetch_remote_wpt_context(urls)


# ---------------------------------------------------------------------------
# HTML anchor slicing
# ---------------------------------------------------------------------------


def test_slice_html_by_heading_anchor_collects_until_same_level() -> None:
    """Slice from an <h3> anchor collects forward to the next <h3>/<h2>/<h1>."""
    html = """
    <html><body>
    <h2 id="other-section">Other</h2>
    <p>other content</p>
    <h3 id="align-content-property">align-content</h3>
    <p>The align-content property...</p>
    <p>It applies to multi-line flex containers.</p>
    <h4 id="sub">Sub-section</h4>
    <p>sub content</p>
    <h3 id="next-property">next-property</h3>
    <p>should be excluded</p>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "align-content-property")
    assert sliced is not None
    assert "align-content property" in sliced
    assert "multi-line flex containers" in sliced
    assert "Sub-section" in sliced  # h4 is below the boundary, included
    assert "sub content" in sliced
    assert "next-property" not in sliced  # same-level h3 → boundary
    assert "should be excluded" not in sliced


def test_slice_html_by_section_anchor_returns_section() -> None:
    """A <section id="..."> anchor returns the whole section."""
    html = """
    <html><body>
    <section id="video">
      <h2>The video element</h2>
      <p>The video element represents a video.</p>
    </section>
    <section id="audio">
      <h2>The audio element</h2>
    </section>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "video")
    assert sliced is not None
    assert "video element" in sliced
    assert "represents a video" in sliced
    assert "audio element" not in sliced


def test_slice_html_by_inline_anchor_walks_to_enclosing_section() -> None:
    """An inline <dfn> anchor walks up to the nearest enclosing <section>."""
    html = """
    <html><body>
    <section>
      <h2>Other</h2>
      <p>other content</p>
    </section>
    <section>
      <h2>The <dfn id="flex-basis">flex-basis</dfn> property</h2>
      <p>flex-basis description.</p>
    </section>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "flex-basis")
    assert sliced is not None
    assert 'id="flex-basis"' in sliced
    assert "flex-basis description" in sliced
    assert "other content" not in sliced


def test_slice_html_by_anchor_missing_returns_none() -> None:
    """A missing anchor returns None so callers can fall back."""
    html = "<html><body><h2 id='real'>Real</h2></body></html>"
    assert _slice_html_by_anchor(html, "does-not-exist") is None


def test_slice_html_by_heading_anchor_higher_level_boundary() -> None:
    """An <h4> anchor stops at the next <h4>/<h3>/<h2>/<h1>, not at <h5>/<h6>."""
    html = """
    <html><body>
    <h4 id="target">Target</h4>
    <p>p1</p>
    <h5>Sub</h5>
    <p>p2</p>
    <h6>Sub-sub</h6>
    <p>p3</p>
    <h3>Higher</h3>
    <p>p4 should be excluded</p>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "target")
    assert sliced is not None
    assert "p1" in sliced
    assert "p2" in sliced
    assert "p3" in sliced
    assert "p4 should be excluded" not in sliced
    assert "Higher" not in sliced


# ---------------------------------------------------------------------------
# fetch_and_slice_spec (slicer + fetch integration)
# ---------------------------------------------------------------------------


def test_fetch_and_slice_spec_without_fragment_uses_full_extract(
    mocker: MockerFixture,
) -> None:
    """A URL with no fragment delegates to fetch_and_extract_text."""
    mocker.patch(
        "wptgen.context.fetch_and_extract_text",
        return_value="full document markdown",
    )
    raw_html_mock = mocker.patch("wptgen.context.fetch_raw_html")

    result = fetch_and_slice_spec("https://example.com/spec/")
    assert result == "full document markdown"
    raw_html_mock.assert_not_called()


def test_fetch_and_slice_spec_with_fragment_slices(
    mocker: MockerFixture,
) -> None:
    """A URL with a fragment fetches raw HTML and slices to the section."""
    raw_html = """
    <html><body>
      <h2 id="other">other</h2>
      <p>excluded</p>
      <h2 id="video">Video element</h2>
      <p>The video element represents a video.</p>
    </body></html>
    """
    mocker.patch("wptgen.context.fetch_raw_html", return_value=raw_html)
    fallback_mock = mocker.patch("wptgen.context.fetch_and_extract_text")

    result = fetch_and_slice_spec("https://example.com/spec/#video")
    assert result is not None
    assert "Video element" in result
    assert "represents a video" in result
    assert "excluded" not in result
    fallback_mock.assert_not_called()


def test_fetch_and_slice_spec_missing_anchor_falls_back_to_full(
    mocker: MockerFixture,
) -> None:
    """Anchor not found → invoke `warn` callback + fall back to the full document."""
    mocker.patch(
        "wptgen.context.fetch_raw_html",
        return_value="<html><body><p>no anchors</p></body></html>",
    )
    fallback_mock = mocker.patch(
        "wptgen.context.fetch_and_extract_text",
        return_value="full document markdown",
    )
    warn = mocker.MagicMock()

    result = fetch_and_slice_spec(
        "https://example.com/spec/#does-not-exist", warn=warn
    )
    assert result == "full document markdown"
    fallback_mock.assert_called_once_with("https://example.com/spec/")
    warn.assert_called_once()


def test_fetch_and_slice_spec_missing_anchor_without_warn_callback(
    mocker: MockerFixture,
) -> None:
    """Missing anchor + no warn callback → silent fallback, no crash."""
    mocker.patch(
        "wptgen.context.fetch_raw_html",
        return_value="<html><body><p>no anchors</p></body></html>",
    )
    mocker.patch(
        "wptgen.context.fetch_and_extract_text",
        return_value="full document markdown",
    )
    # No `warn` kwarg passed; should still succeed.
    assert (
        fetch_and_slice_spec("https://example.com/spec/#does-not-exist")
        == "full document markdown"
    )


def test_fetch_and_slice_spec_raw_fetch_failure_returns_none(
    mocker: MockerFixture,
) -> None:
    mocker.patch("wptgen.context.fetch_raw_html", return_value=None)
    mocker.patch("wptgen.context.fetch_and_extract_text")
    assert fetch_and_slice_spec("https://example.com/spec/#anything") is None


# ---------------------------------------------------------------------------
# slug_for_spec_url
# ---------------------------------------------------------------------------


def test_slug_for_spec_url_basic() -> None:
    assert (
        slug_for_spec_url("https://drafts.csswg.org/css-flexbox/")
        == "spec-drafts-csswg-org-css-flexbox"
    )


def test_slug_for_spec_url_includes_fragment() -> None:
    assert (
        slug_for_spec_url("https://example.com/spec/#video")
        == "spec-example-com-spec-video"
    )


def test_slug_for_spec_url_fragments_distinguish() -> None:
    """`#video` and `#audio` produce different slugs so caches don't collide."""
    a = slug_for_spec_url("https://example.com/spec/#video")
    b = slug_for_spec_url("https://example.com/spec/#audio")
    assert a != b


# ---------------------------------------------------------------------------
# SSRF Protection & IP Hardening
# ---------------------------------------------------------------------------


def test_validate_ip_against_ssrf() -> None:
    """Verifies restricted IP ranges raise ValueError."""
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("127.0.0.1")
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("10.0.0.1")
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("169.254.169.254")
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("100.64.0.1")
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("0.0.0.0")
    with pytest.raises(ValueError, match="restricted IP address"):
        validate_ip_against_ssrf("::ffff:127.0.0.1")
    validate_ip_against_ssrf("8.8.8.8")
    validate_ip_against_ssrf("93.184.216.34")

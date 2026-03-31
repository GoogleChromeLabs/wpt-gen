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

import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from wptgen.context import (
    FeatureMetadata,
    _resolve_patterns,
    extract_dependencies,
    extract_feature_metadata,
    extract_wpt_paths,
    fetch_and_extract_text,
    fetch_feature_yaml,
    fetch_mdn_urls,
    find_feature_tests,
    gather_local_test_context,
    is_wpt_test_file,
    normalize_wpt_path,
    resolve_dependency_path,
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
    assert extract_wpt_paths("") == []
    assert extract_wpt_paths(None) == []  # type: ignore


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
  Look at css/css-grid/alignment/grid-item-alignment-001.html and dom/nodes/Element-getAttribute.html.
  Also html/canvas (a directory).
  """
    paths = extract_wpt_paths(wpt_descr)
    assert paths == []


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

    assert valid == []
    assert len(invalid) == 2


def test_fetch_mdn_urls_success(mocker: MockerFixture) -> None:
    """Test successfully fetching MDN URLs from the mapping JSON."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b'{"fetch": [{"url": "https://developer.mozilla.org/en-US/docs/Web/API/fetch"}]}'
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_mdn_urls("fetch")

    assert result == ["https://developer.mozilla.org/en-US/docs/Web/API/fetch"]
    mock_urlopen.assert_called_once()
    request_obj = mock_urlopen.call_args[0][0]
    assert "mdn-docs.json" in request_obj.full_url


def test_fetch_mdn_urls_not_found(mocker: MockerFixture) -> None:
    """Test that if a feature ID is not in the mapping, it returns an empty list."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b'{"fetch": [{"url": "https://example.com"}]}'
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_mdn_urls("unknown")

    assert result == []


def test_fetch_mdn_urls_error(mocker: MockerFixture) -> None:
    """Test that HTTP errors during mapping fetch return an empty list."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=Message(), fp=None
    )

    result = fetch_mdn_urls("fetch")

    assert result == []


def test_fetch_feature_yaml_success(mocker: MockerFixture) -> None:
    """Test the happy path where the YAML file is successfully fetched and parsed."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")

    # Setup the context manager mock so it returns a byte string when .read() is called
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
    mock_urlopen = mocker.patch("urllib.request.urlopen")

    # Simulate a 404 HTTPError
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=Message(), fp=None
    )

    result = fetch_feature_yaml("fake-feature")

    assert result is None


def test_fetch_feature_yaml_server_error(mocker: MockerFixture) -> None:
    """Test that a 500 error (or rate limit) raises an exception."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")

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
    assert result.specs == []


def test_fetch_and_extract_text_success(mocker: MockerFixture) -> None:
    """Test the happy path where HTML is downloaded and successfully converted to Markdown."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = (
        b"<html><body><main><h1>Spec</h1><p>Text</p></main></body></html>"
    )
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_and_extract_text("https://example.com")

    assert result == "# Spec\n\nText"

    mock_urlopen.assert_called_once()


def test_fetch_and_extract_text_retry_success(mocker: MockerFixture) -> None:
  """Test that fetch_and_extract_text retries on transient errors and eventually succeeds."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')

  mock_response = mocker.MagicMock()
  mock_response.read.return_value = (
    b'<html><body><main><h1>Spec</h1><p>Text</p></main></body></html>'
  )
  mock_response.__enter__.return_value = mock_response

  # Fail twice with 429, then succeed
  error429 = urllib.error.HTTPError(
    url='https://example.com', code=429, msg='Too Many Requests', hdrs=Message(), fp=None
  )

  mock_urlopen.side_effect = [error429, error429, mock_response]

  # We need to mock time.sleep to avoid waiting in tests
  mock_sleep = mocker.patch('time.sleep')

  result = fetch_and_extract_text('https://example.com')

  assert result == '# Spec\n\nText'
  assert mock_urlopen.call_count == 3
  assert mock_sleep.call_count == 2


def test_fetch_and_extract_text_retry_max_reached(mocker: MockerFixture) -> None:
  """Test that fetch_and_extract_text eventually gives up after MAX_RETRIES."""
  from wptgen.utils import MAX_RETRIES

  mock_urlopen = mocker.patch('urllib.request.urlopen')

  error429 = urllib.error.HTTPError(
    url='https://example.com', code=429, msg='Too Many Requests', hdrs=Message(), fp=None
  )

  # Fail MAX_RETRIES times
  mock_urlopen.side_effect = [error429] * MAX_RETRIES

  mock_sleep = mocker.patch('time.sleep')

  result = fetch_and_extract_text('https://example.com')

  assert result is None
  assert mock_urlopen.call_count == MAX_RETRIES
  assert mock_sleep.call_count == MAX_RETRIES - 1


def test_fetch_and_extract_text_fetch_fails(mocker: MockerFixture) -> None:
    """Test that if the URL cannot be fetched, the function returns None."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_urlopen.side_effect = Exception("Network error")

    result = fetch_and_extract_text("https://example.com")

    assert result is None


def test_fetch_and_extract_text_extract_fails(mocker: MockerFixture) -> None:
    """Test that if no content is found, the function returns None."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b"<html></html>"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_and_extract_text("https://example.com")

    assert result is None


def test_fetch_and_extract_text_preserves_internal_links(
    mocker: MockerFixture,
) -> None:
    """Test that internal spec links are preserved while external links are stripped."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")
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
    """Test that _resolve_patterns correctly handles standard and recursive globs."""
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
    """Test that negative patterns (!pattern) successfully remove files from the set."""
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
    """Test that malformed YAML files are gracefully skipped without crashing the loop."""
    # Create a broken YAML file
    feat_dir = tmp_path / "broken-feature"
    feat_dir.mkdir()
    (feat_dir / "WEB_FEATURES.yml").write_text(
        "features:\n - name: oops\n  bad_indent: true"
    )

    # Create a valid one to ensure the loop continues after the error
    valid_dir = tmp_path / "valid-feature"
    valid_dir.mkdir()
    (valid_dir / "WEB_FEATURES.yml").write_text(
        "features:\n  - name: works\n    files:\n      - 'test.html'"
    )
    (valid_dir / "test.html").touch()

    results = find_feature_tests(str(tmp_path), "works")
    # It should have skipped the broken directory and found the valid one
    assert len(results) == 1
    assert results[0] == str(valid_dir / "test.html")


def test_find_feature_tests_feature_not_found(tmp_path: Path) -> None:
    """Test that if a feature ID is not in any YAML, it returns an empty list."""
    (tmp_path / "WEB_FEATURES.yml").write_text(
        "features:\n  - name: grid\n    files:\n      - '*.html'"
    )

    results = find_feature_tests(str(tmp_path), "non-existent-feature")

    assert results == []


def test_extract_dependencies() -> None:
    """Test that dependencies are correctly extracted from HTML and JS content."""
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
    """Test that dependency references are correctly resolved to local absolute paths."""
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
    """Test recursive gathering of tests and dependencies from the local disk."""
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
    mock_urlopen = mocker.patch("urllib.request.urlopen")
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

    assert find_feature_tests(str(tmp_path), "grid") == []


def test_find_feature_tests_exception(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Test that exceptions during YAML processing are caught."""
    feat_dir = tmp_path / "exception"
    feat_dir.mkdir()
    (feat_dir / "WEB_FEATURES.yml").touch()

    # Mock open to raise an exception for this specific file
    mocker.patch("builtins.open", side_effect=Exception("IO Error"))
    assert find_feature_tests(str(tmp_path), "grid") == []


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
    """Test that exceptions during file reading in gather_local_test_context are caught."""
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()
    test_html = wpt_root / "test.html"
    test_html.touch()

    # Mock read_text to raise an exception
    mocker.patch("pathlib.Path.read_text", side_effect=Exception("Read Error"))

    context = gather_local_test_context([str(test_html)], str(wpt_root))
    assert context.test_contents == {}


def test_fetch_feature_yaml_draft(mocker: MockerFixture) -> None:
    """Test that fetching a draft feature constructs the correct URL."""
    mock_urlopen = mocker.patch("urllib.request.urlopen")

    mock_response = mocker.MagicMock()
    mock_response.read.return_value = b"name: 'Draft Feature'"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = fetch_feature_yaml("draft-feature", draft=True)

    assert result == {"name": "Draft Feature"}
    mock_urlopen.assert_called_once()

    request_obj = mock_urlopen.call_args[0][0]
    assert (
        request_obj.full_url
        == "https://raw.githubusercontent.com/web-platform-dx/web-features/main/features/draft/spec/draft-feature.yml"
    )

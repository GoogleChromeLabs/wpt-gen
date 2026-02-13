import pytest
import urllib.error
from wptgen.context import (
  extract_feature_metadata,
  fetch_feature_yaml,
  fetch_and_extract_text,
  find_feature_tests,
  _resolve_patterns,
  extract_dependencies,
  resolve_dependency_path,
  gather_local_test_context,
  WebFeatureMetadata
)


def test_fetch_feature_yaml_success(mocker):
  """Test the happy path where the YAML file is successfully fetched and parsed."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')

  # Setup the context manager mock so it returns a byte string when .read() is called
  mock_response = mocker.MagicMock()
  mock_response.read.return_value = b"spec: 'https://example.com/spec'"
  mock_urlopen.return_value.__enter__.return_value = mock_response

  result = fetch_feature_yaml('popover')

  assert result == {'spec': 'https://example.com/spec'}
  mock_urlopen.assert_called_once()

  # Verify the constructed URL is correct
  request_obj = mock_urlopen.call_args[0][0]
  assert 'popover.yml' in request_obj.full_url
  assert 'raw.githubusercontent.com' in request_obj.full_url


def test_fetch_feature_yaml_not_found(mocker):
  """Test that a 404 error from GitHub safely returns None."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')

  # Simulate a 404 HTTPError
  mock_urlopen.side_effect = urllib.error.HTTPError(
    url='', code=404, msg='Not Found', hdrs={}, fp=None
  )

  result = fetch_feature_yaml('fake-feature')

  assert result is None


def test_fetch_feature_yaml_server_error(mocker):
  """Test that a 500 error (or rate limit) raises an exception."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')

  # Simulate a 500 HTTPError
  mock_urlopen.side_effect = urllib.error.HTTPError(
    url='', code=500, msg='Internal Server Error', hdrs={}, fp=None
  )

  with pytest.raises(urllib.error.HTTPError):
    fetch_feature_yaml('grid')


def test_extract_feature_metadata_single_spec():
  """Test metadata extraction when the spec field is a single string."""
  data = {
    'name': 'popover',
    'description': 'A popup feature',
    'spec': 'https://example.com/spec'
  }
  result = extract_feature_metadata(data)

  assert isinstance(result, WebFeatureMetadata)
  assert result.name == 'popover'
  assert result.description == 'A popup feature'
  assert result.specs == ['https://example.com/spec']


def test_extract_feature_metadata_list_spec():
  """Test metadata extraction when the spec field is a list of URLs."""
  data = {
    'name': 'grid',
    'description': 'Grid layout',
    'spec': [
      'https://example.com/spec1',
      'https://example.com/spec2'
    ]
  }
  result = extract_feature_metadata(data)

  assert result.name == 'grid'
  assert result.specs == [
    'https://example.com/spec1',
    'https://example.com/spec2'
  ]


def test_extract_feature_metadata_defaults():
  """Test that missing fields fall back to safe defaults."""
  data = {}
  result = extract_feature_metadata(data)

  assert result.name == 'Unknown Feature'
  assert result.description == ''
  assert result.specs == []


def test_fetch_and_extract_text_success(mocker):
  """Test the happy path where HTML is downloaded and successfully converted to Markdown."""
  # Mock the Trafilatura functions
  mock_fetch = mocker.patch('wptgen.context.fetch_url', return_value='<html><body><h1>Spec</h1></body></html>')
  mock_extract = mocker.patch('wptgen.context.extract', return_value='# Spec Content')

  result = fetch_and_extract_text('https://example.com')

  assert result == '# Spec Content'
  mock_fetch.assert_called_once_with('https://example.com')

  # Verify extract was called with our optimization flags
  call_kwargs = mock_extract.call_args.kwargs
  assert call_kwargs['output_format'] == 'markdown'
  assert call_kwargs['include_links'] is False
  assert call_kwargs['include_tables'] is True


def test_fetch_and_extract_text_fetch_fails(mocker):
  """Test that if the URL cannot be fetched, the function returns None."""
  mocker.patch('wptgen.context.fetch_url', return_value=None)

  result = fetch_and_extract_text('https://example.com')

  assert result is None


def test_fetch_and_extract_text_extract_fails(mocker):
  """Test that if Trafilatura fails to extract meaningful text, the function returns None."""
  mocker.patch('wptgen.context.fetch_url', return_value='<html></html>')
  mocker.patch('wptgen.context.extract', return_value=None)

  result = fetch_and_extract_text('https://example.com')

  assert result is None


def test_resolve_patterns_basic_and_recursive(tmp_path):
  """Test that _resolve_patterns correctly handles standard and recursive globs."""
  # Create a mock directory structure
  (tmp_path / 'test1.html').touch()
  (tmp_path / 'test2.txt').touch()

  sub_dir = tmp_path / 'subfolder'
  sub_dir.mkdir()
  (sub_dir / 'test3.html').touch()

  # Also create a WEB_FEATURES.yml, which should be explicitly ignored
  (tmp_path / 'WEB_FEATURES.yml').touch()

  # Look for all HTML files, including those in subdirectories
  patterns = ['**/*.html']
  results = _resolve_patterns(tmp_path, patterns)

  assert len(results) == 2
  assert str(tmp_path / 'test1.html') in results
  assert str(sub_dir / 'test3.html') in results
  assert str(tmp_path / 'test2.txt') not in results
  assert str(tmp_path / 'WEB_FEATURES.yml') not in results

def test_resolve_patterns_negative_exclusion(tmp_path):
  """Test that negative patterns (!pattern) successfully remove files from the set."""
  (tmp_path / 'include_me.html').touch()
  (tmp_path / 'exclude_me.html').touch()

  patterns = ['*.html', '!exclude_me.html']

  results = _resolve_patterns(tmp_path, patterns)

  assert len(results) == 1
  assert str(tmp_path / 'include_me.html') in results
  assert str(tmp_path / 'exclude_me.html') not in results

def test_find_feature_tests_happy_path(tmp_path):
  """Test the full end-to-end scan for a specific feature."""
  # Build the repository structure
  feat_dir = tmp_path / 'css' / 'css-grid'
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
  (feat_dir / 'WEB_FEATURES.yml').write_text(yaml_content, encoding='utf-8')

  # Create the test files
  (feat_dir / 'grid_test.html').touch()
  (feat_dir / 'skip.html').touch()

  results = find_feature_tests(str(tmp_path), 'grid')

  assert len(results) == 1
  assert results[0] == str(feat_dir / 'grid_test.html')


def test_find_feature_tests_missing_directory():
  """Test that an invalid repository path raises a ValueError."""
  with pytest.raises(ValueError, match='The directory provided does not exist'):
    find_feature_tests('/path/that/absolutely/does/not/exist', 'grid')


def test_find_feature_tests_malformed_yaml(tmp_path):
  """Test that malformed YAML files are gracefully skipped without crashing the loop."""
  # Create a broken YAML file
  feat_dir = tmp_path / 'broken-feature'
  feat_dir.mkdir()
  (feat_dir / 'WEB_FEATURES.yml').write_text("features:\n - name: oops\n  bad_indent: true")

  # Create a valid one to ensure the loop continues after the error
  valid_dir = tmp_path / 'valid-feature'
  valid_dir.mkdir()
  (valid_dir / 'WEB_FEATURES.yml').write_text("features:\n  - name: works\n    files:\n      - 'test.html'")
  (valid_dir / 'test.html').touch()

  results = find_feature_tests(str(tmp_path), 'works')
  # It should have skipped the broken directory and found the valid one
  assert len(results) == 1
  assert results[0] == str(valid_dir / 'test.html')


def test_find_feature_tests_feature_not_found(tmp_path):
  """Test that if a feature ID is not in any YAML, it returns an empty list."""
  (tmp_path / 'WEB_FEATURES.yml').write_text("features:\n  - name: grid\n    files:\n      - '*.html'")

  results = find_feature_tests(str(tmp_path), 'non-existent-feature')

  assert results == []


def test_extract_dependencies():
  """Test that dependencies are correctly extracted from HTML and JS content."""
  content = """
  <script src="a.js"></script>
  <script src='/b.js'></script>
  import { x } from "./c.js";
  import "./d.js";
  export { y } from "../e.js";
  """
  deps = extract_dependencies(content)
  assert set(deps) == {"a.js", "/b.js", "./c.js", "./d.js", "../e.js"}


def test_resolve_dependency_path(tmp_path):
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
  resolved_abs = resolve_dependency_path(test_file, "/resources/testharness.js", wpt_root)
  assert resolved_abs == testharness

  # Relative path
  resolved_rel = resolve_dependency_path(test_file, "helper.js", wpt_root)
  assert resolved_rel == helper

  # External URL (should be ignored)
  assert resolve_dependency_path(test_file, "http://example.com/js.js", wpt_root) is None

  # Missing file
  assert resolve_dependency_path(test_file, "missing.js", wpt_root) is None


def test_gather_local_test_context(tmp_path):
  """Test recursive gathering of tests and dependencies from the local disk."""
  wpt_root = tmp_path / "wpt"
  wpt_root.mkdir()

  test_dir = wpt_root / "feature"
  test_dir.mkdir()

  test_html = (test_dir / "test.html").resolve()
  test_html.write_text('<script src="dep.js"></script>', encoding='utf-8')

  dep_js = (test_dir / "dep.js").resolve()
  dep_js.write_text('import "./subdep.js";', encoding='utf-8')

  subdep_js = (test_dir / "subdep.js").resolve()
  subdep_js.write_text('// no deps', encoding='utf-8')

  context = gather_local_test_context([str(test_html)], str(wpt_root))

  assert str(test_html) in context.test_contents
  assert str(dep_js) in context.dependency_contents
  assert str(subdep_js) in context.dependency_contents

  # Verify the mapping
  deps_for_test = context.test_to_deps[str(test_html)]
  assert str(dep_js) in deps_for_test
  assert str(subdep_js) in deps_for_test

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

from pytest_mock import MockerFixture

from wptgen.context import (
  extract_chromestatus_metadata,
  extract_wpt_paths_from_descr,
  fetch_chromestatus_feature,
)


def test_fetch_chromestatus_feature_success(mocker: MockerFixture) -> None:
  """Test successfully fetching feature data from ChromeStatus."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')
  mock_response = mocker.MagicMock()
  # Include the XSSI protection string
  mock_response.read.return_value = b')]}\'\n{"name": "Test Feature", "id": 123}'
  mock_urlopen.return_value.__enter__.return_value = mock_response

  result = fetch_chromestatus_feature('123')

  assert result == {'name': 'Test Feature', 'id': 123}
  mock_urlopen.assert_called_once()
  request_obj = mock_urlopen.call_args[0][0]
  assert 'chromestatus.com/api/v0/features/123' in request_obj.full_url


def test_fetch_chromestatus_feature_no_xssi(mocker: MockerFixture) -> None:
  """Test fetching feature data that doesn't have the XSSI prefix (should still work)."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')
  mock_response = mocker.MagicMock()
  mock_response.read.return_value = b'{"name": "Test Feature"}'
  mock_urlopen.return_value.__enter__.return_value = mock_response

  result = fetch_chromestatus_feature('123')
  assert result == {'name': 'Test Feature'}


def test_fetch_chromestatus_feature_not_found(mocker: MockerFixture) -> None:
  """Test that a 404 from ChromeStatus returns None."""
  mock_urlopen = mocker.patch('urllib.request.urlopen')
  mock_urlopen.side_effect = urllib.error.HTTPError(
    url='', code=404, msg='Not Found', hdrs=Message(), fp=None
  )

  result = fetch_chromestatus_feature('999')
  assert result is None


def test_extract_chromestatus_metadata_basic() -> None:
  """Test extracting basic metadata from ChromeStatus data."""
  data = {
    'name': 'Feature Name',
    'summary': 'Feature Summary',
    'spec_link': 'https://example.com/spec',
  }
  metadata = extract_chromestatus_metadata(data)

  assert metadata.name == 'Feature Name'
  assert metadata.description == 'Feature Summary'
  assert metadata.specs == ['https://example.com/spec']


def test_extract_chromestatus_metadata_with_explainers() -> None:
  """Test extracting metadata including explainers and alternative spec links."""
  data = {
    'name': 'Feature Name',
    'summary': 'Summary',
    'explainer_links': ['https://example.com/explainer'],
    'standards': {'spec': 'https://example.com/std_spec'},
  }
  metadata = extract_chromestatus_metadata(data)

  assert metadata.name == 'Feature Name'
  assert 'Explainers:' in metadata.description
  assert 'https://example.com/explainer' in metadata.description
  # specs should include both std spec and explainer
  assert 'https://example.com/std_spec' in metadata.specs
  assert 'https://example.com/explainer' in metadata.specs


def test_extract_wpt_paths_from_descr_urls() -> None:
  """Test extracting WPT paths from wpt.fyi URLs."""
  descr = 'Tests: https://wpt.fyi/results/css/css-grid/grid-model?label=master'
  paths = extract_wpt_paths_from_descr(descr)
  assert 'css/css-grid/grid-model' in paths


def test_extract_wpt_paths_from_descr_raw_paths() -> None:
  """Test extracting WPT paths from raw path strings."""
  descr = 'See /css/css-grid/alignment.html and some/other/test.any.js'
  paths = extract_wpt_paths_from_descr(descr)
  assert 'css/css-grid/alignment.html' in paths
  assert 'some/other/test.any.js' in paths


def test_extract_wpt_paths_from_descr_mixed() -> None:
  """Test mixed content in wpt_descr."""
  descr = """
  Main test: https://wpt.fyi/results/dom/nodes/Node-appendChild.html
  Also check: /dom/nodes/Node-removeChild.html
  """
  paths = extract_wpt_paths_from_descr(descr)
  assert 'dom/nodes/Node-appendChild.html' in paths
  assert 'dom/nodes/Node-removeChild.html' in paths

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
import urllib.error
from email.message import Message

from pytest_mock import MockerFixture

from wptgen.context import DataSource, fetch_chromestatus_metadata


def test_fetch_chromestatus_metadata_success(mocker: MockerFixture) -> None:
  mock_data = {
    'name': 'Test Feature',
    'summary': 'This is a test feature.',
    'explainer_links': ['https://explainer.com/1', 'https://explainer.com/2'],
    'spec_link': 'https://spec.com/test',
  }

  mock_response = mocker.MagicMock()
  mock_response.read.return_value = json.dumps(mock_data).encode('utf-8')
  mock_response.__enter__.return_value = mock_response
  mocker.patch('urllib.request.urlopen', return_value=mock_response)

  metadata = fetch_chromestatus_metadata('12345')

  assert metadata is not None
  assert metadata.name == 'Test Feature'
  assert metadata.description == 'This is a test feature.'
  assert metadata.specs == ['https://spec.com/test']
  assert metadata.source == DataSource.CHROMESTATUS
  assert metadata.explainer_links == ['https://explainer.com/1', 'https://explainer.com/2']


def test_fetch_chromestatus_metadata_not_found(mocker: MockerFixture) -> None:
  mocker.patch(
    'urllib.request.urlopen',
    side_effect=urllib.error.HTTPError('url', 404, 'Not Found', hdrs=Message(), fp=None),
  )

  metadata = fetch_chromestatus_metadata('nonexistent')

  assert metadata is None


def test_fetch_chromestatus_metadata_api_error(mocker: MockerFixture) -> None:
  mocker.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('API Error'))

  metadata = fetch_chromestatus_metadata('12345')

  assert metadata is None

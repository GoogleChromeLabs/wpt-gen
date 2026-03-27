# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import urllib.error
from email.message import Message
from unittest.mock import patch

from wptgen.context import fetch_chromestatus_metadata


def test_fetch_chromestatus_metadata_http_error_non_404() -> None:
  with patch('urllib.request.urlopen') as mock_urlopen:
    mock_urlopen.side_effect = urllib.error.HTTPError(
      url='http://test.com', code=500, msg='Internal Server Error', hdrs=Message(), fp=None
    )
    res = fetch_chromestatus_metadata('1234')
    assert res is None

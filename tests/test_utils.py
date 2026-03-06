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

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from wptgen.utils import retry


def test_retry_success() -> None:
  """Test that retry doesn't interfere with successful calls."""
  call_count = 0

  @retry(exceptions=ValueError, max_attempts=3)
  def success_func() -> str:
    nonlocal call_count
    call_count += 1
    return 'success'

  result = success_func()
  assert result == 'success'
  assert call_count == 1


def test_retry_eventual_success(mocker: MockerFixture) -> None:
  """Test that retry succeeds if the function eventually succeeds."""
  mocker.patch('time.sleep')  # Speed up tests
  call_count = 0

  @retry(exceptions=ValueError, max_attempts=3)
  def eventual_success() -> str:
    nonlocal call_count
    call_count += 1
    if call_count < 3:
      raise ValueError('Fail')
    return 'success'

  result = eventual_success()
  assert result == 'success'
  assert call_count == 3


def test_retry_max_attempts_reached(mocker: MockerFixture) -> None:
  """Test that retry raises the last exception after max attempts."""
  mocker.patch('time.sleep')
  call_count = 0

  @retry(exceptions=ValueError, max_attempts=3)
  def always_fail() -> None:
    nonlocal call_count
    call_count += 1
    raise ValueError(f'Fail {call_count}')

  with pytest.raises(ValueError, match='Fail 3'):
    always_fail()

  assert call_count == 3


def test_retry_unhandled_exception(mocker: MockerFixture) -> None:
  """Test that retry doesn't catch exceptions not in the list."""
  mocker.patch('time.sleep')
  call_count = 0

  @retry(exceptions=ValueError, max_attempts=3)
  def unhandled_fail() -> None:
    nonlocal call_count
    call_count += 1
    raise TypeError('Unhandled')

  with pytest.raises(TypeError, match='Unhandled'):
    unhandled_fail()

  assert call_count == 1


def test_retry_max_attempts_attr(mocker: MockerFixture) -> None:
  """Test that retry correctly looks up max attempts from an instance attribute."""
  mocker.patch('time.sleep')

  class TestClass:
    def __init__(self, retries: int):
      self.retries = retries
      self.calls = 0

    @retry(exceptions=ValueError, max_attempts_attr='retries')
    def do_something(self) -> str:
      self.calls += 1
      raise ValueError('Fail')

  # Case 1: 2 retries
  obj2 = TestClass(retries=2)
  with pytest.raises(ValueError, match='Fail'):
    obj2.do_something()
  assert obj2.calls == 2

  # Case 2: 4 retries
  obj4 = TestClass(retries=4)
  with pytest.raises(ValueError, match='Fail'):
    obj4.do_something()
  assert obj4.calls == 4


def test_retry_multiple_exceptions(mocker: MockerFixture) -> None:
  """Test that retry catches any exception in the provided tuple."""
  mocker.patch('time.sleep')
  call_count = 0

  @retry(exceptions=(ValueError, KeyError), max_attempts=3)
  def multiple_fail() -> None:
    nonlocal call_count
    call_count += 1
    if call_count == 1:
      raise ValueError('Value')
    raise KeyError('Key')

  with pytest.raises(KeyError, match='Key'):
    multiple_fail()

  assert call_count == 3


def test_retry_backoff_timing(mocker: MockerFixture) -> None:
  """Test that the delay increases exponentially without jitter."""
  mock_sleep = mocker.patch('time.sleep')
  call_count = 0

  @retry(
    exceptions=ValueError,
    max_attempts=4,
    initial_delay=1.0,
    backoff_factor=2.0,
    jitter=False,
  )
  def backoff_fail() -> None:
    nonlocal call_count
    call_count += 1
    raise ValueError('Fail')

  with pytest.raises(ValueError, match='Fail'):
    backoff_fail()

  # Expected sleeps: 1.0, 2.0, 4.0
  assert mock_sleep.call_count == 3
  mock_sleep.assert_has_calls(
    [
      mocker.call(1.0),
      mocker.call(2.0),
      mocker.call(4.0),
    ]
  )


def test_retry_max_delay(mocker: MockerFixture) -> None:
  """Test that the delay is capped by the global MAX_DELAY."""
  from wptgen.utils import MAX_DELAY

  mock_sleep = mocker.patch('time.sleep')

  @retry(
    exceptions=ValueError,
    max_attempts=3,
    initial_delay=MAX_DELAY + 10.0,  # Start above limit
    backoff_factor=2.0,
    jitter=False,
  )
  def huge_delay_fail() -> None:
    raise ValueError('Fail')

  with pytest.raises(ValueError, match='Fail'):
    huge_delay_fail()

  # Each sleep should be capped at MAX_DELAY
  assert mock_sleep.call_count == 2
  mock_sleep.assert_has_calls(
    [
      mocker.call(MAX_DELAY),
      mocker.call(MAX_DELAY),
    ]
  )


def test_retry_max_attempts_cap(mocker: MockerFixture) -> None:
  """Test that max_attempts is capped by the global MAX_RETRIES."""
  from wptgen.utils import MAX_RETRIES

  mocker.patch('time.sleep')
  call_count = 0

  # Set max_attempts higher than the global MAX_RETRIES
  @retry(exceptions=ValueError, max_attempts=MAX_RETRIES + 10)
  def capped_fail() -> None:
    nonlocal call_count
    call_count += 1
    raise ValueError('Fail')

  with pytest.raises(ValueError, match='Fail'):
    capped_fail()

  # Should only have attempted MAX_RETRIES times
  assert call_count == MAX_RETRIES


def test_retry_errors() -> None:
  """Test error conditions in the retry decorator."""

  # 1. max_attempts_attr used without 'self' (args empty)
  @retry(exceptions=Exception, max_attempts_attr='retries')
  def no_self() -> None:
    pass

  with pytest.raises(ValueError, match="Cannot find attribute 'retries' because 'self' is missing"):
    no_self()

  # 2. max_attempts_attr missing from 'self'
  class BadClass:
    @retry(exceptions=Exception, max_attempts_attr='truly_missing_attr')
    def missing_attr(self) -> None:
      pass

  with pytest.raises(ValueError, match="has no attribute 'truly_missing_attr'"):
    BadClass().missing_attr()

  # 3. max_attempts < 1
  @retry(exceptions=Exception, max_attempts=0)
  def invalid_attempts() -> None:
    pass

  with pytest.raises(ValueError, match='max_attempts must be an integer >= 1'):
    invalid_attempts()


def test_parse_suggestions_empty() -> None:
  from wptgen.utils import parse_suggestions

  assert parse_suggestions('no suggestions') == []


def test_parse_multi_file_response() -> None:
  from wptgen.utils import parse_multi_file_response

  raw_text = """
[FILE_1: test.html]
test content
[/FILE_1]
Random text
[FILE_2: ref.html]
ref content
[/FILE_2]
"""
  expected = [('.html', 'test content'), ('.html', 'ref content')]
  assert parse_multi_file_response(raw_text) == expected


def test_parse_multi_file_response_complex_suffixes() -> None:
  from wptgen.utils import parse_multi_file_response

  raw_text = """
[FILE_1: .https.any.js]
js content
[/FILE_1]
[FILE_2: .sub.html]
html content
[/FILE_2]
"""
  expected = [('.https.any.js', 'js content'), ('.sub.html', 'html content')]
  assert parse_multi_file_response(raw_text) == expected


def test_parse_multi_file_response_shave_suffixes() -> None:
  from wptgen.utils import parse_multi_file_response

  raw_text = """
[FILE_1: my-test-001.https.html]
content 1
[/FILE_1]
[FILE_2: ref-file.html]
content 2
[/FILE_2]
[FILE_3: just_extension]
content 3
[/FILE_3]
"""
  expected = [
    ('.https.html', 'content 1'),
    ('.html', 'content 2'),
    ('.just_extension', 'content 3'),
  ]
  assert parse_multi_file_response(raw_text) == expected


def test_parse_multi_file_response_empty() -> None:
  from wptgen.utils import parse_multi_file_response

  assert parse_multi_file_response('no files') == []


def test_get_next_available_root_basic(tmp_path: Path) -> None:
  from wptgen.utils import get_next_available_root

  used_names: set[str] = set()
  root = get_next_available_root('feat', tmp_path, used_names)

  assert root == 'feat-001'
  assert 'feat-001' in used_names


def test_get_next_available_root_increment(tmp_path: Path) -> None:
  from wptgen.utils import get_next_available_root

  # Existing file feat-001.html
  (tmp_path / 'feat-001.html').touch()

  used_names: set[str] = set()
  root = get_next_available_root('feat', tmp_path, used_names)
  assert root == 'feat-002'

  # Add feat-002 manually to used_names
  root_3 = get_next_available_root('feat', tmp_path, used_names)
  assert root_3 == 'feat-003'


def test_get_next_available_root_collision_with_other_ext(tmp_path: Path) -> None:
  from wptgen.utils import get_next_available_root

  # Existing JS file feat-001.any.js
  (tmp_path / 'feat-001.any.js').touch()

  used_names: set[str] = set()
  root = get_next_available_root('feat', tmp_path, used_names)
  assert root == 'feat-002'


def test_get_next_available_root_max_length(tmp_path: Path) -> None:
  from wptgen.utils import get_next_available_root

  long_feat = 'a' * 200
  used_names: set[str] = set()
  # Max length 150. Suffix buffer is 35. -4 for -001.
  # 150 - 35 - 4 = 111 chars for feature id.
  root = get_next_available_root(long_feat, tmp_path, used_names)

  assert len(root) <= 150
  assert root.startswith('a' * 111)
  assert root.endswith('-001')


def test_get_next_available_root_large_number(tmp_path: Path) -> None:
  from wptgen.utils import get_next_available_root

  used_names: set[str] = set()
  # Manually simulate 999 tests existing
  for n in range(1, 1000):
    used_names.add(f'feat-{n:03d}')

  root = get_next_available_root('feat', tmp_path, used_names)
  assert root == 'feat-1000'

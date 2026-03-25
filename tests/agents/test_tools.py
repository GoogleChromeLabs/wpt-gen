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
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.adk.tools.function_tool import FunctionTool

from wptgen.agents.tools import (
  _parse_test_results,
  _validate_safe_path,
  create_agent_tools,
)
from wptgen.ui import UIProvider


def test_parse_test_results(tmp_path: Path) -> None:
  log_file = tmp_path / 'test.json'
  log_file.write_text(
    json.dumps(
      {
        'action': 'test_status',
        'test': 'test1',
        'status': 'FAIL',
        'subtest': 'sub1',
        'message': 'msg1',
      }
    )
    + '\n'
    + json.dumps({'action': 'test_end', 'test': 'test1', 'status': 'FAIL', 'message': 'msg2'})
    + '\n'
    + json.dumps({'action': 'test_end', 'test': 'test2', 'status': 'PASS'})
    + '\n'
  )
  results = _parse_test_results(str(log_file))
  assert 'test1' in results
  assert 'Test: FAIL - msg2' in results['test1']
  assert "Subtest 'sub1': FAIL - msg1" in results['test1']
  assert 'test2' not in results


def test_validate_safe_path(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()

  safe = _validate_safe_path(Path('foo/bar.txt'), wpt_root)
  assert safe == (wpt_root / 'foo' / 'bar.txt').resolve()

  with pytest.raises(ValueError, match='outside the designated WPT'):
    _validate_safe_path(Path('../outside.txt'), wpt_root)

  with pytest.raises(ValueError, match='outside the designated WPT'):
    _validate_safe_path(Path('/tmp/absolute.txt'), wpt_root)


def test_create_agent_tools(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  tools = create_agent_tools(wpt_root, MagicMock(spec=UIProvider), 'chrome', 'canary')
  assert len(tools) == 14
  assert all(isinstance(t, FunctionTool) for t in tools)

  tools_by_name = {t.name: t for t in tools}

  # test read_file
  read_file = tools_by_name['read_file']
  (wpt_root / 'test.txt').write_text('line1\nline2\nline3\n')
  res = read_file.func(file_path='test.txt')
  assert res == {'status': 'success', 'content': 'line1\nline2\nline3\n'}

  res2 = read_file.func(file_path='test.txt', start_line=2, end_line=2)
  assert res2 == {'status': 'success', 'content': 'line2\n'}

  res3 = read_file.func(file_path='not_found.txt')
  assert res3['status'] == 'error'

  # test write_file
  write_file = tools_by_name['write_file']
  res4 = write_file.func(file_path='new.txt', content='content')
  assert res4 == {'status': 'success'}
  assert (wpt_root / 'new.txt').read_text() == 'content'

  # test search_files
  search_files = tools_by_name['search_files']
  (wpt_root / 'dir1').mkdir()
  (wpt_root / 'dir1' / 'file1.html').touch()
  res5 = search_files.func(directory='dir1', pattern='*.html')
  assert res5['status'] == 'success'
  assert len(res5['files']) == 1
  assert 'file1.html' in res5['files'][0]

  # test delete_file
  delete_file = tools_by_name['delete_file']
  res6 = delete_file.func(file_path='new.txt')
  assert res6 == {'status': 'success'}
  assert not (wpt_root / 'new.txt').exists()

  # test replace_in_file
  replace_in_file = tools_by_name['replace_in_file']
  res7 = replace_in_file.func(file_path='test.txt', old_string='line2', new_string='new_line2')
  assert res7 == {'status': 'success'}
  assert 'new_line2' in (wpt_root / 'test.txt').read_text()

  res8 = replace_in_file.func(file_path='test.txt', old_string='line', new_string='x')
  assert res8['status'] == 'error'
  assert 'multiple times' in res8['error']


def test_search_file_contents(tmp_path: Path) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  (wpt_root / 'dir1').mkdir()
  (wpt_root / 'dir1' / 'file1.txt').write_text('hello world\nfoo bar\n')
  (wpt_root / 'dir1' / 'file2.txt').write_text('test foo\nbar baz\n')

  tools = create_agent_tools(wpt_root, MagicMock(spec=UIProvider), 'chrome', 'canary')
  tools_by_name = {t.name: t for t in tools}
  search_file_contents = tools_by_name['search_file_contents']

  res = search_file_contents.func(directory='dir1', pattern='foo')
  assert res['status'] == 'success'
  assert 'dir1/file1.txt:2:foo bar' in res['search_output']
  assert 'dir1/file2.txt:1:test foo' in res['search_output']

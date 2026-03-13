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

import textwrap
from pathlib import Path

from wptgen.context import find_feature_yaml_files
from wptgen.utils import sync_web_features_yaml


def test_find_feature_yaml_files(tmp_path: Path) -> None:
  yaml_content = textwrap.dedent("""\
        features:
          - name: grid
            files:
              - 'grid.html'
          - name: flex
            files:
              - 'flex.html'
    """)
  yaml_path = tmp_path / 'WEB_FEATURES.yml'
  yaml_path.write_text(yaml_content, encoding='utf-8')

  # Should find grid
  yaml_files = find_feature_yaml_files(str(tmp_path), 'grid')
  assert len(yaml_files) == 1
  assert yaml_files[0] == yaml_path

  # Should find flex
  yaml_files = find_feature_yaml_files(str(tmp_path), 'flex')
  assert len(yaml_files) == 1

  # Should not find non-existent
  yaml_files = find_feature_yaml_files(str(tmp_path), 'popover')
  assert len(yaml_files) == 0


def test_sync_web_features_yaml_success(tmp_path: Path) -> None:
  yaml_content = textwrap.dedent("""\
        features:
          - name: grid
            files:
              - 'old_test.html'
          - name: other
            files:
              - 'other.html'
    """)
  yaml_path = tmp_path / 'WEB_FEATURES.yml'
  yaml_path.write_text(yaml_content, encoding='utf-8')

  new_files = ['new_test_1.html', 'new_test_2.html']
  result = sync_web_features_yaml(yaml_path, 'grid', new_files)

  assert result is True

  updated_content = yaml_path.read_text(encoding='utf-8')
  assert "- 'new_test_1.html'" in updated_content
  assert "- 'new_test_2.html'" in updated_content
  # Check it's in the right place (after old_test.html)
  lines = updated_content.splitlines()
  grid_idx = -1
  for i, line in enumerate(lines):
    if 'name: grid' in line:
      grid_idx = i
      break

  assert grid_idx != -1
  # Ensure new tests are after grid and before other
  found_new = False
  for i in range(grid_idx, len(lines)):
    if 'name: other' in lines[i]:
      break
    if 'new_test_1.html' in lines[i]:
      found_new = True
      break
  if not found_new:
    print(f'DEBUG: updated_content:\n{updated_content}')
  assert found_new


def test_sync_web_features_yaml_empty_list(tmp_path: Path) -> None:
  yaml_content = textwrap.dedent("""\
        features:
          - name: grid
            files: []
    """)
  yaml_path = tmp_path / 'WEB_FEATURES.yml'
  yaml_path.write_text(yaml_content, encoding='utf-8')

  result = sync_web_features_yaml(yaml_path, 'grid', ['new.html'])
  assert result is True

  updated_content = yaml_path.read_text(encoding='utf-8')
  assert "- 'new.html'" in updated_content
  assert '[]' not in updated_content


def test_sync_web_features_yaml_comments_preserved(tmp_path: Path) -> None:
  yaml_content = textwrap.dedent("""\
        # This is a comment at the top
        features:
          - name: grid # Feature comment
            files:
              # List comment
              - 'old.html'
    """)
  yaml_path = tmp_path / 'WEB_FEATURES.yml'
  yaml_path.write_text(yaml_content, encoding='utf-8')

  result = sync_web_features_yaml(yaml_path, 'grid', ['new.html'])
  assert result is True

  updated_content = yaml_path.read_text(encoding='utf-8')
  assert '# This is a comment at the top' in updated_content
  assert '# Feature comment' in updated_content
  assert '# List comment' in updated_content
  assert "- 'new.html'" in updated_content

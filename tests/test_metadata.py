from pathlib import Path

import yaml

from wptgen.metadata import is_path_covered, update_web_features_yml


def test_is_path_covered() -> None:
  assert is_path_covered(Path('foo.html'), ['*.html'])
  assert is_path_covered(Path('sub/foo.html'), ['**/*.html'])
  # Negative patterns
  assert not is_path_covered(Path('foo.html'), ['*.html', '!foo.html'])
  assert is_path_covered(Path('foo.html'), ['*.html', '!bar.html'])
  # Direct match
  assert is_path_covered(Path('sub/test.js'), ['sub/test.js'])


def test_update_web_features_yml_create_new(tmp_path: Path) -> None:
  output_dir = tmp_path

  generated_paths = [tmp_path / 'test1.html', tmp_path / 'sub' / 'test2.html']

  update_web_features_yml(output_dir, 'my_feature', generated_paths)

  yml_file = output_dir / 'WEB_FEATURES.yml'
  assert yml_file.exists()

  with open(yml_file, encoding='utf-8') as f:
    data = yaml.safe_load(f)

  assert 'my_feature' in data['features']
  files = data['features']['my_feature']['files']
  assert 'test1.html' in files
  assert 'sub/test2.html' in files


def test_update_web_features_yml_append_existing(tmp_path: Path) -> None:
  output_dir = tmp_path
  yml_file = output_dir / 'WEB_FEATURES.yml'

  # Pre-existing file
  initial_data = {'features': {'my_feature': {'files': ['existing.html', '**/*.js']}}}
  with open(yml_file, 'w', encoding='utf-8') as f:
    yaml.dump(initial_data, f)

  generated_paths = [
    tmp_path / 'existing.html',  # Already covered explicitly
    tmp_path / 'new_test.html',  # Not covered
    tmp_path / 'script.js',  # Covered by **/*.js
  ]

  update_web_features_yml(output_dir, 'my_feature', generated_paths)

  with open(yml_file, encoding='utf-8') as f:
    data = yaml.safe_load(f)

  files = data['features']['my_feature']['files']
  assert 'existing.html' in files
  assert 'new_test.html' in files
  assert '**/*.js' in files
  assert 'script.js' not in files  # Should not be explicitly added since **/*.js covers it

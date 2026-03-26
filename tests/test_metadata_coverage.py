from pathlib import Path

import yaml

from wptgen.metadata import update_web_features_yml


def test_update_web_features_yml_no_files_key(tmp_path: Path) -> None:
  yml_file = tmp_path / 'WEB_FEATURES.yml'
  yml_file.write_text(yaml.dump({'features': [{'name': 'test-feature'}]}))
  test_html = tmp_path / 'test.html'
  update_web_features_yml(tmp_path, 'test-feature', [test_html])
  content = yaml.safe_load(yml_file.read_text())
  assert content['features']['test-feature']['files'] == ['test.html']

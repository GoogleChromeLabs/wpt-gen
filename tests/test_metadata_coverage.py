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

"""Tests for metadata coverage analysis."""
from pathlib import Path

import yaml

from wptgen.metadata import update_web_features_yml


def test_update_web_features_yml_no_files_key(tmp_path: Path) -> None:
    yml_file = tmp_path / "WEB_FEATURES.yml"
    yml_file.write_text(
        yaml.dump({"features": [{"name": "test-feature"}]}), encoding="utf-8"
    )
    test_html = tmp_path / "test.html"
    update_web_features_yml(tmp_path, "test-feature", [test_html])
    content = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
    assert content["features"][0]["name"] == "test-feature"
    assert content["features"][0]["files"] == ["test.html"]

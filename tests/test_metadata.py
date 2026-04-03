# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
"""Tests for test_metadata.py."""

#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path

import yaml

from wptgen.metadata import is_path_covered, update_web_features_yml


def test_is_path_covered() -> None:
    """Test if a path is covered by a list of glob patterns."""
    assert is_path_covered(Path("foo.html"), ["*.html"])
    assert is_path_covered(Path("sub/foo.html"), ["**/*.html"])
    # Negative patterns
    assert not is_path_covered(Path("foo.html"), ["*.html", "!foo.html"])
    assert is_path_covered(Path("foo.html"), ["*.html", "!bar.html"])
    # Direct match
    assert is_path_covered(Path("sub/test.js"), ["sub/test.js"])


def test_update_web_features_yml_create_new(tmp_path: Path) -> None:
    """Test creating a new WEB_FEATURES.yml file."""
    output_dir = tmp_path

    generated_paths = [tmp_path / "test1.html", tmp_path / "sub" / "test2.html"]

    update_web_features_yml(output_dir, "my_feature", generated_paths)

    yml_file = output_dir / "WEB_FEATURES.yml"
    assert yml_file.exists()

    with open(yml_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert any(f.get("name") == "my_feature" for f in data["features"])
    files = next(f for f in data["features"] if f.get("name") == "my_feature")[
        "files"
    ]
    assert "test1.html" in files
    assert "sub/test2.html" in files


def test_update_web_features_yml_append_existing(tmp_path: Path) -> None:
    """Test appending to an existing WEB_FEATURES.yml file without duplicating covered files."""  # pylint: disable=line-too-long
    output_dir = tmp_path
    yml_file = output_dir / "WEB_FEATURES.yml"

    # Pre-existing file
    initial_data = {
        "features": [
            {"name": "my_feature", "files": ["existing.html", "**/*.js"]}
        ]
    }
    with open(yml_file, "w", encoding="utf-8") as f:
        yaml.dump(initial_data, f)

    generated_paths = [
        tmp_path / "existing.html",  # Already covered explicitly
        tmp_path / "new_test.html",  # Not covered
        tmp_path / "script.js",  # Covered by **/*.js
    ]

    update_web_features_yml(output_dir, "my_feature", generated_paths)

    with open(yml_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    files = next(f for f in data["features"] if f.get("name") == "my_feature")[
        "files"
    ]
    assert "existing.html" in files
    assert "new_test.html" in files
    assert "**/*.js" in files
    assert (
        "script.js" not in files
    )  # Should not be explicitly added since **/*.js covers it

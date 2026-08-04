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
"""Dependency-free WPT file-discovery helpers, shared across the benchmark scripts."""

from __future__ import annotations

import os
from pathlib import Path

# File-extension groups, mirrored from upstream lint.
EXTENSIONS: dict[str, list[str]] = {
    "html": [".html", ".htm"],
    "xhtml": [".xht", ".xhtml"],
    "svg": [".svg"],
    "js": [".js", ".mjs"],
    "python": [".py"],
}
EXTENSIONS["markup"] = (
    EXTENSIONS["html"] + EXTENSIONS["xhtml"] + EXTENSIONS["svg"]
)
EXTENSIONS["js_all"] = EXTENSIONS["markup"] + EXTENSIONS["js"]


def is_wpt_test_file(path: Path) -> bool:
    """Whether a file name matches conditions for a WPT test file.

    Filters out non-test files like .yml, .md, .py, .ini, .headers, and hidden.
    """
    filename = path.name
    suffix = path.suffix.lower()

    if path.is_dir():
        return False
    if suffix in (".yml", ".yaml", ".md", ".py", ".ini", ".headers", ".txt"):
        return False
    if filename in ("MANIFEST", "META.yml", "WEB_FEATURES.yml"):
        return False
    if "-ref." in filename:
        return False
    if filename.startswith("."):
        return False
    return True


def is_manual_test(path: str) -> bool:
    """A test whose filename marks it manual (`-manual` flag before the ext)."""
    name_stem = os.path.basename(path).split(".", 1)[0]
    return name_stem.endswith("-manual")


def is_worker_js(path: str) -> bool:
    """A `.worker.js` test file."""
    return os.path.basename(path).endswith(".worker.js")

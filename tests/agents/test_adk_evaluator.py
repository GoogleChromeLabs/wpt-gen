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
"""Tests for adk_evaluator.py."""

import pytest

pytest.importorskip("google.adk")

from wptgen.agents.adk_evaluator import EVALUATOR_TOOL_ALLOWLIST


def test_evaluator_tool_allowlist_is_pinned() -> None:
    assert EVALUATOR_TOOL_ALLOWLIST == frozenset(
        {
            "read_file",
            "list_directory",
            "search_files",
            "search_file_contents",
            "run_wpt_lint",
        }
    )

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

"""Tests for the coverage audit phase."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wptgen.config import Config
from wptgen.models import WorkflowContext
from wptgen.phases.coverage_audit import (
    combine_audit_responses,
    partition_requirements_xml,
    provide_coverage_report,
)


@pytest.mark.asyncio
async def test_provide_coverage_report(
    mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
    """Test that provide_coverage_report displays the report and does not save any file."""
    context = WorkflowContext(
        feature_id="feat-id", audit_response="Audit markdown"
    )
    mock_config.output_dir = str(tmp_path)

    await provide_coverage_report(context, mock_config, mock_ui)

    expected_path = tmp_path / "feat-id_coverage_audit.md"
    assert not expected_path.exists()
    mock_ui.report_coverage_audit.assert_called_with("Audit markdown")
    mock_ui.confirm.assert_not_called()


def test_partition_requirements_xml() -> None:
    """Test partition logic."""
    # Empty or no tags
    assert not partition_requirements_xml("")
    assert partition_requirements_xml("just text") == ["just text"]

    # Less than threshold
    reqs = (
        '<requirement id="1">A</requirement>\n'
        '<requirement id="2">B</requirement>'
    )
    assert partition_requirements_xml(reqs, max_threshold=2) == [reqs]

    # Even split (4 total, max 2)
    reqs4 = "\n".join(
        f'<requirement id="{i}">{i}</requirement>' for i in range(1, 5)
    )
    parts = partition_requirements_xml(reqs4, max_threshold=2)
    assert len(parts) == 2
    assert 'id="1"' in parts[0]
    assert 'id="2"' in parts[0]
    assert 'id="3"' in parts[1]
    assert 'id="4"' in parts[1]

    # Uneven split: 41 requirements, max 40 -> chunks of 21 and 20
    reqs41 = "\n".join(
        f'<requirement id="{i}">{i}</requirement>' for i in range(1, 42)
    )
    parts41 = partition_requirements_xml(reqs41, max_threshold=40)
    assert len(parts41) == 2
    assert len(re.findall(r"<requirement\b[^>]*>", parts41[0])) == 21
    assert len(re.findall(r"<requirement\b[^>]*>", parts41[1])) == 20
    assert 'id="21"' in parts41[0]
    assert 'id="22"' in parts41[1]

    # Straggler distribution (42 reqs, max 40 -> 21 and 21)
    reqs42 = "\n".join(
        f'<requirement id="{i}">{i}</requirement>' for i in range(1, 43)
    )
    parts42 = partition_requirements_xml(reqs42, max_threshold=40)
    assert len(parts42) == 2
    assert len(re.findall(r"<requirement\b[^>]*>", parts42[0])) == 21
    assert len(re.findall(r"<requirement\b[^>]*>", parts42[1])) == 21


def test_combine_audit_responses() -> None:
    """Test combine audit logic."""
    resp1 = """<status>SATISFIED</status>
<audit_worksheet>
R1: COVERED
</audit_worksheet>"""

    resp2 = """<status>TESTS_NEEDED</status>
<audit_worksheet>
R2: UNCOVERED
</audit_worksheet>
<test_suggestion>Suggestion 1</test_suggestion>"""

    resp3 = """<status>SATISFIED</status>
<audit_worksheet>
R3: COVERED
</audit_worksheet>
<test_suggestion>Suggestion 2</test_suggestion>"""

    combined = combine_audit_responses([resp1, resp2, resp3])

    assert "<status>TESTS_NEEDED</status>" in combined
    assert "R1: COVERED" in combined
    assert "R2: UNCOVERED" in combined
    assert "R3: COVERED" in combined
    assert "<test_suggestion>Suggestion 1</test_suggestion>" in combined
    assert "<test_suggestion>Suggestion 2</test_suggestion>" in combined

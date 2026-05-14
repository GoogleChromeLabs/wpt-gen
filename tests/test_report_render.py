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

"""Tests for report_render.py."""

from wptgen.phases.report_render import (
    MarkdownReportRenderer,
    RequirementAudit,
    SuggestionData,
    parse_audit_worksheet,
    parse_test_suggestions,
)


def test_parse_audit_worksheet_basic() -> None:
    """Test parsing a simple worksheet with mixed results."""
    worksheet = """
    [Category 1]
    R1: Spec requirement 1 -> [COVERED by test1.html]
    R2: Spec requirement 2 -> [UNCOVERED]

    [Category 2]
    R3: Spec requirement 3 -> [COVERED by test2.html, test3.html]
    """

    results = parse_audit_worksheet(worksheet)

    assert len(results) == 3

    # Check R1
    assert results[0].id == "R1"
    assert results[0].category == "Category 1"
    assert results[0].text == "Spec requirement 1"
    assert results[0].status == "COVERED"
    assert results[0].tests == ["test1.html"]

    # Check R2
    assert results[1].id == "R2"
    assert results[1].category == "Category 1"
    assert results[1].text == "Spec requirement 2"
    assert results[1].status == "UNCOVERED"
    assert results[1].tests == []

    # Check R3
    assert results[2].id == "R3"
    assert results[2].category == "Category 2"
    assert results[2].text == "Spec requirement 3"
    assert results[2].status == "COVERED"
    assert results[2].tests == ["test2.html", "test3.html"]


def test_parse_audit_worksheet_uncategorized() -> None:
    """Test parsing when no category is specified."""
    worksheet = "R1: Req text -> [UNCOVERED]"
    results = parse_audit_worksheet(worksheet)

    assert len(results) == 1
    assert results[0].category == "Uncategorized"


def test_parse_test_suggestions_full() -> None:
    """Test parsing full mode suggestions."""
    xml = """
    <test_suggestions>
      <test_suggestion>
        <title>Test Title</title>
        <description>Test Description</description>
        <test_type>JavaScript test</test_type>
        <pre_conditions><![CDATA[<div></div>]]></pre_conditions>
        <steps>
          <step>Step 1</step>
          <step>Step 2</step>
        </steps>
        <expected_result>Success</expected_result>
      </test_suggestion>
    </test_suggestions>
    """

    results = parse_test_suggestions(xml)

    assert len(results) == 1
    assert results[0].title == "Test Title"
    assert results[0].description == "Test Description"
    assert results[0].test_type == "JavaScript test"
    assert results[0].pre_conditions == "<div></div>"
    assert results[0].steps == ["Step 1", "Step 2"]
    assert results[0].expected_result == "Success"


def test_parse_test_suggestions_brief() -> None:
    """Test parsing brief mode suggestions."""
    xml = """
    <test_suggestions>
      <test_suggestion>
        <description>Test Description</description>
      </test_suggestion>
    </test_suggestions>
    """

    results = parse_test_suggestions(xml)

    assert len(results) == 1
    assert results[0].description == "Test Description"
    assert results[0].title is None
    assert results[0].steps == []
    assert results[0].test_type is None


def test_parse_test_suggestions_empty() -> None:
    """Test parsing empty suggestions."""
    xml = "<test_suggestions></test_suggestions>"
    results = parse_test_suggestions(xml)
    assert len(results) == 0


def test_parse_test_suggestions_invalid() -> None:
    """Test parsing invalid XML (missing description)."""
    xml = """
    <test_suggestions>
      <test_suggestion>
        <title>Only Title</title>
      </test_suggestion>
    </test_suggestions>
    """
    results = parse_test_suggestions(xml)
    # Should skip suggestions without description
    assert len(results) == 0


def test_render_basic() -> None:
    """Test rendering with mixed coverage results."""
    renderer = MarkdownReportRenderer()

    audit_rows = [
        RequirementAudit(
            id="R1",
            category="Existence",
            text="Interface must exist",
            status="COVERED",
            tests=["test1.html"],
        ),
        RequirementAudit(
            id="R2",
            category="Common Use Cases",
            text="Basic behavior works",
            status="UNCOVERED",
        ),
    ]

    suggestions = [SuggestionData(description="Add test for basic behavior")]

    report = renderer.render(audit_rows, suggestions)

    # Verify headers are present
    assert "#### 1. Existence" in report
    assert (
        "**Conclusion:** Some test suggestions are available. See below."
        in report
    )
    assert (
        "**Summary of Analysis:** The audit analyzed 2 requirements" in report
    )
    assert "#### 2. Common Use Cases" in report
    assert "### Test Suggestions" in report

    # Verify status mapping
    assert "* **Status:** Covered" in report  # For Existence
    assert "* **Status:** Not Covered" in report  # For Common Use Cases

    # Verify evidence and gaps
    assert "Verified in `test1.html`" in report
    assert "Missing test coverage for: Basic behavior works" in report

    # Verify suggestions are listed
    assert "Add test for basic behavior" in report


def test_render_empty_suggestions() -> None:
    """Test rendering when all requirements are covered."""
    renderer = MarkdownReportRenderer()

    audit_rows = [
        RequirementAudit(
            id="R1",
            category="Existence",
            text="Interface must exist",
            status="COVERED",
            tests=["test1.html"],
        )
    ]

    suggestions: list[SuggestionData] = []

    report = renderer.render(audit_rows, suggestions)

    assert (
        "No test suggestions found. This feature has great test coverage!"
        in report
    )

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

"""Data models and parsers for generating WPT coverage reports."""

import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup


@dataclass
class RequirementAudit:
    """Represents the audit result for a single requirement."""

    id: str
    category: str
    text: str
    status: str  # "COVERED" or "UNCOVERED"
    tests: list[str] = field(default_factory=list)


@dataclass
class SuggestionData:
    """Represents a suggested test blueprint."""

    description: str
    title: str | None = None
    test_type: str | None = None
    pre_conditions: str | None = None
    steps: list[str] = field(default_factory=list)
    expected_result: str | None = None


def parse_audit_worksheet(worksheet_text: str) -> list[RequirementAudit]:
    """Parses the semi-structured audit worksheet text.

    Expected format:
    [Category Name]
    R1: Requirement text -> [COVERED by file.html]
    R2: Requirement text -> [UNCOVERED]
    """
    results = []
    current_category = "Uncategorized"

    # Regex to match lines like "R1: text -> [COVERED by file.html]"
    row_re = re.compile(
        r"^(R\d+):\s*(.*?)\s*->\s*\[(COVERED|UNCOVERED)(?:\s*by\s*(.*))?\]$"
    )

    for line in worksheet_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Check if it's a category header
        if line.startswith("[") and line.endswith("]") and "->" not in line:
            current_category = line[1:-1].strip()
            continue

        match = row_re.match(line)
        if match:
            req_id = match.group(1)
            req_text = match.group(2)
            status = match.group(3)
            tests_str = match.group(4)

            tests = []
            if tests_str:
                # Handle comma-separated list of tests if present
                tests = [t.strip() for t in tests_str.split(",")]

            results.append(
                RequirementAudit(
                    id=req_id,
                    category=current_category,
                    text=req_text,
                    status=status,
                    tests=tests,
                )
            )

    return results


def parse_test_suggestions(suggestions_xml: str) -> list[SuggestionData]:
    """Parses the structured XML test suggestions."""
    results = []
    soup = BeautifulSoup(suggestions_xml, "xml")

    for suggestion in soup.find_all("test_suggestion"):
        description = suggestion.find("description")
        if not description:
            continue

        title = suggestion.find("title")
        test_type = suggestion.find("test_type")
        pre_conditions = suggestion.find("pre_conditions")
        expected_result = suggestion.find("expected_result")

        steps = []
        steps_tag = suggestion.find("steps")
        if steps_tag:
            steps = [step.text.strip() for step in steps_tag.find_all("step")]

        results.append(
            SuggestionData(
                description=description.text.strip(),
                title=title.text.strip() if title else None,
                test_type=test_type.text.strip() if test_type else None,
                pre_conditions=(
                    pre_conditions.text.strip() if pre_conditions else None
                ),
                steps=steps,
                expected_result=(
                    expected_result.text.strip() if expected_result else None
                ),
            )
        )

    return results

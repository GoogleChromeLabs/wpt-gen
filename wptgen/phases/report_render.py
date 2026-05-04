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
from typing import Any
from bs4 import BeautifulSoup
from jinja2 import Environment, PackageLoader, select_autoescape


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


class MarkdownReportRenderer:
    """Renders parsed audit data into a specific Markdown format."""

    def __init__(self) -> None:
        self.env = Environment(
            loader=PackageLoader("wptgen", "templates"),
            autoescape=select_autoescape(),
        )
        self.template = self.env.get_template("report_render.jinja")

    def render(
        self,
        audit_rows: list[RequirementAudit],
        suggestions: list[SuggestionData],
    ) -> str:
        """Renders the report based on structured data."""
        data = self._prepare_data(audit_rows, suggestions)
        return self.template.render(**data)

    def _prepare_data(
        self,
        audit_rows: list[RequirementAudit],
        suggestions: list[SuggestionData],
    ) -> dict[str, Any]:
        """Groups and maps data into the structure expected by the template."""
        categories: dict[str, dict[str, Any]] = {
            "existence": {"status": "Not Covered", "records": []},
            "common_use_cases": {"status": "Not Covered", "records": []},
            "error_scenarios": {"status": "Not Covered", "records": []},
            "invalidation": {"status": "Not Covered", "records": []},
            "integration": {"status": "Not Covered", "records": []},
        }

        def map_category(cat: str) -> str:
            cat_lower = cat.lower()
            if "existence" in cat_lower:
                return "existence"
            if "common" in cat_lower or "use case" in cat_lower:
                return "common_use_cases"
            if "error" in cat_lower or "exception" in cat_lower:
                return "error_scenarios"
            if "invalidation" in cat_lower or "dynamic" in cat_lower:
                return "invalidation"
            if "integration" in cat_lower or "interact" in cat_lower:
                return "integration"
            return "common_use_cases"

        for row in audit_rows:
            key = map_category(row.category)
            evidence = "None"
            gaps = "None"
            if row.status == "COVERED":
                evidence = (
                    f'Verified in `{", ".join(row.tests)}`'
                    if row.tests
                    else "Verified"
                )
            else:
                gaps = f"Missing test coverage for: {row.text}"

            categories[key]["records"].append(
                {"requirement": row.text, "evidence": evidence, "gaps": gaps}
            )

        for _, cat_data in categories.items():
            if not cat_data["records"]:
                cat_data["status"] = "N/A"
                continue

            all_covered = all(
                item["gaps"] == "None" for item in cat_data["records"]
            )
            all_uncovered = all(
                item["evidence"] == "None" for item in cat_data["records"]
            )

            if all_covered:
                cat_data["status"] = "Covered"
            elif all_uncovered:
                cat_data["status"] = "Not Covered"
            else:
                cat_data["status"] = "Partially Covered"

        sug_data: dict[str, Any] = {
            "status": "GAPS_FOUND" if suggestions else "SATISFIED",
            "existence": [],
            "common_use_cases": [],
            "error_scenarios": [],
            "invalidation": [],
            "integration": [],
        }

        for sug in suggestions:
            desc_lower = sug.description.lower()
            if "existence" in desc_lower:
                sug_data["existence"].append(sug.description)
            elif "error" in desc_lower or "exception" in desc_lower:
                sug_data["error_scenarios"].append(sug.description)
            elif "invalidation" in desc_lower or "dynamic" in desc_lower:
                sug_data["invalidation"].append(sug.description)
            elif "integration" in desc_lower or "interact" in desc_lower:
                sug_data["integration"].append(sug.description)
            else:
                sug_data["common_use_cases"].append(sug.description)

        return {
            "existence": categories["existence"],
            "common_use_cases": categories["common_use_cases"],
            "error_scenarios": categories["error_scenarios"],
            "invalidation": categories["invalidation"],
            "integration": categories["integration"],
            "suggestions": sug_data,
        }

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

from dataclasses import dataclass, field
from enum import Enum


class TestType(Enum):
  JAVASCRIPT = 'JavaScript Test'
  REFTEST = 'Reftest'
  CRASHTEST = 'Crashtest'


# Map test types to their corresponding style guide resource files
STYLE_GUIDE_MAP = {
  TestType.JAVASCRIPT: 'javascript_html_style_guide.md',
  TestType.REFTEST: 'reftest_style_guide.md',
  TestType.CRASHTEST: 'crashtest_style_guide.md',
}


@dataclass
class WebFeatureMetadata:
  name: str
  description: str
  specs: list[str]


@dataclass
class WPTContext:
  """Holds the results of a local WPT content and dependency fetch operation."""

  test_contents: dict[str, str] = field(default_factory=dict)
  dependency_contents: dict[str, str] = field(default_factory=dict)
  test_to_deps: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class WorkflowContext:
  """Maintains the state of the WPT generation workflow."""

  feature_id: str
  metadata: WebFeatureMetadata | None = None
  spec_contents: str | None = None
  wpt_context: WPTContext | None = None
  requirements_xml: str | None = None
  audit_response: str | None = None
  suggestions: list[str] = field(default_factory=list)
  approved_suggestions_xml: list[str] = field(default_factory=list)
  mdn_contents: list[str] | None = None

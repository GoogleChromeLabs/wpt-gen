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

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class WorkflowPhase(str, Enum):
  CONTEXT_ASSEMBLY = 'context_assembly'
  REQUIREMENTS_EXTRACTION = 'requirements_extraction'
  COVERAGE_AUDIT = 'coverage_audit'
  GENERATION = 'generation'
  EVALUATION = 'evaluation'
  EXECUTION = 'execution'


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

REQUIREMENT_CATEGORIES = [
  ('Existence', "Rules defining the feature's surface area (interfaces, methods, properties)."),
  (
    'Common Use Cases',
    'Rules defining successful behaviors, processing models, and realistic "happy paths."',
  ),
  ('Error Scenarios', 'Rules defining error conditions, thrown exceptions, and invalid states.'),
  ('Invalidation', 'Rules regarding caching, state changes, and dynamic updates, if any.'),
  (
    'Integration',
    'Rules defining mandatory interactions with other platform features, if any.',
  ),
]


@dataclass
class WebFeatureMetadata:
  name: str
  description: str
  specs: list[str]

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> 'WebFeatureMetadata':
    return cls(**data)


@dataclass
class WPTContext:
  """Holds the results of a local WPT content and dependency fetch operation."""

  test_contents: dict[str, str] = field(default_factory=dict)
  dependency_contents: dict[str, str] = field(default_factory=dict)
  test_to_deps: dict[str, set[str]] = field(default_factory=dict)

  def to_dict(self) -> dict[str, Any]:
    data = asdict(self)
    # Convert sets to lists for JSON serialization
    data['test_to_deps'] = {k: list(v) for k, v in self.test_to_deps.items()}
    return data

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> 'WPTContext':
    # Convert lists back to sets
    if 'test_to_deps' in data:
      data['test_to_deps'] = {k: set(v) for k, v in data['test_to_deps'].items()}
    return cls(**data)


@dataclass
class WorkflowContext:
  """Maintains the state of the WPT generation workflow."""

  feature_id: str
  metadata: WebFeatureMetadata | None = None
  spec_contents: dict[str, str] | None = None
  wpt_context: WPTContext | None = None
  requirements_xml: str | None = None
  audit_response: str | None = None
  suggestions: list[str] = field(default_factory=list)
  approved_suggestions_xml: list[str] = field(default_factory=list)
  mdn_contents: list[str] | None = None
  generated_tests: list[tuple[Path, str, str]] | None = None

  def to_dict(self) -> dict[str, Any]:
    data = {
      'feature_id': self.feature_id,
      'metadata': self.metadata.to_dict() if self.metadata else None,
      'spec_contents': self.spec_contents,
      'wpt_context': self.wpt_context.to_dict() if self.wpt_context else None,
      'requirements_xml': self.requirements_xml,
      'audit_response': self.audit_response,
      'suggestions': self.suggestions,
      'approved_suggestions_xml': self.approved_suggestions_xml,
      'mdn_contents': self.mdn_contents,
      'generated_tests': (
        [(str(p), c, s) for p, c, s in self.generated_tests] if self.generated_tests else None
      ),
    }
    return data

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> 'WorkflowContext':
    metadata = WebFeatureMetadata.from_dict(data['metadata']) if data.get('metadata') else None
    wpt_context = WPTContext.from_dict(data['wpt_context']) if data.get('wpt_context') else None
    generated_tests = None
    if data.get('generated_tests'):
      generated_tests = [(Path(p), c, s) for p, c, s in data['generated_tests']]

    spec_contents = data.get('spec_contents')
    if isinstance(spec_contents, str):
      # Fallback for old cache format
      spec_url = metadata.specs[0] if metadata and metadata.specs else 'unknown'
      spec_contents = {spec_url: spec_contents}

    return cls(
      feature_id=data['feature_id'],
      metadata=metadata,
      spec_contents=spec_contents,
      wpt_context=wpt_context,
      requirements_xml=data.get('requirements_xml'),
      audit_response=data.get('audit_response'),
      suggestions=data.get('suggestions', []),
      approved_suggestions_xml=data.get('approved_suggestions_xml', []),
      mdn_contents=data.get('mdn_contents'),
      generated_tests=generated_tests,
    )

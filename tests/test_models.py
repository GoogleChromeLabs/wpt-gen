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

from typing import Any

from wptgen.models import WorkflowContext


def test_workflow_context_from_dict_legacy_spec_contents() -> None:
  data: dict[str, Any] = {
    'feature_id': 'mock_feature',
    'metadata': {'name': 'Mock Feature', 'description': 'Mock', 'specs': ['https://mock.spec']},
    'spec_contents': 'Legacy spec content string',
    'wpt_context': None,
    'requirements_xml': None,
    'audit_response': None,
    'suggestions': [],
    'approved_suggestions_xml': [],
    'mdn_contents': None,
    'generated_tests': None,
  }
  context = WorkflowContext.from_dict(data)
  assert context.spec_contents == {'https://mock.spec': 'Legacy spec content string'}


def test_workflow_context_from_dict_legacy_spec_contents_no_metadata() -> None:
  data: dict[str, Any] = {
    'feature_id': 'mock_feature',
    'metadata': None,
    'spec_contents': 'Legacy spec content string',
    'wpt_context': None,
    'requirements_xml': None,
    'audit_response': None,
    'suggestions': [],
    'approved_suggestions_xml': [],
    'mdn_contents': None,
    'generated_tests': None,
  }
  context = WorkflowContext.from_dict(data)
  assert context.spec_contents == {'unknown': 'Legacy spec content string'}

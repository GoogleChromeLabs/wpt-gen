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

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent.parent / 'wptgen' / 'templates'


def test_coverage_audit_system_template_brief() -> None:
  env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
  template = env.get_template('coverage_audit_system.jinja')

  # Test with brief_suggestions=True
  rendered_brief = template.render(brief_suggestions=True, spec_urls=['https://example.com/spec'])
  assert '<title>' not in rendered_brief
  assert '<description>' in rendered_brief
  assert '<test_type>' not in rendered_brief
  assert '<pre_conditions>' not in rendered_brief
  assert '<steps>' not in rendered_brief
  assert '<expected_result>' not in rendered_brief
  assert '<spec_url>https://example.com/spec</spec_url>' not in rendered_brief

  # Test with brief_suggestions=False
  rendered_full = template.render(brief_suggestions=False)
  assert '<title>' in rendered_full
  assert '<description>' in rendered_full
  assert '<test_type>' in rendered_full
  assert '<pre_conditions>' in rendered_full
  assert '<steps>' in rendered_full
  assert '<expected_result>' in rendered_full

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
from unittest.mock import MagicMock

import pytest
from jinja2 import Environment

from wptgen.config import Config
from wptgen.models import WorkflowContext, WPTContext
from wptgen.phases.coverage_audit import run_coverage_audit


@pytest.fixture
def mock_ui() -> MagicMock:
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  return Config(
    provider='test',
    default_model='test-model',
    api_key='test-key',
    wpt_path=str(tmp_path),
    categories={},
    phase_model_mapping={},
  )


@pytest.mark.asyncio
async def test_run_coverage_audit_token_limit_exceeded(
  mock_config: Config, mock_ui: MagicMock
) -> None:
  wpt_context = WPTContext()
  context = WorkflowContext(
    feature_id='test',
    requirements_xml='<requirements><requirement id="R1">Test requirement</requirement></requirements>',
    wpt_context=wpt_context,
  )

  mock_llm = MagicMock()
  mock_llm.prompt_exceeds_input_token_limit.return_value = True

  jinja_env = MagicMock(spec=Environment)
  mock_template = MagicMock()
  mock_template.render.return_value = 'Rendered Prompt'
  jinja_env.get_template.return_value = mock_template

  result = await run_coverage_audit(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert result is None
  mock_ui.error.assert_called_once_with('This test suite to too large to audit.')


def test_combine_audit_responses_all_satisfied() -> None:
  from wptgen.phases.coverage_audit import combine_audit_responses

  responses = [
    '<status>SATISFIED</status>\n<audit_worksheet>W1</audit_worksheet>',
    '<status>SATISFIED</status>\n<audit_worksheet>W2</audit_worksheet>',
  ]
  result = combine_audit_responses(responses)
  assert '<status>SATISFIED</status>' in result
  assert '<audit_worksheet>\nW1\nW2\n</audit_worksheet>' in result
  assert 'test_suggestions' not in result


def test_combine_audit_responses_with_suggestions() -> None:
  from wptgen.phases.coverage_audit import combine_audit_responses

  responses = [
    '<status>SATISFIED</status>\n<audit_worksheet>W1</audit_worksheet>',
    '<audit_worksheet>W2</audit_worksheet>\n<test_suggestions>\n<test_suggestion>T1</test_suggestion>\n</test_suggestions>',
  ]
  result = combine_audit_responses(responses)
  assert '<status>TESTS_NEEDED</status>' in result
  assert '<audit_worksheet>\nW1\nW2\n</audit_worksheet>' in result
  assert '<test_suggestions>\n<test_suggestion>T1</test_suggestion>\n</test_suggestions>' in result


@pytest.mark.asyncio
async def test_run_coverage_audit_single_partition(
  mocker: MagicMock, mock_config: Config, mock_ui: MagicMock
) -> None:
  wpt_context = WPTContext()
  context = WorkflowContext(
    feature_id='test',
    requirements_xml='<requirements><requirement id="R1">Test requirement</requirement></requirements>',
    wpt_context=wpt_context,
  )

  mock_llm = MagicMock()
  mock_llm.prompt_exceeds_input_token_limit.return_value = False

  jinja_env = MagicMock(spec=Environment)
  mock_template = MagicMock()
  mock_template.render.return_value = 'Rendered Prompt'
  jinja_env.get_template.return_value = mock_template

  mocker.patch('wptgen.phases.coverage_audit.confirm_prompts')
  mocker.patch(
    'wptgen.phases.coverage_audit.generate_safe',
    return_value='<status>SATISFIED</status>\n<audit_worksheet>W1</audit_worksheet>',
  )

  result = await run_coverage_audit(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert result is not None
  assert '<status>SATISFIED</status>' in result


@pytest.mark.asyncio
async def test_run_coverage_audit_multiple_partitions(
  mocker: MagicMock, mock_config: Config, mock_ui: MagicMock
) -> None:
  wpt_context = WPTContext()
  reqs = ''.join([f'<requirement id="R{i}">T</requirement>' for i in range(50)])
  context = WorkflowContext(
    feature_id='test',
    requirements_xml=f'<requirements>{reqs}</requirements>',
    wpt_context=wpt_context,
  )

  mock_llm = MagicMock()
  mock_llm.prompt_exceeds_input_token_limit.return_value = False

  jinja_env = MagicMock(spec=Environment)
  mock_template = MagicMock()
  mock_template.render.return_value = 'Rendered Prompt'
  jinja_env.get_template.return_value = mock_template

  mocker.patch('wptgen.phases.coverage_audit.confirm_prompts')
  mocker.patch(
    'wptgen.phases.coverage_audit.generate_safe',
    return_value='<status>SATISFIED</status>\n<audit_worksheet>W1</audit_worksheet>',
  )

  result = await run_coverage_audit(context, mock_config, mock_llm, mock_ui, jinja_env)

  assert result is not None
  assert 'W1\nW1' in result


@pytest.mark.asyncio
async def test_provide_coverage_report_save_error(
  mocker: MagicMock, mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  from wptgen.phases.coverage_audit import provide_coverage_report

  mock_config.output_dir = str(tmp_path)
  context = WorkflowContext(feature_id='test', audit_response='Mock audit response')
  mock_ui.confirm.return_value = True

  mocker.patch('pathlib.Path.write_text', side_effect=PermissionError('Mock write error'))

  await provide_coverage_report(context, mock_config, mock_ui)

  mock_ui.error.assert_called_with('Error saving file: Mock write error')


def test_partition_requirements_xml_empty() -> None:
  from wptgen.phases.coverage_audit import partition_requirements_xml

  assert partition_requirements_xml('') == []


def test_partition_requirements_xml_no_matches() -> None:
  from wptgen.phases.coverage_audit import partition_requirements_xml

  assert partition_requirements_xml('<foo></foo>') == ['<foo></foo>']
  assert partition_requirements_xml('   ') == []


@pytest.mark.asyncio
async def test_provide_coverage_report_save_success(
  mocker: MagicMock, mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  from wptgen.phases.coverage_audit import provide_coverage_report

  mock_config.output_dir = str(tmp_path)
  context = WorkflowContext(feature_id='test', audit_response='Mock audit response')
  mock_ui.confirm.return_value = True

  await provide_coverage_report(context, mock_config, mock_ui)

  mock_ui.success.assert_called_with(f'Saved: {(tmp_path / "test_coverage_audit.md").absolute()}')

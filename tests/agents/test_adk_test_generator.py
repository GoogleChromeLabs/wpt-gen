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

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from wptgen.agents.adk_test_generator import generate_test_with_adk
from wptgen.config import Config
from wptgen.models import TestType as WPTTestType
from wptgen.models import WorkflowContext


@pytest.mark.asyncio
async def test_generate_test_with_adk(tmp_path: Path, mocker: MagicMock) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()

  # Create the file we pretend the agent generated
  output_dir = wpt_root / 'output'
  output_dir.mkdir()
  test_file = output_dir / 'my-feature-1.html'
  test_file.write_text('<!DOCTYPE html>\n<title>Test</title>', encoding='utf-8')

  # Mock the ADK Runner to simulate the agent calling the completion tool
  mock_runner_cls = mocker.patch('wptgen.agents.adk_test_generator.Runner')
  mock_runner_instance = mock_runner_cls.return_value

  async def mock_run_async(*args: Any, **kwargs: Any) -> Any:
    # In actual ADK, the tools are attached to the agent which is passed to Runner
    agent = mock_runner_cls.call_args.kwargs['agent']
    completion_tool = next(
      t for t in agent.tools if t.func.__name__ == 'report_generation_complete'
    )

    # Simulate the LLM calling the tool with the generated path
    completion_tool.func([str(test_file)])

    # Yield an empty mock event to simulate the stream finishing
    yield MagicMock()

  mock_runner_instance.run_async = mock_run_async

  # Mock environment setup to avoid needing real API keys during tests
  mocker.patch('wptgen.agents.adk_test_generator.setup_adk_environment', return_value='gemini-mock')
  mocker.patch.dict(os.environ, {'GOOGLE_API_KEY': 'fake'}, clear=True)

  config = Config(
    provider='google',
    default_model='gemini',
    api_key='fake',
    wpt_path=str(wpt_root),
    output_dir=str(output_dir),
    categories={},
    phase_model_mapping={},
  )

  context = WorkflowContext(
    feature_id='my-feature',
    spec_contents={'spec1': 'fake spec'},
    metadata=None,
    audit_response='fake audit',
  )

  mock_jinja_env = MagicMock()
  mock_system_template = MagicMock()
  mock_prompt_template = MagicMock()
  mock_system_template.render.return_value = 'Mock System Instruction'
  mock_prompt_template.render.return_value = 'Mock Prompt'

  def mock_get_template(name: str) -> MagicMock:
    if name == 'adk_test_generator_system.jinja':
      return mock_system_template
    return mock_prompt_template

  mock_jinja_env.get_template.side_effect = mock_get_template

  mock_ui = MagicMock()
  results = await generate_test_with_adk(
    suggestion_xml='<test_suggestion></test_suggestion>',
    root_name='my-feature-1',
    test_type_enum=WPTTestType.JAVASCRIPT,
    context=context,
    config=config,
    jinja_env=mock_jinja_env,
    ui=mock_ui,
    wpt_style_guide='Mock guide',
    test_type_guide='Mock JS guide',
  )

  assert len(results) == 1
  assert results[0][0] == test_file.resolve()
  assert '<!DOCTYPE html>' in results[0][1]
  assert results[0][2] == '<test_suggestion></test_suggestion>'

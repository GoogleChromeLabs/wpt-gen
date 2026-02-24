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

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.engine import WPTGenEngine


@pytest.fixture
def engine(mocker: MockerFixture) -> WPTGenEngine:
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  mock_config = MagicMock()
  mock_config.provider = 'gemini'
  mock_config.model = 'gemini-pro'
  mock_config.api_key = 'fake-key'
  mock_config.wpt_path = '/fake/wpt'
  mock_config.yes_tokens = False
  mock_config.suggestions_only = False
  mock_config.cache_path = '/tmp/cache'

  mock_llm = MagicMock()
  mock_llm.generate_content.return_value = 'Mocked LLM Response'
  mock_llm.count_tokens.return_value = 100

  with patch('wptgen.engine.get_llm_client', return_value=mock_llm):
    return WPTGenEngine(mock_config)


@pytest.mark.asyncio
async def test_unified_flow_fits_in_context(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Verify that the unified flow is used when the prompt fits in the context window."""
  # Mock context assembly
  mock_metadata = MagicMock()
  mock_metadata.name = 'Test Feature'
  mock_metadata.description = 'Test Description'
  mock_metadata.specs = ['http://spec']

  mock_wpt_context = MagicMock()
  mock_wpt_context.test_contents = {}
  mock_wpt_context.dependency_contents = {}

  context = {
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': mock_wpt_context,
  }
  mocker.patch.object(engine, '_phase_context_assembly', return_value=context)

  # Mock token check to say it FITS (prompt_exceeds_input_token_limit returns False)
  cast(MagicMock, engine.llm.prompt_exceeds_input_token_limit).return_value = False

  # Mock the phases
  mock_unified = mocker.patch.object(
    engine,
    '_phase_unified_suggestions',
    return_value='<test_suggestion>...</test_suggestion>',
  )
  mock_analysis = mocker.patch.object(engine, '_phase_requirements_analysis')
  mock_suggestions = mocker.patch.object(engine, '_phase_test_suggestions')
  mocker.patch.object(engine, '_phase_test_generation', return_value=None)

  await engine._run_async_workflow('feat-id')

  # Should use unified flow
  mock_unified.assert_called_once()
  # Verify system prompt was passed (rendered from template)
  args, kwargs = mock_unified.call_args
  assert 'system_instruction' in kwargs
  assert 'SYSTEM ROLE' in kwargs['system_instruction']

  # Should NOT use multi-step flow
  mock_analysis.assert_not_called()
  mock_suggestions.assert_not_called()


@pytest.mark.asyncio
async def test_unified_flow_exceeds_context(engine: WPTGenEngine, mocker: MockerFixture) -> None:
  """Verify that the multi-step flow is used as fallback when the prompt exceeds the context window."""
  # Mock context assembly
  mock_metadata = MagicMock()
  mock_metadata.name = 'Test Feature'
  mock_metadata.description = 'Test Description'
  mock_metadata.specs = ['http://spec']

  mock_wpt_context = MagicMock()
  mock_wpt_context.test_contents = {}
  mock_wpt_context.dependency_contents = {}

  context = {
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': mock_wpt_context,
  }
  mocker.patch.object(engine, '_phase_context_assembly', return_value=context)

  # Mock token check to say it EXCEEDS (prompt_exceeds_input_token_limit returns True)
  cast(MagicMock, engine.llm.prompt_exceeds_input_token_limit).return_value = True

  # Mock the phases
  mock_unified = mocker.patch.object(engine, '_phase_unified_suggestions')
  mock_analysis = mocker.patch.object(
    engine, '_phase_requirements_analysis', return_value=('spec', 'test')
  )
  mock_suggestions = mocker.patch.object(
    engine,
    '_phase_test_suggestions',
    return_value='<test_suggestion>...</test_suggestion>',
  )
  mocker.patch.object(engine, '_phase_test_generation', return_value=None)

  await engine._run_async_workflow('feat-id')

  # Should NOT use unified flow
  mock_unified.assert_not_called()

  # Should use multi-step flow
  mock_analysis.assert_called_once()
  mock_suggestions.assert_called_once()


@pytest.mark.asyncio
async def test_phase_unified_suggestions_execution(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verify that _phase_unified_suggestions correctly calls the LLM with system prompt."""
  prompt = 'Unified Prompt'
  system_prompt = 'System Prompt'

  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  mock_generate = mocker.patch.object(engine, '_generate_safe', return_value='Suggestions')

  # Test without system prompt
  await engine._phase_unified_suggestions(prompt)
  mock_generate.assert_called_with(
    prompt, 'Consolidated Suggestions', system_instruction=None, temperature=0.0
  )

  # Test with system prompt
  result = await engine._phase_unified_suggestions(prompt, system_instruction=system_prompt)
  assert result == 'Suggestions'
  mock_generate.assert_called_with(
    prompt, 'Consolidated Suggestions', system_instruction=system_prompt, temperature=0.0
  )


@pytest.mark.asyncio
async def test_phase_unified_suggestions_failure(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verify that _phase_unified_suggestions handles failure gracefully."""
  prompt = 'Unified Prompt'

  mocker.patch.object(engine, '_confirm_prompts', return_value=None)
  # Simulate failure (empty string return from _generate_safe)
  mocker.patch.object(engine, '_generate_safe', return_value='')

  result = await engine._phase_unified_suggestions(prompt)

  assert result is None

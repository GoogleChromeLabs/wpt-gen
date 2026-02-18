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
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.engine import WPTGenEngine


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a basic Config object with a temporary cache path."""
  return Config(
    provider='llmbargainbin',
    model='discountmodel',
    api_key='fake-key',
    wpt_path='/fake/wpt',
    yes_tokens=True,
    cache_path=str(tmp_path / '.wpt-gen-cache'),
  )


@pytest.fixture
def mock_llm() -> MagicMock:
  """Provides a mocked LLM client."""
  llm = MagicMock()
  llm.generate_content.return_value = 'Mocked LLM Response'
  llm.count_tokens.return_value = 100
  llm.prompt_exceeds_input_token_limit.return_value = False
  return llm


@pytest.fixture
def engine(mock_config: Config, mock_llm: MagicMock) -> WPTGenEngine:
  """Provides a WPTGenEngine instance with a mocked LLM client."""
  with patch('wptgen.engine.get_llm_client', return_value=mock_llm):
    return WPTGenEngine(mock_config)


@pytest.mark.asyncio
async def test_requirements_analysis_cache_miss(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 generates and saves cache on a miss."""
  context = {
    'metadata': MagicMock(name='Feat', description='Desc', specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }

  # Mock LLM to return distinct responses based on prompt content.
  def llm_side_effect(prompt: str) -> str:
    if '<spec_document>' in prompt:
      return 'New Spec Synthesis'
    return 'New Test Analysis'

  mock_llm.generate_content.side_effect = llm_side_effect

  # Mock Confirm.ask to return True if called
  # (though it shouldn't be for cache check if file doesn't exist).
  mock_confirm_ask = mocker.patch('wptgen.engine.Confirm.ask', return_value=True)

  web_feature_id = 'test-feat'
  result = await engine._phase_requirements_analysis(web_feature_id, context)

  assert result == ('New Spec Synthesis', 'New Test Analysis')

  # Verify cache file was created
  cache_file = engine.spec_synthesis_cache_dir / f'{web_feature_id}.md'
  assert cache_file.exists()
  assert cache_file.read_text() == 'New Spec Synthesis'

  # Confirm.ask should NOT have been called for cache because file didn't exist
  # Wait, Confirm.ask is also used in _confirm_prompts, but we set yes_tokens=True
  mock_confirm_ask.assert_not_called()


@pytest.mark.asyncio
async def test_requirements_analysis_cache_hit_accept(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 uses cached synthesis when user accepts."""
  web_feature_id = 'cached-feat'
  cache_file = engine.spec_synthesis_cache_dir / f'{web_feature_id}.md'
  cache_file.write_text('Cached Spec Synthesis')

  context = {
    'metadata': MagicMock(name='Feat', description='Desc', specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }

  # User accepts cache
  mock_confirm_ask = mocker.patch('wptgen.engine.Confirm.ask', return_value=True)
  # Only Test Analysis should be generated
  mock_llm.generate_content.return_value = 'New Test Analysis'

  result = await engine._phase_requirements_analysis(web_feature_id, context)

  assert result == ('Cached Spec Synthesis', 'New Test Analysis')

  # LLM should only have been called once (for Test Analysis).
  assert mock_llm.generate_content.call_count == 1
  mock_confirm_ask.assert_called_once_with('Use cached Spec Synthesis?')


@pytest.mark.asyncio
async def test_requirements_analysis_cache_hit_reject(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 regenerates synthesis when user rejects cache."""
  web_feature_id = 'rejected-cache-feat'
  cache_file = engine.spec_synthesis_cache_dir / f'{web_feature_id}.md'
  cache_file.write_text('Old Cached Spec Synthesis')

  context = {
    'metadata': MagicMock(name='Feat', description='Desc', specs=['http://spec']),
    'spec_contents': 'spec',
    'wpt_context': MagicMock(),
  }

  # User rejects cache
  mocker.patch('wptgen.engine.Confirm.ask', return_value=False)

  # Both should be generated
  def llm_side_effect(prompt: str) -> str:
    if '<spec_document>' in prompt:
      return 'New Spec Synthesis'
    return 'New Test Analysis'

  mock_llm.generate_content.side_effect = llm_side_effect

  result = await engine._phase_requirements_analysis(web_feature_id, context)

  assert result == ('New Spec Synthesis', 'New Test Analysis')

  # LLM should have been called twice.
  assert mock_llm.generate_content.call_count == 2

  # Cache file should be updated.
  assert cache_file.read_text() == 'New Spec Synthesis'

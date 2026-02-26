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
async def test_requirements_cache_miss(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 generates and saves cache on a miss."""
  mock_metadata = MagicMock()
  mock_metadata.name = 'Feat'
  mock_metadata.description = 'Desc'
  mock_metadata.specs = ['http://spec']

  context = {
    'feature_id': 'test-feat',
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': MagicMock(),
  }

  mock_llm.generate_content.return_value = '<requirements_list>New Requirements</requirements_list>'
  mocker.patch('wptgen.engine.Confirm.ask', return_value=True)
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)

  result = await engine._phase_requirements_extraction(context)

  assert result == '<requirements_list>New Requirements</requirements_list>'

  # Verify cache file was created
  cache_file = engine.cache_dir / 'test-feat__requirements.xml'
  assert cache_file.exists()
  assert cache_file.read_text() == '<requirements_list>New Requirements</requirements_list>'


@pytest.mark.asyncio
async def test_requirements_cache_hit_accept(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 uses cached requirements when user accepts."""
  web_feature_id = 'cached-feat'
  cache_file = engine.cache_dir / f'{web_feature_id}__requirements.xml'
  cache_file.write_text('<requirements_list>Cached Requirements</requirements_list>')

  context = {
    'feature_id': web_feature_id,
    'metadata': MagicMock(),
    'wpt_context': MagicMock(),
  }

  # User accepts cache
  mock_confirm_ask = mocker.patch('wptgen.engine.Confirm.ask', return_value=True)

  result = await engine._phase_requirements_extraction(context)

  assert result == '<requirements_list>Cached Requirements</requirements_list>'

  # LLM should NOT have been called (for extraction).
  assert mock_llm.generate_content.call_count == 0
  mock_confirm_ask.assert_called_once_with('Use cached requirements?')


@pytest.mark.asyncio
async def test_requirements_cache_hit_reject(
  engine: WPTGenEngine, mock_llm: MagicMock, mocker: MockerFixture
) -> None:
  """Verify that Phase 2 regenerates requirements when user rejects cache."""
  web_feature_id = 'rejected-cache-feat'
  cache_file = engine.cache_dir / f'{web_feature_id}__requirements.xml'
  cache_file.write_text('<requirements_list>Old Cached Requirements</requirements_list>')

  mock_metadata = MagicMock()
  mock_metadata.name = 'Feat'
  mock_metadata.description = 'Desc'
  mock_metadata.specs = ['http://spec']

  context = {
    'feature_id': web_feature_id,
    'metadata': mock_metadata,
    'spec_contents': 'spec content',
    'wpt_context': MagicMock(),
  }

  # User rejects cache
  mocker.patch('wptgen.engine.Confirm.ask', return_value=False)
  mocker.patch.object(engine, '_confirm_prompts', return_value=None)

  mock_llm.generate_content.return_value = '<requirements_list>New Requirements</requirements_list>'

  result = await engine._phase_requirements_extraction(context)

  assert result == '<requirements_list>New Requirements</requirements_list>'

  # LLM should have been called once.
  assert mock_llm.generate_content.call_count == 1

  # Cache file should be updated.
  assert cache_file.read_text() == '<requirements_list>New Requirements</requirements_list>'

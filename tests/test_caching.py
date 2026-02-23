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

from wptgen.config import Config
from wptgen.models import WebFeatureMetadata, WorkflowContext
from wptgen.phases.requirements_extraction import run_requirements_extraction


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
def mock_ui() -> MagicMock:
  ui = MagicMock()
  ui.status.return_value.__enter__.return_value = None
  return ui


@pytest.mark.asyncio
async def test_requirements_cache_miss(
  mock_config: Config, mock_llm: MagicMock, mock_ui: MagicMock, tmp_path: Path
) -> None:
  """Verify that requirements extraction generates and saves cache on a miss."""
  metadata = WebFeatureMetadata(name='Feat', description='Desc', specs=['http://spec'])
  context = WorkflowContext(
    feature_id='test-feat',
    metadata=metadata,
    spec_contents='spec content',
  )
  cache_dir = tmp_path / 'cache'
  cache_dir.mkdir()

  mock_llm.generate_content.return_value = '<requirements_list>New Requirements</requirements_list>'
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    result = await run_requirements_extraction(
      context, mock_config, mock_llm, mock_ui, jinja_env, cache_dir
    )

  assert result == '<requirements_list>New Requirements</requirements_list>'

  # Verify cache file was created
  cache_file = cache_dir / 'test-feat__requirements.xml'
  assert cache_file.exists()
  assert cache_file.read_text() == '<requirements_list>New Requirements</requirements_list>'


@pytest.mark.asyncio
async def test_requirements_cache_hit_accept(
  mock_config: Config, mock_llm: MagicMock, mock_ui: MagicMock, tmp_path: Path
) -> None:
  """Verify that requirements extraction uses cached requirements when user accepts."""
  web_feature_id = 'cached-feat'
  cache_dir = tmp_path / 'cache'
  cache_dir.mkdir()
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  cache_file.write_text('<requirements_list>Cached Requirements</requirements_list>')

  context = WorkflowContext(
    feature_id=web_feature_id,
    metadata=MagicMock(),
  )

  # User accepts cache
  mock_ui.confirm.return_value = True

  result = await run_requirements_extraction(
    context, mock_config, mock_llm, mock_ui, MagicMock(), cache_dir
  )

  assert result == '<requirements_list>Cached Requirements</requirements_list>'

  # LLM should NOT have been called (for extraction).
  assert mock_llm.generate_content.call_count == 0
  mock_ui.confirm.assert_called_once_with('Use cached requirements?')


@pytest.mark.asyncio
async def test_requirements_cache_hit_reject(
  mock_config: Config, mock_llm: MagicMock, mock_ui: MagicMock, tmp_path: Path
) -> None:
  """Verify that requirements extraction regenerates requirements when user rejects cache."""
  web_feature_id = 'rejected-cache-feat'
  cache_dir = tmp_path / 'cache'
  cache_dir.mkdir()
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  cache_file.write_text('<requirements_list>Old Cached Requirements</requirements_list>')

  metadata = WebFeatureMetadata(name='Feat', description='Desc', specs=['http://spec'])
  context = WorkflowContext(
    feature_id=web_feature_id,
    metadata=metadata,
    spec_contents='spec content',
  )

  # User rejects cache
  mock_ui.confirm.return_value = False
  mock_llm.generate_content.return_value = '<requirements_list>New Requirements</requirements_list>'
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Prompt'

  with patch('wptgen.phases.requirements_extraction.confirm_prompts', return_value=None):
    result = await run_requirements_extraction(
      context, mock_config, mock_llm, mock_ui, jinja_env, cache_dir
    )

  assert result == '<requirements_list>New Requirements</requirements_list>'

  # LLM should have been called once.
  assert mock_llm.generate_content.call_count == 1

  # Cache file should be updated.
  assert cache_file.read_text() == '<requirements_list>New Requirements</requirements_list>'

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
from typer.testing import CliRunner

from wptgen.config import Config
from wptgen.engine import WorkflowError, WPTGenEngine
from wptgen.main import app

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Provides a dummy configuration object."""
  return Config(
    provider='gemini',
    default_model='gemini-3.1-pro-preview',
    api_key='fake-key',
    categories={
      'lightweight': 'gemini-3.1-pro-preview',
      'reasoning': 'gemini-3-pro-preview',
    },
    phase_model_mapping={
      'requirements_extraction': 'reasoning',
      'coverage_audit': 'reasoning',
      'generation': 'lightweight',
      'evaluation': 'lightweight',
    },
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / 'cache'),
    output_dir=str(tmp_path / 'output'),
    max_retries=3,
  )


@pytest.fixture
def mock_ui() -> MagicMock:
  """Provides a mocked UI provider."""
  return MagicMock()


@pytest.fixture
def engine(mock_config: Config, mock_ui: MagicMock) -> WPTGenEngine:
  """Provides a WPTGenEngine instance."""
  with patch('wptgen.engine.get_llm_client'):
    return WPTGenEngine(mock_config, mock_ui)


def test_workflow_error_display(mocker: MockerFixture, mock_config: Config) -> None:
  """Verify that a WorkflowError results in a red failure panel and exit code 1."""
  mocker.patch('wptgen.main.load_config', return_value=mock_config)

  mock_engine_class = mocker.patch('wptgen.main.WPTGenEngine')
  mock_engine_instance = mock_engine_class.return_value
  # Simulate a workflow failure by raising WorkflowError
  mock_engine_instance.run_workflow.side_effect = WorkflowError('Phase 1 failure')

  result = runner.invoke(app, ['generate', 'grid'])

  # Verify exit code
  assert result.exit_code == 1
  # Verify failure message is present
  assert 'Workflow completed with errors' in result.stdout
  # Verify success message is NOT present
  assert 'Workflow completed successfully' not in result.stdout


@pytest.mark.asyncio
async def test_engine_raises_workflow_error_on_phase_failure(
  engine: WPTGenEngine, mocker: MockerFixture
) -> None:
  """Verify that the engine specifically raises WorkflowError when a phase returns None."""
  # Mock run_context_assembly to return None (failure)
  mocker.patch('wptgen.engine.run_context_assembly', return_value=None)

  with pytest.raises(WorkflowError, match='Phase 1: Context Assembly failed.'):
    await engine._run_async_workflow('test-feature')

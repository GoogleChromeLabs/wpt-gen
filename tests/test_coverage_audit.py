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

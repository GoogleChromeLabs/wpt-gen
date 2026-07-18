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

"""Shared fixtures for tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wptgen.config import Config

# The benchmark harness modules form the ``benchmark`` package under
# ``scripts/``. Adding it here lets the benchmark tests use 
# ``from benchmark... import`` with no per-file setup.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture
def mock_ui() -> MagicMock:
    """Fixture that provides a mocked UI provider with a status context manager."""
    ui = MagicMock()
    ui.status.return_value.__enter__.return_value = None
    return ui


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Fixture that provides a basic test configuration."""
    return Config(
        provider="test",
        default_model="test-model",
        api_key="test-key",
        categories={
            "lightweight": "fast-model",
            "reasoning": "smart-model",
        },
        phase_model_mapping={
            "requirements_extraction": "reasoning",
            "coverage_audit": "reasoning",
            "generation": "lightweight",
        },
        wpt_path=str(tmp_path / "wpt"),
        cache_path=str(tmp_path / "cache"),
        output_dir=str(tmp_path / "output"),
    )


@pytest.fixture
def mock_llm() -> MagicMock:
    """Fixture that provides a mocked LLM client."""
    llm = MagicMock()
    llm.count_tokens.return_value = 10
    llm.prompt_exceeds_input_token_limit.return_value = False
    llm.generate_content.return_value = "Mock Response"
    llm.model = "mock-model"
    return llm

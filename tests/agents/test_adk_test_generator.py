# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
"""Tests for test_adk_test_generator.py."""

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


@pytest.fixture
def mock_jinja_env() -> MagicMock:
    """Fixture to provide a mocked Jinja environment that returns simple text
    strings.
    """
    env = MagicMock()
    system_template = MagicMock()
    prompt_template = MagicMock()
    system_template.render.return_value = (
        "Mock System Instruction with {{host}} and {{ invalid var }}"
    )
    prompt_template.render.return_value = "Mock Prompt"

    def mock_get_template(name: str) -> MagicMock:
        if name == "adk_test_generator_system.jinja":
            return system_template
        return prompt_template

    env.get_template.side_effect = mock_get_template
    return env


@pytest.mark.asyncio
async def test_generate_test_with_adk(
    tmp_path: Path, mocker: MagicMock, mock_jinja_env: MagicMock
) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Create the file we pretend the agent generated
    output_dir = wpt_root / "output"
    output_dir.mkdir()
    test_file = output_dir / "my-feature-1.html"
    test_file.write_text(
        "<!DOCTYPE html>\n<title>Test</title>", encoding="utf-8"
    )

    # Mock the ADK Runner to simulate the agent calling the completion tool
    mock_runner_cls = mocker.patch("wptgen.agents.adk_test_generator.Runner")
    mock_runner_instance = mock_runner_cls.return_value
    mock_runner_instance.close = mocker.AsyncMock()

    async def mock_run_async(*args: Any, **kwargs: Any) -> Any:
        # In actual ADK, the tools are attached to the agent which is passed to
        # Runner
        agent = mock_runner_cls.call_args.kwargs["agent"]
        completion_tool = next(
            t
            for t in agent.tools
            if t.func.__name__ == "report_generation_complete"
        )

        # Simulate the LLM calling the tool with the generated path
        completion_tool.func([str(test_file)])

        # Yield an empty mock event to simulate the stream finishing
        yield MagicMock()

    mock_runner_instance.run_async = mock_run_async

    # Mock environment setup to avoid needing real API keys during tests
    # Use gemini-pro to ensure coverage of the native thought-blocks logic
    mocker.patch(
        "wptgen.agents.adk_test_generator.setup_adk_environment",
        return_value="gemini-pro",
    )
    mocker.patch.dict(os.environ, {"GOOGLE_API_KEY": "fake"}, clear=True)

    # Ensure skill directory doesn't exist to cover the "skill directory not
    # found" UI warning path
    mocker.patch(
        "wptgen.agents.adk_test_generator.Path.is_dir", return_value=False
    )

    config = Config(
        provider="gemini",
        default_model="gemini-pro",
        api_key="fake",
        wpt_path=str(wpt_root),
        output_dir=str(output_dir),
        categories={},
        phase_model_mapping={},
    )

    context = WorkflowContext(
        feature_id="my-feature",
        spec_contents={"spec1": "fake spec"},
        metadata=None,
        audit_response="fake audit",
    )

    mock_ui = MagicMock()
    results = await generate_test_with_adk(
        suggestion_xml="<test_suggestion></test_suggestion>",
        root_name="my-feature-1",
        test_type_enum=WPTTestType.JAVASCRIPT,
        context=context,
        config=config,
        jinja_env=mock_jinja_env,
        ui=mock_ui,
    )

    assert len(results) == 1
    assert results[0][0] == test_file.resolve()
    assert "<!DOCTYPE html>" in results[0][1]
    msg = (
        "wpt-generator skill directory not found. Agent will generate tests "
        "without skill guidance."
    )
    mock_ui.warning.assert_called_with(msg)


@pytest.mark.asyncio
async def test_generate_test_missing_output_dir_and_no_paths(
    tmp_path: Path, mocker: MagicMock, mock_jinja_env: MagicMock
) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Mock the ADK Runner to simulate an agent that finishes *without* calling
    # the completion tool
    mock_runner_cls = mocker.patch("wptgen.agents.adk_test_generator.Runner")
    mock_runner_instance = mock_runner_cls.return_value
    mock_runner_instance.close = mocker.AsyncMock()

    async def mock_run_async(*args: Any, **kwargs: Any) -> Any:
        # Do not call the completion tool at all, simulating a lazy/failed agent
        # execution
        yield MagicMock()

    mock_runner_instance.run_async = mock_run_async

    # Setup the mock environment
    mocker.patch(
        "wptgen.agents.adk_test_generator.setup_adk_environment",
        return_value="gemini-mock",
    )

    # Mock load_skill_from_dir to raise an exception, testing the error
    # handling for malformed skills
    mocker.patch(
        "wptgen.agents.adk_test_generator.Path.is_dir", return_value=True
    )
    mocker.patch(
        "wptgen.agents.adk_test_generator.load_skill_from_dir",
        side_effect=Exception("Test error"),
    )

    config = Config(
        provider="google",
        default_model="gemini",
        api_key="fake",
        wpt_path=str(wpt_root),
        output_dir="",  # Cover logic where output_dir falls back to wpt_root
        categories={},
        phase_model_mapping={},
    )

    context = WorkflowContext(
        feature_id="my-feature",
        spec_contents={"spec1": "fake spec"},
        metadata=None,
        audit_response="fake audit",
    )

    mock_ui = MagicMock()
    results = await generate_test_with_adk(
        suggestion_xml="<test_suggestion></test_suggestion>",
        root_name="my-feature-1",
        test_type_enum=WPTTestType.JAVASCRIPT,
        context=context,
        config=config,
        jinja_env=mock_jinja_env,
        ui=mock_ui,
    )

    assert len(results) == 0
    mock_ui.warning.assert_called_with(
        "Agent finished but did not report any generated paths."
    )
    mock_ui.error.assert_called_with(
        "Failed to load wpt-generator skill: Test error"
    )


@pytest.mark.asyncio
async def test_generate_test_invalid_path(
    tmp_path: Path, mocker: MagicMock, mock_jinja_env: MagicMock
) -> None:
    wpt_root = tmp_path / "wpt"
    wpt_root.mkdir()

    # Mock the ADK Runner to simulate an agent that tries to write maliciously
    # outside the root
    mock_runner_cls = mocker.patch("wptgen.agents.adk_test_generator.Runner")
    mock_runner_instance = mock_runner_cls.return_value
    mock_runner_instance.close = mocker.AsyncMock()

    async def mock_run_async(*args: Any, **kwargs: Any) -> Any:
        agent = mock_runner_cls.call_args.kwargs["agent"]
        completion_tool = next(
            t
            for t in agent.tools
            if t.func.__name__ == "report_generation_complete"
        )

        # Provide an invalid path outside wpt_root (simulating a path traversal
        # attack / mistake)
        completion_tool.func(["/etc/passwd"])
        yield MagicMock()

    mock_runner_instance.run_async = mock_run_async

    # Setup the mock environment
    mocker.patch(
        "wptgen.agents.adk_test_generator.setup_adk_environment",
        return_value="gemini-mock",
    )

    # Ensure the skill is loaded properly for coverage
    mocker.patch(
        "wptgen.agents.adk_test_generator.Path.is_dir", return_value=True
    )
    mocker.patch(
        "wptgen.agents.adk_test_generator.load_skill_from_dir",
        return_value=MagicMock(),
    )

    config = Config(
        provider="google",
        default_model="gemini",
        api_key="fake",
        wpt_path=str(wpt_root),
        output_dir=str(wpt_root),
        categories={},
        phase_model_mapping={},
    )

    context = WorkflowContext(
        feature_id="my-feature",
        spec_contents={"spec1": "fake spec"},
        metadata=None,
        audit_response="fake audit",
    )

    mock_ui = MagicMock()
    results = await generate_test_with_adk(
        suggestion_xml="<test_suggestion></test_suggestion>",
        root_name="my-feature-1",
        test_type_enum=WPTTestType.JAVASCRIPT,
        context=context,
        config=config,
        jinja_env=mock_jinja_env,
        ui=mock_ui,
    )

    assert len(results) == 0
    assert mock_ui.error.call_count == 1
    assert (
        "Failed to read securely generated file '/etc/passwd'"
        in mock_ui.error.call_args[0][0]
    )

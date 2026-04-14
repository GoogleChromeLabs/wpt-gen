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

"""Tests for the generation phase."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.models import FeatureMetadata, WorkflowContext
from wptgen.phases.generation import (
    _generate_adk_loop,
    run_single_test_generation,
    run_test_generation,
)


@pytest.mark.asyncio
async def test_run_test_generation_satisfied(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
    """Test test generation when audit status is SATISFIED."""
    context = WorkflowContext(
        feature_id="feat",
        audit_response="<status>SATISFIED</status>",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
    )
    jinja_env = MagicMock()

    res = await run_test_generation(
        context, mock_config, mock_llm, mock_ui, jinja_env
    )

    assert not res
    mock_ui.success.assert_called_once_with(
        "All identified test requirements have been satisfied."
    )
    mock_ui.info.assert_called_once()


@pytest.mark.asyncio
async def test_run_test_generation_no_suggestions(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
    """Test test generation when no suggestions are found in audit response."""
    context = WorkflowContext(
        feature_id="feat",
        audit_response="no suggestions here",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
    )
    jinja_env = MagicMock()

    res = await run_test_generation(
        context, mock_config, mock_llm, mock_ui, jinja_env
    )

    assert not res
    mock_ui.warning.assert_called_once_with(
        "No valid <test_suggestion> blocks found in the LLM response."
    )


@pytest.mark.asyncio
async def test_run_test_generation_none_selected(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock
) -> None:
    """Test test generation when user rejects all suggestions."""
    suggestion_xml = (
        "<test_suggestion><title>T1</title>"
        "<description>D1</description></test_suggestion>"
    )
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        audit_response=suggestion_xml,
    )
    jinja_env = MagicMock()

    mock_ui.confirm.return_value = False

    res = await run_test_generation(
        context, mock_config, mock_llm, mock_ui, jinja_env
    )

    assert not res
    mock_ui.warning.assert_any_call("No tests selected. Exiting.")


@pytest.mark.asyncio
async def test_run_test_generation_adk(
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    mocker: MockerFixture,
) -> None:
    """Test that ADK generation branches correctly and calls
    _generate_adk_loop.
    """
    suggestion_xml = (
        "<test_suggestion><title>T1</title>"
        "<description>D1</description></test_suggestion>"
    )
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "D", ["url"]),
        audit_response=f"<audit_worksheet>W</audit_worksheet>{suggestion_xml}",
    )
    mock_ui.confirm.return_value = True

    mock_adk = mocker.patch("wptgen.phases.generation._generate_adk_loop")
    mock_adk.return_value = []

    jinja_env = MagicMock()

    results = await run_test_generation(
        context, mock_config, mock_llm, mock_ui, jinja_env
    )

    assert mock_adk.called
    assert not results


@pytest.mark.asyncio
async def test_generate_adk_loop(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that _generate_adk_loop properly maps the suggestions and triggers
    tasks.
    """
    mock_config.output_dir = "test_dir"
    mock_config.brief_suggestions = False

    suggestion_xml = (
        "<test_suggestion><title>T1</title>"
        "<test_type>JavaScript Test</test_type>"
        "<description>D1</description></test_suggestion>"
    )
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "D", ["url"]),
    )

    mock_adk = mocker.patch(
        "wptgen.agents.adk_test_generator.generate_test_with_adk",
        new_callable=AsyncMock,
        create=True,
    )
    mock_adk.return_value = [
        (Path("test_dir/feat.html"), "content", suggestion_xml)
    ]

    jinja_env = MagicMock()

    results = await _generate_adk_loop(
        [suggestion_xml], context, mock_config, mock_ui, jinja_env
    )

    assert mock_adk.called
    assert len(results) == 1
    assert results[0][1] == "content"


@pytest.mark.asyncio
async def test_run_single_test_generation(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test the run_single_test_generation function."""
    mock_generate_adk = mocker.patch(
        "wptgen.phases.generation._generate_adk_loop"
    )
    mock_generate_adk.return_value = [
        (Path("test.html"), "content", "suggestion")
    ]
    jinja_env = MagicMock()

    result = await run_single_test_generation(
        web_feature_id="custom-feat",
        spec_urls=["http://spec.com"],
        description="A cool feature",
        title="Cool Test",
        test_type="testharness",
        config=mock_config,
        ui=mock_ui,
        jinja_env=jinja_env,
    )

    assert len(result) == 1
    mock_generate_adk.assert_called_once()

    args, kwargs = mock_generate_adk.call_args
    suggestions_xml = args[0]
    context = args[1]

    assert len(suggestions_xml) == 1
    assert "A cool feature" in suggestions_xml[0]
    assert "<title>Cool Test</title>" in suggestions_xml[0]
    assert "<test_type>testharness</test_type>" in suggestions_xml[0]

    assert context.feature_id == "custom-feat"
    assert context.metadata.specs == ["http://spec.com"]


@pytest.mark.asyncio
async def test_run_single_test_generation_no_feature_id(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test run_single_test_generation when web_feature_id is None."""
    mock_generate_adk = mocker.patch(
        "wptgen.phases.generation._generate_adk_loop"
    )
    mock_generate_adk.return_value = []
    jinja_env = MagicMock()

    await run_single_test_generation(
        web_feature_id=None,
        spec_urls=["http://spec.com"],
        description="A cool feature",
        title=None,
        test_type=None,
        config=mock_config,
        ui=mock_ui,
        jinja_env=jinja_env,
    )

    mock_generate_adk.assert_called_once()

    args, kwargs = mock_generate_adk.call_args
    context = args[1]

    assert context.feature_id is None
    assert context.metadata.name == "custom_feature"

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

"""Tests for the requirements extraction phase."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.models import FeatureMetadata, WorkflowContext
from wptgen.phases.requirements_extraction import (
    run_requirements_extraction,
    run_requirements_extraction_categorized,
)


@pytest.mark.asyncio
async def test_run_requirements_extraction_cached(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
    """Test requirements extraction when a valid cache exists."""
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec"},
    )
    cache_dir = tmp_path
    cache_file = cache_dir / "feat__requirements.xml"
    cache_file.write_text("<reqs>cached</reqs>", encoding="utf-8")

    mock_ui.confirm.return_value = True

    res = await run_requirements_extraction(
        context, mock_config, mock_llm, mock_ui, MagicMock(), cache_dir
    )

    assert res == "<reqs>cached</reqs>"
    mock_ui.info.assert_called_once()
    mock_ui.success.assert_any_call("Using cached requirements.")
    mock_ui.success.assert_any_call("Extracted 0 test requirements.")


@pytest.mark.asyncio
async def test_run_requirements_extraction_with_explainer(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
    """Test requirements extraction when explainer contents are present."""
    context = WorkflowContext(
        feature_id="feat-explainer",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec Content"},
        explainer_contents={
            "http://explainer1": "Explainer Content 1",
            "http://explainer2": "Explainer Content 2",
        },
    )
    jinja_env = MagicMock()
    template_mock = MagicMock()
    jinja_env.get_template.return_value = template_mock

    req_xml = (
        '<requirements_list><requirement id="R1">'
        "<category>Existence</category><description>D1</description>"
        "</requirement></requirements_list>"
    )
    with patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        return_value=req_xml,
    ):
        await run_requirements_extraction(
            context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
        )

    # Verify explainer_contents was passed to render
    template_mock.render.assert_any_call(
        feature_name="Feat",
        feature_description="Desc",
        specs={"http://spec": "Spec Content"},
        mdn_contents=None,
        explainer_contents={
            "http://explainer1": "Explainer Content 1",
            "http://explainer2": "Explainer Content 2",
        },
    )


@pytest.mark.asyncio
async def test_run_requirements_extraction_success(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
    """Test successful requirements extraction with mocked LLM response."""
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec Content"},
    )
    jinja_env = MagicMock()
    template_mock = MagicMock()
    jinja_env.get_template.return_value = template_mock

    req_xml = (
        '<requirements_list><requirement id="R1">'
        "<category>Existence</category><description>D1</description>"
        "</requirement></requirements_list>"
    )
    with patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        return_value=req_xml,
    ):
        await run_requirements_extraction(
            context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
        )

    mock_ui.on_phase_start.assert_called_once_with(2, "Requirements Extraction")
    mock_ui.success.assert_any_call("Extracted 1 test requirements.")


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_with_explainer(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
    """Test categorized requirements extraction when explainer contents are
    present.
    """
    context = WorkflowContext(
        feature_id="feat-explainer-cat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec Content"},
        explainer_contents={"http://explainer1": "Explainer Content 1"},
    )
    jinja_env = MagicMock()
    template_mock = MagicMock()
    jinja_env.get_template.return_value = template_mock

    req_xml = (
        '<requirements_list><requirement id="R1">'
        "<category>Existence</category><description>D1</description>"
        "</requirement></requirements_list>"
    )
    with patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        return_value=req_xml,
    ):
        await run_requirements_extraction_categorized(
            context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
        )

    # Verify explainer_contents was passed to render
    template_mock.render.assert_any_call(
        feature_name="Feat",
        feature_description="Desc",
        specs={"http://spec": "Spec Content"},
        mdn_contents=None,
        explainer_contents={"http://explainer1": "Explainer Content 1"},
    )


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized(
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Test categorized requirements extraction with mocked LLM responses."""
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec"},
    )
    jinja_env = MagicMock()
    jinja_env.get_template.return_value.render.return_value = "Mock Template"

    # Mock generate_safe to return a single requirement for each call
    mocker.patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        side_effect=[
            '<requirements_list><requirement id="R1">'
            "<category>Existence</category><description>D1</description>"
            "</requirement></requirements_list>",
            '<requirements_list><requirement id="R1">'
            "<category>Common Use Cases</category><description>D2</description>"
            "</requirement></requirements_list>",
            '<requirements_list><requirement id="R1">'
            "<category>Error Scenarios</category><description>D3</description>"
            "</requirement></requirements_list>",
            '<requirements_list><requirement id="R1">'
            "<category>Invalidation</category><description>D4</description>"
            "</requirement></requirements_list>",
            '<requirements_list><requirement id="R1">'
            "<category>Integration</category><description>D5</description>"
            "</requirement></requirements_list>",
        ],
    )
    res = await run_requirements_extraction_categorized(
        context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

    assert res is not None
    assert '<requirement id="R1">' in res
    assert '<requirement id="R2">' in res
    assert '<requirement id="R3">' in res
    assert '<requirement id="R4">' in res
    assert '<requirement id="R5">' in res
    assert "<category>Existence</category>" in res
    assert "<category>Integration</category>" in res
    assert res.count("<requirement id=") == 5


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_partial_empty(
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Test categorized requirements extraction with some empty responses."""
    context = WorkflowContext(
        feature_id="feat-partial",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec"},
    )
    jinja_env = MagicMock()
    jinja_env.get_template.return_value.render.return_value = "Mock Template"

    # Mock generate_safe to return a mixture of requirements and empty lists
    mocker.patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        side_effect=[
            '<requirements_list><requirement id="R1">'
            "<category>Existence</category><description>D1</description>"
            "</requirement></requirements_list>",
            "<requirements_list></requirements_list>",  # Empty
            '<requirements_list><requirement id="R1">'
            "<category>Error Scenarios</category><description>D3</description>"
            "</requirement></requirements_list>",
            "<requirements_list></requirements_list>",  # Empty
            "<requirements_list></requirements_list>",  # Empty
        ],
    )
    res = await run_requirements_extraction_categorized(
        context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

    assert res is not None
    assert '<requirement id="R1">' in res
    assert '<requirement id="R2">' in res
    assert "<category>Existence</category>" in res
    assert "<category>Error Scenarios</category>" in res
    assert res.count("<requirement id=") == 2


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_with_rationale(
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Test categorized requirements extraction with a rationale for an empty
    category.
    """
    context = WorkflowContext(
        feature_id="feat-rationale",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec"},
    )
    jinja_env = MagicMock()
    jinja_env.get_template.return_value.render.return_value = "Mock Template"

    # Mock generate_safe to return one category with a requirement and one
    # with a rationale
    req_xmls = [
        '<requirements_list><requirement id="R1">'
        "<category>Existence</category><description>D1</description>"
        "</requirement></requirements_list>",
        "<requirements_list><rationale>This feature is a simple object and "
        "has no complex invalidation rules.</rationale>"
        "</requirements_list>",
        "<requirements_list></requirements_list>",  # Empty without rationale
        "<requirements_list></requirements_list>",
        "<requirements_list></requirements_list>",
    ]
    mocker.patch(
        "wptgen.phases.requirements_extraction.generate_safe",
        side_effect=req_xmls,
    )
    res = await run_requirements_extraction_categorized(
        context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
    )

    assert res is not None
    assert '<requirement id="R1">' in res
    assert "rationale" not in res  # Final XML should NOT contain rationales

    # Verify ui.info was called with the rationale
    mock_ui.info.assert_any_call(
        "No requirements found for category [Common Use Cases] "
        "This feature is a simple object and has no complex "
        "invalidation rules."
    )


@pytest.mark.asyncio
async def test_run_requirements_extraction_agentic_success(
    mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, tmp_path: Path
) -> None:
    """Test successful agentic requirements extraction."""
    context = WorkflowContext(
        feature_id="feat",
        metadata=FeatureMetadata("Feat", "Desc", ["http://spec"]),
        spec_contents={"http://spec": "Spec"},
    )
    jinja_env = MagicMock()

    # Mock run_generator_turn and run_critic_turn
    with patch(
        "wptgen.phases.requirements_extraction.run_generator_turn"
    ) as mock_gen, patch(
        "wptgen.phases.requirements_extraction.run_critic_turn"
    ) as mock_critic:

        mock_gen.return_value = (
            "<requirements><requirement id='R1'>Req 1</requirement></requirements>"
        )
        # First turn: Needs revision
        # Second turn: Approved
        mock_critic.side_effect = [
            "<critic_review><status>NEEDS_REVISION</status><issues><issue>...</issue></issues></critic_review>",
            "<critic_review><status>APPROVED</status></critic_review>",
        ]

        from wptgen.phases.requirements_extraction import (
            run_requirements_extraction_agentic,
        )

        res = await run_requirements_extraction_agentic(
            context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
        )

        assert res is not None
        assert "<requirement id='R1'>Req 1</requirement>" in res
        assert mock_gen.call_count == 2
        assert mock_critic.call_count == 2


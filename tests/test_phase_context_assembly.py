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

"""Tests for the context assembly phase."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.models import FeatureMetadata, WPTContext
from wptgen.phases.context_assembly import run_context_assembly


@pytest.mark.asyncio
async def test_run_context_assembly_success(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test successful context assembly for a registered feature."""
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    metadata = FeatureMetadata("Feat", "Desc", ["http://spec"])
    metadata.explainer_links = ["http://explainer"]
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=metadata,
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    mock_fetch.side_effect = ["Spec Content", "Explainer Content"]
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is not None
    assert context.feature_id == "feat-id"
    assert context.metadata is not None
    assert context.metadata.name == "Feat"
    assert context.spec_contents == {"http://spec": "Spec Content"}
    assert context.explainer_contents == {
        "http://explainer": "Explainer Content"
    }
    mock_ui.on_phase_start.assert_called_once_with(1, "Context Assembly")
    mock_ui.report_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_with_mdn(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly with MDN documentation fetching."""
    mock_config.include_mdn_docs = True
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=FeatureMetadata("Feat", "Desc", ["http://spec"]),
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_mdn_urls",
        return_value=["http://mdn1", "http://mdn2"],
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    mock_fetch.side_effect = ["Spec Content", "MDN Content 1", "MDN Content 2"]

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is not None
    assert isinstance(context.mdn_contents, list)
    assert len(context.mdn_contents) == 2
    mock_ui.report_context_summary.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_without_mdn(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly skips MDN fetching when include_mdn_docs is
    False.
    """
    mock_config.include_mdn_docs = False
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=FeatureMetadata("Feat", "Desc", ["http://spec"]),
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    mock_fetch_mdn = mocker.patch(
        "wptgen.phases.context_assembly.fetch_mdn_urls"
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    mock_fetch.return_value = "Spec Content"

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is not None
    assert context.mdn_contents is None
    mock_fetch_mdn.assert_not_called()
    mock_ui.print.assert_any_call(
        "Skipping MDN documentation fetch (not requested)."
    )


@pytest.mark.asyncio
async def test_run_context_assembly_chromestatus_skips_mdn(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that context assembly skips MDN fetching for ChromeStatus
    features.
    """
    mock_config.chromestatus = True
    mock_config.include_mdn_docs = True
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_chromestatus_metadata",
        return_value=FeatureMetadata("Feat", "Desc", ["http://spec"]),
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text",
        return_value="Spec Content",
    )
    mock_fetch_mdn = mocker.patch(
        "wptgen.phases.context_assembly.fetch_mdn_urls"
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is not None
    assert context.mdn_contents is None
    mock_fetch_mdn.assert_not_called()
    mock_ui.print.assert_any_call(
        "Skipping MDN documentation fetch for ChromeStatus feature."
    )


@pytest.mark.asyncio
async def test_run_context_assembly_unregistered_with_params(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly for an unregistered feature with manual
    parameters.
    """
    mock_config.spec_urls = ["http://manual-spec"]
    mock_config.feature_description = "Manual Description"

    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml", return_value=None
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_mdn_urls", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text",
        return_value="Spec Content",
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    context = await run_context_assembly("unregistered", mock_config, mock_ui)

    assert context is not None
    assert context.metadata is not None
    assert context.metadata.name == "unregistered"
    assert mock_ui.warning.call_count == 2
    mock_ui.warning.assert_any_call(
        "Feature unregistered not found in the web-features repository."
    )
    mock_ui.warning.assert_any_call(
        "No existing Web Platform Tests were successfully loaded."
    )


@pytest.mark.asyncio
async def test_run_context_assembly_not_found(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly when feature is not found and no manual params
    provided.
    """
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml", return_value=None
    )
    context = await run_context_assembly("not-found", mock_config, mock_ui)
    assert context is None
    mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_no_specs(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly failure when no spec URLs are found."""
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=FeatureMetadata("Feat", "Desc", []),
    )
    context = await run_context_assembly("feat-id", mock_config, mock_ui)
    assert context is None
    mock_ui.error.assert_called_once()


@pytest.mark.asyncio
async def test_run_context_assembly_chromestatus_with_wpt_descr(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test context assembly for a ChromeStatus feature with wpt_descr."""
    mock_config.chromestatus = True
    metadata = FeatureMetadata(
        "Feat", "Desc", ["http://spec"], wpt_descr="css/test.html"
    )

    mock_fetch_meta = mocker.patch(
        "wptgen.phases.context_assembly.fetch_chromestatus_metadata",
        return_value=metadata,
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text",
        return_value="Spec Content",
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mock_extract = mocker.patch(
        "wptgen.phases.context_assembly.extract_wpt_paths",
        return_value=["css/test.html"],
    )
    mock_validate = mocker.patch(
        "wptgen.phases.context_assembly.validate_wpt_paths",
        return_value=(["/abs/css/test.html"], ["invalid/path"]),
    )
    mock_gather = mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is not None
    assert context.wpt_urls == ["css/test.html"]
    mock_fetch_meta.assert_called_once()
    mock_extract.assert_called_once_with("css/test.html")
    mock_validate.assert_called_once_with(
        ["css/test.html"], mock_config.wpt_path
    )
    mock_ui.warning.assert_called_with(
        "Referenced WPT test file could not be found or read: invalid/path"
    )
    # Check that gather_local_test_context was called with the validated path
    mock_gather.assert_called_once_with(
        ["/abs/css/test.html"], mock_config.wpt_path
    )


@pytest.mark.asyncio
async def test_run_context_assembly_chromestatus_too_many_tests(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that context assembly warns but proceeds if too many tests are
    found.
    """
    mock_config.chromestatus = True
    metadata = FeatureMetadata(
        "Feat", "Desc", ["http://spec"], wpt_descr="css/"
    )

    mocker.patch(
        "wptgen.phases.context_assembly.fetch_chromestatus_metadata",
        return_value=metadata,
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text",
        return_value="Spec Content",
    )
    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.extract_wpt_paths",
        return_value=["css/"],
    )
    mocker.patch(
        "wptgen.phases.context_assembly.validate_wpt_paths",
        side_effect=ValueError("Too many tests found (60). Max allowed is 50."),
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(test_contents={}),
    )

    await run_context_assembly("feat-id", mock_config, mock_ui)

    # Should have warned about skipping ChromeStatus tests
    mock_ui.warning.assert_any_call(
        "Skipping ChromeStatus tests: Too many tests found (60). "
        "Max allowed is 50."
    )
    # Should also have warned that no tests were loaded
    mock_ui.warning.assert_any_call(
        "No existing Web Platform Tests were successfully loaded."
    )


@pytest.mark.asyncio
async def test_run_context_assembly_explainer_fetch_warning(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that a warning is shown if an explainer fails to fetch meaningful
    text.
    """
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    metadata = FeatureMetadata("Feat", "Desc", ["http://spec"])
    metadata.explainer_links = ["http://explainer-fail"]
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=metadata,
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    # First for spec (success), second for explainer (fail with None)
    mock_fetch.side_effect = ["Spec Content", None]

    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    await run_context_assembly("feat-id", mock_config, mock_ui)

    mock_ui.warning.assert_any_call(
        "Failed to fetch or extract meaningful text from explainer: "
        "http://explainer-fail"
    )


@pytest.mark.asyncio
async def test_run_context_assembly_explainer_fetch_exception(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that a warning is shown if an explainer fetch raises an
    exception.
    """
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    metadata = FeatureMetadata("Feat", "Desc", ["http://spec"])
    metadata.explainer_links = ["http://explainer-error"]
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=metadata,
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    # First for spec (success), second for explainer (exception)
    mock_fetch.side_effect = ["Spec Content", Exception("Network error")]

    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    await run_context_assembly("feat-id", mock_config, mock_ui)

    mock_ui.warning.assert_any_call(
        "Failed to fetch or extract content from explainer "
        "(http://explainer-error): Network error"
    )


@pytest.mark.asyncio
async def test_run_context_assembly_spec_fetch_exception(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that a warning is shown if a spec fetch raises an exception."""
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_feature_yaml",
        return_value={"name": "feat"},
    )
    mocker.patch(
        "wptgen.phases.context_assembly.extract_feature_metadata",
        return_value=FeatureMetadata("Feat", "Desc", ["http://spec-error"]),
    )
    mock_fetch = mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text"
    )
    mock_fetch.side_effect = [Exception("404 Not Found")]

    mocker.patch(
        "wptgen.phases.context_assembly.find_feature_tests", return_value=[]
    )
    mocker.patch(
        "wptgen.phases.context_assembly.gather_local_test_context",
        return_value=WPTContext(),
    )

    context = await run_context_assembly("feat-id", mock_config, mock_ui)

    assert context is None
    mock_ui.warning.assert_any_call(
        "Failed to fetch spec (http://spec-error): 404 Not Found"
    )
    mock_ui.error.assert_any_call("Failed to extract spec content.")


@pytest.mark.asyncio
async def test_run_context_assembly_library_mode_remote_fetching(
    mock_config: Config, mock_ui: MagicMock, mocker: MockerFixture
) -> None:
    """Test that library mode correctly populates wpt_context via remote fetching."""
    mock_config.library_mode = True
    mock_config.wpt_path = None
    mock_config.chromestatus = True

    metadata = FeatureMetadata("Feat", "Desc", ["http://spec"])
    metadata.wpt_descr = """
    Here are the WPT results for this feature:
    - https://wpt.fyi/results/css/css-grid/grid-model?label=master
    - https://wpt.fyi/results/css/css-flexbox/flex-minimum-height-flex-items-005.xht?run_id=12345
    Check these out.
    """
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_chromestatus_metadata",
        return_value=metadata,
    )
    mocker.patch(
        "wptgen.phases.context_assembly.fetch_and_extract_text",
        return_value="Spec Content",
    )

    mock_remote_context = WPTContext(
        test_contents={
            "/css/css-grid/grid-model": "grid content",
            "/css/css-flexbox/flex-minimum-height-flex-items-005.xht": "flex content",
        }
    )
    mock_fetch_remote = mocker.patch(
        "wptgen.phases.context_assembly.fetch_remote_wpt_context",
        return_value=mock_remote_context,
    )

    context = await run_context_assembly("517399", mock_config, mock_ui)

    assert context is not None
    assert context.wpt_context == mock_remote_context
    mock_fetch_remote.assert_called_once_with(
        [
            "css/css-flexbox/flex-minimum-height-flex-items-005.xht",
            "css/css-grid/grid-model",
        ]
    )

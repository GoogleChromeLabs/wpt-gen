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

"""Tests for the exposed programmatic API."""

from unittest.mock import MagicMock
from typing import Any
from wptgen import generate_audit_report
from wptgen.models import WorkflowContext
from wptgen.config import Config


def test_generate_audit_report_success(mocker: Any) -> None:
    mock_load_config = mocker.patch("wptgen.config.load_config")
    mock_engine_class = mocker.patch("wptgen.WPTGenEngine")
    """Test that generate_audit_report correctly initializes the engine."""
    mock_context = MagicMock(spec=WorkflowContext)
    mock_context.markdown_report = "# Fake Report"

    mock_engine = MagicMock()
    mock_engine.run_workflow.return_value = mock_context
    mock_engine_class.return_value = mock_engine

    mock_config = MagicMock(spec=Config)
    mock_load_config.return_value = mock_config

    report = generate_audit_report(feature_id="12345", provider="gemini")

    # Assertions
    mock_load_config.assert_called_once()
    kwargs = mock_load_config.call_args.kwargs
    assert kwargs["provider_override"] == "gemini"
    assert kwargs["yes_tokens_override"] is True

    assert mock_config.library_mode is True
    assert mock_config.suggestions_only is True
    assert mock_config.wpt_path is None

    mock_engine.run_workflow.assert_called_once_with(
        "12345", disable_directory_inference=True
    )
    assert report == "# Fake Report"


def test_generate_audit_report_opt_out_explainer(mocker: Any) -> None:
    mock_load_config = mocker.patch("wptgen.config.load_config")
    mock_engine_class = mocker.patch("wptgen.WPTGenEngine")
    """Test that generate_audit_report respects empty explainer list (opt-out)."""
    mock_context = MagicMock(spec=WorkflowContext)
    mock_context.markdown_report = "# Fake Report"

    mock_engine = MagicMock()
    mock_engine.run_workflow.return_value = mock_context
    mock_engine_class.return_value = mock_engine

    # To make it clear that it overrides something, we simulate that load_config
    # initially loads a list with an old explainer, but then applies the override.
    def mock_load_config_impl(
        provider_override: str | None = None,
        yes_tokens_override: bool = False,
        explainer_urls_override: list[str] | None = None,
        **kwargs: Any,
    ) -> MagicMock:
        cfg = MagicMock(spec=Config)
        # Simulate pre-existing explainers loaded from defaults
        cfg.explainer_urls = ["https://example.com/old-explainer"]
        # Apply override if it was provided
        if explainer_urls_override is not None:
            cfg.explainer_urls = explainer_urls_override
        return cfg

    mock_load_config.side_effect = mock_load_config_impl

    report = generate_audit_report(
        feature_id="12345",
        explainer_urls=[],
    )

    # Assertions
    mock_load_config.assert_called_once()

    # Verify that the final config passed to the engine has empty explainers!
    args, kwargs = mock_engine_class.call_args
    config = kwargs["config"]
    assert config.explainer_urls == []
    assert config.suggestions_only is True
    assert config.wpt_path is None

    mock_engine.run_workflow.assert_called_once_with(
        "12345", disable_directory_inference=True
    )
    assert report == "# Fake Report"

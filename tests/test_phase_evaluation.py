# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the evaluation phase: dataclasses, payload conversion, the
report renderer, and run_evaluation."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from wptgen.agents.adk_conformance_evaluator import SpecRequirements
from wptgen.agents.adk_evaluator import EvaluatorStrategy
from wptgen.agents.streaming import TokenUsage
from wptgen.config import DEFAULT_EVALUATOR_CACHE_DIR, Config
from wptgen.context import slug_for_spec_url
from wptgen.phases.evaluation import (
    ConformanceSection,
    EvaluationReportRenderer,
    Finding,
    InputScope,
    InputScopeFile,
    _build_findings_payload,
    _count_findings,
    _payload_to_findings,
    _payload_to_input_scope,
    run_evaluation,
)

# ---------------------------------------------------------------------------
# InputScope dataclass properties
# ---------------------------------------------------------------------------


def test_input_scope_total_bytes_sums_files() -> None:
    scope = InputScope(
        files=[
            InputScopeFile(path="a.md", bytes=100, role="skill"),
            InputScopeFile(path="b.md", bytes=250, role="reading-list"),
            InputScopeFile(path="c.html", bytes=50, role="test"),
        ],
    )
    assert scope.total_bytes == 400


def test_input_scope_token_estimate_is_bytes_over_four() -> None:
    scope = InputScope(
        files=[InputScopeFile(path="a.md", bytes=4000, role="skill")],
    )
    assert scope.approximate_input_tokens == 1000


def test_input_scope_empty_files_zeroes() -> None:
    scope = InputScope()
    assert scope.total_bytes == 0
    assert scope.approximate_input_tokens == 0


# ---------------------------------------------------------------------------
# Payload conversion
# ---------------------------------------------------------------------------


def test_payload_to_findings_roundtrips_all_fields() -> None:
    payload = [
        {
            "title": "missing charset",
            "severity": "warn",
            "test_line": "Lines 1-4",
            "evidence": "<head>...",
            "source": "wpt/docs/writing-tests/general-guidelines.md:L82-L87",
            "summary": "HTML files must declare encoding.",
        }
    ]
    findings = _payload_to_findings(payload)
    assert len(findings) == 1
    f = findings[0]
    assert f.title == "missing charset"
    assert f.severity == "warn"
    assert f.test_line == "Lines 1-4"
    assert f.evidence == "<head>..."
    assert f.source == "wpt/docs/writing-tests/general-guidelines.md:L82-L87"
    assert f.summary == "HTML files must declare encoding."


def test_payload_to_findings_tolerates_missing_fields() -> None:
    findings = _payload_to_findings([{}])
    assert len(findings) == 1
    f = findings[0]
    assert f.title == ""
    assert f.severity == ""
    assert f.test_line == ""
    assert f.evidence == ""
    assert f.source == ""
    assert f.summary == ""


def test_payload_to_findings_empty_list() -> None:
    assert _payload_to_findings([]) == []


def test_payload_to_input_scope_full() -> None:
    payload = {
        "files": [
            {"path": "skill.md", "bytes": 100, "role": "skill"},
            {"path": "test.html", "bytes": 50, "role": "test"},
        ],
        "dependencies_not_read": [
            "/resources/testharness.js",
            "http://example.com",
        ],
        "strategy": "raw",
    }
    scope = _payload_to_input_scope(payload)
    assert len(scope.files) == 2
    assert scope.files[0].path == "skill.md"
    assert scope.files[0].bytes == 100
    assert scope.files[0].role == "skill"
    assert scope.dependencies_not_read == [
        "/resources/testharness.js",
        "http://example.com",
    ]
    assert scope.strategy == "raw"


def test_payload_to_input_scope_tolerates_empty_payload() -> None:
    scope = _payload_to_input_scope({})
    assert scope.files == []
    assert scope.dependencies_not_read == []
    assert scope.strategy == "distilled"  # default


def test_payload_to_input_scope_handles_none_lists() -> None:
    # Agents might serialize empty fields as null/None — the conversion
    # should not crash.
    scope = _payload_to_input_scope(
        {"files": None, "dependencies_not_read": None}
    )
    assert scope.files == []
    assert scope.dependencies_not_read == []


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------


def _sample_finding(**overrides: Any) -> Finding:
    defaults: dict[str, Any] = {
        "title": "missing character encoding declaration",
        "severity": "warn",
        "test_line": "Lines 1-4",
        "evidence": "<!DOCTYPE html>",
        "source": "wpt/docs/writing-tests/general-guidelines.md:L82-L87",
        "summary": "HTML must declare encoding.",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _sample_scope(**overrides: Any) -> InputScope:
    defaults: dict[str, Any] = {
        "files": [
            InputScopeFile(
                path="wptgen/skills/wpt-evaluator/SKILL.md",
                bytes=7_500,
                role="skill",
            ),
            InputScopeFile(
                path="wpt/css/css-flexbox/align-content_center.html",
                bytes=968,
                role="test",
            ),
        ],
        "dependencies_not_read": [],
        "strategy": "raw",
    }
    defaults.update(overrides)
    return InputScope(**defaults)


def _sample_metadata() -> dict[str, Any]:
    return {"provider": "gemini", "model": "gemini-3.1-pro-preview"}


def _render(
    test_path: str,
    findings: list[Finding],
    input_scope: InputScope | None = None,
    conformance: ConformanceSection | None = None,
) -> str:
    """Builds the payload and renders it, mirroring run_evaluation's path."""
    payload = _build_findings_payload(
        test_path=Path(test_path),
        findings=findings,
        input_scope=input_scope if input_scope is not None else _sample_scope(),
        conformance=conformance,
        run_metadata=_sample_metadata(),
    )
    return EvaluationReportRenderer().render_from_payload(payload)


def test_build_findings_payload_is_json_serializable() -> None:
    """The payload must survive json.dumps — it is written to disk as-is."""
    payload = _build_findings_payload(
        test_path=Path("wpt/foo/bar.html"),
        findings=[_sample_finding()],
        input_scope=_sample_scope(),
        conformance=None,
        run_metadata=_sample_metadata(),
    )
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload


def test_build_findings_payload_records_run_metadata() -> None:
    payload = _build_findings_payload(
        test_path=Path("wpt/foo/bar.html"),
        findings=[],
        input_scope=_sample_scope(),
        conformance=None,
        run_metadata=_sample_metadata(),
    )
    assert payload["run_metadata"] == {
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
    }


def test_build_findings_payload_conformance_is_none_without_spec() -> None:
    payload = _build_findings_payload(
        test_path=Path("wpt/foo/bar.html"),
        findings=[],
        input_scope=_sample_scope(),
        conformance=None,
        run_metadata=_sample_metadata(),
    )
    assert payload["conformance"] is None


def test_build_findings_payload_includes_conformance_section() -> None:
    conformance = ConformanceSection(
        specs=[
            SpecRequirements(
                spec_url="https://drafts.csswg.org/css-flexbox/",
                requirements_xml="x" * 2_048,
            )
        ],
        findings=[_conformance_finding()],
        input_scope=InputScope(strategy=EvaluatorStrategy.DISTILLED),
    )
    payload = _build_findings_payload(
        test_path=Path("wpt/foo/bar.html"),
        findings=[],
        input_scope=_sample_scope(),
        conformance=conformance,
        run_metadata=_sample_metadata(),
    )
    section = payload["conformance"]
    assert len(section["specs"]) == 1
    assert (
        section["specs"][0]["spec_url"]
        == "https://drafts.csswg.org/css-flexbox/"
    )
    assert section["specs"][0]["requirements_xml_bytes"] == 2_048
    assert len(section["findings"]) == 1
    assert section["input_scope"]["strategy"] == "distilled"


def test_render_basic_finding() -> None:
    """A single finding renders with all expected fields."""
    report = _render(
        test_path="wpt/css/css-flexbox/align-content_center.html",
        findings=[_sample_finding(rule_id="GENERAL-005")],
    )

    # Top-level header
    assert "# Findings: wpt/css/css-flexbox/align-content_center.html" in report

    # Finding section + fields
    assert "### Finding 1 — missing character encoding declaration" in report
    assert "**Rule**: `GENERAL-005`" in report
    assert "**Severity**: warn" in report
    assert "**Test line**: Lines 1-4" in report
    assert (
        "**Source**: `wpt/docs/writing-tests/general-guidelines.md:L82-L87`"
        in report
    )
    assert "**Summary**: HTML must declare encoding." in report

    # Evidence is code-fenced
    assert "```\n  <!DOCTYPE html>\n  ```" in report


def test_render_multiline_evidence_stays_inside_code_fence() -> None:
    """Multi-line evidence renders within a single fenced block."""
    evidence = "<head>\n  <title>foo</title>\n  <meta>"
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[_sample_finding(evidence=evidence)],
    )

    # Verify each line of the evidence is inside the fence (indented).
    assert "  <head>" in report
    assert "  <title>foo</title>" in report
    assert "  <meta>" in report

    # Verify the fenced block is well-formed: opening fence, content,
    # closing fence — and that we have exactly two fence markers for
    # this finding's evidence.
    fence_lines = [
        line for line in report.splitlines() if line.strip() == "```"
    ]
    assert len(fence_lines) == 2


def test_render_empty_findings_shows_fallback() -> None:
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
    )
    assert "No findings raised." in report
    # Input scope still renders.
    assert "## Input scope" in report


def test_render_input_scope_table_format() -> None:
    """The Input scope table uses comma-formatted bytes and a Total row."""
    scope = InputScope(
        files=[
            InputScopeFile(path="a.md", bytes=1_500, role="skill"),
            InputScopeFile(path="b.md", bytes=12_345, role="reading-list"),
            InputScopeFile(path="c.html", bytes=968, role="test"),
        ],
        strategy=EvaluatorStrategy.DISTILLED,
    )
    report = _render(test_path="wpt/c.html", findings=[], input_scope=scope)

    # Each row shows comma-formatted bytes.
    assert "| a.md | 1,500 | skill |" in report
    assert "| b.md | 12,345 | reading-list |" in report
    assert "| c.html | 968 | test |" in report
    # Total row matches total_bytes (1500 + 12345 + 968 = 14813).
    assert "**Total** | **14,813**" in report
    # Token estimate is total_bytes // 4 = 3703.
    assert "Approximate input tokens: ~3,703" in report


def test_render_no_dependencies_says_none() -> None:
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        input_scope=_sample_scope(dependencies_not_read=[]),
    )
    assert "Declared dependencies (not read): none" in report


def test_render_dependencies_comma_separated() -> None:
    deps = ["/resources/testharness.js", "http://example.com/foo.js"]
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        input_scope=_sample_scope(dependencies_not_read=deps),
    )
    assert (
        "Declared dependencies (not read): "
        "/resources/testharness.js, http://example.com/foo.js"
    ) in report


def test_render_strategy_label_appears() -> None:
    """The strategy label flows through to the rendered Markdown."""
    scope = _sample_scope(strategy=EvaluatorStrategy.RAW)
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        input_scope=scope,
    )
    assert "Strategy: raw" in report


# ---------------------------------------------------------------------------
# run_evaluation integration (agent mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def wpt_root_with_test(tmp_path: Path) -> tuple[Path, Path]:
    """Creates a fake WPT root with a single test file inside it."""
    wpt = tmp_path / "wpt"
    wpt.mkdir()
    test = wpt / "foo.html"
    test.write_text("<!doctype html><title>hi</title>", encoding="utf-8")
    return wpt, test


@pytest.fixture
def evaluation_config(
    wpt_root_with_test: tuple[Path, Path], tmp_path: Path
) -> Config:
    wpt_root, _ = wpt_root_with_test
    return Config(
        provider="anthropic",
        default_model="test-model",
        api_key="test-key",
        wpt_path=str(wpt_root),
        cache_path=str(tmp_path / "cache"),
        categories={"lightweight": "fast", "reasoning": "smart"},
        phase_model_mapping={
            "requirements_extraction": "reasoning",
            "coverage_audit": "reasoning",
            "generation": "lightweight",
        },
    )


@pytest.mark.asyncio
async def test_run_evaluation_writes_report_when_agent_succeeds(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Happy path: agent returns a payload, report is rendered and written."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    agent_payload = {
        "findings": [
            {
                "rule_id": "GENERAL-005",
                "title": "missing charset",
                "severity": "warn",
                "test_line": "Lines 1-4",
                "evidence": "<!doctype html>",
                "source": (
                    "wpt/docs/writing-tests/general-guidelines.md:L82-L87"
                ),
                "summary": "HTML must declare encoding.",
            }
        ],
        "input_scope": {
            "files": [{"path": "foo.html", "bytes": 30, "role": "test"}],
            "dependencies_not_read": [],
            "strategy": "distilled",
        },
    }

    mock_agent = mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(return_value=(agent_payload, TokenUsage())),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
    )

    assert report_path is not None
    assert report_path.is_file()
    contents = report_path.read_text(encoding="utf-8")
    assert "# Findings:" in contents
    assert "### Finding 1 — missing charset" in contents
    assert "Strategy: distilled" in contents
    mock_agent.assert_awaited_once()
    mock_ui.on_phase_start.assert_any_call(1, "Documentation Evaluation")
    mock_ui.report_findings_summary.assert_called_once()
    mock_ui.report_input_scope_summary.assert_called_once()
    mock_ui.report_token_usage_actual.assert_called_once()


@pytest.mark.asyncio
async def test_run_evaluation_returns_none_when_agent_returns_none(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Agent failure / empty response: no report file is written."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(return_value=None),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
    )

    assert report_path is None
    # The output directory should not have been populated with a report.
    assert not output_dir.exists() or not any(output_dir.iterdir())


# ---------------------------------------------------------------------------
# Spec conformance rendering
# ---------------------------------------------------------------------------


def _conformance_finding() -> Finding:
    return Finding(
        title="assertion contradicts requirement",
        severity="error",
        test_line="Line 42",
        evidence="assert_equals(getComputedStyle(el).flexBasis, '0px')",
        source="requirements.xml#R3",
        summary="Spec says flex-basis defaults to 'auto', not '0px'.",
    )


def test_render_conformance_skipped_when_none() -> None:
    """No conformance section means the report says 'skipped'."""
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        conformance=None,
    )
    assert "Conformance check: skipped (no spec provided)." in report
    # The conformance-finding heading shape should NOT appear.
    assert "Conformance finding" not in report


def test_render_conformance_with_findings() -> None:
    """A conformance section with findings renders them in their own block."""
    conformance = ConformanceSection(
        specs=[
            SpecRequirements(
                spec_url="https://drafts.csswg.org/css-flexbox/",
                requirements_xml="x" * 12_345,
            )
        ],
        findings=[_conformance_finding()],
        input_scope=InputScope(strategy=EvaluatorStrategy.DISTILLED),
    )
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        conformance=conformance,
    )
    assert "## Spec conformance" in report
    assert "**Spec**: https://drafts.csswg.org/css-flexbox/" in report
    assert "12,345 bytes" in report
    assert "### Conformance finding 1 — assertion contradicts requirement" in (
        report
    )
    assert "**Severity**: error" in report
    assert "**Source**: `requirements.xml#R3`" in report
    # Should not also render the "skipped" line.
    assert "Conformance check: skipped" not in report


def test_render_conformance_empty_findings_fallback() -> None:
    """Empty conformance findings show the no-findings fallback in the section."""
    conformance = ConformanceSection(
        specs=[
            SpecRequirements(
                spec_url="https://drafts.csswg.org/css-flexbox/",
                requirements_xml="x" * 2_048,
            )
        ],
        findings=[],
        input_scope=InputScope(strategy=EvaluatorStrategy.DISTILLED),
    )
    report = _render(
        test_path="wpt/foo/bar.html",
        findings=[],
        conformance=conformance,
    )
    assert "2,048 bytes" in report
    assert "No conformance findings raised." in report


# ---------------------------------------------------------------------------
# run_evaluation with conformance pass (both agents mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_evaluation_with_spec_url_runs_conformance_pass(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """When spec_url is provided, both agents run and conformance is rendered."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    doc_inputs_payload = {
        "findings": [],
        "input_scope": {
            "files": [{"path": "foo.html", "bytes": 30, "role": "test"}],
            "dependencies_not_read": [],
            "strategy": "raw",
        },
    }
    conformance_payload = {
        "findings": [
            {
                "title": "contradicts requirement",
                "severity": "error",
                "test_line": "Line 12",
                "evidence": "assert_equals(x, 'wrong')",
                "source": "requirements.xml#R1",
                "summary": "Spec requires 'right', not 'wrong'.",
            }
        ],
        "input_scope": {
            "files": [{"path": "foo.html", "bytes": 30, "role": "test"}],
            "dependencies_not_read": [],
            "strategy": "distilled",
        },
    }

    mock_doc_inputs = mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(return_value=(doc_inputs_payload, TokenUsage())),
    )
    mock_conformance = mocker.patch(
        "wptgen.phases.evaluation.evaluate_conformance_with_adk",
        new=AsyncMock(return_value=(conformance_payload, TokenUsage())),
    )
    mock_extract = mocker.patch(
        "wptgen.phases.evaluation._extract_requirements_for_spec",
        new=AsyncMock(return_value="<requirements_list/>"),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        spec_urls=["https://drafts.csswg.org/css-flexbox/"],
    )

    assert report_path is not None
    contents = report_path.read_text(encoding="utf-8")

    # Both agents were called.
    mock_doc_inputs.assert_awaited_once()
    mock_extract.assert_awaited_once()
    mock_conformance.assert_awaited_once()

    # Doc-inputs section renders empty findings.
    assert "No findings raised." in contents
    # Conformance section renders with the spec URL and the finding.
    assert "## Spec conformance" in contents
    assert "**Spec**: https://drafts.csswg.org/css-flexbox/" in contents
    assert "### Conformance finding 1 — contradicts requirement" in contents
    # Skipped message should not appear.
    assert "Conformance check: skipped" not in contents
    # Phase headers and findings summary fired for both passes.
    mock_ui.on_phase_start.assert_any_call(1, "Documentation Evaluation")
    mock_ui.on_phase_start.assert_any_call(
        3,
        "Spec Conformance Evaluation "
        "(https://drafts.csswg.org/css-flexbox/)",
    )
    mock_ui.report_findings_summary.assert_called_once()
    # Per-pass input-scope and token-usage summaries fire twice (one per pass).
    assert mock_ui.report_input_scope_summary.call_count == 2
    assert mock_ui.report_token_usage_actual.call_count == 2


@pytest.mark.asyncio
async def test_run_evaluation_multiple_specs_judged_in_one_pass(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Requirements are extracted per spec, but a single conformance pass
    judges the test against every spec at once (both in the agent's
    context), attributing findings back to each spec."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    doc_inputs_payload = {
        "findings": [],
        "input_scope": {
            "files": [],
            "dependencies_not_read": [],
            "strategy": "raw",
        },
    }

    spec_a = "https://drafts.csswg.org/css-flexbox/"
    spec_b = "https://drafts.csswg.org/css-grid/"

    # One conformance pass returns findings attributed to both specs.
    conformance_payload = {
        "findings": [
            {
                "title": "contradicts flexbox",
                "severity": "error",
                "test_line": "Line 12",
                "evidence": "assert_equals(x, 'wrong')",
                "source": f"{spec_a}#R1",
                "summary": "flexbox disagrees.",
            },
            {
                "title": "contradicts grid",
                "severity": "warn",
                "test_line": "Line 20",
                "evidence": "assert_true(y)",
                "source": f"{spec_b}#R4",
                "summary": "grid disagrees.",
            },
        ],
        "input_scope": {
            "files": [],
            "dependencies_not_read": [],
            "strategy": "distilled",
        },
    }

    mock_doc_inputs = mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(return_value=(doc_inputs_payload, TokenUsage())),
    )
    mock_conformance = mocker.patch(
        "wptgen.phases.evaluation.evaluate_conformance_with_adk",
        new=AsyncMock(return_value=(conformance_payload, TokenUsage())),
    )
    # Extraction still runs per spec, returning a distinct doc for each.
    mock_extract = mocker.patch(
        "wptgen.phases.evaluation._extract_requirements_for_spec",
        new=AsyncMock(side_effect=["<requirements a/>", "<requirements b/>"]),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        spec_urls=[spec_a, spec_b],
    )

    assert report_path is not None
    contents = report_path.read_text(encoding="utf-8")

    # Extraction per spec, but only ONE conformance pass over both.
    mock_doc_inputs.assert_awaited_once()
    assert mock_extract.await_count == 2
    mock_conformance.assert_awaited_once()

    # The single conformance call received both specs, each with its own XML.
    passed_specs = mock_conformance.await_args_list[0].kwargs["specs"]
    assert [s.spec_url for s in passed_specs] == [spec_a, spec_b]
    assert passed_specs[0].requirements_xml == "<requirements a/>"
    assert passed_specs[1].requirements_xml == "<requirements b/>"

    # One conformance section lists both specs and both attributed findings.
    assert f"**Spec**: {spec_a}" in contents
    assert f"**Spec**: {spec_b}" in contents
    assert "contradicts flexbox" in contents
    assert "contradicts grid" in contents
    assert f"**Source**: `{spec_a}#R1`" in contents
    assert f"**Source**: `{spec_b}#R4`" in contents
    assert "Conformance check: skipped" not in contents

    # A single conformance phase header fired, labeled with both specs.
    mock_ui.on_phase_start.assert_any_call(
        3, f"Spec Conformance Evaluation ({spec_a}, {spec_b})"
    )
    mock_ui.report_findings_summary.assert_called_once()


@pytest.mark.asyncio
async def test_run_evaluation_multi_spec_pulls_each_spec_from_cache(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """With two specs cached, each conformance pass gets *its own* cached XML."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    spec_a = "https://drafts.csswg.org/css-flexbox/"
    spec_b = "https://drafts.csswg.org/css-grid/"
    xml_a = '<requirements_list><requirement id="A1"/></requirements_list>'
    xml_b = '<requirements_list><requirement id="B1"/></requirements_list>'

    # run_evaluation resolves the cache dir relative to cwd; write the cache
    # files there under the real spec-slug names so a slug change breaks this.
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / DEFAULT_EVALUATOR_CACHE_DIR
    cache_dir.mkdir(parents=True)
    for url, xml in ((spec_a, xml_a), (spec_b, xml_b)):
        cache_file = cache_dir / f"{slug_for_spec_url(url)}__requirements.xml"
        cache_file.write_text(xml, encoding="utf-8")

    # Auto-accept the cache so no UI prompt is needed for the hit.
    evaluation_config.yes_cache = True

    mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(
            return_value=(
                {
                    "findings": [],
                    "input_scope": {
                        "files": [],
                        "dependencies_not_read": [],
                        "strategy": "raw",
                    },
                },
                TokenUsage(),
            )
        ),
    )
    # Spec text is per-URL, but it must never reach the LLM: the cache hits.
    mocker.patch(
        "wptgen.phases.evaluation.fetch_and_slice_spec",
        return_value="spec text",
    )
    mocker.patch(
        "wptgen.phases.evaluation.get_llm_client",
        return_value=MagicMock(),
    )
    # The extractor LLM. If a cache lookup misses, this fires — and we assert
    # it does not.
    mock_generate = mocker.patch(
        "wptgen.phases.utils.generate_safe",
        new=AsyncMock(return_value="<should-not-be-used/>"),
    )

    conformance_payload = {
        "findings": [],
        "input_scope": {
            "files": [],
            "dependencies_not_read": [],
            "strategy": "distilled",
        },
    }
    mock_conformance = mocker.patch(
        "wptgen.phases.evaluation.evaluate_conformance_with_adk",
        new=AsyncMock(return_value=(conformance_payload, TokenUsage())),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        spec_urls=[spec_a, spec_b],
    )

    assert report_path is not None
    # The cache satisfied both extractions — the extractor LLM never ran.
    mock_generate.assert_not_awaited()

    # The single conformance pass received each spec's own cached XML, keyed
    # to the right spec (a cross-spec cache collision would swap these).
    mock_conformance.assert_awaited_once()
    passed_specs = mock_conformance.await_args_list[0].kwargs["specs"]
    by_url = {s.spec_url: s.requirements_xml for s in passed_specs}
    assert by_url == {spec_a: xml_a, spec_b: xml_b}


@pytest.mark.asyncio
async def test_run_evaluation_without_spec_skips_conformance(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Without spec_urls, neither extraction nor conformance agent runs."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(
            return_value=(
                {
                    "findings": [],
                    "input_scope": {
                        "files": [],
                        "dependencies_not_read": [],
                        "strategy": "raw",
                    },
                },
                TokenUsage(),
            )
        ),
    )
    mock_conformance = mocker.patch(
        "wptgen.phases.evaluation.evaluate_conformance_with_adk",
        new=AsyncMock(),
    )
    mock_extract = mocker.patch(
        "wptgen.phases.evaluation._extract_requirements_for_spec",
        new=AsyncMock(),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        spec_urls=None,
    )

    assert report_path is not None
    contents = report_path.read_text(encoding="utf-8")
    assert "Conformance check: skipped (no spec provided)." in contents
    mock_extract.assert_not_awaited()
    mock_conformance.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_evaluation_with_spec_renders_skipped_when_extraction_fails(
    wpt_root_with_test: tuple[Path, Path],
    evaluation_config: Config,
    mock_ui: MagicMock,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """If extraction returns None (fetch failed), conformance is omitted but
    the raw-strategy report still writes."""
    _, test_path = wpt_root_with_test
    output_dir = tmp_path / "out"

    mocker.patch(
        "wptgen.phases.evaluation.evaluate_test_with_adk",
        new=AsyncMock(
            return_value=(
                {
                    "findings": [],
                    "input_scope": {
                        "files": [],
                        "dependencies_not_read": [],
                        "strategy": "raw",
                    },
                },
                TokenUsage(),
            )
        ),
    )
    mock_conformance = mocker.patch(
        "wptgen.phases.evaluation.evaluate_conformance_with_adk",
        new=AsyncMock(),
    )
    mocker.patch(
        "wptgen.phases.evaluation._extract_requirements_for_spec",
        new=AsyncMock(return_value=None),
    )

    report_path = await run_evaluation(
        test_path=test_path,
        output_dir=output_dir,
        config=evaluation_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        spec_urls=["https://drafts.csswg.org/css-flexbox/"],
    )

    assert report_path is not None
    contents = report_path.read_text(encoding="utf-8")
    # Conformance agent should NOT have been called.
    mock_conformance.assert_not_awaited()
    # Report degrades gracefully: shows "skipped" rather than half-rendered.
    assert "Conformance check: skipped (no spec provided)." in contents


# ---------------------------------------------------------------------------
# Findings summary + phase boundaries
# ---------------------------------------------------------------------------


def test_count_findings_tallies_by_severity() -> None:
    findings = [
        Finding("a", "error", "L1", "e", "s", "y"),
        Finding("b", "error", "L2", "e", "s", "y"),
        Finding("c", "warn", "L3", "e", "s", "y"),
        Finding("d", "info", "L4", "e", "s", "y"),
        Finding("e", "nit", "L5", "e", "s", "y"),
    ]
    counts = _count_findings(findings)
    assert counts == {"error": 2, "warn": 1, "info": 1, "nit": 1}


def test_count_findings_empty_list_zeroes_all_severities() -> None:
    counts = _count_findings([])
    assert counts == {"error": 0, "warn": 0, "info": 0, "nit": 0}


def test_count_findings_ignores_unknown_severity() -> None:
    """Defensive: an agent that emits a typo'd severity shouldn't crash."""
    findings = [
        Finding("a", "fatal", "L1", "e", "s", "y"),
        Finding("b", "warn", "L2", "e", "s", "y"),
    ]
    counts = _count_findings(findings)
    assert counts == {"error": 0, "warn": 1, "info": 0, "nit": 0}


def test_files_by_role_groups_input_scope_files() -> None:
    from wptgen.phases.evaluation import _files_by_role

    scope = InputScope(
        files=[
            InputScopeFile(path="a.md", bytes=10, role="skill"),
            InputScopeFile(path="b.md", bytes=20, role="reading-list"),
            InputScopeFile(path="c.md", bytes=30, role="reading-list"),
            InputScopeFile(path="d.html", bytes=40, role="test"),
        ],
    )
    assert _files_by_role(scope) == {
        "skill": 1,
        "reading-list": 2,
        "test": 1,
    }

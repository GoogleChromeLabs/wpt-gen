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
"""Evaluation phase — run the wpt-evaluator agent on a single test file."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from wptgen.agents.adk_conformance_evaluator import (
    evaluate_conformance_with_adk,
)
from wptgen.agents.adk_evaluator import evaluate_test_with_adk
from wptgen.agents.streaming import TokenUsage
from wptgen.agents.tools import _validate_safe_path
from wptgen.config import Config
from wptgen.context import fetch_and_slice_spec
from wptgen.llm import get_llm_client
from wptgen.models import WorkflowContext
from wptgen.phases.requirements_extraction import run_requirements_extraction
from wptgen.ui import UIProvider

DEFAULT_OUTPUT_DIR = Path(".wptgen/evaluator/outputs")
DEFAULT_CACHE_DIR = Path(".wptgen/evaluator/cache")


@dataclass
class Finding:
    """A single advisory finding produced by the evaluator."""

    title: str
    severity: str  # "error", "warn", "info", or "nit"
    test_line: str  # e.g. "Line 24" or "Lines 21-23" or "filename"
    evidence: str
    source: str  # e.g. "wpt/docs/writing-tests/general-guidelines.md:L82-L87"
    summary: str


@dataclass
class InputScopeFile:
    """A single row in the Input scope table."""

    path: str
    bytes: int
    role: str  # "skill", "reading-list", "rules", "test", "dependency"


@dataclass
class InputScope:
    """Records what the evaluator read in service of the evaluation."""

    files: list[InputScopeFile] = field(default_factory=list)
    dependencies_not_read: list[str] = field(default_factory=list)
    approach: str = "doc-inputs"

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes for f in self.files)

    @property
    def approximate_input_tokens(self) -> int:
        # Standard byte-to-token approximation for ASCII English text.
        return self.total_bytes // 4


@dataclass
class ConformanceSection:
    """Conformance pass results, rendered as a distinct section."""

    spec_url: str
    findings: list[Finding]
    input_scope: InputScope
    requirements_xml_bytes: int


class EvaluationReportRenderer:
    """Renders structured evaluator output into the report Markdown format."""

    def __init__(self) -> None:
        self.env = Environment(
            loader=PackageLoader("wptgen", "templates"),
            autoescape=select_autoescape(disabled_extensions=("jinja",)),
        )
        self.template = self.env.get_template("evaluator_report.jinja")

    def render(
        self,
        test_path: str,
        findings: list[Finding],
        input_scope: InputScope,
        conformance: ConformanceSection | None = None,
    ) -> str:
        return self.template.render(
            test_path=test_path,
            findings=findings,
            input_scope=input_scope,
            conformance=conformance,
        )


def _payload_to_findings(payload: list[dict[str, Any]]) -> list[Finding]:
    """Converts the agent's JSON-shaped findings payload into Finding objects.

    Tolerates missing fields by substituting empty strings — the renderer
    will display the gap rather than crash.
    """
    findings: list[Finding] = []
    for item in payload:
        findings.append(
            Finding(
                title=str(item.get("title", "")),
                severity=str(item.get("severity", "")),
                test_line=str(item.get("test_line", "")),
                evidence=str(item.get("evidence", "")),
                source=str(item.get("source", "")),
                summary=str(item.get("summary", "")),
            )
        )
    return findings


def _payload_to_input_scope(payload: dict[str, Any]) -> InputScope:
    """Converts the agent's JSON-shaped input scope payload into an InputScope."""
    files_raw = payload.get("files", []) or []
    files = [
        InputScopeFile(
            path=str(item.get("path", "")),
            bytes=int(item.get("bytes", 0) or 0),
            role=str(item.get("role", "")),
        )
        for item in files_raw
    ]
    deps = payload.get("dependencies_not_read", []) or []
    return InputScope(
        files=files,
        dependencies_not_read=[str(d) for d in deps],
        approach=str(payload.get("approach", "doc-inputs")),
    )


async def _extract_requirements_for_spec(
    spec_url: str,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
) -> str | None:
    """Fetches a spec URL and extracts normative requirements from it.

    Returns:
        The requirements XML, or None if the spec could not be fetched
        or the extractor failed.
    """
    spec_text = await asyncio.to_thread(
        fetch_and_slice_spec, spec_url, ui.warning
    )
    if not spec_text:
        ui.error(f"Failed to fetch spec content from {spec_url}.")
        return None

    context = WorkflowContext(spec_contents={spec_url: spec_text})
    llm = get_llm_client(config)
    cache_dir = Path.cwd() / DEFAULT_CACHE_DIR
    return await run_requirements_extraction(
        context, config, llm, ui, jinja_env, cache_dir
    )


async def run_evaluation(
    test_path: Path,
    output_dir: Path | None,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
    spec_url: str | None = None,
) -> Path | None:
    """Evaluates a single WPT test file.

    Args:
        test_path: Path to the test file to evaluate.
        output_dir: Directory where the findings report will be written.
            If None, defaults to `.wptgen/evaluator/outputs/` relative
            to the current working directory.
        config: The tool configuration.
        jinja_env: The Jinja2 environment (used for agent prompt rendering;
            the report renderer instantiates its own environment).
        ui: The UI provider.
        spec_url: Optional URL of the governing specification. When
            provided, a second conformance pass extracts requirements
            from the spec and judges the test's assertions against
            them. When None, only the doc-inputs pass runs.

    Returns:
        The path to the written findings report, or None if the
        doc-inputs agent did not produce one.
    """
    if not config.wpt_path:
        raise ValueError("WPT path is required to evaluate tests.")
    wpt_root = Path(config.wpt_path)

    test_path = _validate_safe_path(test_path, wpt_root)
    if not test_path.is_file():
        raise FileNotFoundError(f"Test file not found: {test_path}")

    ui.on_phase_start(1, "Documentation Evaluation")
    agent_result = await evaluate_test_with_adk(
        test_path=test_path,
        config=config,
        jinja_env=jinja_env,
        ui=ui,
    )

    if not agent_result:
        return None

    agent_payload, doc_inputs_tokens = agent_result
    findings = _payload_to_findings(agent_payload.get("findings", []) or [])
    input_scope = _payload_to_input_scope(
        agent_payload.get("input_scope", {}) or {}
    )
    _report_pass_summaries(ui, "Documentation", input_scope, doc_inputs_tokens)

    conformance: ConformanceSection | None = None
    if spec_url:
        requirements_xml = await _extract_requirements_for_spec(
            spec_url=spec_url,
            config=config,
            jinja_env=jinja_env,
            ui=ui,
        )
        if requirements_xml:
            ui.on_phase_start(3, "Spec Conformance Evaluation")
            conformance_result = await evaluate_conformance_with_adk(
                test_path=test_path,
                requirements_xml=requirements_xml,
                config=config,
                jinja_env=jinja_env,
                ui=ui,
            )
            if conformance_result:
                conformance_payload, conformance_tokens = conformance_result
                conformance_scope = _payload_to_input_scope(
                    conformance_payload.get("input_scope", {}) or {}
                )
                conformance = ConformanceSection(
                    spec_url=spec_url,
                    findings=_payload_to_findings(
                        conformance_payload.get("findings", []) or []
                    ),
                    input_scope=conformance_scope,
                    requirements_xml_bytes=len(
                        requirements_xml.encode("utf-8")
                    ),
                )
                _report_pass_summaries(
                    ui,
                    "Spec conformance",
                    conformance_scope,
                    conformance_tokens,
                )

    ui.report_findings_summary(
        doc_inputs_counts=_count_findings(findings),
        conformance_counts=(
            _count_findings(conformance.findings) if conformance else None
        ),
    )

    renderer = EvaluationReportRenderer()
    report_markdown = renderer.render(
        test_path=str(test_path),
        findings=findings,
        input_scope=input_scope,
        conformance=conformance,
    )

    if output_dir is None:
        output_dir = Path.cwd() / DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{test_path.name}.md"
    output_path.write_text(report_markdown, encoding="utf-8")
    return output_path


def _count_findings(findings: list[Finding]) -> dict[str, int]:
    """Tallies findings by severity for the CLI summary."""
    counts: dict[str, int] = {"error": 0, "warn": 0, "info": 0, "nit": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    return counts


def _files_by_role(input_scope: InputScope) -> dict[str, int]:
    """Tallies input-scope file counts grouped by role."""
    counts: dict[str, int] = {}
    for file in input_scope.files:
        counts[file.role] = counts.get(file.role, 0) + 1
    return counts


def _report_pass_summaries(
    ui: UIProvider,
    label: str,
    input_scope: InputScope,
    tokens: TokenUsage,
) -> None:
    """Emits the input-scope and token-usage summaries for a finished pass."""
    ui.report_input_scope_summary(
        label=label,
        files_by_role=_files_by_role(input_scope),
        total_bytes=input_scope.total_bytes,
        approximate_tokens=input_scope.approximate_input_tokens,
    )
    ui.report_token_usage_actual(
        label=label,
        prompt_tokens=tokens.prompt_tokens,
        candidates_tokens=tokens.candidates_tokens,
        total_tokens=tokens.total_tokens,
    )

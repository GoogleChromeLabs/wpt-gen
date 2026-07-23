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
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from wptgen.agents.adk_conformance_evaluator import (
    SpecRequirements,
    evaluate_conformance_with_adk,
)
from wptgen.agents.adk_evaluator import (
    DEFAULT_EVALUATOR_STRATEGY,
    EvaluatorStrategy,
    evaluate_test_with_adk,
)
from wptgen.agents.streaming import TokenUsage
from wptgen.agents.tools import _validate_safe_path
from wptgen.config import (
    DEFAULT_EVALUATOR_CACHE_DIR,
    DEFAULT_EVALUATOR_OUTPUT_DIR,
    Config,
)
from wptgen.context import fetch_and_slice_spec
from wptgen.llm import get_llm_client
from wptgen.models import WorkflowContext
from wptgen.phases.requirements_extraction import run_requirements_extraction
from wptgen.ui import UIProvider


@dataclass
class Finding:
    """A single advisory finding produced by the evaluator."""

    title: str
    severity: str  # "error", "warn", "info", or "nit"
    test_line: str  # e.g. "Line 24" or "Lines 21-23" or "filename"
    evidence: str
    source: str  # e.g. "wpt/docs/writing-tests/general-guidelines.md:L82-L87"
    summary: str
    rule_id: str = (
        ""  # e.g. "GENERAL-005"; empty for findings not tied to a rule
    )


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
    # Which reading strategy produced this scope: "distilled" (judge against
    # the distilled rules corpus / extracted requirements) or "raw" (read the
    # upstream docs / spec directly).
    strategy: EvaluatorStrategy = EvaluatorStrategy.DISTILLED

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes for f in self.files)

    @property
    def approximate_input_tokens(self) -> int:
        # Standard byte-to-token approximation for ASCII English text.
        return self.total_bytes // 4


@dataclass
class ConformanceSection:
    """Conformance pass results, rendered as a distinct section.

    A single judging pass covers every governing spec at once, so `specs`
    lists each spec that was judged and `findings` are attributed back to a
    spec via each finding's `source`.
    """

    specs: list[SpecRequirements]
    findings: list[Finding]
    input_scope: InputScope


class EvaluationReportRenderer:
    """Renders the findings payload into the report Markdown format."""

    def __init__(self) -> None:
        self.env = Environment(
            loader=PackageLoader("wptgen", "templates"),
            autoescape=select_autoescape(disabled_extensions=("jinja",)),
        )
        self.template = self.env.get_template("evaluator_report.jinja")

    def render_from_payload(self, payload: dict[str, Any]) -> str:
        return self.template.render(**payload)


def _build_findings_payload(
    test_path: Path,
    findings: list[Finding],
    input_scope: InputScope,
    conformance: ConformanceSection | None,
    run_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Assembles the machine-readable findings payload.

    The payload is the source of truth for both the JSON output and the
    rendered Markdown report, so downstream tooling (e.g. the benchmark
    harness) consumes exactly what the report shows.

    ``run_metadata`` records how this evaluation was produced (provider,
    model). It travels with the findings so consumers know which model
    generated them without re-deriving it from config that may since have
    changed.
    """
    payload: dict[str, Any] = {
        "test_path": str(test_path),
        "run_metadata": run_metadata,
        "findings": [asdict(f) for f in findings],
        "input_scope": _input_scope_to_payload(input_scope),
        "conformance": None,
    }
    if conformance is not None:
        payload["conformance"] = {
            "specs": [
                {
                    "spec_url": spec.spec_url,
                    "requirements_xml_bytes": spec.requirements_xml_bytes,
                }
                for spec in conformance.specs
            ],
            "findings": [asdict(f) for f in conformance.findings],
            "input_scope": _input_scope_to_payload(conformance.input_scope),
        }
    return payload


def _input_scope_to_payload(input_scope: InputScope) -> dict[str, Any]:
    """Serializes an InputScope, including its derived totals."""
    return {
        "files": [asdict(f) for f in input_scope.files],
        "dependencies_not_read": list(input_scope.dependencies_not_read),
        "strategy": input_scope.strategy,
        "total_bytes": input_scope.total_bytes,
        "approximate_input_tokens": input_scope.approximate_input_tokens,
    }


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
                rule_id=str(item.get("rule_id", "")),
            )
        )
    return findings


def _payload_to_input_scope(payload: dict[str, Any]) -> InputScope:
    """Converts the agent's JSON payload into an InputScope."""
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
    try:
        strategy = EvaluatorStrategy(payload.get("strategy", "distilled"))
    except ValueError:
        strategy = EvaluatorStrategy.DISTILLED
    return InputScope(
        files=files,
        dependencies_not_read=[str(d) for d in deps],
        strategy=strategy,
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
    cache_dir = Path.cwd() / DEFAULT_EVALUATOR_CACHE_DIR
    return await run_requirements_extraction(
        context, config, llm, ui, jinja_env, cache_dir
    )


async def _gather_spec_requirements(
    spec_urls: list[str],
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
) -> list[SpecRequirements]:
    """Extracts (and caches) requirements for each spec, one at a time.

    Extraction stays per-spec so each spec keeps its own cached requirements
    XML. A spec that cannot be fetched or extracted is skipped (one bad spec
    does not sink the rest).
    """
    gathered: list[SpecRequirements] = []
    for spec_url in spec_urls:
        requirements_xml = await _extract_requirements_for_spec(
            spec_url=spec_url,
            config=config,
            jinja_env=jinja_env,
            ui=ui,
        )
        if requirements_xml:
            gathered.append(
                SpecRequirements(
                    spec_url=spec_url, requirements_xml=requirements_xml
                )
            )
    return gathered


async def _run_conformance(
    specs: list[SpecRequirements],
    test_path: Path,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
) -> ConformanceSection | None:
    """Judges the test against every spec in a single conformance pass."""
    if not specs:
        return None

    label = ", ".join(s.spec_url for s in specs)
    ui.on_phase_start(3, f"Spec Conformance Evaluation ({label})")
    conformance_result = await evaluate_conformance_with_adk(
        test_path=test_path,
        specs=specs,
        config=config,
        jinja_env=jinja_env,
        ui=ui,
    )
    if not conformance_result:
        return None

    conformance_payload, conformance_tokens = conformance_result
    conformance_scope = _payload_to_input_scope(
        conformance_payload.get("input_scope", {}) or {}
    )
    _report_pass_summaries(
        ui,
        "Spec conformance",
        conformance_scope,
        conformance_tokens,
    )
    return ConformanceSection(
        specs=specs,
        findings=_payload_to_findings(
            conformance_payload.get("findings", []) or []
        ),
        input_scope=conformance_scope,
    )


async def run_evaluation(
    test_path: Path,
    output_dir: Path | None,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
    spec_urls: list[str] | None = None,
    strategy: EvaluatorStrategy = DEFAULT_EVALUATOR_STRATEGY,
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
        spec_urls: Optional URLs of the governing specification(s). When
            provided, a conformance pass runs per spec: each spec's
            normative requirements are extracted and the test's assertions
            judged against them, producing one conformance section per
            spec. When None or empty, only the documentation pass runs.
        strategy: Which evaluator strategy to use for the documentation
            pass — `"distilled"` (default; judges against the distilled
            rules corpus) or `"raw"` (reads the curated upstream docs
            live).

    Returns:
        The path to the written findings report, or None if the
        documentation-pass agent did not produce one.
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
        strategy=strategy,
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
    specs = await _gather_spec_requirements(
        spec_urls or [], config, jinja_env, ui
    )
    if specs:
        conformance = await _run_conformance(
            specs=specs,
            test_path=test_path,
            config=config,
            jinja_env=jinja_env,
            ui=ui,
        )

    ui.report_findings_summary(
        doc_inputs_counts=_count_findings(findings),
        conformance_counts=(
            _count_findings(conformance.findings) if conformance else None
        ),
    )

    if output_dir is None:
        output_dir = Path.cwd() / DEFAULT_EVALUATOR_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    run_metadata: dict[str, Any] = {
        "provider": config.provider,
        "model": config.default_model,
    }
    payload = _build_findings_payload(
        test_path=test_path,
        findings=findings,
        input_scope=input_scope,
        conformance=conformance,
        run_metadata=run_metadata,
    )
    json_output_path = output_dir / f"{test_path.name}.json"
    json_output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    renderer = EvaluationReportRenderer()
    report_markdown = renderer.render_from_payload(payload)
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

"""Evaluation phase — run the wpt-evaluator agent on a single test file."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from wptgen.agents.adk_evaluator import evaluate_test_with_adk
from wptgen.agents.tools import _validate_safe_path
from wptgen.config import Config
from wptgen.ui import UIProvider


DEFAULT_OUTPUT_DIR = Path(".wptgen/evaluator/outputs")


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
    ) -> str:
        return self.template.render(
            test_path=test_path,
            findings=findings,
            input_scope=input_scope,
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


async def run_evaluation(
    test_path: Path,
    output_dir: Path | None,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
) -> Path | None:
    """Evaluates a single WPT test file.

    Args:
        test_path: Path to the test file to evaluate.
        output_dir: Directory where the findings report will be written.
            If None, defaults to `.wpt-evaluator-tmp/outputs/` relative
            to the current working directory.
        config: The tool configuration.
        jinja_env: The Jinja2 environment (used for agent prompt rendering;
            the report renderer instantiates its own environment).
        ui: The UI provider.

    Returns:
        The path to the written findings report, or None if the agent
        did not produce one.
    """
    if not config.wpt_path:
        raise ValueError("WPT path is required to evaluate tests.")
    wpt_root = Path(config.wpt_path)

    # The test under evaluation must live inside the configured WPT root.
    test_path = _validate_safe_path(test_path, wpt_root)
    if not test_path.is_file():
        raise FileNotFoundError(f"Test file not found: {test_path}")

    agent_result = await evaluate_test_with_adk(
        test_path=test_path,
        config=config,
        jinja_env=jinja_env,
        ui=ui,
    )

    if not agent_result:
        return None

    findings = _payload_to_findings(agent_result.get("findings", []) or [])
    input_scope = _payload_to_input_scope(
        agent_result.get("input_scope", {}) or {}
    )

    renderer = EvaluationReportRenderer()
    report_markdown = renderer.render(
        test_path=str(test_path),
        findings=findings,
        input_scope=input_scope,
    )

    if output_dir is None:
        output_dir = Path.cwd() / DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{test_path.name}.md"
    output_path.write_text(report_markdown, encoding="utf-8")
    return output_path

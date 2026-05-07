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

"""Data models and enums for the WPT generation workflow."""

from dataclasses import asdict, dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any


class WorkflowError(Exception):
    """Raised when a phase of the workflow fails to complete."""


class WorkflowAborted(Exception):
    """Exception raised when a workflow step is aborted by user or policy."""


class WorkflowPhase(StrEnum):
    """Enumeration of the phases in the WPT generation workflow."""

    CONTEXT_ASSEMBLY = "context_assembly"
    REQUIREMENTS_EXTRACTION = "requirements_extraction"
    COVERAGE_AUDIT = "coverage_audit"
    GENERATION = "generation"


class TestType(Enum):
    """Enumeration of WPT test types."""

    __test__ = False
    JAVASCRIPT = "JavaScript Test"
    REFTEST = "Reftest"
    CRASHTEST = "Crashtest"


REQUIREMENT_CATEGORIES = [
    (
        "Existence",
        "Rules defining the feature's surface area (interfaces, methods, "
        "properties).",
    ),
    (
        "Common Use Cases",
        "Rules defining successful behaviors, processing models, and "
        'realistic "happy paths."',
    ),
    (
        "Error Scenarios",
        "Rules defining error conditions, thrown exceptions, and invalid "
        "states.",
    ),
    (
        "Invalidation",
        "Rules regarding caching, state changes, and dynamic updates, if any.",
    ),
    (
        "Integration",
        "Rules defining mandatory interactions with other platform features, "
        "if any.",
    ),
]


class DataSource(StrEnum):
    """Source of web feature metadata."""

    WEB_FEATURES = "web-features"
    CHROMESTATUS = "chromestatus"


class BrowserType(StrEnum):
    """Supported browser engines."""

    CHROME = "chrome"
    FIREFOX = "firefox"
    SAFARI = "safari"
    EDGE = "edge"


class BrowserChannel(StrEnum):
    """Browser release channels."""

    CANARY = "canary"
    NIGHTLY = "nightly"
    STABLE = "stable"
    DEV = "dev"


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    GEMINI = "gemini"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ModelCategory(StrEnum):
    """Categories of LLM models used in the workflow."""

    DEFAULT = "default"
    LIGHTWEIGHT = "lightweight"
    REASONING = "reasoning"


@dataclass(frozen=True)
class ProviderDefaults:
    """Default configuration for an LLM provider."""

    env_var: str
    default_model: str


@dataclass
class FeatureMetadata:
    """Metadata for a web feature."""

    name: str
    description: str
    specs: list[str]
    source: DataSource = DataSource.WEB_FEATURES
    explainer_links: list[str] = field(default_factory=list)
    wpt_descr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converts the metadata to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeatureMetadata":
        """Creates a FeatureMetadata instance from a dictionary."""
        return cls(**data)


@dataclass
class WPTContext:
    """Holds results of local WPT content and dependency fetch operation."""

    test_contents: dict[str, str] = field(default_factory=dict)
    dependency_contents: dict[str, str] = field(default_factory=dict)
    test_to_deps: dict[str, set[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converts the context to a dictionary, serializing sets as lists."""
        data = asdict(self)
        # Convert sets to lists for JSON serialization
        data["test_to_deps"] = {
            k: list(v) for k, v in self.test_to_deps.items()
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WPTContext":
        """Creates a WPTContext instance from a dictionary."""
        # Convert lists back to sets
        if "test_to_deps" in data:
            data["test_to_deps"] = {
                k: set(v) for k, v in data["test_to_deps"].items()
            }
        return cls(**data)


@dataclass
class WorkflowContext:
    """Maintains the state of the WPT generation workflow."""

    feature_id: str | None = None
    metadata: FeatureMetadata | None = None
    spec_contents: dict[str, str] | None = None
    explainer_contents: dict[str, str] | None = None
    wpt_context: WPTContext | None = None
    requirements_xml: str | None = None
    audit_response: str | None = None
    suggestions: list[str] = field(default_factory=list)
    approved_suggestions_xml: list[str] = field(default_factory=list)
    mdn_contents: list[str] | None = None
    generated_tests: list[tuple[Path, str, str]] | None = None
    wpt_urls: list[str] | None = None
    markdown_report: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converts the context to a dictionary."""
        data = {
            "feature_id": self.feature_id,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "spec_contents": self.spec_contents,
            "explainer_contents": self.explainer_contents,
            "wpt_context": (
                self.wpt_context.to_dict() if self.wpt_context else None
            ),
            "requirements_xml": self.requirements_xml,
            "audit_response": self.audit_response,
            "suggestions": self.suggestions,
            "approved_suggestions_xml": self.approved_suggestions_xml,
            "mdn_contents": self.mdn_contents,
            "generated_tests": (
                [(str(p), c, s) for p, c, s in self.generated_tests]
                if self.generated_tests
                else None
            ),
            "wpt_urls": self.wpt_urls,
            "markdown_report": self.markdown_report,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowContext":
        """Creates a WorkflowContext instance from a dictionary."""
        metadata = (
            FeatureMetadata.from_dict(data["metadata"])
            if data.get("metadata")
            else None
        )
        wpt_context = (
            WPTContext.from_dict(data["wpt_context"])
            if data.get("wpt_context")
            else None
        )
        generated_tests = None
        if data.get("generated_tests"):
            generated_tests = [
                (Path(p), c, s) for p, c, s in data["generated_tests"]
            ]

        spec_contents = data.get("spec_contents")
        if isinstance(spec_contents, str):
            # Fallback for old cache format
            spec_url = (
                metadata.specs[0] if metadata and metadata.specs else "unknown"
            )
            spec_contents = {spec_url: spec_contents}

        return cls(
            feature_id=data["feature_id"],
            metadata=metadata,
            spec_contents=spec_contents,
            explainer_contents=data.get("explainer_contents"),
            wpt_context=wpt_context,
            requirements_xml=data.get("requirements_xml"),
            audit_response=data.get("audit_response"),
            suggestions=data.get("suggestions", []),
            approved_suggestions_xml=data.get("approved_suggestions_xml", []),
            mdn_contents=data.get("mdn_contents"),
            generated_tests=generated_tests,
            wpt_urls=data.get("wpt_urls"),
            markdown_report=data.get("markdown_report"),
        )

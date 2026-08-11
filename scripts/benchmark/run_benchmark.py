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
"""WPT evaluator benchmark harness.

Runs the real ``wpt-gen evaluate`` CLI over the manifest corpus, N times per
entry, then scores the JSON outputs.

    python scripts/benchmark/run_benchmark.py \\
      --manifest benchmarks/manifest.yaml \\
      --wpt-dir ~/dev/wpt \\
      --repeats 8 \\
      --out bench-runs/2026-07-16/ \\
      [--provider …] [--filter kind=reftest] [--score-only]

Design notes:
- Scoring math lives in scoring.py; manifest parsing/validation in
  manifest.py. Both are pure and unit-tested (tests/benchmark/), so this
  file stays thin orchestration.
- Seeds are copied into ``<wpt_dir>/wpt-gen-bench/`` because run_evaluation
  requires the test to live inside the checkout (``_validate_safe_path``).
  The harness refuses to run if that dir already exists and it did not
  create it, and removes what it staged on exit.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

# Puts the package's parent (scripts/) on the path so it resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.manifest import (  # noqa: E402
    GOLDEN_STAGING_SUBDIR,
    REPO_ROOT,
    STAGING_DIRNAME,
    BenchmarkEntry,
    CorpusEntry,
    GoldenEntry,
    Manifest,
    ManifestError,
    SeedEntry,
    load_golden_entries,
    load_manifest,
    validate_against_checkout,
)
from benchmark.scoring import (  # noqa: E402
    ConsistencyClassification,
    ConsistencyRow,
    EntryRuns,
    GoldenScore,
    MechanicalIssue,
    SeedScore,
    classify_consistency_rows,
    consistency_histogram,
    consistency_rows,
    load_entry_runs,
    mechanical_issues,
    score_golden,
    score_seed,
    warnings_for_row,
)

# Seeds are staged into ``<wpt_dir>/<STAGING_DIRNAME>/``. A marker file
# records that this run created it, so cleanup never deletes a directory the
# harness did not make.
STAGING_MARKER = ".wpt-gen-bench-created"


class HarnessError(Exception):
    """A fatal harness condition (bad checkout state, staging conflict)."""


# --- Manifest filtering -----------------------------------------------------


def apply_filter(
    entries: list[BenchmarkEntry], filter_expr: str | None
) -> list[BenchmarkEntry]:
    """Applies a ``field=value`` filter (currently ``kind=`` / ``role=``)."""
    if not filter_expr:
        return entries
    if "=" not in filter_expr:
        raise HarnessError(f"--filter must be field=value, got {filter_expr!r}")
    field_name, _, value = filter_expr.partition("=")
    field_name = field_name.strip()
    value = value.strip()
    if field_name == "kind":
        return [e for e in entries if e.kind == value]
    if field_name == "role":
        return [e for e in entries if _role_of(e) == value]
    raise HarnessError(
        f'--filter supports "kind" and "role", not {field_name!r}'
    )


# --- Seed staging -----------------------------------------------------------


def _ensure_staging(wpt_dir: Path) -> Path:
    """Creates the marker-protected staging root (idempotent within a run).

    Refuses if the dir already exists without the harness's marker (never
    clobber a real directory); otherwise (re)creates it fresh on first call.
    """
    staging = wpt_dir / STAGING_DIRNAME
    if staging.exists():
        if not (staging / STAGING_MARKER).exists():
            raise HarnessError(
                f"{staging} already exists and was not created by the "
                "harness; refusing to overwrite. Remove it and re-run."
            )
        return staging
    staging.mkdir(parents=True)
    (staging / STAGING_MARKER).write_text(
        "Created by scripts/benchmark/run_benchmark.py; safe to delete.\n",
        encoding="utf-8",
    )
    return staging


def stage_seeds(
    seeds_root: Path, wpt_dir: Path, seeds: list[SeedEntry]
) -> Path:
    """Stages seed files into ``<wpt_dir>/wpt-gen-bench/``.

    Returns the staging dir.
    """
    staging = _ensure_staging(wpt_dir)

    for entry in seeds:
        assert entry.seed is not None
        src = seeds_root / entry.seed
        dest_abs = wpt_dir / entry.test_rel_path()
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_abs)

        # Carry a sibling references/ dir (reftest references), preserving the
        # test-relative path the <link rel=match> uses.
        refs_src = src.parent / "references"
        if refs_src.is_dir():
            shutil.copytree(
                refs_src, dest_abs.parent / "references", dirs_exist_ok=True
            )

    return staging


def stage_golden(wpt_dir: Path, entries: list[GoldenEntry]) -> Path:
    """Decodes each golden entry's test bytes into the staging root.

    All of the chosen commit block's ``files_b64`` are written (so a test's
    same-commit siblings are present), under
    ``<staging>/golden/<pr>/<path>``. Returns the staging dir.
    """
    staging = _ensure_staging(wpt_dir)
    for entry in entries:
        for rel_path, content_b64 in entry.files_b64.items():
            dest_abs = (
                staging / GOLDEN_STAGING_SUBDIR / str(entry.pr) / rel_path
            )
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            dest_abs.write_bytes(base64.b64decode(content_b64))
    return staging


def unstage(wpt_dir: Path) -> None:
    """Removes the staging dir, but only if the harness created it."""
    staging = wpt_dir / STAGING_DIRNAME
    if staging.exists() and (staging / STAGING_MARKER).exists():
        shutil.rmtree(staging)


# --- Running the evaluator --------------------------------------------------


@dataclass
class RunRecord:
    """Outcome metadata for one (entry, repeat) evaluator invocation."""

    entry_id: str
    repeat: int
    exit_code: int
    wall_seconds: float
    output_dir: str


def _rep_dir(out: Path, entry_id: str, repeat: int) -> Path:
    return out / "runs" / entry_id / f"rep-{repeat}"


class Progress:
    """Prints one atomic completion line per evaluator invocation.

    Workers run concurrently, each worker emits a single line when its run
    finishes. The counter increment and write are lock-guarded.
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0
        self._lock = threading.Lock()

    def start(self, entry_id: str, repeat: int) -> None:
        with self._lock:
            sys.stderr.write(f"[started] {entry_id} rep {repeat + 1}\n")
            sys.stderr.flush()

    def complete(
        self, entry_id: str, repeat: int, exit_code: int, elapsed: float
    ) -> None:
        status = "ok" if exit_code == 0 else f"FAILED ({exit_code})"
        with self._lock:
            self.done += 1
            sys.stderr.write(
                f"[{self.done}/{self.total}] {entry_id} rep {repeat + 1} "
                f"{status} {elapsed:.1f}s\n"
            )
            sys.stderr.flush()


def run_single(
    entry: BenchmarkEntry,
    repeat: int,
    wpt_dir: Path,
    out: Path,
    provider: str | None,
    config: Path,
    progress: Progress | None = None,
) -> RunRecord:
    """Invokes ``wpt-gen evaluate`` once for one (entry, repeat) pair."""
    rep_dir = _rep_dir(out, entry.entry_id, repeat)
    rep_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "wpt-gen",
        "evaluate",
        str(wpt_dir / entry.test_rel_path()),
        "--wpt-dir",
        str(wpt_dir),
        "--output-dir",
        str(rep_dir),
        "--config",
        str(config),
    ]
    if provider:
        cmd += ["--provider", provider]

    if progress:
        progress.start(entry.entry_id, repeat)
    started = time.monotonic()
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    if progress:
        progress.complete(entry.entry_id, repeat, completed.returncode, elapsed)
    if completed.returncode != 0:
        # Record it and move on; an errored repeat scores as an empty run
        # (no findings) and still counts in the denominator.
        sys.stderr.write(
            f"[warn] {entry.entry_id} rep-{repeat} exited "
            f"{completed.returncode}\n{completed.stderr}\n"
        )
    return RunRecord(
        entry_id=entry.entry_id,
        repeat=repeat,
        exit_code=completed.returncode,
        wall_seconds=elapsed,
        output_dir=str(rep_dir),
    )


# --- Scoring an entry from its run dirs -------------------------------------


@dataclass
class EntryReport:
    """Everything scored for one entry, ready to serialize."""

    entry_id: str
    role: str
    kind: str
    num_repeats: int
    # Flat list of every consistency row (all keys/buckets).
    consistency: list[dict[str, Any]]
    consistency_histogram: dict[str, int]
    seed_score: dict[str, Any] | None
    # Recall-vs-human for golden entries; None otherwise.
    golden_score: dict[str, Any] | None
    # For seed entries: consistency rows bracketed by gold-label match, plus
    # any missed labels. None for corpus entries (no labels to classify by).
    consistency_by_outcome: dict[str, Any] | None
    # Source-citation warnings — findings whose `source` cites a doc not on
    # the skill's reading list. Advisory: reported, not scored.
    advisory_notes: list[dict[str, Any]]
    test_rel_path: str = ""


def _consistency_row_to_dict(
    row: ConsistencyRow, notes: list[MechanicalIssue]
) -> dict[str, Any]:
    return {
        "key": row.key,
        "title": row.title,
        "severity": row.severity,
        "line_bucket": list(row.line_bucket) if row.line_bucket else None,
        "firings": row.firings,
        "repeats": row.repeats,
        "rate": round(row.rate, 4),
        # Advisory-note counts for this specific finding, e.g. {"evidence": 2}.
        "warnings": warnings_for_row(row, notes),
    }


def _classification_to_dict(
    classification: ConsistencyClassification,
    notes: list[MechanicalIssue],
) -> dict[str, Any]:
    return {
        "true_positives": [
            _consistency_row_to_dict(r, notes)
            for r in classification.true_positives
        ],
        "false_positives": [
            _consistency_row_to_dict(r, notes)
            for r in classification.false_positives
        ],
        "missed_labels": [
            {
                "key": label.key,
                "line_window": (
                    list(label.line_window) if label.line_window else None
                ),
            }
            for label in classification.missed_labels
        ],
    }


def _seed_score_to_dict(score: SeedScore) -> dict[str, Any]:
    return {
        "true_positives": score.true_positives,
        "false_positives": score.false_positives,
        "false_negatives": score.false_negatives,
        "precision": round(score.precision, 4),
        "recall": round(score.recall, 4),
        "per_repeat_recall": [round(r, 4) for r in score.per_repeat_recall],
    }


def _golden_score_to_dict(score: GoldenScore) -> dict[str, Any]:
    return {
        "true_positives": score.true_positives,
        "false_negatives": score.false_negatives,
        "unmatched_predictions": score.unmatched_predictions,
        "recall": round(score.recall, 4),
        "per_repeat_recall": [round(r, 4) for r in score.per_repeat_recall],
    }


# --- Top-level scoring pass -------------------------------------------------


@dataclass
class BenchmarkReport:
    """The full scored benchmark, serialized to report.json."""

    manifest: str
    provider: str | None
    model: str | None
    wpt_dir: str
    wpt_upstream_commit_expected: str | None
    wpt_upstream_commit_actual: str | None
    repeats: int
    entries: list[dict[str, Any]]
    run_records: list[dict[str, Any]]
    aggregate: dict[str, Any]
    quality_thresholds: dict[str, Any] | None = None
    quality_gate_failures: list[str] = field(default_factory=list)


class EntryRole(StrEnum):
    """The dataset role of a benchmark entry."""

    SEED = "seed"
    GOLDEN = "golden"
    CORPUS = "corpus"


class ConsistencyBucket(StrEnum):
    """Consistency histogram bucket categories."""

    ALWAYS = "always"
    HIGH = "high"
    MID = "mid"
    LOW = "low"
    NEVER = "never"


def _role_of(entry: BenchmarkEntry) -> EntryRole:
    """The role label ("seed" | "golden" | "corpus") for report metadata."""
    if isinstance(entry, SeedEntry):
        return EntryRole.SEED
    if isinstance(entry, GoldenEntry):
        return EntryRole.GOLDEN
    return EntryRole.CORPUS


def score_all(
    manifest: Manifest,
    entries: list[BenchmarkEntry],
    out: Path,
    repeats: int,
    reading_list: set[str],
) -> tuple[list[EntryReport], set[tuple[str, str]]]:
    """Loads every entry's run dirs and scores them."""
    reports: list[EntryReport] = []
    models: set[tuple[str, str]] = set()
    for entry in entries:
        repeat_dirs = [_rep_dir(out, entry.entry_id, i) for i in range(repeats)]
        runs = load_entry_runs(
            entry_id=entry.entry_id,
            role=_role_of(entry),
            repeat_dirs=repeat_dirs,
            test_file_name=entry.test_file_name(),
        )
        models |= runs.models
        reports.append(score_entry(entry, runs, reading_list))
    return reports, models


def score_entry(
    entry: BenchmarkEntry,
    runs: EntryRuns,
    reading_list: set[str],
) -> EntryReport:
    """Scores a single entry from its loaded runs."""
    cons_rows = consistency_rows(runs)

    notes: list[MechanicalIssue] = []
    for i, repeat in enumerate(runs.repeats):
        notes.extend(
            mechanical_issues(
                entry_id=entry.entry_id,
                repeat_index=i,
                predictions=repeat,
                reading_list=reading_list,
            )
        )
    seed_score_dict: dict[str, Any] | None = None
    golden_score_dict: dict[str, Any] | None = None
    classification_dict: dict[str, Any] | None = None
    if isinstance(entry, SeedEntry):
        score = score_seed(runs, entry.expect)
        seed_score_dict = _seed_score_to_dict(score)
        classification_dict = _classification_to_dict(
            classify_consistency_rows(cons_rows, entry.expect), notes
        )
    elif isinstance(entry, GoldenEntry):
        golden_score_dict = _golden_score_to_dict(
            score_golden(runs, entry.expect)
        )
        # Same classifier as seeds; renders TP vs. unmatched (uncharged).
        classification_dict = _classification_to_dict(
            classify_consistency_rows(cons_rows, entry.expect), notes
        )

    return EntryReport(
        entry_id=entry.entry_id,
        role=_role_of(entry),
        kind=entry.kind,
        num_repeats=runs.num_repeats,
        consistency=[_consistency_row_to_dict(r, notes) for r in cons_rows],
        consistency_histogram=consistency_histogram(cons_rows),
        seed_score=seed_score_dict,
        golden_score=golden_score_dict,
        consistency_by_outcome=classification_dict,
        advisory_notes=[asdict(n) for n in notes],
        test_rel_path=(
            entry.test_rel_path() if hasattr(entry, "test_rel_path") else ""
        ),
    )


def _aggregate(reports: list[EntryReport]) -> dict[str, Any]:
    """Rolls per-entry scores into headline numbers."""
    tp = fp = fn = 0
    g_tp = g_fn = g_unmatched = 0
    advisory = 0
    hist = {"always": 0, "high": 0, "mid": 0, "low": 0, "never": 0}
    for report in reports:
        if report.seed_score:
            tp += report.seed_score["true_positives"]
            fp += report.seed_score["false_positives"]
            fn += report.seed_score["false_negatives"]
        if report.golden_score:
            g_tp += report.golden_score["true_positives"]
            g_fn += report.golden_score["false_negatives"]
            g_unmatched += report.golden_score["unmatched_predictions"]
        advisory += len(report.advisory_notes)
        for bucket, count in report.consistency_histogram.items():
            hist[bucket] += count

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    golden_recall = g_tp / (g_tp + g_fn) if (g_tp + g_fn) else 1.0
    return {
        "seed_true_positives": tp,
        "seed_false_positives": fp,
        "seed_false_negatives": fn,
        "seed_precision": round(precision, 4),
        "seed_recall": round(recall, 4),
        "golden_true_positives": g_tp,
        "golden_false_negatives": g_fn,
        "golden_unmatched_predictions": g_unmatched,
        "golden_recall": round(golden_recall, 4),
        # Advisory only (off-reading-list citations); not a pass/fail gate.
        "advisory_notes": advisory,
        "consistency_histogram": hist,
    }


# --- Quality gates ----------------------------------------------------------


@dataclass
class QualityThresholds:
    """CI pass/fail bounds. None disables a check."""

    min_precision: float | None = None
    min_recall: float | None = None
    min_golden_recall: float | None = None
    max_fn: int | None = None


def check_quality_gates(
    aggregate: dict[str, Any], thresholds: QualityThresholds
) -> list[str]:
    """Returns one message per breached threshold (empty = all pass).

    Reads the keys ``_aggregate`` already emits; ``max_fn`` sums seed and
    golden false negatives.
    """
    failures: list[str] = []
    t = thresholds
    if t.min_precision is not None:
        got = aggregate["seed_precision"]
        if got < t.min_precision:
            failures.append(f"seed precision {got} < {t.min_precision}")
    if t.min_recall is not None:
        got = aggregate["seed_recall"]
        if got < t.min_recall:
            failures.append(f"seed recall {got} < {t.min_recall}")
    if t.min_golden_recall is not None:
        got = aggregate["golden_recall"]
        if got < t.min_golden_recall:
            failures.append(f"golden recall {got} < {t.min_golden_recall}")
    if t.max_fn is not None:
        got = (
            aggregate["seed_false_negatives"]
            + aggregate["golden_false_negatives"]
        )
        if got > t.max_fn:
            failures.append(f"false negatives {got} > {t.max_fn}")
    return failures


# --- Report emission --------------------------------------------------------


def _resolve_run_model(
    models: set[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Derives the report's (provider, model) from what the runs recorded.

    Empty (no run_metadata found) -> (None, None), rendered "unknown". A
    single pair -> that pair. More than one -> a mixed marker, because the
    runs were not all produced on the same model and their numbers should
    not be read as one model's result.
    """
    if not models:
        return None, None
    if len(models) == 1:
        provider, model = next(iter(models))
        return provider or None, model or None
    providers = sorted({p for p, _ in models})
    model_names = sorted({m for _, m in models})
    return (
        "MIXED: " + ", ".join(providers),
        "MIXED: " + ", ".join(model_names),
    )


def build_report(
    manifest: Manifest,
    models: set[tuple[str, str]],
    wpt_dir: Path,
    repeats: int,
    reports: list[EntryReport],
    run_records: list[RunRecord],
    actual_commit: str | None,
    thresholds: QualityThresholds | None = None,
    quality_gate_failures: list[str] | None = None,
) -> BenchmarkReport:
    provider, model = _resolve_run_model(models)
    thresholds_dict = asdict(thresholds) if thresholds else None
    failures = quality_gate_failures or []
    return BenchmarkReport(
        manifest=str(manifest.source_path),
        provider=provider,
        model=model,
        wpt_dir=str(wpt_dir),
        wpt_upstream_commit_expected=manifest.wpt_upstream_commit,
        wpt_upstream_commit_actual=actual_commit,
        repeats=repeats,
        entries=[asdict(r) for r in reports],
        run_records=[asdict(r) for r in run_records],
        aggregate=_aggregate(reports),
        quality_thresholds=thresholds_dict,
        quality_gate_failures=failures,
    )


# Firing-rate buckets, ordered best-to-worst: (name, rate, short meaning).
_CONSISTENCY_BUCKETS: tuple[tuple[ConsistencyBucket, str, str], ...] = (
    (ConsistencyBucket.ALWAYS, "1.0", "fires every repeat - trustworthy"),
    (ConsistencyBucket.HIGH, "≥0.75", "usually fires"),
    (ConsistencyBucket.MID, "0.25–0.75", "flaky zone"),
    (ConsistencyBucket.LOW, ">0", "rarely fires"),
    (ConsistencyBucket.NEVER, "0.0", "never fires"),
)

# Absolute link targets so permalinks work seamlessly in terminal, local markdown, and GitHub PR comments.
_README_LEGEND_LINK = "https://github.com/GoogleChromeLabs/wpt-gen/blob/main/benchmarks/README.md#reading-a-benchmark-report"
_RULES_DOC_LINK = "https://github.com/GoogleChromeLabs/wpt-gen/blob/main/wptgen/skills/wpt-evaluator/references/rules.yaml"


def _escape_md_cell(text: str | None) -> str:
    """Escapes pipe characters, newlines, and raw HTML in table cells."""
    if not text:
        return ""
    clean = str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    clean = clean.replace("|", r"\|")
    clean = clean.replace("<", "&lt;").replace(">", "&gt;")
    return clean.strip()


def _entry_source_url(
    entry: dict[str, Any], pinned_commit: str | None
) -> str | None:
    """Generates a permalink for an entry's test file on GitHub."""
    role = entry.get("role", "")
    path = entry.get("test_rel_path", "")
    if not path:
        return None
    if role == EntryRole.SEED:
        seed_name = Path(path).name
        return f"https://github.com/GoogleChromeLabs/wpt-gen/blob/main/benchmarks/seeds/{seed_name}"
    commit = pinned_commit or "master"
    return f"https://github.com/web-platform-tests/wpt/blob/{commit}/{path}"


def _render_executive_banner(report: BenchmarkReport) -> list[str]:
    """Renders the top-level executive pass/fail badge."""
    lines: list[str] = []
    failures = report.quality_gate_failures
    if failures:
        lines.append(f"### ❌ FAIL · Quality Gate Regression ({len(failures)})")
        lines.append("")
        for f in failures:
            lines.append(f"- ⚠️ **Gate Breached**: `{f}`")
        lines.append("")
    elif report.quality_thresholds and any(
        v is not None for v in report.quality_thresholds.values()
    ):
        lines.append("### ✅ PASS · Quality Gates Satisfied")
        lines.append("")
    return lines


def _render_legend() -> list[str]:
    """A one-line pointer to the report legend in the README."""
    return [
        f"> 📖 How to read this report: see the [Benchmark Guide]({_README_LEGEND_LINK})",
        "",
    ]


def _render_consistency_table(hist: dict[str, int]) -> list[str]:
    """Renders the consistency histogram as a table with short meanings."""
    lines = ["### Consistency buckets", ""]
    lines.append("Firing rate across repeats, per finding.")
    lines.append("")
    lines.append("| bucket | firing rate | count | meaning |")
    lines.append("| --- | --- | --- | --- |")
    for name, rate, meaning in _CONSISTENCY_BUCKETS:
        lines.append(
            f"| {name.value} | {rate} | {hist[name.value]} | {meaning} |"
        )
    lines.append("")
    return lines


def _entry_counts(entries: list[dict[str, Any]]) -> dict[EntryRole, int]:
    """Entry count per role."""
    counts = {EntryRole.SEED: 0, EntryRole.GOLDEN: 0, EntryRole.CORPUS: 0}
    for entry in entries:
        role = EntryRole(entry["role"])
        counts[role] = counts.get(role, 0) + 1
    return counts


def _render_summary(report: BenchmarkReport) -> list[str]:
    """Per-dataset headline table: one row per dataset that has entries."""
    agg = report.aggregate
    counts = _entry_counts(report.entries)
    mid = agg["consistency_histogram"][ConsistencyBucket.MID]
    lines = [
        "## 📈 Summary",
        "",
        "| dataset | what it measures | score / value | target | status |",
        "| :--- | :--- | :---: | :---: | :---: |",
    ]
    if counts[EntryRole.SEED]:
        prec = agg["seed_precision"]
        rec = agg["seed_recall"]
        status = "✅ Pass" if rec >= 1.0 else "❌ Regression"
        lines.append(
            f"| **`seed`** ({counts[EntryRole.SEED]}) | Injected defect detection & false"
            f" alarms | **{prec}** precision / **{rec}** recall | 1.0 Recall |"
            f" {status} |"
        )
    if counts[EntryRole.GOLDEN]:
        g_rec = agg["golden_recall"]
        lines.append(
            f"| **`golden`** ({counts[EntryRole.GOLDEN]}) | Agreement with human reviewer"
            f" comments | **{g_rec}** recall | Informational | ℹ️ Tracked |"
        )
    if counts[EntryRole.CORPUS]:
        status = (
            "✅ Clean"
            if mid == 0
            else f"⚠️ {mid} Flaky" if mid <= 5 else f"❌ {mid} Flaky"
        )
        lines.append(
            f"| **`corpus`** ({counts[EntryRole.CORPUS]}) | Run-to-run output stability /"
            f" variance | **{mid}** flaky findings | 0 Flaky | {status} |"
        )
    lines.append("")
    return lines


def _render_action_items(report: BenchmarkReport) -> list[str]:
    """Constructs actionable troubleshooting steps for regressions, false alarms, and crashes."""
    lines = ["## 🛠️ Action Items & Diagnosis", ""]
    items: list[str] = []

    # 1. Subprocess Execution Errors (Crashes or Timeouts)
    errored_runs = [r for r in report.run_records if r.get("exit_code", 0) != 0]
    if errored_runs:
        for r in errored_runs:
            items.append(
                f"- 🚨 **Subprocess Execution Error in `{r['entry_id']}` (repeat {r['repeat']})**:\n"
                f"  - **Exit Code**: `{r['exit_code']}`\n"
                f"  - **Run Directory**: `{r.get('output_dir', '')}`\n"
                f"  - **Action**: Check run stderr logs in the output directory for agent tracebacks or timeout failures."
            )

    # 2. Seed False Negatives (Missed Expected Injected Defects)
    for entry in report.entries:
        if entry.get("role") == EntryRole.SEED:
            outcome = entry.get("consistency_by_outcome") or {}
            missed = outcome.get("missed_labels", [])
            for label in missed:
                url = _entry_source_url(
                    entry, report.wpt_upstream_commit_expected
                )
                test_link = (
                    f"[`{entry.get('test_rel_path', entry['entry_id'])}`]({url})"
                    if url
                    else f"`{entry.get('test_rel_path', entry['entry_id'])}`"
                )
                window = (
                    f"L{label['line_window'][0]}-{label['line_window'][1]}"
                    if label.get("line_window")
                    else "file"
                )
                items.append(
                    f"- ❌ **Missed Expected Defect in `{entry['entry_id']}`** ({test_link}):\n"
                    f"  - **Missed Rule**: `{label['key']}` @ {window}\n"
                    f"  - **Action**: The evaluator failed to identify this injected defect. Review rule instructions in [rules.yaml]({_RULES_DOC_LINK}) or inspect agent thoughts in `runs/{entry['entry_id']}/rep-1/`."
                )

    # 3. Seed False Positives (False Alarms on Clean Seeds)
    for entry in report.entries:
        if entry.get("role") == EntryRole.SEED:
            ss = entry.get("seed_score") or {}
            if ss.get("false_positives", 0) > 0:
                outcome = entry.get("consistency_by_outcome") or {}
                fps = outcome.get("false_positives", [])
                for fp in fps:
                    url = _entry_source_url(
                        entry, report.wpt_upstream_commit_expected
                    )
                    test_link = (
                        f"[`{entry.get('test_rel_path', entry['entry_id'])}`]({url})"
                        if url
                        else f"`{entry.get('test_rel_path', entry['entry_id'])}`"
                    )
                    bucket = (
                        f"L{fp['line_bucket'][0]}-{fp['line_bucket'][1]}"
                        if fp.get("line_bucket")
                        else "file"
                    )
                    items.append(
                        f"- ⚠️ **False Alarm on Test in `{entry['entry_id']}`** ({test_link}):\n"
                        f"  - **Triggered Rule**: `{fp['key']}` @ {bucket} (fired {fp['firings']}/{fp['repeats']} times)\n"
                        f"  - **Action**: The evaluator flagged acceptable code. The rule prompt in [rules.yaml]({_RULES_DOC_LINK}) may be overly strict; consider adding negative exceptions."
                    )

    # 4. Flaky Consistency Notice (Mid-zone)
    mid_count = report.aggregate["consistency_histogram"].get(
        ConsistencyBucket.MID, 0
    )
    if mid_count > 0:
        items.append(
            f"- ℹ️ **Flaky Findings Detected ({mid_count} in the 25–75% firing zone)**:\n"
            f"  - **Action**: Findings in the mid bucket produced inconsistent verdicts across repeat runs. Consider refining rule wording in `wptgen/skills/wpt-evaluator/` for deterministic evaluation."
        )

    if not items:
        lines.append(
            "✅ **No regressions or execution issues detected.** All quality gates"
            " satisfied and seeds evaluated as expected."
        )
    else:
        lines.extend(items)
    lines.append("")
    return lines


def render_report_markdown(report: BenchmarkReport) -> str:
    """Renders the benchmark report as Markdown from its JSON payload."""
    agg = report.aggregate
    lines: list[str] = []
    lines.append("# WPT evaluator benchmark report")
    lines.append("")

    lines.extend(_render_executive_banner(report))

    model = report.model or "unknown"
    provider = report.provider or "unknown"
    counts = _entry_counts(report.entries)
    lines.append(f"- **Model**: `{model}` (provider: `{provider}`)")
    lines.append(
        f"- **Scope**: {counts[EntryRole.SEED]} seed, {counts[EntryRole.GOLDEN]} golden,"
        f" {counts[EntryRole.CORPUS]} corpus · {report.repeats} repeats"
    )
    lines.append(f"- Manifest: `{report.manifest}`")
    lines.append(f"- wpt checkout: `{report.wpt_dir}`")
    if report.wpt_upstream_commit_expected:
        pinned = report.wpt_upstream_commit_expected
        actual = report.wpt_upstream_commit_actual or "unknown"
        match = "✓" if pinned == actual else "⚠ MISMATCH"
        lines.append(
            f"- Pinned commit: `{pinned}` (checkout at `{actual}`) {match}"
        )
    lines.append("")

    lines.extend(_render_legend())

    lines.extend(_render_summary(report))

    lines.extend(_render_action_items(report))

    # Golden unmatched + advisory are not in the summary (neither is scored);
    # surface them as a compact caveat line so they are not lost.
    caveats = []
    if agg["golden_unmatched_predictions"]:
        caveats.append(
            f"{agg['golden_unmatched_predictions']} golden unmatched (not charged)"
        )
    if agg["advisory_notes"]:
        caveats.append(f"{agg['advisory_notes']} advisory note(s)")
    if caveats:
        lines.append("_" + "; ".join(caveats) + "._")
        lines.append("")

    lines.extend(_render_consistency_table(agg["consistency_histogram"]))

    lines.append("<details>")
    lines.append(
        f"<summary><b>🔍 Detailed Per-Entry Breakdown ({len(report.entries)}"
        " entries)</b></summary>"
    )
    lines.append("")
    lines.append("## Per entry")
    lines.append("")
    for entry in report.entries:
        lines.extend(_render_entry(entry, report.wpt_upstream_commit_expected))
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines) + "\n"


def _render_entry(
    entry: dict[str, Any], pinned_commit: str | None = None
) -> list[str]:
    """One entry's heading, score line, and finding tables."""
    url = _entry_source_url(entry, pinned_commit)
    title_link = (
        f"[`{entry['entry_id']}`]({url})" if url else f"`{entry['entry_id']}`"
    )
    lines = [f"### {title_link} ({entry['role']}/{entry['kind']})", ""]
    if entry["seed_score"]:
        ss = entry["seed_score"]
        lines.append(
            f"- Seed: precision {ss['precision']}, recall {ss['recall']} (TP"
            f" {ss['true_positives']}, FP {ss['false_positives']}, FN"
            f" {ss['false_negatives']})"
        )
    if entry["golden_score"]:
        gs = entry["golden_score"]
        lines.append(
            f"- Golden: recall {gs['recall']} (TP {gs['true_positives']}, FN"
            f" {gs['false_negatives']}, unmatched {gs['unmatched_predictions']})"
        )
    lines.append("")
    lines.extend(_render_entry_consistency(entry))
    return lines


def _bucket_label(row: dict[str, Any]) -> str:
    if row["line_bucket"]:
        return f'L{row["line_bucket"][0]}-{row["line_bucket"][1]}'
    return "file"


def _warnings_cell(row: dict[str, Any]) -> str:
    """Compact per-finding warning summary, e.g. ``⚠ source ×2``."""
    warnings = row.get("warnings") or {}
    if not warnings:
        return ""
    return "⚠ " + ", ".join(
        f"{check} ×{count}" for check, count in sorted(warnings.items())
    )


def _finding_table(rows: list[dict[str, Any]]) -> list[str]:
    """A finding table: title | source | firing rate | warnings."""
    if not rows:
        return ["_(none)_", ""]
    lines = [
        "| title | source | firing rate | warnings |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        raw_title = row.get("title") or row["key"].rsplit("/", 1)[-1]
        title = _escape_md_cell(raw_title)
        source = f'`{row["key"]}` @ {_bucket_label(row)}'
        rate = f'{row["firings"]}/{row["repeats"]} ({row["rate"]})'
        lines.append(f"| {title} | {source} | {rate} | {_warnings_cell(row)} |")
    lines.append("")
    return lines


def _render_entry_consistency(entry: dict[str, Any]) -> list[str]:
    """Per-entry consistency as tables."""
    if not entry["consistency"]:
        return ["- Consistency: no findings across repeats", ""]

    outcome = entry["consistency_by_outcome"]
    if outcome is None:  # corpus: no labels to classify by
        return ["**Findings**", "", *_finding_table(entry["consistency"])]

    # Golden unmatched findings are not charged (possible human misses), so
    # they read differently from a seed's false positives.
    is_golden = entry["role"] == "golden"
    unmatched_header = "**Unmatched**" if is_golden else "**False positives**"
    missed_header = (
        "**Missed labels** (never fired):"
        if is_golden
        else "**False negatives** (expected but never fired):"
    )

    lines = [
        "**True positives**",
        "",
        *_finding_table(outcome["true_positives"]),
    ]
    lines += [
        unmatched_header,
        "",
        *_finding_table(outcome["false_positives"]),
    ]
    if outcome["missed_labels"]:
        lines.append(missed_header)
        lines.append("")
        for label in outcome["missed_labels"]:
            window = (
                f'L{label["line_window"][0]}-{label["line_window"][1]}'
                if label["line_window"]
                else "file"
            )
            lines.append(f'- `{label["key"]}` @ {window}')
        lines.append("")
    return lines


def write_reports(out: Path, report: BenchmarkReport) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(asdict(report), indent=2), encoding="utf-8"
    )
    (out / "report.md").write_text(
        render_report_markdown(report), encoding="utf-8"
    )


# --- Checkout commit probe --------------------------------------------------


def wpt_head_commit(wpt_dir: Path) -> str | None:
    """Best-effort HEAD sha of the wpt checkout (None if not a git repo)."""
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(wpt_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def wpt_dir_from_config(config_path: Path) -> Path | None:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    wpt_path = raw.get("wpt_path")
    if not isinstance(wpt_path, str) or not wpt_path:
        return None
    return (config_path.resolve().parent / wpt_path).resolve()


# The evaluator skill whose curated reading list is the source of truth for
# the source-citation check. A finding may only cite a doc the skill lists.
_SKILL_PATH = REPO_ROOT / "wptgen" / "skills" / "wpt-evaluator" / "SKILL.md"
# Reading-list docs appear in SKILL.md as backtick-wrapped paths, e.g.
# `wpt/docs/writing-tests/testharness.md`.
_READING_LIST_RE = re.compile(r"`(wpt/docs/[\w./-]+\.md)`")


def load_reading_list(skill_path: Path = _SKILL_PATH) -> set[str]:
    """Parses the curated reading list (doc keys) from the evaluator SKILL.md.

    The skill lists its docs as backtick-wrapped ``wpt/docs/….md`` paths;
    anchor-free, those are exactly the normalized finding keys a prediction's
    ``source`` reduces to, so the returned set is directly comparable to
    ``finding_key(...)``. This is the source of truth for the source-citation
    check — no separate file to maintain.

    Raises HarnessError if the skill cannot be read or lists no docs (rather
    than silently disabling the check).
    """
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(
            f"cannot read evaluator skill at {skill_path}: {exc}"
        ) from exc
    keys = set(_READING_LIST_RE.findall(text))
    if not keys:
        raise HarnessError(
            f"no reading-list docs found in {skill_path}; the "
            "source-citation check cannot run."
        )
    return keys


# --- CLI --------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and score the WPT evaluator benchmark."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "manifest.yaml",
        help="Path to manifest.yaml (default: benchmarks/manifest.yaml).",
    )
    parser.add_argument(
        "--wpt-dir",
        type=Path,
        default=None,
        help="Local wpt checkout (default: wpt_path from --config).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output/run directory (default: bench-runs/<date>-<time>/).",
    )
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Concurrent evaluator runs (default: 1). The bound is provider "
        "rate limits, not cores; 4-8 is usually safe.",
    )
    parser.add_argument("--provider", default=None)
    parser.add_argument(
        "--filter", default=None, help="field=value, e.g. kind=reftest"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("wpt-gen.yml"),
        help="wpt-gen config passed through to each evaluate run.",
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "golden",
        help="Golden set root (candidates/ + annotated/); "
        "pass a nonexistent path to skip golden entries.",
    )
    parser.add_argument(
        "--golden-set",
        default=None,
        help="Name of a manifest golden_sets entry to run (empty list = all).",
    )
    parser.add_argument(
        "--golden-prs",
        default=None,
        help="Ad-hoc comma-separated PR numbers to run, e.g. 43400,47302. "
        "Intersected with --golden-set if both are given.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Regression tier: the manifest's `smoke` corpus/seed/golden sets "
        "only. Composes with --filter; repeats stay --repeats.",
    )
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="Re-score existing run dirs in --out; do not run the agent.",
    )
    # CI quality gates: reports are always written first; these only affect the
    # exit code. Omit a flag to leave that check off.
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument("--min-golden-recall", type=float, default=None)
    parser.add_argument("--max-fn", type=int, default=None)
    return parser.parse_args(argv)


def _load_golden(golden_dir: Path) -> list[GoldenEntry]:
    """Loads golden entries from ``<golden_dir>/{candidates,annotated}/``.

    Empty when the dirs are absent (golden set not present in this checkout).
    """
    candidates = golden_dir / "candidates"
    annotated = golden_dir / "annotated"
    if not candidates.is_dir() or not annotated.is_dir():
        return []
    return load_golden_entries(candidates, annotated)


def select_golden(
    entries: list[GoldenEntry],
    manifest: Manifest,
    set_name: str | None,
    pr_csv: str | None,
) -> list[GoldenEntry]:
    """Narrows loaded golden entries to a named set and/or a PR list.

    ``--golden-set`` names a manifest ``golden_sets`` entry (empty list = all);
    ``--golden-prs`` is an ad-hoc comma-separated PR list. Both, if given, are
    intersected. A requested PR with no loaded entry is warned and skipped.
    Neither given -> all loaded entries.
    """
    wanted: set[int] | None = None

    def add(prs: list[int]) -> None:
        nonlocal wanted
        want = set(prs)
        wanted = want if wanted is None else (wanted & want)

    if set_name is not None:
        if set_name not in manifest.golden_sets:
            raise HarnessError(
                f"--golden-set {set_name!r} not in manifest golden_sets "
                f'({", ".join(sorted(manifest.golden_sets)) or "none"})'
            )
        prs = manifest.golden_sets[set_name]
        if prs:  # empty list means "all"
            add(prs)
    if pr_csv:
        try:
            add([int(p) for p in pr_csv.split(",") if p.strip()])
        except ValueError as exc:
            raise HarnessError(
                f"--golden-prs must be comma-separated integers: {exc}"
            ) from exc

    if wanted is None:
        return entries

    by_pr = {e.pr: e for e in entries}
    for pr in sorted(wanted - by_pr.keys()):
        sys.stderr.write(
            f"[warn] golden PR {pr} requested but has no "
            "candidate/annotation on disk; skipping.\n"
        )
    return [by_pr[pr] for pr in sorted(wanted & by_pr.keys())]


SMOKE_SET_NAME = "smoke"


def select_smoke(
    manifest: Manifest, corpus: list[CorpusEntry], seeds: list[SeedEntry]
) -> tuple[list[CorpusEntry], list[SeedEntry]]:
    """Narrows corpus/seeds to their ``smoke`` set (the regression tier).

    An id listed in a set but absent from the manifest is a stale grouping;
    fail loudly rather than silently run a smaller tier.
    """
    return (
        _by_ids(corpus, manifest.corpus_sets.get(SMOKE_SET_NAME, []), "corpus"),
        _by_ids(seeds, manifest.seed_sets.get(SMOKE_SET_NAME, []), "seed"),
    )


def _by_ids(entries: list[Any], ids: list[str], label: str) -> list[Any]:
    by_id = {e.entry_id: e for e in entries}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HarnessError(
            f"{label} smoke set names unknown ids: {', '.join(missing)}"
        )
    return [by_id[i] for i in ids]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve defaults: wpt-dir from the config's wpt_path, out from the
    # timestamp.
    if args.wpt_dir is None:
        args.wpt_dir = wpt_dir_from_config(args.config)
        if args.wpt_dir is None:
            sys.stderr.write(
                "--wpt-dir not given and no wpt_path in "
                f"{args.config}; pass --wpt-dir explicitly.\n"
            )
            return 2
    if args.out is None:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        args.out = Path("bench-runs") / stamp

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        sys.stderr.write(f"manifest error: {exc}\n")
        return 2

    seeds_root = args.manifest.parent / "seeds"

    try:
        corpus, seeds = manifest.corpus, manifest.seeds
        golden_set = args.golden_set
        if args.smoke:
            corpus, seeds = select_smoke(manifest, corpus, seeds)
            # Smoke drives golden via its own set unless one was named.
            golden_set = golden_set or SMOKE_SET_NAME
        golden_entries = select_golden(
            _load_golden(args.golden_dir),
            manifest,
            golden_set,
            args.golden_prs,
        )
        entries = apply_filter([*corpus, *seeds, *golden_entries], args.filter)
    except HarnessError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if not entries:
        sys.stderr.write("no entries matched --filter\n")
        return 2

    # Validate only the selected entries against the checkout, so a scoped run
    # doesn't hard-fail on drift in entries it never stages. A full run selects
    # everything and still validates the whole manifest.
    problems = validate_against_checkout(
        [e for e in entries if isinstance(e, CorpusEntry)],
        [e for e in entries if isinstance(e, SeedEntry)],
        args.wpt_dir,
        seeds_root,
    )
    if problems:
        sys.stderr.write("manifest/checkout mismatches:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        return 2

    actual_commit = wpt_head_commit(args.wpt_dir)
    if (
        manifest.wpt_upstream_commit
        and actual_commit
        and actual_commit != manifest.wpt_upstream_commit
    ):
        sys.stderr.write(
            f"[warn] checkout at {actual_commit}, manifest pins "
            f"{manifest.wpt_upstream_commit}; corpus files may differ.\n"
        )

    run_records: list[RunRecord] = []
    staged = False
    try:
        reading_list = load_reading_list()
        if not args.score_only:
            seed_entries = [e for e in entries if isinstance(e, SeedEntry)]
            gold_entries = [e for e in entries if isinstance(e, GoldenEntry)]
            if seed_entries or gold_entries:
                unstage(args.wpt_dir)  # clear any stale staging first
                staged = True
            if seed_entries:
                stage_seeds(seeds_root, args.wpt_dir, seed_entries)
            if gold_entries:
                stage_golden(args.wpt_dir, gold_entries)
            # Flatten to (entry, repeat) tasks so the pool fills evenly.
            tasks = [
                (entry, i) for entry in entries for i in range(args.repeats)
            ]
            progress = Progress(total=len(tasks))
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = [
                    pool.submit(
                        run_single,
                        entry=entry,
                        repeat=i,
                        wpt_dir=args.wpt_dir,
                        out=args.out,
                        provider=args.provider,
                        config=args.config,
                        progress=progress,
                    )
                    for entry, i in tasks
                ]
                run_records = [f.result() for f in as_completed(futures)]
            # Completion order is nondeterministic; sort for a stable report.
            run_records.sort(key=lambda r: (r.entry_id, r.repeat))

        reports, models = score_all(
            manifest=manifest,
            entries=entries,
            out=args.out,
            repeats=args.repeats,
            reading_list=reading_list,
        )
    except HarnessError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        if staged:
            unstage(args.wpt_dir)

    thresholds = QualityThresholds(
        min_precision=args.min_precision,
        min_recall=args.min_recall,
        min_golden_recall=args.min_golden_recall,
        max_fn=args.max_fn,
    )
    agg = _aggregate(reports)
    failures = check_quality_gates(agg, thresholds)

    report = build_report(
        manifest=manifest,
        models=models,
        wpt_dir=args.wpt_dir,
        repeats=args.repeats,
        reports=reports,
        run_records=run_records,
        actual_commit=actual_commit,
        thresholds=thresholds,
        quality_gate_failures=failures,
    )
    write_reports(args.out, report)
    sys.stderr.write(f'wrote {args.out / "report.md"}\n')

    if failures:
        sys.stderr.write("quality gate failed:\n")
        for failure in failures:
            sys.stderr.write(f"  - {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

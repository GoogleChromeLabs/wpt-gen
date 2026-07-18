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
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Repo root: this file is scripts/benchmark/run_benchmark.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Puts the package's parent (scripts/) on the path so it resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.manifest import (  # noqa: E402
    BenchmarkEntry,
    Manifest,
    ManifestError,
    SeedEntry,
    load_manifest,
    validate_against_checkout,
)
from benchmark.scoring import (  # noqa: E402
    ConsistencyClassification,
    ConsistencyRow,
    EntryRuns,
    MechanicalIssue,
    SeedScore,
    classify_consistency_rows,
    consistency_histogram,
    consistency_rows,
    load_entry_runs,
    mechanical_issues,
    score_seed,
    warnings_for_row,
)

# The subdir the harness stages seeds into, inside the wpt checkout. Matches
# the seed manifest's ``dest``. A marker file records that this run created
# it, so cleanup never deletes a directory the harness did not make.
STAGING_DIRNAME = "wpt-gen-bench"
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
        if value == "seed":
            return [e for e in entries if isinstance(e, SeedEntry)]
        if value == "corpus":
            return [e for e in entries if not isinstance(e, SeedEntry)]
        return []
    raise HarnessError(
        f'--filter supports "kind" and "role", not {field_name!r}'
    )


# --- Seed staging -----------------------------------------------------------


def stage_seeds(
    seeds_root: Path, wpt_dir: Path, seeds: list[SeedEntry]
) -> Path:
    """Stages seed files into ``<wpt_dir>/wpt-gen-bench/``.

    Refuses if the staging dir already exists without the harness's marker
    (never clobber a real directory). Returns the staging dir.
    """
    staging = wpt_dir / STAGING_DIRNAME
    if staging.exists():
        if not (staging / STAGING_MARKER).exists():
            raise HarnessError(
                f"{staging} already exists and was not created by the "
                "harness; refusing to overwrite. Remove it and re-run."
            )
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    (staging / STAGING_MARKER).write_text(
        "Created by scripts/benchmark/run_benchmark.py; safe to delete.\n",
        encoding="utf-8",
    )

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


def unstage_seeds(wpt_dir: Path) -> None:
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


def run_entry(
    entry: BenchmarkEntry,
    manifest: Manifest,
    wpt_dir: Path,
    out: Path,
    repeats: int,
    provider: str | None,
    config: Path,
) -> list[RunRecord]:
    """Invokes ``wpt-gen evaluate`` ``repeats`` times for one entry."""
    records: list[RunRecord] = []
    test_rel = entry.test_rel_path()
    test_abs = wpt_dir / test_rel

    for i in range(repeats):
        rep_dir = _rep_dir(out, entry.entry_id, i)
        rep_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "wpt-gen",
            "evaluate",
            str(test_abs),
            "--wpt-dir",
            str(wpt_dir),
            "--output-dir",
            str(rep_dir),
            "--config",
            str(config),
        ]
        if provider:
            cmd += ["--provider", provider]

        started = time.monotonic()
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.monotonic() - started
        if completed.returncode != 0:
            # Record it and move on; an errored repeat scores as an empty
            # run (no findings) and still counts in the denominator.
            sys.stderr.write(
                f"[warn] {entry.entry_id} rep-{i} exited "
                f"{completed.returncode}\n{completed.stderr}\n"
            )
        records.append(
            RunRecord(
                entry_id=entry.entry_id,
                repeat=i,
                exit_code=completed.returncode,
                wall_seconds=elapsed,
                output_dir=str(rep_dir),
            )
        )
    return records


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
    # For seed entries: consistency rows bracketed by gold-label match, plus
    # any missed labels. None for corpus entries (no labels to classify by).
    consistency_by_outcome: dict[str, Any] | None
    # Source-citation warnings — findings whose `source` cites a doc not on
    # the skill's reading list. Advisory: reported, not scored.
    advisory_notes: list[dict[str, Any]]


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


def _role_of(entry: BenchmarkEntry) -> str:
    """The role label ("seed" | "corpus") for report metadata."""
    return "seed" if isinstance(entry, SeedEntry) else "corpus"


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
    classification_dict: dict[str, Any] | None = None
    if isinstance(entry, SeedEntry):
        score = score_seed(runs, entry.expect)
        seed_score_dict = _seed_score_to_dict(score)
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
        consistency_by_outcome=classification_dict,
        advisory_notes=[asdict(n) for n in notes],
    )


def _aggregate(reports: list[EntryReport]) -> dict[str, Any]:
    """Rolls per-entry scores into headline numbers."""
    tp = fp = fn = 0
    advisory = 0
    hist = {"always": 0, "high": 0, "mid": 0, "low": 0, "never": 0}
    for report in reports:
        if report.seed_score:
            tp += report.seed_score["true_positives"]
            fp += report.seed_score["false_positives"]
            fn += report.seed_score["false_negatives"]
        advisory += len(report.advisory_notes)
        for bucket, count in report.consistency_histogram.items():
            hist[bucket] += count

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "seed_true_positives": tp,
        "seed_false_positives": fp,
        "seed_false_negatives": fn,
        "seed_precision": round(precision, 4),
        "seed_recall": round(recall, 4),
        # Advisory only (off-reading-list citations); not a pass/fail gate.
        "advisory_notes": advisory,
        "consistency_histogram": hist,
    }


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
) -> BenchmarkReport:
    provider, model = _resolve_run_model(models)
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
    )


# Firing-rate buckets, ordered best-to-worst: (name, rate, short meaning).
_CONSISTENCY_BUCKETS = [
    ("always", "1.0", "fires every repeat - trustworthy"),
    ("high", "≥0.75", "usually fires"),
    ("mid", "0.25–0.75", "flaky zone"),
    ("low", ">0", "rarely fires"),
    ("never", "0.0", "never fires"),
]

# Link target for the legend. A repo-relative path so it resolves whether
# the report is viewed in the repo or alongside it under bench-runs/.
_README_LEGEND_LINK = "../../benchmarks/README.md#reading-a-benchmark-report"


def _render_legend() -> list[str]:
    """A one-line pointer to the report legend in the README."""
    return [
        f"> How to read this report: see the [README]({_README_LEGEND_LINK})",
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
        lines.append(f"| {name} | {rate} | {hist[name]} | {meaning} |")
    lines.append("")
    return lines


def render_report_markdown(report: BenchmarkReport) -> str:
    """Renders the benchmark report as Markdown from its JSON payload."""
    agg = report.aggregate
    lines: list[str] = []
    lines.append("# WPT evaluator benchmark report")
    lines.append("")
    model = report.model or "unknown"
    provider = report.provider or "unknown"
    lines.append(f"- **Model**: `{model}` (provider: `{provider}`)")
    lines.append(f"- Manifest: `{report.manifest}`")
    lines.append(f"- wpt checkout: `{report.wpt_dir}`")
    lines.append(f"- Repeats per entry: {report.repeats}")
    if report.wpt_upstream_commit_expected:
        pinned = report.wpt_upstream_commit_expected
        actual = report.wpt_upstream_commit_actual or "unknown"
        match = "✓" if pinned == actual else "⚠ MISMATCH"
        lines.append(
            f"- Pinned commit: `{pinned}` (checkout at `{actual}`) {match}"
        )
    lines.append("")

    lines.extend(_render_legend())

    lines.append("## Aggregate")
    lines.append("")
    lines.append("| metric | value | target |")
    lines.append("| --- | --- | --- |")
    lines.append(f'| seed precision | {agg["seed_precision"]} | 1.0 |')
    lines.append(f'| seed recall | {agg["seed_recall"]} | 1.0 |')
    lines.append(
        f'| seed TP / FP / FN | {agg["seed_true_positives"]} / '
        f'{agg["seed_false_positives"]} / {agg["seed_false_negatives"]} '
        "| FP=0, FN=0 |"
    )
    lines.append("")
    lines.append("- **TP** — true positive: an expected finding fired.")
    lines.append("- **FP** — false positive: an unexpected finding fired.")
    lines.append("- **FN** — false negative: an expected finding was missed.")
    lines.append("")
    lines.append(
        f'Advisory notes: {agg["advisory_notes"]} finding(s) cite a source '
        "doc that is not on the evaluator's curated reading list. Advisory "
        "only — not a pass/fail gate."
    )
    lines.append("")
    lines.extend(_render_consistency_table(agg["consistency_histogram"]))

    lines.append("## Per entry")
    lines.append("")
    for entry in report.entries:
        lines.append(
            f'### `{entry["entry_id"]}` ({entry["role"]}/{entry["kind"]})'
        )
        lines.append("")
        if entry["seed_score"]:
            ss = entry["seed_score"]
            lines.append(
                f'- Seed: precision {ss["precision"]}, recall '
                f'{ss["recall"]} '
                f'(TP {ss["true_positives"]}, FP {ss["false_positives"]}, '
                f'FN {ss["false_negatives"]})'
            )
        lines.append("")
        lines.extend(_render_entry_consistency(entry))

    return "\n".join(lines) + "\n"


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
        title = row.get("title") or row["key"].rsplit("/", 1)[-1]
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

    lines = [
        "**True positives**",
        "",
        *_finding_table(outcome["true_positives"]),
    ]
    lines += [
        "**False positives**",
        "",
        *_finding_table(outcome["false_positives"]),
    ]
    if outcome["missed_labels"]:
        lines.append("**False negatives** (expected but never fired):")
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
_SKILL_PATH = _REPO_ROOT / "wptgen" / "skills" / "wpt-evaluator" / "SKILL.md"
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
        default=_REPO_ROOT / "benchmarks" / "manifest.yaml",
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
        "--score-only",
        action="store_true",
        help="Re-score existing run dirs in --out; do not run the agent.",
    )
    return parser.parse_args(argv)


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
    problems = validate_against_checkout(manifest, args.wpt_dir, seeds_root)
    if problems:
        sys.stderr.write("manifest/checkout mismatches:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        return 2

    try:
        entries = apply_filter(manifest.entries, args.filter)
    except HarnessError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if not entries:
        sys.stderr.write("no entries matched --filter\n")
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
            if seed_entries:
                stage_seeds(seeds_root, args.wpt_dir, seed_entries)
                staged = True
            for entry in entries:
                run_records.extend(
                    run_entry(
                        entry=entry,
                        manifest=manifest,
                        wpt_dir=args.wpt_dir,
                        out=args.out,
                        repeats=args.repeats,
                        provider=args.provider,
                        config=args.config,
                    )
                )

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
            unstage_seeds(args.wpt_dir)

    report = build_report(
        manifest=manifest,
        models=models,
        wpt_dir=args.wpt_dir,
        repeats=args.repeats,
        reports=reports,
        run_records=run_records,
        actual_commit=actual_commit,
    )
    write_reports(args.out, report)
    sys.stderr.write(f'wrote {args.out / "report.md"}\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

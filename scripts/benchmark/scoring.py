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
"""Scoring core for the WPT evaluator benchmark.

Pure functions over parsed evaluator JSON payloads: finding-key
normalization, test-line bucketing, and the three metric families
(consistency, seed precision/recall, mechanical issue advisory notes).

The orchestration that actually runs the evaluator lives in
run_benchmark.py; it feeds parsed payloads into here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- Finding identity -------------------------------------------------------

# A source citation such as
#   wpt/docs/writing-tests/testharness.md:L82-L87
# or wpt/docs/writing-tests/testharness.md#L82 . The line anchor varies
# run-to-run for the same conceptual guidance, so it is stripped to form the
# stable finding key.
_SOURCE_ANCHOR_RE = re.compile(r"(?::L?\d+(?:-L?\d+)?|#L?\d+(?:-L?\d+)?)\s*$")


def normalize_source_doc(source: str) -> str:
    """Strips the trailing ``#L…`` / ``:L…`` line anchor from a citation.

    ``wpt/docs/.../testharness.md:L82-L87`` -> ``wpt/docs/.../testharness.md``.
    Leaves a bare doc path untouched.
    """
    return _SOURCE_ANCHOR_RE.sub("", source.strip())


def finding_key(finding: dict[str, Any]) -> str:
    """The stable identity of a finding.

    ``rule_id`` when the finding carries a non-empty one (post-rules-merge);
    otherwise the normalized ``source`` doc path.
    """
    rule_id = finding.get("rule_id")
    if rule_id:
        return str(rule_id)
    return normalize_source_doc(str(finding.get("source", "")))


# --- Test-line bucketing ----------------------------------------------------

# Matches the evaluator's ``test_line`` phrasings: "Line 24", "Lines 21-23",
# or a bare "24" / "21-23". Non-numeric anchors ("filename") yield no range.
_LINE_RANGE_RE = re.compile(r"(\d+)(?:\s*[-–]\s*(\d+))?")


def parse_line_range(test_line: str) -> tuple[int, int] | None:
    """Parses a ``test_line`` string into an inclusive ``(start, end)`` range.

    Returns None when the string carries no line number (e.g. "filename",
    an empty string) — such findings are file-scoped, not line-anchored.
    """
    match = _LINE_RANGE_RE.search(test_line or "")
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if end < start:
        start, end = end, start
    return start, end


def _ranges_overlap(
    a: tuple[int, int] | None, b: tuple[int, int] | None
) -> bool:
    """Whether two inclusive ranges overlap.

    A None range is file-scoped and overlaps anything (including another
    None) — a file-level finding cannot be excluded by a line window.
    """
    if a is None or b is None:
        return True
    return a[0] <= b[1] and b[0] <= a[1]


def _merge_ranges(
    ranges: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        # Adjacent ranges (last_end + 1 == start) merge too: findings that
        # cite "Line 12" and "Lines 13-14" describe one contiguous region.
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


# --- Parsed run model -------------------------------------------------------


@dataclass(frozen=True)
class Prediction:
    """One finding the evaluator emitted in a single run.

    An ML-eval "prediction": the model's output that gets scored against
    ground truth (a seed's ``expect`` labels). Reduced to the fields matching
    needs — the raw finding's ``source`` becomes the anchor-stripped ``key``
    and its ``test_line`` becomes the numeric ``line_range``.
    """

    key: str
    line_range: tuple[int, int] | None
    evidence: str
    source: str
    severity: str
    title: str = ""


@dataclass
class EntryRuns:
    """One manifest entry's findings across all its repeated runs."""

    entry_id: str
    role: str
    repeats: list[list[Prediction]] = field(default_factory=list)
    models: set[tuple[str, str]] = field(default_factory=set)

    @property
    def num_repeats(self) -> int:
        return len(self.repeats)


def payload_to_predictions(payload: dict[str, Any]) -> list[Prediction]:
    """Flattens an evaluator JSON payload's findings into Predictions."""
    predictions: list[Prediction] = []
    raw_findings: list[dict[str, Any]] = list(payload.get("findings") or [])
    conformance = payload.get("conformance")
    if isinstance(conformance, dict):
        raw_findings.extend(conformance.get("findings") or [])

    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        predictions.append(
            Prediction(
                key=finding_key(finding),
                line_range=parse_line_range(str(finding.get("test_line", ""))),
                evidence=str(finding.get("evidence", "")),
                source=str(finding.get("source", "")),
                severity=str(finding.get("severity", "")),
                title=str(finding.get("title", "")),
            )
        )
    return predictions


# --- Consistency ------------------------------------------------------------


@dataclass
class ConsistencyRow:
    """Firing rate for one (key, merged-line-bucket) across an entry's repeats."""

    entry_id: str
    key: str
    line_bucket: tuple[int, int] | None
    firings: int
    repeats: int
    # First-seen title/severity for this finding. The evaluator rewords the
    # title across repeats, so this is a representative label (the earliest
    # repeat's), not a canonical one.
    title: str = ""
    severity: str = ""

    @property
    def rate(self) -> float:
        return self.firings / self.repeats if self.repeats else 0.0


def _bucket_predictions(
    runs: EntryRuns,
) -> list[tuple[str, tuple[int, int] | None]]:
    """Computes the merged (key, line-bucket) space for an entry.

    Per key, the line ranges seen across all repeats are merged so that a
    finding drifting between "Line 12" and "Lines 11-13" counts as one
    conceptual finding, not two. File-scoped (None-range) findings form
    their own bucket per key.
    """
    line_ranges: dict[str, list[tuple[int, int]]] = {}
    has_file_scope: dict[str, bool] = {}
    for repeat in runs.repeats:
        for pred in repeat:
            if pred.line_range is None:
                has_file_scope[pred.key] = True
            else:
                line_ranges.setdefault(pred.key, []).append(pred.line_range)

    buckets: list[tuple[str, tuple[int, int] | None]] = []
    for key, ranges in line_ranges.items():
        for merged in _merge_ranges(ranges):
            buckets.append((key, merged))
    for key in has_file_scope:
        buckets.append((key, None))
    return buckets


def consistency_rows(runs: EntryRuns) -> list[ConsistencyRow]:
    """Firing rate per (key, line-bucket) for one entry across its repeats.

    A repeat "fires" a bucket if any of its predictions share the key and
    overlap the bucket's line range.
    """
    rows: list[ConsistencyRow] = []
    for key, bucket in _bucket_predictions(runs):
        firings = 0
        title = ""
        severity = ""
        for repeat in runs.repeats:
            matches = [
                pred
                for pred in repeat
                if pred.key == key and _ranges_overlap(pred.line_range, bucket)
            ]
            if matches:
                firings += 1
                # First-seen title/severity: keep the earliest repeat's.
                if not title:
                    title = matches[0].title
                    severity = matches[0].severity
        rows.append(
            ConsistencyRow(
                entry_id=runs.entry_id,
                key=key,
                line_bucket=bucket,
                firings=firings,
                repeats=runs.num_repeats,
                title=title,
                severity=severity,
            )
        )
    return rows


def consistency_histogram(rows: list[ConsistencyRow]) -> dict[str, int]:
    """Buckets firing rates into a coarse histogram."""
    hist = {"always": 0, "high": 0, "mid": 0, "low": 0, "never": 0}
    for row in rows:
        rate = row.rate
        if rate >= 1.0:
            hist["always"] += 1
        elif rate >= 0.75:
            hist["high"] += 1
        elif rate >= 0.25:
            hist["mid"] += 1
        elif rate > 0.0:
            hist["low"] += 1
        else:
            hist["never"] += 1
    return hist


# --- Seed precision / recall ------------------------------------------------


@dataclass(frozen=True)
class ExpectLabel:
    """A gold label: a finding key that must fire within a line window."""

    key: str
    line_window: tuple[int, int] | None


@dataclass
class SeedScore:
    """Precision/recall for one seed entry, aggregated over its repeats."""

    entry_id: str
    true_positives: int
    false_positives: int
    false_negatives: int
    # Per-repeat recall lets the caller see whether a seed is reliably
    # caught or only caught sometimes (a consistency signal on gold labels).
    per_repeat_recall: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0


def _label_matched(label: ExpectLabel, preds: list[Prediction]) -> bool:
    return any(
        pred.key == label.key
        and _ranges_overlap(pred.line_range, label.line_window)
        for pred in preds
    )


def score_seed(
    runs: EntryRuns,
    expect: list[ExpectLabel],
) -> SeedScore:
    """Scores one seed entry across its repeats.

    Counted per repeat, then summed — so a seed run 3× contributes up to 3
    true positives per label. A prediction matches a gold label on an exact
    key join plus an overlapping line window.
    Any prediction not matching an ``expect`` label is a false positive (so
    every finding on a clean seed, whose ``expect`` is empty, counts against
    precision).
    """
    tp = fp = fn = 0
    per_repeat_recall: list[float] = []

    for repeat in runs.repeats:
        matched_labels = 0
        matched_predictions: set[int] = set()
        for label in expect:
            hit = False
            for idx, pred in enumerate(repeat):
                if pred.key == label.key and _ranges_overlap(
                    pred.line_range, label.line_window
                ):
                    hit = True
                    matched_predictions.add(idx)
            if hit:
                matched_labels += 1
                tp += 1
            else:
                fn += 1

        # Every prediction that did not satisfy some expect label is a false
        # positive.
        fp += len(repeat) - len(matched_predictions)

        if expect:
            per_repeat_recall.append(matched_labels / len(expect))

    return SeedScore(
        entry_id=runs.entry_id,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        per_repeat_recall=per_repeat_recall,
    )


def parse_expect(raw: list[dict[str, Any]] | None) -> list[ExpectLabel]:
    """Parses manifest ``expect`` entries into ExpectLabels.

    ``source_doc`` is the finding key on ``main`` (normalized the same way a
    prediction's citation is); ``rule_id`` takes precedence once set.
    ``test_file_lines`` is the acceptable inclusive window in the seed file.
    """
    labels: list[ExpectLabel] = []
    for item in raw or []:
        rule_id = item.get("rule_id")
        key = (
            str(rule_id)
            if rule_id
            else normalize_source_doc(str(item.get("source_doc", "")))
        )
        window_raw = item.get("test_file_lines")
        window: tuple[int, int] | None = None
        if isinstance(window_raw, (list, tuple)) and len(window_raw) == 2:
            start, end = int(window_raw[0]), int(window_raw[1])
            window = (min(start, end), max(start, end))
        labels.append(ExpectLabel(key=key, line_window=window))
    return labels


@dataclass
class ConsistencyClassification:
    """Consistency rows partitioned against a seed's gold labels."""

    true_positives: list[ConsistencyRow] = field(default_factory=list)
    false_positives: list[ConsistencyRow] = field(default_factory=list)
    missed_labels: list[ExpectLabel] = field(default_factory=list)


def classify_consistency_rows(
    rows: list[ConsistencyRow], expect: list[ExpectLabel]
) -> ConsistencyClassification:
    """Partitions consistency rows into TP/FP and finds missed labels."""

    result = ConsistencyClassification()
    matched_labels: set[int] = set()
    for row in rows:
        hit = False
        for idx, label in enumerate(expect):
            if row.key == label.key and _ranges_overlap(
                row.line_bucket, label.line_window
            ):
                hit = True
                matched_labels.add(idx)
        (result.true_positives if hit else result.false_positives).append(row)
    result.missed_labels = [
        label for idx, label in enumerate(expect) if idx not in matched_labels
    ]
    return result


# --- Mechanical validity checks ---------------------------------------------


@dataclass
class MechanicalIssue:
    """One mechanical-validity note, itemized for the report."""

    entry_id: str
    repeat: int
    check: str  # "evidence" | "source"
    detail: str
    # The finding key + line range this note is about, so the report can
    # attribute it to the specific consistency row (key + line bucket) it
    # belongs to — not just any row sharing the doc.
    key: str = ""
    line_range: tuple[int, int] | None = None


def check_source_on_reading_list(
    prediction: Prediction, reading_list: set[str]
) -> bool:
    """Whether the finding cites a doc on the skill's curated reading list.

    Guards against invented citations: a finding whose ``source`` doc is not
    one the skill told the evaluator to read is suspect. This is the right
    check while the evaluator reads the raw curated docs (today's only
    strategy); once a ``rules.yaml`` strategy exists it would be replaced by
    a rule-id validity check.
    """
    return prediction.key in reading_list


def mechanical_issues(
    entry_id: str,
    repeat_index: int,
    predictions: list[Prediction],
    reading_list: set[str],
) -> list[MechanicalIssue]:
    """Runs the mechanical checks over one repeat, itemizing failures."""
    issues: list[MechanicalIssue] = []
    for pred in predictions:
        if not check_source_on_reading_list(pred, reading_list):
            issues.append(
                MechanicalIssue(
                    entry_id=entry_id,
                    repeat=repeat_index,
                    check="source",
                    detail=f"source not on reading list: {pred.source!r}",
                    key=pred.key,
                    line_range=pred.line_range,
                )
            )
    return issues


def warnings_for_row(
    row: ConsistencyRow, notes: list[MechanicalIssue]
) -> dict[str, int]:
    """Counts advisory notes belonging to one consistency row, by check type.

    A note belongs to the row when it shares the finding key and its line
    overlaps the row's merged bucket — the same match rule used to build the
    row — so two distinct findings in the same doc get their own counts
    instead of the doc's total.
    """
    counts: dict[str, int] = {}
    for note in notes:
        if note.key == row.key and _ranges_overlap(
            note.line_range, row.line_bucket
        ):
            counts[note.check] = counts.get(note.check, 0) + 1
    return counts


# --- Run-directory loading --------------------------------------------------


def load_entry_runs(
    entry_id: str,
    role: str,
    repeat_dirs: list[Path],
    test_file_name: str,
) -> EntryRuns:
    """Loads an entry's per-repeat payloads from its run directories.

    Each ``repeat_dirs[i]`` is a ``rep-<i>`` directory containing
    ``<test_file_name>.json``. A missing or unparseable payload records an
    empty repeat (the run errored) rather than raising, so one failed repeat
    does not abort scoring — but it still counts in the denominator.
    """
    import json

    repeats: list[list[Prediction]] = []
    models: set[tuple[str, str]] = set()
    for rep_dir in repeat_dirs:
        json_path = rep_dir / f"{test_file_name}.json"
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            repeats.append(payload_to_predictions(payload))
            meta = payload.get("run_metadata")
            if isinstance(meta, dict) and meta.get("model"):
                models.add((str(meta.get("provider", "")), str(meta["model"])))
        except (OSError, ValueError):
            repeats.append([])
    return EntryRuns(
        entry_id=entry_id, role=role, repeats=repeats, models=models
    )

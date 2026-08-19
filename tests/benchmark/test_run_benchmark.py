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

"""Tests for the benchmark harness scoring, manifest, and orchestration.

No agent calls: scoring runs over synthetic run directories written by the
fixtures below, so consistency math, line bucketing, finding-key
normalization, seed P/R, and the mechanical checks are all exercised
against JSON.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest
import yaml

# scripts/ is put on sys.path by tests/conftest.py, so the
# ``benchmark`` package resolves here.
from benchmark import run_benchmark
from benchmark.manifest import (
    GOLDEN_STAGING_SUBDIR,
    REPO_ROOT,
    STAGING_DIRNAME,
    CorpusEntry,
    GoldenEntry,
    ManifestError,
    SeedEntry,
    load_golden_entries,
    load_manifest,
    load_rule_ids,
    validate_against_checkout,
)
from benchmark.scoring import (
    ConsistencyRow,
    EntryRuns,
    ExpectLabel,
    GoldenLabel,
    MechanicalIssue,
    Prediction,
    check_source_on_reading_list,
    classify_consistency_rows,
    consistency_decomposition,
    consistency_histogram,
    graded_consistency_histogram,
    consistency_rows,
    corpus_stability,
    corpus_stability_with_churn,
    finding_key,
    line_consistency_histogram,
    line_consistency_rows,
    load_entry_runs,
    mechanical_issues,
    near_miss_flakiness,
    normalize_source_doc,
    parse_expect,
    parse_line_range,
    payload_to_predictions,
    score_golden,
    score_seed,
    warnings_for_row,
)

# --- Payload helpers --------------------------------------------------------


def _finding(
    source: str = "wpt/docs/writing-tests/testharness.md:L5-L9",
    test_line: str = "Line 7",
    evidence: str = "done()",
    severity: str = "warn",
    rule_id: str | None = None,
) -> dict[str, object]:
    return {
        "title": "t",
        "severity": severity,
        "test_line": test_line,
        "evidence": evidence,
        "source": source,
        "summary": "s",
        "rule_id": rule_id,
    }


def _payload(findings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "test_path": "/wpt/wpt-gen-bench/foo.worker.js",
        "findings": findings,
        "input_scope": {
            "files": [],
            "dependencies_not_read": [],
            "approach": "doc-inputs",
            "total_bytes": 0,
            "approximate_input_tokens": 0,
        },
        "conformance": None,
    }


def _write_run(
    out: Path,
    entry_id: str,
    repeat: int,
    test_name: str,
    payload: dict[str, object],
) -> None:
    rep = out / "runs" / entry_id / f"rep-{repeat}"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / f"{test_name}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# --- Finding-key normalization ----------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("wpt/docs/x.md:L82-L87", "wpt/docs/x.md"),
        ("wpt/docs/x.md#L82", "wpt/docs/x.md"),
        ("wpt/docs/x.md:82", "wpt/docs/x.md"),
        ("wpt/docs/x.md", "wpt/docs/x.md"),
        ("  wpt/docs/x.md#L5  ", "wpt/docs/x.md"),
    ],
)
def test_normalize_source_strips_line_anchor(
    source: str, expected: str
) -> None:
    assert normalize_source_doc(source) == expected


def test_finding_key_prefers_rule_id() -> None:
    finding = _finding(source="wpt/docs/x.md#L5", rule_id="TH-DONE-001")
    assert finding_key(finding) == "TH-DONE-001"


def test_finding_key_falls_back_to_source_doc() -> None:
    finding = _finding(source="wpt/docs/x.md#L5", rule_id=None)
    assert finding_key(finding) == "wpt/docs/x.md"


# --- Line bucketing ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Line 24", (24, 24)),
        ("Lines 21-23", (21, 23)),
        ("21-23", (21, 23)),
        ("Lines 23-21", (21, 23)),  # normalized
        ("filename", None),
        ("", None),
    ],
)
def test_parse_line_range(text: str, expected: tuple[int, int] | None) -> None:
    assert parse_line_range(text) == expected


# --- payload_to_predictions -------------------------------------------------


def test_payload_to_predictions_includes_conformance_findings() -> None:
    payload = _payload([_finding(source="wpt/docs/a.md#L1")])
    payload["conformance"] = {
        "specs": [{"spec_url": "https://spec", "requirements_xml_bytes": 0}],
        "findings": [_finding(source="wpt/docs/b.md#L2")],
        "input_scope": {},
    }
    preds = payload_to_predictions(payload)
    keys = {p.key for p in preds}
    assert keys == {"wpt/docs/a.md", "wpt/docs/b.md"}


def test_payload_to_predictions_tolerates_malformed_findings() -> None:
    payload = _payload([_finding(), "not-a-dict"])  # type: ignore[list-item]
    preds = payload_to_predictions(payload)
    assert len(preds) == 1


# --- Consistency ------------------------------------------------------------


def _runs(
    entry_id: str,
    repeats: list[list[Prediction]],
    role: str = "corpus",
) -> EntryRuns:
    return EntryRuns(entry_id=entry_id, role=role, repeats=repeats)


def test_consistency_full_firing() -> None:
    pred = Prediction("k", (7, 7), "e", "s", "warn")
    runs = _runs("e", [[pred], [pred], [pred]])
    rows = consistency_rows(runs)
    assert len(rows) == 1
    assert rows[0].firings == 3
    assert rows[0].repeats == 3
    assert rows[0].rate == pytest.approx(1.0)


def test_consistency_flaky_half() -> None:
    pred = Prediction("k", (7, 7), "e", "s", "warn")
    runs = _runs("e", [[pred], [], [pred], []])
    rows = consistency_rows(runs)
    assert rows[0].firings == 2
    assert rows[0].rate == pytest.approx(0.5)


def test_consistency_merges_overlapping_line_ranges() -> None:
    # Same key drifting across "Line 12" and "Lines 11-13" is ONE finding.
    runs = _runs(
        "e",
        [
            [Prediction("k", (12, 12), "e", "s", "warn")],
            [Prediction("k", (11, 13), "e", "s", "warn")],
        ],
    )
    rows = consistency_rows(runs)
    assert len(rows) == 1
    assert rows[0].firings == 2


def test_consistency_separates_distant_line_ranges() -> None:
    runs = _runs(
        "e",
        [
            [Prediction("k", (5, 5), "e", "s", "warn")],
            [Prediction("k", (80, 80), "e", "s", "warn")],
        ],
    )
    rows = consistency_rows(runs)
    assert len(rows) == 2
    assert all(row.firings == 1 for row in rows)


def test_consistency_histogram_buckets() -> None:
    rows = consistency_rows(
        _runs(
            "e",
            [
                [Prediction("always", (1, 1), "e", "s", "w")],
                [Prediction("always", (1, 1), "e", "s", "w")],
            ],
        )
    )
    hist = consistency_histogram(rows)
    assert hist["always"] == 1
    assert sum(hist.values()) == 1


# --- Line-vs-rule_id decomposition ------------------------------------------


def test_line_rows_collapse_competing_rules_to_one_line() -> None:
    # Two rules on the same line every repeat -> one line, detected 2/2.
    runs = _runs(
        "e",
        [
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
            [Prediction("RULE-B", (5, 5), "e", "s", "warn")],
        ],
    )
    line_rows = line_consistency_rows(runs)
    assert len(line_rows) == 1
    row = line_rows[0]
    assert row.detection_rate == pytest.approx(1.0)
    assert row.keys == ["RULE-A", "RULE-B"]
    assert row.label_churn is True  # stable detection, >1 rule


def test_line_row_not_churn_when_single_rule() -> None:
    runs = _runs(
        "e",
        [
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
        ],
    )
    (row,) = line_consistency_rows(runs)
    assert row.label_churn is False


def test_line_row_not_churn_when_detection_flaky() -> None:
    # Detected only 1/2 -> flaky detection, so not "churn" even with 2 rules.
    runs = _runs(
        "e",
        [
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
            [],
        ],
    )
    (row,) = line_consistency_rows(runs)
    assert row.detection_rate == pytest.approx(0.5)
    assert row.label_churn is False


def test_file_and_line_scoped_findings_do_not_cross_buckets() -> None:
    # A file-scoped finding (line_range=None) and a line-scoped finding on
    # the same entry are distinct defects; they must land in separate buckets
    # each with a single key, not smear together into phantom label churn.
    runs = _runs(
        "e",
        [
            [
                Prediction("LINE-RULE", (22, 22), "e", "s", "warn"),
                Prediction("FILE-RULE", None, "e", "s", "warn"),
            ],
            [
                Prediction("LINE-RULE", (22, 22), "e", "s", "warn"),
                Prediction("FILE-RULE", None, "e", "s", "warn"),
            ],
        ],
    )
    line_rows = line_consistency_rows(runs)
    assert len(line_rows) == 2
    by_bucket = {lr.line_bucket: lr for lr in line_rows}
    line_row = by_bucket[(22, 22)]
    file_row = by_bucket[None]
    assert line_row.keys == ["LINE-RULE"]
    assert file_row.keys == ["FILE-RULE"]
    # Both detected every repeat, but each has exactly one rule -> no churn.
    assert line_row.detection_rate == pytest.approx(1.0)
    assert file_row.detection_rate == pytest.approx(1.0)
    assert line_row.label_churn is False
    assert file_row.label_churn is False


def test_line_histogram_keys_on_detection() -> None:
    # A line drawing 2 rules every repeat is one `always` line, not two mid.
    runs = _runs(
        "e",
        [
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
            [Prediction("RULE-B", (5, 5), "e", "s", "warn")],
        ],
    )
    hist = line_consistency_histogram(line_consistency_rows(runs))
    assert hist["always"] == 1
    assert hist["mid"] == 0


def test_graded_histogram_splits_at_warn_at() -> None:
    # rates 1.0, 0.67, 0.33 with warn_at 0.61: two stable, one unstable.
    runs = _runs(
        "e",
        [
            [
                Prediction("A", (10, 10), "e", "s", "w"),
                Prediction("B", (20, 20), "e", "s", "w"),
                Prediction("C", (30, 30), "e", "s", "w"),
            ],
            [
                Prediction("A", (10, 10), "e", "s", "w"),
                Prediction("B", (20, 20), "e", "s", "w"),
            ],
            [Prediction("A", (10, 10), "e", "s", "w")],
        ],
    )
    hist = graded_consistency_histogram(line_consistency_rows(runs), 0.61)
    assert hist == {"stable": 2, "unstable": 1, "never": 0}


def test_decomposition_separates_detection_from_churn() -> None:
    runs = _runs(
        "e",
        [
            # L5: stable detection, two rules -> churn.
            # L9: flaky detection -> detection instability.
            [
                Prediction("RULE-A", (5, 5), "e", "s", "warn"),
                Prediction("RULE-X", (9, 9), "e", "s", "warn"),
            ],
            [Prediction("RULE-B", (5, 5), "e", "s", "warn")],
        ],
    )
    rule_rows = consistency_rows(runs)
    line_rows = line_consistency_rows(runs)
    d = consistency_decomposition(rule_rows, line_rows)
    assert d["line_flaky"] == 1  # L9
    assert d["label_churn"] == 1  # L5


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0), (0.25, 0.5), (0.75, 0.5)],
)
def test_near_miss_flakiness(rate: float, expected: float) -> None:
    assert near_miss_flakiness(rate) == pytest.approx(expected)


def test_corpus_stability_extremes_and_midpoint() -> None:
    # All lines fire every repeat -> perfectly stable (1.0).
    stable = _runs(
        "e",
        [
            [Prediction("A", (1, 1), "e", "s", "w")],
            [Prediction("A", (1, 1), "e", "s", "w")],
        ],
    )
    assert corpus_stability(line_consistency_rows(stable)) == pytest.approx(1.0)

    # One line at rate 0.5 -> maximally flaky (0.0).
    flaky = _runs("e", [[Prediction("A", (1, 1), "e", "s", "w")], []])
    assert corpus_stability(line_consistency_rows(flaky)) == pytest.approx(0.0)


def test_corpus_stability_no_detections_is_one() -> None:
    assert corpus_stability([]) == pytest.approx(1.0)


def test_stability_excludes_churn_but_with_churn_includes_it() -> None:
    # One line, detected every repeat, drawing two rules (pure churn).
    runs = _runs(
        "e",
        [
            [Prediction("RULE-A", (5, 5), "e", "s", "warn")],
            [Prediction("RULE-B", (5, 5), "e", "s", "warn")],
        ],
    )
    line_rows = line_consistency_rows(runs)
    rule_rows = consistency_rows(runs)
    # Detection-only: the line fires 2/2 -> perfectly stable.
    assert corpus_stability(line_rows) == pytest.approx(1.0)
    # Churn-inclusive: two rule-buckets each fire 1/2 (rate 0.5) -> 0.0.
    assert corpus_stability_with_churn(rule_rows) == pytest.approx(0.0)


# --- Seed precision / recall ------------------------------------------------


def test_seed_perfect_recall_and_precision() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    pred = Prediction("wpt/docs/testharness.md", (7, 7), "e", "s", "warn")
    score = score_seed(_runs("s", [[pred], [pred]], role="seed"), [label])
    assert score.recall == pytest.approx(1.0)
    assert score.precision == pytest.approx(1.0)
    assert score.true_positives == 2


def test_seed_miss_is_false_negative() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    score = score_seed(_runs("s", [[], []], role="seed"), [label])
    assert score.recall == pytest.approx(0.0)
    assert score.false_negatives == 2


def test_seed_out_of_window_prediction_is_fp_and_fn() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    # Right key, wrong line window: does not satisfy the label, counts as FP.
    pred = Prediction("wpt/docs/testharness.md", (99, 99), "e", "s", "warn")
    score = score_seed(_runs("s", [[pred]], role="seed"), [label])
    assert score.false_negatives == 1
    assert score.false_positives == 1


def test_clean_seed_any_finding_is_false_positive() -> None:
    pred = Prediction("wpt/docs/x.md", (3, 3), "e", "s", "warn")
    score = score_seed(_runs("s", [[pred]], role="seed"), [])
    assert score.false_positives == 1
    assert score.precision == pytest.approx(0.0)


def test_clean_seed_no_findings_is_perfect() -> None:
    score = score_seed(_runs("s", [[], []], role="seed"), [])
    assert score.precision == pytest.approx(1.0)
    assert score.recall == pytest.approx(1.0)
    assert score.false_positives == 0


# --- classify_consistency_rows ----------------------------------------------


def _crow(
    key: str, bucket: tuple[int, int] | None, firings: int
) -> ConsistencyRow:
    return ConsistencyRow(
        entry_id="e", key=key, line_bucket=bucket, firings=firings, repeats=2
    )


def test_classify_splits_tp_and_fp() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    tp_row = _crow("wpt/docs/testharness.md", (15, 16), 2)  # in window
    fp_row = _crow("wpt/docs/checklist.md", (1, 1), 1)  # different key
    result = classify_consistency_rows([tp_row, fp_row], [label])
    assert result.true_positives == [tp_row]
    assert result.false_positives == [fp_row]
    assert result.missed_labels == []


def test_classify_out_of_window_is_fp() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    row = _crow("wpt/docs/testharness.md", (99, 99), 2)  # right key, wrong line
    result = classify_consistency_rows([row], [label])
    assert result.false_positives == [row]
    assert result.true_positives == []


def test_classify_reports_missed_label() -> None:
    label = ExpectLabel("wpt/docs/testharness.md", (4, 17))
    result = classify_consistency_rows([], [label])
    assert result.missed_labels == [label]


# --- warnings_for_row -------------------------------------------------------


def _note(key: str, line_range: tuple[int, int] | None) -> MechanicalIssue:
    return MechanicalIssue(
        entry_id="e",
        repeat=0,
        check="source",
        detail="d",
        key=key,
        line_range=line_range,
    )


def test_warnings_attributed_per_row_not_per_doc() -> None:
    # Two findings in the same doc at different lines; each note attributes
    # only to the row whose bucket it overlaps.
    row_a = _crow("wpt/docs/testharness.md", (15, 16), 2)
    row_b = _crow("wpt/docs/testharness.md", (1, 1), 1)
    notes = [
        _note("wpt/docs/testharness.md", (15, 16)),  # -> row_a
        _note("wpt/docs/testharness.md", (16, 16)),  # -> row_a (overlaps)
        _note("wpt/docs/testharness.md", (1, 1)),  # -> row_b
    ]
    assert warnings_for_row(row_a, notes) == {"source": 2}
    assert warnings_for_row(row_b, notes) == {"source": 1}


def test_warnings_none_when_no_matching_note() -> None:
    row = _crow("wpt/docs/testharness.md", (3, 3), 2)
    notes = [_note("wpt/docs/checklist.md", (3, 3))]  # different doc
    assert warnings_for_row(row, notes) == {}


# --- parse_expect -----------------------------------------------------------


def test_parse_expect_uses_source_doc_normalized() -> None:
    labels = parse_expect(
        [
            {
                "source_doc": "wpt/docs/testharness.md#L92",
                "rule_id": None,
                "test_file_lines": [4, 17],
            }
        ]
    )
    assert labels[0].key == "wpt/docs/testharness.md"
    assert labels[0].line_window == (4, 17)


def test_parse_expect_prefers_rule_id() -> None:
    labels = parse_expect(
        [
            {
                "source_doc": "wpt/docs/x.md",
                "rule_id": "R-1",
                "test_file_lines": [1, 2],
            }
        ]
    )
    assert labels[0].key == "R-1"


# --- Mechanical checks (source citation) ------------------------------------


def test_source_on_reading_list_pass_and_fail() -> None:
    reading_list = {"wpt/docs/writing-tests/testharness.md"}
    on = Prediction(
        "wpt/docs/writing-tests/testharness.md", None, "e", "s", "w"
    )
    off = Prediction("wpt/docs/invented.md", None, "e", "s", "w")
    assert check_source_on_reading_list(on, reading_list)
    assert not check_source_on_reading_list(off, reading_list)


def test_mechanical_issues_flags_off_list_citation() -> None:
    reading_list = {"wpt/docs/writing-tests/testharness.md"}
    preds = [
        Prediction(
            "wpt/docs/writing-tests/testharness.md", (1, 1), "e", "s", "w"
        ),
        Prediction("wpt/docs/invented.md", (2, 2), "e", "s", "w"),
    ]
    notes = mechanical_issues(
        entry_id="e",
        repeat_index=0,
        predictions=preds,
        reading_list=reading_list,
    )
    assert len(notes) == 1
    assert notes[0].check == "source"
    assert notes[0].key == "wpt/docs/invented.md"


# --- load_entry_runs from fixture dirs --------------------------------------


def test_load_entry_runs_reads_repeats(tmp_path: Path) -> None:
    payload = _payload([_finding(source="wpt/docs/testharness.md#L7")])
    _write_run(tmp_path, "seed-x", 0, "foo.worker.js", payload)
    _write_run(tmp_path, "seed-x", 1, "foo.worker.js", payload)
    repeat_dirs = [
        tmp_path / "runs" / "seed-x" / "rep-0",
        tmp_path / "runs" / "seed-x" / "rep-1",
    ]
    runs = load_entry_runs("seed-x", "seed", repeat_dirs, "foo.worker.js")
    assert runs.num_repeats == 2
    assert runs.repeats[0][0].key == "wpt/docs/testharness.md"


def test_load_entry_runs_missing_json_is_empty_repeat(tmp_path: Path) -> None:
    (tmp_path / "runs" / "e" / "rep-0").mkdir(parents=True)
    runs = load_entry_runs(
        "e", "corpus", [tmp_path / "runs" / "e" / "rep-0"], "foo.html"
    )
    assert runs.num_repeats == 1
    assert runs.repeats[0] == []


# --- discover_scored_entries (--score-only) ---------------------------------


def test_discover_scored_entries_narrows_to_on_disk_and_infers_repeats(
    tmp_path: Path,
) -> None:
    # Two entries selected, but only one actually ran (3 rep dirs). A re-score
    # must score just that entry, at the 3 reps found -- not the full
    # selection at some default repeat count.
    ran = SeedEntry(entry_id="seed-ran", kind="testharness", seed="ran.html")
    never = SeedEntry(
        entry_id="seed-never", kind="testharness", seed="never.html"
    )
    payload = _payload([_finding()])
    for i in range(3):
        _write_run(tmp_path, "seed-ran", i, "ran.html", payload)

    present, repeats = run_benchmark.discover_scored_entries(
        tmp_path, [ran, never]
    )
    assert [e.entry_id for e in present] == ["seed-ran"]
    assert repeats == 3


def test_discover_scored_entries_empty_when_nothing_ran(
    tmp_path: Path,
) -> None:
    (tmp_path / "runs").mkdir(parents=True)
    entry = SeedEntry(entry_id="seed-x", kind="testharness", seed="x.html")
    present, repeats = run_benchmark.discover_scored_entries(tmp_path, [entry])
    assert present == []
    assert repeats == 0


# --- detection-flaky band (score_entry) -------------------------------------


def test_detection_flaky_band_caps_at_target_and_has_no_floor() -> None:
    # At 3 reps warn_at is 0.61. A rare 1/3 (0.33) line is flagged; a 2/3
    # (0.67) line at/above target and an always-firing line are not.
    entry = CorpusEntry(entry_id="e", kind="testharness", path="e.html")
    runs = _runs(
        "e",
        [
            [
                Prediction("RARE", (10, 10), "e", "s", "warn"),
                Prediction("MEETS", (20, 20), "e", "s", "warn"),
                Prediction("ALWAYS", (30, 30), "e", "s", "warn"),
            ],
            [
                Prediction("MEETS", (20, 20), "e", "s", "warn"),
                Prediction("ALWAYS", (30, 30), "e", "s", "warn"),
            ],
            [Prediction("ALWAYS", (30, 30), "e", "s", "warn")],
        ],
    )
    report = run_benchmark.score_entry(entry, runs, reading_list=set())
    flagged = {cl["line"] for cl in report.detection_flaky_lines}
    assert flagged == {"L10"}


# --- Manifest validation ----------------------------------------------------


def _write_manifest(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _valid_manifest_dict() -> dict[str, Any]:
    return {
        "version": 1,
        "rules_version": None,
        "wpt_upstream_commit": "abc123",
        "canary": "guid",
        "corpus": [
            {
                "id": "corpus-a",
                "path": "css/foo.html",
                "kind": "testharness",
            },
        ],
        "seeds": [
            {
                "id": "seed-a",
                "seed": "testharness/foo.worker.js",
                "kind": "testharness",
                "expect": [
                    {
                        "source_doc": "wpt/docs/writing-tests/testharness.md",
                        "rule_id": None,
                        "test_file_lines": [4, 17],
                    }
                ],
            },
        ],
    }


def test_load_valid_manifest(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _valid_manifest_dict())
    manifest = load_manifest(path)
    assert len(manifest.entries) == 2
    assert [e.entry_id for e in manifest.corpus] == ["corpus-a"]
    seed = manifest.seeds[0]
    assert seed.test_rel_path() == "wpt-gen-bench/foo.worker.js"
    assert seed.test_file_name() == "foo.worker.js"
    assert seed.expect[0].key == "wpt/docs/writing-tests/testharness.md"


def test_corpus_test_rel_path_is_path_directly(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    assert manifest.corpus[0].test_rel_path() == "css/foo.html"


def test_manifest_seed_missing_expect_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    del data["seeds"][0]["expect"]
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ManifestError, match='needs an "expect"'):
        load_manifest(path)


def test_manifest_corpus_missing_path_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    del data["corpus"][0]["path"]
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ManifestError, match='needs a "path"'):
        load_manifest(path)


def test_manifest_duplicate_id_across_lists_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    data["seeds"][0]["id"] = "corpus-a"
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ManifestError, match="duplicate entry id"):
        load_manifest(path)


def test_manifest_empty_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    data["corpus"] = []
    data["seeds"] = []
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ManifestError, match="no entries"):
        load_manifest(path)


def test_validate_against_checkout_flags_missing_paths(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _valid_manifest_dict())
    manifest = load_manifest(path)
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    problems = validate_against_checkout(
        manifest.corpus, manifest.seeds, wpt_dir, seeds_root
    )
    # corpus path missing, seed file missing, and the expect doc missing.
    assert any("corpus path not found" in p for p in problems)
    assert any("seed file not found" in p for p in problems)
    assert any("doc not in checkout" in p for p in problems)


def test_validate_against_checkout_clean(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _valid_manifest_dict())
    manifest = load_manifest(path)
    wpt_dir = tmp_path / "wpt"
    (wpt_dir / "css").mkdir(parents=True)
    (wpt_dir / "css" / "foo.html").write_text("x", encoding="utf-8")
    (wpt_dir / "docs" / "writing-tests").mkdir(parents=True)
    (wpt_dir / "docs" / "writing-tests" / "testharness.md").write_text(
        "x", encoding="utf-8"
    )
    seeds_root = tmp_path / "seeds" / "testharness"
    seeds_root.mkdir(parents=True)
    (seeds_root / "foo.worker.js").write_text("x", encoding="utf-8")
    problems = validate_against_checkout(
        manifest.corpus, manifest.seeds, wpt_dir, tmp_path / "seeds"
    )
    assert problems == []


def test_load_rule_ids_parses_corpus(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "version: 1\nrules:\n"
        "  - id: TESTHARNESS-005\n    rule: a\n"
        "  - id: REFTESTS-002\n    rule: b\n",
        encoding="utf-8",
    )
    assert load_rule_ids(rules) == {"TESTHARNESS-005", "REFTESTS-002"}


def test_load_rule_ids_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_rule_ids(tmp_path / "nope.yaml") == set()


def _manifest_dict_with_rule_id(rule_id: str) -> dict[str, Any]:
    """A valid manifest whose single seed is keyed on a rule id."""
    data = _valid_manifest_dict()
    data["seeds"][0]["expect"][0]["rule_id"] = rule_id
    return data


def test_validate_flags_unknown_rule_id(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_dict_with_rule_id("TH-BOGUS-1"))
    manifest = load_manifest(path)
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    seeds_root = tmp_path / "seeds" / "testharness"
    seeds_root.mkdir(parents=True)
    (seeds_root / "foo.worker.js").write_text("x", encoding="utf-8")
    problems = validate_against_checkout(
        manifest.corpus,
        manifest.seeds,
        wpt_dir,
        tmp_path / "seeds",
        rule_ids={"TESTHARNESS-005"},
    )
    assert any("rule id not in rules.yaml: TH-BOGUS-1" in p for p in problems)


def test_validate_accepts_known_rule_id(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path, _manifest_dict_with_rule_id("TESTHARNESS-005")
    )
    manifest = load_manifest(path)
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    seeds_root = tmp_path / "seeds" / "testharness"
    seeds_root.mkdir(parents=True)
    (seeds_root / "foo.worker.js").write_text("x", encoding="utf-8")
    problems = validate_against_checkout(
        manifest.corpus,
        manifest.seeds,
        wpt_dir,
        tmp_path / "seeds",
        rule_ids={"TESTHARNESS-005"},
    )
    # Rule id resolves; only the (unrelated) corpus path is missing here.
    assert not any("rule id" in p for p in problems)


def test_validate_skips_rule_id_check_when_corpus_empty(
    tmp_path: Path,
) -> None:
    """An empty rule-id set (corpus unreadable) disables the check rather
    than flagging every rule id as unknown."""
    path = _write_manifest(tmp_path, _manifest_dict_with_rule_id("TH-BOGUS-1"))
    manifest = load_manifest(path)
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    seeds_root = tmp_path / "seeds" / "testharness"
    seeds_root.mkdir(parents=True)
    (seeds_root / "foo.worker.js").write_text("x", encoding="utf-8")
    problems = validate_against_checkout(
        manifest.corpus,
        manifest.seeds,
        wpt_dir,
        tmp_path / "seeds",
        rule_ids=set(),
    )
    assert not any("rule id" in p for p in problems)


# --- Model recorded in run_metadata -----------------------------------------


def _meta_payload(
    findings: list[dict[str, object]], provider: str, model: str
) -> dict[str, object]:
    p = _payload(findings)
    p["run_metadata"] = {"provider": provider, "model": model}
    return p


def test_load_entry_runs_collects_model_from_metadata(tmp_path: Path) -> None:
    payload = _meta_payload([_finding()], "anthropic", "claude-opus-4-6")
    _write_run(tmp_path, "e", 0, "foo.html", payload)
    _write_run(tmp_path, "e", 1, "foo.html", payload)
    runs = load_entry_runs(
        "e",
        "seed",
        [tmp_path / "runs" / "e" / f"rep-{i}" for i in (0, 1)],
        "foo.html",
    )
    assert runs.models == {("anthropic", "claude-opus-4-6")}


def test_resolve_run_model_single() -> None:
    assert run_benchmark._resolve_run_model(
        {("anthropic", "claude-opus-4-6")}
    ) == (
        "anthropic",
        "claude-opus-4-6",
        {
            "default": "claude-opus-4-6",
            "lightweight": "claude-opus-4-6",
            "reasoning": "claude-opus-4-6",
        },
    )


def test_resolve_run_model_single_with_categories() -> None:
    assert run_benchmark._resolve_run_model(
        {
            (
                "gemini",
                "gemini-3.7-flash",
                "gemini-3.7-flash",
                "gemini-3.7-flash",
                "gemini-3.7-flash",
            )
        }
    ) == (
        "gemini",
        "gemini-3.7-flash",
        {
            "default": "gemini-3.7-flash",
            "lightweight": "gemini-3.7-flash",
            "reasoning": "gemini-3.7-flash",
        },
    )


def test_resolve_run_model_empty_is_unknown() -> None:
    assert run_benchmark._resolve_run_model(set()) == (None, None, None)


def test_resolve_run_model_mixed_is_flagged() -> None:
    provider, model, categories = run_benchmark._resolve_run_model(
        {("anthropic", "claude-opus-4-6"), ("gemini", "gemini-3.1-pro")}
    )
    assert provider is not None
    assert provider.startswith("MIXED")
    assert model is not None
    assert model.startswith("MIXED")
    assert categories is None
    assert "claude-opus-4-6" in model
    assert "gemini-3.1-pro" in model


# --- wpt-dir from config ----------------------------------------------------


def test_wpt_dir_from_config_resolves_relative_to_config(
    tmp_path: Path,
) -> None:
    (tmp_path / "wpt").mkdir()
    cfg = tmp_path / "wpt-gen.yml"
    cfg.write_text("wpt_path: ./wpt\n", encoding="utf-8")
    resolved = run_benchmark.wpt_dir_from_config(cfg)
    assert resolved == (tmp_path / "wpt").resolve()


def test_wpt_dir_from_config_relative_parent(tmp_path: Path) -> None:
    # `../wpt` resolves against the config's directory, not cwd.
    (tmp_path / "wpt").mkdir()
    (tmp_path / "repo").mkdir()
    cfg = tmp_path / "repo" / "wpt-gen.yml"
    cfg.write_text("wpt_path: ../wpt\n", encoding="utf-8")
    assert (
        run_benchmark.wpt_dir_from_config(cfg) == (tmp_path / "wpt").resolve()
    )


def test_wpt_dir_from_config_missing_returns_none(tmp_path: Path) -> None:
    assert run_benchmark.wpt_dir_from_config(tmp_path / "nope.yml") is None


def test_wpt_dir_from_config_no_wpt_path_returns_none(tmp_path: Path) -> None:
    cfg = tmp_path / "wpt-gen.yml"
    cfg.write_text("default_provider: gemini\n", encoding="utf-8")
    assert run_benchmark.wpt_dir_from_config(cfg) is None


# --- Reading list from SKILL.md ---------------------------------------------


def test_load_reading_list_parses_skill_doc_paths(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "- `wpt/docs/writing-tests/testharness.md`\n"
        "- `wpt/docs/reviewing-tests/checklist.md`\n"
        "not a doc: `some/other/path.py`\n",
        encoding="utf-8",
    )
    keys = run_benchmark.load_reading_list(skill)
    assert keys == {
        "wpt/docs/writing-tests/testharness.md",
        "wpt/docs/reviewing-tests/checklist.md",
    }


def test_load_reading_list_default_reads_real_skill() -> None:
    # The default resolves the real evaluator SKILL.md and finds its docs.
    keys = run_benchmark.load_reading_list()
    assert "wpt/docs/writing-tests/testharness.md" in keys


def test_load_reading_list_missing_skill_raises(tmp_path: Path) -> None:
    with pytest.raises(run_benchmark.HarnessError, match="cannot read"):
        run_benchmark.load_reading_list(tmp_path / "nope.md")


def test_load_reading_list_empty_skill_raises(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("no doc paths here\n", encoding="utf-8")
    with pytest.raises(run_benchmark.HarnessError, match="no reading-list"):
        run_benchmark.load_reading_list(skill)


# --- Filtering --------------------------------------------------------------


def test_apply_filter_by_kind(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    filtered = run_benchmark.apply_filter(manifest.entries, "kind=testharness")
    assert {e.entry_id for e in filtered} == {"corpus-a", "seed-a"}


def test_apply_filter_by_role(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    filtered = run_benchmark.apply_filter(manifest.entries, "role=seed")
    assert [e.entry_id for e in filtered] == ["seed-a"]


def test_apply_filter_bad_expr_raises() -> None:
    with pytest.raises(run_benchmark.HarnessError):
        run_benchmark.apply_filter([], "nonsense")


# --- Seed staging safety ----------------------------------------------------


def _seed_entry(seed: str, kind: str = "testharness") -> SeedEntry:
    return SeedEntry(
        entry_id=f"seed-{Path(seed).stem}",
        kind=kind,
        seed=seed,
    )


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""


def _fake_run_recording(calls: list[list[str]]) -> Any:
    """A subprocess.run stand-in that records argv and returns success."""

    def _run(cmd: list[str], *a: Any, **k: Any) -> _FakeProc:
        calls.append(cmd)
        return _FakeProc()

    return _run


def test_parallel_runs_match_sequential_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flattened pool produces the same (entry_id, repeat) records as the
    sequential path, regardless of completion order."""
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    entries = [_seed_entry("testharness/a.js"), _seed_entry("testharness/b.js")]
    repeats = 3
    tasks = [(e, i) for e in entries for i in range(repeats)]

    def _run_all(jobs: int) -> set[tuple[str, int]]:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            "benchmark.run_benchmark.subprocess.run",
            _fake_run_recording(calls),
        )
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [
                pool.submit(
                    run_benchmark.run_single,
                    entry=e,
                    repeat=i,
                    wpt_dir=wpt_dir,
                    out=tmp_path / "out",
                    provider=None,
                    config=Path("wpt-gen.yml"),
                )
                for e, i in tasks
            ]
            records = [f.result() for f in as_completed(futures)]
        return {(r.entry_id, r.repeat) for r in records}

    expected = {(e.entry_id, i) for e, i in tasks}
    assert _run_all(jobs=1) == expected
    assert _run_all(jobs=4) == expected


# --- Quality gates ----------------------------------------------------------


def _agg(
    seed_precision: float = 1.0,
    seed_recall: float = 1.0,
    golden_recall: float = 1.0,
    seed_fn: int = 0,
    golden_fn: int = 0,
    corpus_stability: float = 1.0,
) -> dict[str, Any]:
    return {
        "seed_precision": seed_precision,
        "seed_recall": seed_recall,
        "golden_recall": golden_recall,
        "seed_false_negatives": seed_fn,
        "golden_false_negatives": golden_fn,
        "corpus_stability": corpus_stability,
    }


def test_quality_gates_pass_when_unset() -> None:
    # No thresholds set -> nothing checked, even on a poor aggregate.
    agg = _agg(seed_precision=0.0, seed_recall=0.0, golden_recall=0.0)
    assert (
        run_benchmark.check_quality_gates(
            agg, run_benchmark.QualityThresholds()
        )
        == []
    )


def test_quality_gates_flag_each_breach() -> None:
    agg = _agg(
        seed_precision=0.5, seed_recall=0.5, golden_recall=0.5, seed_fn=3
    )
    failures = run_benchmark.check_quality_gates(
        agg,
        run_benchmark.QualityThresholds(
            min_precision=0.9,
            min_recall=0.9,
            min_golden_recall=0.9,
            max_fn=2,
        ),
    )
    assert len(failures) == 4


def test_quality_gate_max_fn_sums_seed_and_golden() -> None:
    agg = _agg(seed_fn=1, golden_fn=2)
    thresholds = run_benchmark.QualityThresholds(max_fn=2)
    assert run_benchmark.check_quality_gates(agg, thresholds) == [
        "false negatives 3 > 2"
    ]


def test_quality_gate_boundary_is_inclusive() -> None:
    # Exactly meeting a floor passes; exactly at max_fn passes.
    agg = _agg(seed_precision=0.8, seed_fn=2)
    thresholds = run_benchmark.QualityThresholds(min_precision=0.8, max_fn=2)
    assert run_benchmark.check_quality_gates(agg, thresholds) == []


def test_quality_gate_min_stability() -> None:
    thresholds = run_benchmark.QualityThresholds(min_stability=0.7)
    # Below floor -> breach.
    assert run_benchmark.check_quality_gates(
        _agg(corpus_stability=0.5), thresholds
    ) == ["corpus stability 0.5 < 0.7"]
    # Exactly at floor -> passes (inclusive).
    assert (
        run_benchmark.check_quality_gates(
            _agg(corpus_stability=0.7), thresholds
        )
        == []
    )
    # Unset -> never breaches.
    assert (
        run_benchmark.check_quality_gates(
            _agg(corpus_stability=0.0), run_benchmark.QualityThresholds()
        )
        == []
    )


def test_stage_seeds_refuses_unmarked_existing_dir(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    (seeds_root / "testharness").mkdir(parents=True)
    (seeds_root / "testharness" / "s.js").write_text("x", encoding="utf-8")
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    # A pre-existing, non-harness staging dir must NOT be clobbered.
    (wpt_dir / STAGING_DIRNAME).mkdir()
    with pytest.raises(
        run_benchmark.HarnessError, match="refusing to overwrite"
    ):
        run_benchmark.stage_seeds(
            seeds_root, wpt_dir, [_seed_entry("testharness/s.js")]
        )


def test_stage_seeds_flattens_category_dir(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    (seeds_root / "testharness").mkdir(parents=True)
    (seeds_root / "testharness" / "s.js").write_text("x", encoding="utf-8")
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    entry = _seed_entry("testharness/s.js")

    staging = run_benchmark.stage_seeds(seeds_root, wpt_dir, [entry])
    # Flat: the category dir (testharness/) is dropped, and the staged path
    # is exactly what the subprocess is pointed at.
    assert (staging / "s.js").is_file()
    assert not (staging / "testharness").exists()
    assert (wpt_dir / entry.test_rel_path()).is_file()
    assert (staging / run_benchmark.STAGING_MARKER).is_file()


def test_stage_seeds_carries_reftest_references(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    (seeds_root / "reftest" / "references").mkdir(parents=True)
    (seeds_root / "reftest" / "t.html").write_text(
        '<link rel=match href="references/t-ref.html">', encoding="utf-8"
    )
    (seeds_root / "reftest" / "references" / "t-ref.html").write_text(
        "ref", encoding="utf-8"
    )
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()

    staging = run_benchmark.stage_seeds(
        seeds_root, wpt_dir, [_seed_entry("reftest/t.html", kind="reftest")]
    )
    # The test is flat, but its references/ sibling is carried so the
    # relative <link rel=match> still resolves.
    assert (staging / "t.html").is_file()
    assert (staging / "references" / "t-ref.html").is_file()


def test_stage_and_unstage_roundtrip(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    (seeds_root / "testharness").mkdir(parents=True)
    (seeds_root / "testharness" / "s.js").write_text("x", encoding="utf-8")
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    seeds = [_seed_entry("testharness/s.js")]

    staging = run_benchmark.stage_seeds(seeds_root, wpt_dir, seeds)
    assert (staging / "s.js").is_file()

    # A second stage over the harness-created dir is allowed (marker present).
    run_benchmark.stage_seeds(seeds_root, wpt_dir, seeds)

    run_benchmark.unstage(wpt_dir)
    assert not staging.exists()


def test_unstage_leaves_unmarked_dir_alone(tmp_path: Path) -> None:
    wpt_dir = tmp_path / "wpt"
    staging = wpt_dir / STAGING_DIRNAME
    staging.mkdir(parents=True)
    (staging / "real.txt").write_text("x", encoding="utf-8")
    run_benchmark.unstage(wpt_dir)
    assert staging.exists()  # no marker -> untouched


# --- End-to-end scoring (score-only over fixture run dirs) ------------------


def test_score_all_and_report(tmp_path: Path) -> None:
    """Full scoring pass over synthetic run dirs, no agent."""
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    out = tmp_path / "out"
    # The reading list the source-citation check runs against.
    reading_list = {"wpt/docs/writing-tests/testharness.md"}

    # seed-a: fires the expected finding in both repeats -> recall 1.0. Its
    # source doc is on the reading list, so no advisory note.
    seed_finding = _finding(
        source="wpt/docs/writing-tests/testharness.md#L92",
        test_line="Line 5",
        evidence="never calls done()",
    )
    prov, mdl = "anthropic", "claude-opus-4-6"
    _write_run(
        out,
        "seed-a",
        0,
        "foo.worker.js",
        _meta_payload([seed_finding], prov, mdl),
    )
    _write_run(
        out,
        "seed-a",
        1,
        "foo.worker.js",
        _meta_payload([seed_finding], prov, mdl),
    )
    # corpus-a: one finding, one silent repeat -> flaky (0.5).
    corpus_finding = _finding(source="wpt/docs/writing-tests/testharness.md#L3")
    _write_run(
        out,
        "corpus-a",
        0,
        "foo.html",
        _meta_payload([corpus_finding], prov, mdl),
    )
    _write_run(out, "corpus-a", 1, "foo.html", _meta_payload([], prov, mdl))

    reports, models = run_benchmark.score_all(
        manifest=manifest,
        entries=manifest.entries,
        out=out,
        repeats=2,
        reading_list=reading_list,
    )
    by_id = {r.entry_id: r for r in reports}
    assert models == {(prov, mdl)}

    seed_report = by_id["seed-a"]
    assert seed_report.seed_score is not None
    assert seed_report.seed_score["recall"] == pytest.approx(1.0)
    assert seed_report.advisory_notes == []
    # The intended finding is bracketed as a true positive.
    assert seed_report.consistency_by_outcome is not None
    assert len(seed_report.consistency_by_outcome["true_positives"]) == 1
    assert seed_report.consistency_by_outcome["false_positives"] == []

    corpus_report = by_id["corpus-a"]
    assert corpus_report.seed_score is None
    # Corpus entries carry no gold labels, so no TP/FP bracketing.
    assert corpus_report.consistency_by_outcome is None
    assert corpus_report.consistency[0]["rate"] == pytest.approx(0.5)

    full = run_benchmark.build_report(
        manifest=manifest,
        models=models,
        wpt_dir=tmp_path / "wpt",
        repeats=2,
        reports=reports,
        run_records=[],
        actual_commit="abc123",
    )
    assert full.aggregate["seed_recall"] == pytest.approx(1.0)
    md = run_benchmark.render_report_markdown(full)
    assert "WPT evaluator benchmark report" in md
    # The model/provider must appear in the report header.
    assert "claude-opus-4-6" in md
    assert "anthropic" in md
    # Structural anchors only (not prose, which is subject to change): the
    # legend link, the per-dataset summary + scope line, the aggregate bucket
    # table, and the per-entry finding tables.
    assert "#reading-a-benchmark-report" in md
    assert "Summary" in md
    assert "seed" in md
    assert "corpus" in md
    assert "**Scope**:" in md
    assert "### Consistency buckets" in md
    assert "| bucket | firing rate | count | meaning |" in md
    assert "**True positives**" in md
    assert "**False positives**" in md
    assert "| title | source | firing rate | warnings |" in md
    assert "## 🛠️ Action Items & Diagnosis" in md
    assert "<details>" in md


def _bench_report(
    entries: list[dict[str, Any]],
    aggregate: dict[str, Any],
    quality_thresholds: dict[str, Any] | None = None,
    quality_gate_failures: list[str] | None = None,
    run_records: list[dict[str, Any]] | None = None,
    repo_commit_sha: str | None = None,
    provider: str | None = "p",
    model: str | None = "mdl",
    categories: dict[str, str] | None = None,
) -> Any:
    return run_benchmark.BenchmarkReport(
        manifest="m.yaml",
        provider=provider,
        model=model,
        categories=categories,
        wpt_dir="/wpt",
        wpt_upstream_commit_expected="pinned123",
        wpt_upstream_commit_actual=None,
        repeats=3,
        entries=entries,
        run_records=run_records or [],
        aggregate=aggregate,
        quality_thresholds=quality_thresholds,
        quality_gate_failures=(
            tuple(quality_gate_failures) if quality_gate_failures else ()
        ),
        repo_commit_sha=repo_commit_sha,
    )


def test_summary_renders_a_row_per_present_dataset() -> None:
    entries = [
        {"role": "seed", "kind": "testharness"},
        {"role": "golden", "kind": "js"},
        {"role": "corpus", "kind": "reftest"},
    ]
    agg = {
        "seed_precision": 0.8,
        "seed_recall": 1.0,
        "golden_recall": 0.75,
        "consistency_histogram": {"mid": 2},
        "consistency_decomposition": {"label_churn": 3},
        "corpus_stability": 0.95,
        "golden_unmatched_predictions": 0,
        "advisory_notes": 0,
    }
    lines = run_benchmark._render_summary(_bench_report(entries, agg))
    md = "\n".join(lines)
    assert "| **`seed`** (1) |" in md
    assert "**0.8** precision / **1.0** recall" in md
    assert "| **`golden`** (1) |" in md
    assert "**0.75** recall" in md
    assert "| **`corpus`** (1) |" in md
    # Corpus centres the stability score; churn is advisory, not scored.
    assert "**0.95** stability" in md
    assert "3 label-churn (advisory)" in md


def test_summary_omits_absent_datasets() -> None:
    # A seed-only run has no golden/corpus rows.
    entries = [{"role": "seed", "kind": "testharness"}]
    agg = {
        "seed_precision": 1.0,
        "seed_recall": 1.0,
        "golden_recall": 1.0,
        "consistency_histogram": {"mid": 0},
        "corpus_stability": 1.0,
    }
    md = "\n".join(run_benchmark._render_summary(_bench_report(entries, agg)))
    assert "| **`seed`** (1) |" in md
    assert "**`golden`**" not in md
    assert "**`corpus`**" not in md


@pytest.mark.parametrize(
    ("stability", "repeats", "expected"),
    [
        (1.0, 8, "✅ Stable"),
        (0.6, 8, "⚠️ Variable"),  # warn<0.72, fail<0.52 at 8 reps
        (0.4, 8, "❌ Unstable"),
        # Bands widen at low repeats: 0.65 passes at 3 reps (warn<0.61) but
        # would only warn at 8 reps (warn<0.72).
        (0.65, 3, "✅ Stable"),
        (0.65, 8, "⚠️ Variable"),
    ],
)
def test_stability_status_widens_with_repeats(
    stability: float, repeats: int, expected: str
) -> None:
    assert run_benchmark._stability_status(stability, repeats) == expected


def test_summary_reflects_quality_thresholds() -> None:
    entries = [
        {"role": "seed", "kind": "testharness"},
        {"role": "golden", "kind": "js"},
    ]
    agg = {
        "seed_precision": 1.0,
        "seed_recall": 1.0,
        "golden_recall": 0.8,
        "consistency_histogram": {"mid": 0},
        "corpus_stability": 1.0,
    }
    # 1. Configured thresholds
    rep_with_t = _bench_report(
        entries,
        agg,
        quality_thresholds={
            "min_recall": 1.0,
            "min_precision": 0.9,
            "min_golden_recall": 0.8,
        },
    )
    md_with_t = "\n".join(run_benchmark._render_summary(rep_with_t))
    assert "1.0 Recall, 0.9 Precision | ✅ Pass" in md_with_t
    assert "0.8 Recall | ✅ Pass" in md_with_t

    # 2. Informational (no thresholds)
    rep_info = _bench_report(entries, agg, quality_thresholds=None)
    md_info = "\n".join(run_benchmark._render_summary(rep_info))
    assert "Informational | ℹ️ Tracked" in md_info


def test_format_quality_gate_descriptors() -> None:
    # None / empty
    active, unset = run_benchmark._format_quality_gate_descriptors(None)
    assert active == []
    assert unset == [
        "min-precision",
        "min-recall",
        "min-golden-recall",
        "max-fn",
        "min-stability",
    ]

    # Partial
    active, unset = run_benchmark._format_quality_gate_descriptors(
        {"min_recall": 1.0, "min_precision": None}
    )
    assert active == ["seed recall ≥ 1.0"]
    assert unset == [
        "min-precision",
        "min-golden-recall",
        "max-fn",
        "min-stability",
    ]

    # All set
    active, unset = run_benchmark._format_quality_gate_descriptors(
        run_benchmark.QualityThresholds(
            min_precision=0.9,
            min_recall=1.0,
            min_golden_recall=0.8,
            max_fn=0,
            min_stability=0.7,
        )
    )
    assert active == [
        "seed recall ≥ 1.0",
        "seed precision ≥ 0.9",
        "golden recall ≥ 0.8",
        "max false negatives ≤ 0",
        "corpus stability ≥ 0.7",
    ]
    assert unset == []


def test_render_executive_banner() -> None:
    # 1. No thresholds -> empty
    rep_none = _bench_report([], {})
    assert run_benchmark._render_executive_banner(rep_none) == []

    # 2. Passing thresholds
    rep_pass = _bench_report(
        [], {}, quality_thresholds={"min_recall": 1.0}, quality_gate_failures=[]
    )
    banner_pass = "\n".join(run_benchmark._render_executive_banner(rep_pass))
    assert "### ✅ PASS · Quality Gates Satisfied" in banner_pass
    assert "- **Active Gates**: `seed recall ≥ 1.0`" in banner_pass
    assert (
        "- _(Unset thresholds: min-precision, min-golden-recall, max-fn,"
        " min-stability)_" in banner_pass
    )

    # 3. Failing thresholds
    rep_fail = _bench_report(
        [],
        {},
        quality_thresholds={"min_recall": 1.0},
        quality_gate_failures=["seed recall 0.5 < 1.0"],
    )
    banner_fail = "\n".join(run_benchmark._render_executive_banner(rep_fail))
    assert "### ❌ FAIL · Quality Gate Regression (1)" in banner_fail
    assert "seed recall 0.5 < 1.0" in banner_fail
    assert "- **Active Gates**: `seed recall ≥ 1.0`" in banner_fail
    assert (
        "- _(Unset thresholds: min-precision, min-golden-recall, max-fn,"
        " min-stability)_" in banner_fail
    )


def test_escape_md_cell() -> None:
    assert run_benchmark._escape_md_cell("Simple title") == "Simple title"
    assert (
        run_benchmark._escape_md_cell("Title with | pipe")
        == r"Title with \| pipe"
    )
    assert (
        run_benchmark._escape_md_cell("Tag <script>alert(1)</script>")
        == "Tag &lt;script&gt;alert(1)&lt;/script&gt;"
    )
    assert (
        run_benchmark._escape_md_cell("Multi\nline\r\ntitle")
        == "Multi line title"
    )


def test_entry_source_url() -> None:
    seed_entry = {"role": "seed", "test_rel_path": "wpt-gen-bench/foo.html"}
    assert (
        run_benchmark._entry_source_url(seed_entry, "pinned_sha")
        == "https://github.com/GoogleChromeLabs/wpt-gen/blob/main/benchmarks/seeds/foo.html"
    )

    corpus_entry = {"role": "corpus", "test_rel_path": "dom/nodes/foo.html"}
    assert (
        run_benchmark._entry_source_url(corpus_entry, "pinned_sha")
        == "https://github.com/web-platform-tests/wpt/blob/pinned_sha/dom/nodes/foo.html"
    )

    golden_entry = {"role": "golden", "test_rel_path": "golden/pr123/bar.html"}
    assert (
        run_benchmark._entry_source_url(golden_entry, "pinned_sha")
        == "https://github.com/web-platform-tests/wpt/blob/pinned_sha/golden/pr123/bar.html"
    )


def test_render_action_items() -> None:
    # 1. Clean run
    clean_report = _bench_report(
        entries=[
            {
                "role": "seed",
                "entry_id": "seed-1",
                "test_rel_path": "wpt-gen-bench/seed1.html",
            }
        ],
        aggregate={"consistency_histogram": {"mid": 0}},
    )
    clean_md = "\n".join(run_benchmark._render_action_items(clean_report))
    assert "✅ **No regressions or execution issues detected.**" in clean_md

    # 2. Subprocess crash + False Negative + False Positive + Flaky
    faulty_report = _bench_report(
        entries=[
            {
                "role": "seed",
                "entry_id": "seed-fail",
                "test_rel_path": "wpt-gen-bench/seed-fail.html",
                "seed_score": {"false_positives": 1},
                "detection_flaky_lines": [
                    {
                        "line": "L12",
                        "keys": ["FLAKY-001"],
                        "firings": 1,
                        "repeats": 3,
                        "rate": 0.3333,
                    }
                ],
                "label_churn_lines": [
                    {"line": "L4", "keys": ["RULE-A", "RULE-B"]}
                ],
                "consistency_by_outcome": {
                    "missed_labels": [
                        {"key": "CHECKLIST-004", "line_window": [10, 20]}
                    ],
                    "false_positives": [
                        {
                            "key": "CHECKLIST-010",
                            "line_bucket": [5, 5],
                            "firings": 2,
                            "repeats": 3,
                        }
                    ],
                },
            },
            {
                "role": "golden",
                "entry_id": "golden-fail",
                "test_rel_path": "wpt-gen-bench/golden-fail.html",
                "consistency_by_outcome": {
                    "missed_labels": [
                        {"key": "GOLDEN-RULE-001", "line_window": [30, 35]}
                    ]
                },
            },
        ],
        aggregate={"consistency_histogram": {"mid": 1}},
        run_records=[
            {
                "entry_id": "seed-fail",
                "repeat": 0,
                "exit_code": 1,
                "output_dir": "/tmp/out",
            }
        ],
    )
    faulty_md = "\n".join(run_benchmark._render_action_items(faulty_report))
    assert "🚨 **Subprocess Execution Error in `seed-fail`" in faulty_md
    assert "❌ **Missed Expected Injected Defect in `seed-fail`" in faulty_md
    assert "CHECKLIST-004" in faulty_md
    assert (
        "❌ **Missed Expected Human Reviewer Defect in `golden-fail`"
        in faulty_md
    )
    assert "GOLDEN-RULE-001" in faulty_md
    assert "⚠️ **False Alarm on Test in `seed-fail`" in faulty_md
    assert "CHECKLIST-010" in faulty_md
    # Flakiness is bracketed: detection instability (scored) vs. label churn.
    assert "⚠️ **Detection Instability (1)**" in faulty_md
    assert "`seed-fail` @ L12 (1/3, rate 0.33): `FLAKY-001`" in faulty_md
    assert "ℹ️ **Label Churn (1)**" in faulty_md
    assert "`seed-fail` @ L4: `RULE-A`, `RULE-B`" in faulty_md
    assert "💡 **Quick Triage Tip**" in faulty_md


def test_render_legend_is_collapsible() -> None:
    lines = run_benchmark._render_legend()
    md = "\n".join(lines)
    assert "<details>" in md
    assert (
        "<summary><b>📖 How to Read & Interpret This Report</b></summary>" in md
    )
    assert "* **`seed`**:" in md
    assert "* **`golden`**:" in md
    assert "* **`corpus`**:" in md
    assert "* **Graded band**:" in md
    assert "* **Fixed band**:" in md
    assert "</details>" in md


def test_render_report_markdown_includes_evaluated_commit() -> None:
    rep = _bench_report(
        entries=[],
        aggregate={"consistency_histogram": {"mid": 0}},
        repo_commit_sha="b5488ba5b588b4a773af28e9f3391434661b4fbb",
    )
    md = run_benchmark.render_report_markdown(rep)
    assert (
        "- **Evaluated Commit**: [`b5488ba`](https://github.com/GoogleChromeLabs/wpt-gen/commit/b5488ba5b588b4a773af28e9f3391434661b4fbb)"
        in md
    )


def test_render_report_markdown_includes_explicit_categories() -> None:
    rep = _bench_report(
        entries=[],
        aggregate={"consistency_histogram": {"mid": 0}},
        provider="gemini",
        model="gemini-3.7-flash",
        categories={
            "default": "gemini-3.7-flash",
            "lightweight": "gemini-3.7-flash",
            "reasoning": "gemini-3.7-flash",
        },
    )
    md = run_benchmark.render_report_markdown(rep)
    assert (
        "- **Model**: `gemini-3.7-flash` (provider: `gemini` · default: `gemini-3.7-flash` · lightweight: `gemini-3.7-flash` · reasoning: `gemini-3.7-flash`)"
        in md
    )


def test_progress_start_prints_atomic_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_benchmark.Progress(total=4).start("seed-a", 1)
    err = capsys.readouterr().err
    # One atomic, newline-terminated line naming the started rep (1-indexed).
    assert err == "[started] seed-a rep 2\n"


def _finding_row(key: str, rate: float) -> dict[str, Any]:
    return {
        "key": key,
        "title": key,
        "line_bucket": [1, 1],
        "firings": 2,
        "repeats": 2,
        "rate": rate,
        "warnings": {},
    }


def test_golden_entry_renders() -> None:
    entry = {
        "entry_id": "golden-1-abcd",
        "role": "golden",
        "kind": "testharness",
        "seed_score": None,
        "golden_score": {
            "recall": 1.0,
            "true_positives": 1,
            "false_negatives": 0,
            "unmatched_predictions": 1,
        },
        "consistency": [_finding_row("CHECKLIST-005", 1.0)],
        "consistency_by_outcome": {
            "true_positives": [_finding_row("CHECKLIST-005", 1.0)],
            "false_positives": [_finding_row("GENERAL-007", 0.5)],
            "missed_labels": [],
        },
    }
    md = "\n".join(run_benchmark._render_entry(entry))
    assert "**True positives**" in md
    assert "**Unmatched**" in md
    # Golden must not borrow the seed vocabulary.
    assert "**False positives**" not in md


def test_off_reading_list_citation_is_advisory_note(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    out = tmp_path / "out"
    # A finding that cites a doc NOT on the reading list -> advisory note.
    bad = _finding(
        source="wpt/docs/writing-tests/invented-doc.md#L1",
        test_line="Line 1",
    )
    _write_run(out, "seed-a", 0, "foo.worker.js", _payload([bad]))

    reports, _ = run_benchmark.score_all(
        manifest=manifest,
        entries=[e for e in manifest.entries if e.entry_id == "seed-a"],
        out=out,
        repeats=1,
        reading_list={"wpt/docs/writing-tests/testharness.md"},
    )
    notes = reports[0].advisory_notes
    assert any(n["check"] == "source" for n in notes)


# --- Golden: score_golden ---------------------------------------------------


def test_golden_recall_and_unmatched_not_charged() -> None:
    label = GoldenLabel("CHECKLIST-005", (4, 17))
    hit = Prediction("CHECKLIST-005", (7, 7), "e", "s", "warn")
    extra = Prediction("GENERAL-006", (99, 99), "e", "s", "warn")
    score = score_golden(_runs("g", [[hit, extra]], role="golden"), [label])
    assert score.true_positives == 1
    assert score.recall == pytest.approx(1.0)
    # A prediction with no gold label is unmatched, NOT a false positive.
    assert score.unmatched_predictions == 1


def test_golden_miss_is_false_negative() -> None:
    label = GoldenLabel("CHECKLIST-005", (4, 17))
    score = score_golden(_runs("g", [[]], role="golden"), [label])
    assert score.false_negatives == 1
    assert score.recall == pytest.approx(0.0)


def test_golden_no_labels_still_counts_predictions() -> None:
    # A PR whose comments were all no-rule: empty expect, no denominator, but
    # its predictions still land in unmatched (not charged).
    pred = Prediction("CHECKLIST-004", (3, 3), "e", "s", "warn")
    score = score_golden(_runs("g", [[pred]], role="golden"), [])
    assert score.true_positives == 0
    assert score.false_negatives == 0
    assert score.unmatched_predictions == 1
    assert score.recall == pytest.approx(1.0)  # empty denominator


# --- Golden: loader ---------------------------------------------------------


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _write_golden_fixture(
    root: Path,
    pr: int,
    labels: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    files: dict[str, str] | None = None,
) -> None:
    candidates = root / "candidates"
    annotated = root / "annotated"
    candidates.mkdir(parents=True, exist_ok=True)
    annotated.mkdir(parents=True, exist_ok=True)
    commit_id = "3b54d1442da4757e229d56520d77c7581e79d877"
    files = files or {labels[0]["path"]: "test body\n"}
    candidate = {
        "pr": pr,
        "reviewed_commits": [
            {
                "commit_id": commit_id,
                "test_files": [
                    {"path": p, "content_b64": _b64(body)}
                    for p, body in files.items()
                ],
                "comments": comments,
            }
        ],
    }
    (candidates / f"{pr}.json").write_text(
        json.dumps(candidate), encoding="utf-8"
    )
    (annotated / f"{pr}.yaml").write_text(
        yaml.safe_dump({"pr": pr, "labels": labels}), encoding="utf-8"
    )


def test_load_golden_drops_no_rule_and_joins_fixed(tmp_path: Path) -> None:
    url_mapped = "https://x/pull/1#discussion_r1"
    url_norule = "https://x/pull/1#discussion_r2"
    _write_golden_fixture(
        tmp_path,
        pr=1,
        labels=[
            {
                "html_url": url_mapped,
                "rule_id": "CHECKLIST-005",
                "path": "a/t.js",
                "lines": [4, 4],
            },
            {
                "html_url": url_norule,
                "rule_id": "no-rule",
                "path": "a/t.js",
                "lines": [9, 9],
            },
        ],
        comments=[
            {"html_url": url_mapped, "fixed_before_merge": True},
            {"html_url": url_norule, "fixed_before_merge": False},
        ],
    )
    entries = load_golden_entries(
        tmp_path / "candidates", tmp_path / "annotated"
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entry_id == "golden-1-3b54d144"
    # no-rule dropped -> one gold label.
    assert [label.key for label in entry.expect] == ["CHECKLIST-005"]
    assert entry.expect[0].fixed_before_merge is True


def test_load_golden_all_no_rule_loads_empty_expect(tmp_path: Path) -> None:
    _write_golden_fixture(
        tmp_path,
        pr=2,
        labels=[
            {
                "html_url": "https://x/2#r1",
                "rule_id": "no-rule",
                "path": "a/t.js",
                "lines": [1, 1],
            }
        ],
        comments=[{"html_url": "https://x/2#r1", "fixed_before_merge": False}],
    )
    entries = load_golden_entries(
        tmp_path / "candidates", tmp_path / "annotated"
    )
    assert len(entries) == 1  # not skipped
    assert entries[0].expect == []


def test_load_golden_picks_most_commented_block(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates"
    annotated = tmp_path / "annotated"
    candidates.mkdir()
    annotated.mkdir()
    candidate = {
        "pr": 3,
        "reviewed_commits": [
            {
                "commit_id": "a" * 40,
                "test_files": [{"path": "t.js", "content_b64": _b64("x")}],
                "comments": [{"html_url": "u1"}],
            },
            {
                "commit_id": "b" * 40,
                "test_files": [{"path": "t.js", "content_b64": _b64("y")}],
                "comments": [{"html_url": "u2"}, {"html_url": "u3"}],
            },
        ],
    }
    (candidates / "3.json").write_text(json.dumps(candidate), encoding="utf-8")
    (annotated / "3.yaml").write_text(
        yaml.safe_dump({"pr": 3, "labels": []}), encoding="utf-8"
    )
    entry = load_golden_entries(candidates, annotated)[0]
    assert entry.commit_id == "b" * 40  # the 2-comment block


def test_load_golden_skips_candidate_without_annotation(
    tmp_path: Path,
) -> None:
    candidates = tmp_path / "candidates"
    annotated = tmp_path / "annotated"
    candidates.mkdir()
    annotated.mkdir()
    (candidates / "9.json").write_text(
        json.dumps({"pr": 9, "reviewed_commits": []}), encoding="utf-8"
    )
    assert load_golden_entries(candidates, annotated) == []


def test_load_golden_reads_real_dev_set() -> None:
    # The checked-in dev set loads; #43400 has 2 CHECKLIST-005 labels.
    golden_dir = REPO_ROOT / "benchmarks" / "golden"
    entries = load_golden_entries(
        golden_dir / "candidates", golden_dir / "annotated"
    )
    by_pr = {e.pr: e for e in entries}
    assert 43400 in by_pr
    keys = [label.key for label in by_pr[43400].expect]
    assert keys == ["CHECKLIST-005", "CHECKLIST-005"]


# --- Golden: staging --------------------------------------------------------


def test_stage_golden_decodes_bytes_to_per_pr_path(tmp_path: Path) -> None:
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    entry = GoldenEntry(
        entry_id="golden-1-abcd1234",
        kind="js",
        pr=1,
        commit_id="abcd1234" + "0" * 32,
        path="a/t.js",
        files_b64={"a/t.js": _b64("hello\n")},
    )
    run_benchmark.stage_golden(wpt_dir, [entry])
    staged = (
        wpt_dir / STAGING_DIRNAME / GOLDEN_STAGING_SUBDIR / "1" / "a" / "t.js"
    )
    assert staged.read_text(encoding="utf-8") == "hello\n"
    # The staged path matches the entry's advertised test_rel_path.
    assert (wpt_dir / entry.test_rel_path()) == staged


# --- Golden: subset selection -----------------------------------------------


def _golden_entry(pr: int) -> GoldenEntry:
    return GoldenEntry(
        entry_id=f"golden-{pr}-abcd1234",
        kind="js",
        pr=pr,
        commit_id="abcd1234" + "0" * 32,
        path="a/t.js",
    )


def _manifest_with_sets(tmp_path: Path, sets: dict[str, list[int]]) -> Any:
    data = _valid_manifest_dict()
    data["golden_sets"] = sets
    return load_manifest(_write_manifest(tmp_path, data))


def test_select_golden_no_args_returns_all(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {})
    entries = [_golden_entry(1), _golden_entry(2)]
    assert run_benchmark.select_golden(entries, manifest, None, None) == entries


def test_select_golden_named_set(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {"smoke": [2]})
    entries = [_golden_entry(1), _golden_entry(2), _golden_entry(3)]
    got = run_benchmark.select_golden(entries, manifest, "smoke", None)
    assert [e.pr for e in got] == [2]


def test_select_golden_empty_set_means_all(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {"all": []})
    entries = [_golden_entry(1), _golden_entry(2)]
    got = run_benchmark.select_golden(entries, manifest, "all", None)
    assert [e.pr for e in got] == [1, 2]


def test_select_golden_pr_csv(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {})
    entries = [_golden_entry(1), _golden_entry(2), _golden_entry(3)]
    got = run_benchmark.select_golden(entries, manifest, None, "3,1")
    assert [e.pr for e in got] == [1, 3]  # sorted


def test_select_golden_set_and_prs_intersect(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {"mapped": [1, 2, 3]})
    entries = [_golden_entry(1), _golden_entry(2), _golden_entry(3)]
    got = run_benchmark.select_golden(entries, manifest, "mapped", "2,3,99")
    assert [e.pr for e in got] == [2, 3]


def test_select_golden_unknown_set_errors(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {"smoke": [1]})
    with pytest.raises(run_benchmark.HarnessError, match="nope"):
        run_benchmark.select_golden([_golden_entry(1)], manifest, "nope", None)


def test_select_golden_missing_pr_warns_and_skips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest_with_sets(tmp_path, {})
    got = run_benchmark.select_golden(
        [_golden_entry(1)], manifest, None, "1,99999"
    )
    assert [e.pr for e in got] == [1]
    assert "99999" in capsys.readouterr().err


def test_select_golden_bad_pr_csv_errors(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {})
    with pytest.raises(run_benchmark.HarnessError):
        run_benchmark.select_golden(
            [_golden_entry(1)], manifest, None, "1,notanint"
        )


def test_manifest_golden_sets_parsed(tmp_path: Path) -> None:
    manifest = _manifest_with_sets(tmp_path, {"smoke": [43400], "all": []})
    assert manifest.golden_sets == {"smoke": [43400], "all": []}


def test_manifest_golden_sets_non_int_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    data["golden_sets"] = {"bad": ["43400"]}
    with pytest.raises(ManifestError, match="non-integer"):
        load_manifest(_write_manifest(tmp_path, data))


# --- Smoke / regression tier ------------------------------------------------


def _manifest_with_id_sets(
    tmp_path: Path,
    corpus_sets: dict[str, list[str]] | None = None,
    seed_sets: dict[str, list[str]] | None = None,
) -> Any:
    data = _valid_manifest_dict()
    if corpus_sets is not None:
        data["corpus_sets"] = corpus_sets
    if seed_sets is not None:
        data["seed_sets"] = seed_sets
    return load_manifest(_write_manifest(tmp_path, data))


def test_manifest_id_sets_parsed(tmp_path: Path) -> None:
    manifest = _manifest_with_id_sets(
        tmp_path, corpus_sets={"smoke": ["corpus-a"]}, seed_sets={}
    )
    assert manifest.corpus_sets == {"smoke": ["corpus-a"]}
    assert manifest.seed_sets == {}


def test_manifest_id_sets_non_string_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    data["corpus_sets"] = {"smoke": [123]}
    with pytest.raises(ManifestError, match="non-string"):
        load_manifest(_write_manifest(tmp_path, data))


def test_select_smoke_narrows_corpus_and_seeds(tmp_path: Path) -> None:
    manifest = _manifest_with_id_sets(
        tmp_path,
        corpus_sets={"smoke": ["corpus-a"]},
        seed_sets={"smoke": ["seed-a"]},
    )
    corpus, seeds = run_benchmark.select_smoke(
        manifest, manifest.corpus, manifest.seeds
    )
    assert [c.entry_id for c in corpus] == ["corpus-a"]
    assert [s.entry_id for s in seeds] == ["seed-a"]


def test_select_smoke_empty_set_selects_nothing(tmp_path: Path) -> None:
    # No `smoke` entry for a type -> that type contributes nothing.
    manifest = _manifest_with_id_sets(tmp_path, corpus_sets={"smoke": []})
    corpus, seeds = run_benchmark.select_smoke(
        manifest, manifest.corpus, manifest.seeds
    )
    assert corpus == []
    assert seeds == []


def test_select_smoke_unknown_id_errors(tmp_path: Path) -> None:
    manifest = _manifest_with_id_sets(
        tmp_path, corpus_sets={"smoke": ["corpus-nope"]}
    )
    with pytest.raises(run_benchmark.HarnessError, match="corpus-nope"):
        run_benchmark.select_smoke(manifest, manifest.corpus, manifest.seeds)

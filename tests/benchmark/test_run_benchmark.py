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
from pathlib import Path
from typing import Any

import pytest
import yaml

# scripts/ is put on sys.path by tests/conftest.py, so the
# ``benchmark`` package resolves here.
from benchmark import run_benchmark
from benchmark.manifest import (
    ManifestError,
    SeedEntry,
    load_manifest,
    validate_against_checkout,
)
from benchmark.scoring import (
    ConsistencyRow,
    EntryRuns,
    ExpectLabel,
    MechanicalIssue,
    Prediction,
    check_source_on_reading_list,
    classify_consistency_rows,
    consistency_histogram,
    consistency_rows,
    finding_key,
    load_entry_runs,
    mechanical_issues,
    normalize_source_doc,
    parse_expect,
    parse_line_range,
    payload_to_predictions,
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
                "dest": "wpt-gen-bench/",
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


def test_manifest_seed_missing_dest_rejected(tmp_path: Path) -> None:
    data = _valid_manifest_dict()
    del data["seeds"][0]["dest"]
    path = _write_manifest(tmp_path, data)
    with pytest.raises(ManifestError, match='needs a "dest"'):
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
    problems = validate_against_checkout(manifest, wpt_dir, seeds_root)
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
    problems = validate_against_checkout(manifest, wpt_dir, tmp_path / "seeds")
    assert problems == []


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
    ) == ("anthropic", "claude-opus-4-6")


def test_resolve_run_model_empty_is_unknown() -> None:
    assert run_benchmark._resolve_run_model(set()) == (None, None)


def test_resolve_run_model_mixed_is_flagged() -> None:
    provider, model = run_benchmark._resolve_run_model(
        {("anthropic", "claude-opus-4-6"), ("gemini", "gemini-3.1-pro")}
    )
    assert provider is not None
    assert provider.startswith("MIXED")
    assert model is not None
    assert model.startswith("MIXED")
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
        dest="wpt-gen-bench/",
    )


def test_stage_seeds_refuses_unmarked_existing_dir(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    (seeds_root / "testharness").mkdir(parents=True)
    (seeds_root / "testharness" / "s.js").write_text("x", encoding="utf-8")
    wpt_dir = tmp_path / "wpt"
    wpt_dir.mkdir()
    # A pre-existing, non-harness staging dir must NOT be clobbered.
    (wpt_dir / run_benchmark.STAGING_DIRNAME).mkdir()
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

    run_benchmark.unstage_seeds(wpt_dir)
    assert not staging.exists()


def test_unstage_leaves_unmarked_dir_alone(tmp_path: Path) -> None:
    wpt_dir = tmp_path / "wpt"
    staging = wpt_dir / run_benchmark.STAGING_DIRNAME
    staging.mkdir(parents=True)
    (staging / "real.txt").write_text("x", encoding="utf-8")
    run_benchmark.unstage_seeds(wpt_dir)
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
    assert "seed recall" in md
    # The model/provider must appear in the report header.
    assert "claude-opus-4-6" in md
    assert "anthropic" in md
    # Structural anchors only (not prose, which is subject to change): the
    # legend link, the aggregate bucket table, and the per-entry finding
    # tables (TP/FP sections + the finding-table column header).
    assert "#reading-a-benchmark-report" in md
    assert "### Consistency buckets" in md
    assert "| bucket | firing rate | count | meaning |" in md
    assert "**True positives**" in md
    assert "**False positives**" in md
    assert "| title | source | firing rate | warnings |" in md


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

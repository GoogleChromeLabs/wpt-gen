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
"""Manifest loading and validation for the benchmark harness.

Kept separate from run_benchmark.py so validation is unit-testable without
touching the wpt checkout or the evaluator. Structural errors (a seed with
no ``expect`` key, an ``expect`` label whose doc path is not in the checkout)
surface here as ManifestError, before any agent runs.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from benchmark.scoring import ExpectLabel, parse_expect


class ManifestError(Exception):
    """A manifest that is structurally invalid or inconsistent."""


@dataclass
class BenchmarkEntry:
    """Common to every entry: an id, a test kind, and a locatable test file."""

    entry_id: str
    kind: str

    def test_rel_path(self) -> str:
        """The test file's path relative to the wpt root."""
        raise NotImplementedError

    def test_file_name(self) -> str:
        """The test file's basename (used to find its ``<name>.json`` output)."""
        return Path(self.test_rel_path()).name


@dataclass
class CorpusEntry(BenchmarkEntry):
    """A real merged wpt file, referenced by path. No gold labels."""

    # Path relative to the wpt root.
    path: str

    def test_rel_path(self) -> str:
        return self.path


@dataclass
class SeedEntry(BenchmarkEntry):
    """A checked-in seed file, staged into the checkout, with gold labels."""

    # Path relative to benchmarks/seeds/.
    seed: str
    # Subdir created inside the checkout to stage the seed into.
    dest: str
    expect: list[ExpectLabel] = field(default_factory=list)

    def test_rel_path(self) -> str:
        # Staged location: <dest>/<seed-basename>.
        return f'{self.dest.rstrip("/")}/{Path(self.seed).name}'


@dataclass
class Manifest:
    """A parsed, validated benchmark manifest."""

    version: int
    rules_version: str | None
    wpt_upstream_commit: str | None
    canary: str | None
    corpus: list[CorpusEntry]
    seeds: list[SeedEntry]
    source_path: Path

    @property
    def entries(self) -> list[BenchmarkEntry]:
        """All entries, corpus first then seeds — for uniform iteration."""
        return [*self.corpus, *self.seeds]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _entry_id(raw: dict[str, Any], list_name: str, index: int) -> str:
    entry_id = raw.get("id")
    _require(
        isinstance(entry_id, str) and bool(entry_id),
        f'{list_name}[{index}]: missing or empty "id"',
    )
    return str(entry_id)


def _kind(raw: dict[str, Any], entry_id: str) -> str:
    kind = str(raw.get("kind", ""))
    _require(bool(kind), f'{entry_id}: missing "kind"')
    return kind


def _parse_corpus(raw: dict[str, Any], index: int) -> CorpusEntry:
    entry_id = _entry_id(raw, "corpus", index)
    kind = _kind(raw, entry_id)
    _require(
        isinstance(raw.get("path"), str) and bool(raw.get("path")),
        f'{entry_id}: corpus entry needs a "path"',
    )
    return CorpusEntry(entry_id=entry_id, kind=kind, path=str(raw["path"]))


def _parse_seed(raw: dict[str, Any], index: int) -> SeedEntry:
    entry_id = _entry_id(raw, "seeds", index)
    kind = _kind(raw, entry_id)
    _require(
        isinstance(raw.get("seed"), str) and bool(raw.get("seed")),
        f'{entry_id}: seed entry needs a "seed" path',
    )
    _require(
        isinstance(raw.get("dest"), str) and bool(raw.get("dest")),
        f'{entry_id}: seed entry needs a "dest" subdir',
    )
    _require(
        "expect" in raw,
        f'{entry_id}: seed entry needs an "expect" list '
        "(empty [] for a known-clean seed)",
    )
    return SeedEntry(
        entry_id=entry_id,
        kind=kind,
        seed=str(raw["seed"]),
        dest=str(raw["dest"]),
        expect=parse_expect(raw.get("expect")),
    )


def _parse_list(raw: Any, list_name: str) -> list[dict[str, Any]]:
    """Validates that a top-level entry list is a list of mappings."""
    if raw is None:
        return []
    _require(isinstance(raw, list), f'"{list_name}" must be a list')
    for i, item in enumerate(raw):
        _require(
            isinstance(item, dict),
            f"{list_name}[{i}] must be a mapping",
        )
    return list(raw)


def load_manifest(path: Path) -> Manifest:
    """Loads and structurally validates a manifest file.

    Raises ManifestError on any structural problem. Does not touch the wpt
    checkout — cross-checking ``expect`` doc paths and seed files against a
    real checkout is validate_against_checkout's job.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML in {path}: {exc}") from exc

    _require(isinstance(raw, dict), "manifest root must be a mapping")

    version = raw.get("version")
    _require(
        isinstance(version, int),
        f'"version" must be an integer, got {version!r}',
    )

    corpus = [
        _parse_corpus(item, i)
        for i, item in enumerate(_parse_list(raw.get("corpus"), "corpus"))
    ]
    seeds = [
        _parse_seed(item, i)
        for i, item in enumerate(_parse_list(raw.get("seeds"), "seeds"))
    ]
    _require(
        bool(corpus) or bool(seeds),
        'manifest has no entries (need a "corpus" and/or "seeds" list)',
    )

    seen: set[str] = set()
    for entry in [*corpus, *seeds]:
        _require(
            entry.entry_id not in seen,
            f"duplicate entry id: {entry.entry_id}",
        )
        seen.add(entry.entry_id)

    return Manifest(
        version=int(version),
        rules_version=(
            str(raw["rules_version"])
            if raw.get("rules_version") is not None
            else None
        ),
        wpt_upstream_commit=(
            str(raw["wpt_upstream_commit"])
            if raw.get("wpt_upstream_commit") is not None
            else None
        ),
        canary=str(raw["canary"]) if raw.get("canary") is not None else None,
        corpus=corpus,
        seeds=seeds,
        source_path=path,
    )


def validate_against_checkout(
    manifest: Manifest,
    wpt_dir: Path,
    seeds_root: Path,
) -> list[str]:
    """Cross-checks the manifest against a real wpt checkout and seed tree.

    Returns a list of human-readable problems (empty = clean):

    - corpus ``path`` resolves to a file inside the checkout;
    - seed file exists under ``seeds_root``;
    - every ``expect`` ``source_doc`` key resolves to a file in the checkout
      (an unknown doc path is a stale label — the plan's Phase 5 calls this
      out as an explicit validation error).

    Doc-path keys are checked; rule-id keys (post-rules-merge) are skipped
    here — validating those is the rules-corpus check that activates later.
    """
    problems: list[str] = []

    for corpus_entry in manifest.corpus:
        if not (wpt_dir / corpus_entry.path).is_file():
            problems.append(
                f"{corpus_entry.entry_id}: corpus path not found in "
                f"checkout: {corpus_entry.path}"
            )

    for seed_entry in manifest.seeds:
        if not (seeds_root / seed_entry.seed).is_file():
            problems.append(
                f"{seed_entry.entry_id}: seed file not found: {seed_entry.seed}"
            )

        for label in seed_entry.expect:
            # A doc-path key looks like "wpt/docs/...": check it exists in the
            # checkout. A rule-id key (no slash / not a doc path) is left for
            # the post-merge rules-corpus validity check.
            if "/" not in label.key:
                continue
            doc_rel = label.key
            # Keys are stored as "wpt/docs/..."; the checkout root already is
            # the wpt dir, so strip a leading "wpt/" component if present.
            if doc_rel.startswith("wpt/"):
                doc_rel = doc_rel[len("wpt/") :]
            if not (wpt_dir / doc_rel).is_file():
                problems.append(
                    f"{seed_entry.entry_id}: expect cites a doc not in "
                    f"checkout: {label.key}"
                )

    return problems

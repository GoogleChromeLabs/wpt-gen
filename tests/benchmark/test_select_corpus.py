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

"""Tests for the consistency-corpus selector.

No wpt checkout needed: the classifier is a pure function of a path (+ an
optional byte sniff), and the sampler/enumerator run against a tiny synthetic
tree built in a tmp dir. The properties that matter — correct kind
classification, mechanical filtering, and *reproducible* sampling — are all
exercised here.
"""

from pathlib import Path

import pytest
import yaml

# scripts/ is on sys.path via tests/conftest.py.
from benchmark import select_corpus
from benchmark.manifest import _parse_corpus

# --- classify ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # testharness: js globals + plain harness markup
        ("fetch/api/basic/response-null-body.any.js", "testharness"),
        ("dom/events/foo.window.js", "testharness"),
        ("workers/foo.worker.js", "testharness"),
        # idl: idlharness by name wins over the .js-global classification
        ("speech-api/idlharness.https.window.js", "idl"),
        ("webnn/idlharness.https.any.js", "idl"),
        ("css/foo/idlharness.html", "idl"),
        # references are never their own test
        ("css/foo/bar-ref.html", None),
        ("css/foo/bar-notref.html", None),
        ("css/foo/bar-ref.xht", None),
        # -expected refs (gentest canvas): marker on the final dot-segment
        ("html/canvas/foo.grid.pattern-expected.html", None),
        ("css/foo/bar-expected.html", None),
        # crash / manual by flag token, robust to compound extensions
        ("css/anchor/long-chain-crash.html", "crashtest"),
        ("accname/manual/name-radio-manual.html", "manual"),
        ("presentation/onclose-manual.https.html", "manual"),
        ("svg/import/use-11-f-manual.svg", "manual"),
        # a bare helper .js is not a standalone test
        ("resources/helper.js", None),
        ("css/support/util.mjs", None),
        # unsupported extension
        ("tools/foo.py", None),
    ],
)
def test_classify_path_only(path: str, expected: str | None) -> None:
    # sniff=None exercises path-only classification (no content split).
    assert select_corpus.classify(path, sniff=None) == expected


def test_classify_markup_needs_sniff_to_split() -> None:
    p = "css/css-grid/grid-001.html"
    # Path alone can't split plain markup: returns None without a sniff.
    assert select_corpus.classify(p, sniff=None) is None
    # Reftest link -> reftest.
    ref = b'<link rel="match" href="grid-001-ref.html">'
    assert select_corpus.classify(p, sniff=ref) == "reftest"
    # mismatch link also counts.
    mismatch = b"<link rel='mismatch' href='x.html'>"
    assert select_corpus.classify(p, sniff=mismatch) == "reftest"
    # testharness import -> testharness.
    th = b'<script src="/resources/testharness.js"></script>'
    assert select_corpus.classify(p, sniff=th) == "testharness"
    # Neither -> visual (a self-describing rendered page).
    assert select_corpus.classify(p, sniff=b"<html><body>hi</body>") == (
        "visual"
    )


def test_classify_manual_beats_content_sniff() -> None:
    # A -manual markup file is manual even if it imports testharness.
    p = "wai-aria/foo-manual.html"
    assert select_corpus.classify(p, sniff=b"testharness.js") == "manual"


def test_compound_extension_stem() -> None:
    assert select_corpus._base_stem("bar-crash.https.html") == "bar-crash"
    assert select_corpus._base_stem("bar.any.js") == "bar"
    assert select_corpus._base_stem("baz.html") == "baz"
    assert select_corpus._base_stem("noext") == "noext"


# --- enumerate_candidates (mechanical filters) ------------------------------


def _write(root: Path, rel: str, content: bytes = b"x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def test_enumerate_filters(tmp_path: Path) -> None:
    root = tmp_path / "wpt"
    th = b'<script src="/resources/testharness.js"></script>' + b" " * 2000
    # In-bounds testharness test.
    _write(root, "css/foo/test-001.html", th)
    # Too small -> filtered.
    _write(root, "css/foo/tiny.html", b"<script src='testharness.js'>")
    # Too big -> filtered.
    _write(root, "css/foo/huge.html", th + b"z" * 40_000)
    # Under an excluded top-level dir -> filtered.
    _write(root, "tools/gen.html", th)
    # Under a `support` segment -> filtered.
    _write(root, "css/foo/support/helper.html", th)
    # A reference -> filtered by classify.
    _write(root, "css/foo/test-001-ref.html", th)
    # In-bounds but not a test file -> filtered by is_wpt_test_file gate.
    _write(root, "css/foo/test-001.html.headers", th)

    cands = select_corpus.enumerate_candidates(
        root, min_bytes=1024, max_bytes=15360
    )
    paths = {c.path for c in cands}
    assert paths == {"css/foo/test-001.html"}
    assert cands[0].kind == "testharness"
    assert cands[0].size >= 1024


# --- sample (reproducibility + stratification) ------------------------------


def _candidates(spec: list[tuple[str, str]]) -> list[select_corpus.Candidate]:
    return [select_corpus.Candidate(path=p, kind=k, size=2048) for p, k in spec]


def test_sample_is_deterministic() -> None:
    cands = _candidates(
        [(f"area{i}/th-{i}.html", "testharness") for i in range(20)]
    )
    a, _ = select_corpus.sample(cands, rng_seed=1)
    b, _ = select_corpus.sample(cands, rng_seed=1)
    c, _ = select_corpus.sample(cands, rng_seed=2)
    assert [x.path for x in a] == [x.path for x in b]
    # A different seed should (with 20 choose 8) pick a different set.
    assert [x.path for x in a] != [x.path for x in c]


def test_sample_respects_quota_and_reports_shortfall() -> None:
    # Two kinds: testharness over-supplied, idl under-supplied.
    cands = _candidates(
        [(f"a{i}/th-{i}.html", "testharness") for i in range(20)]
        + [("x/idlharness.any.js", "idl")]  # only 1, quota is 4
    )
    selected, shortfalls = select_corpus.sample(cands, rng_seed=1)
    by_kind: dict[str, int] = {}
    for c in selected:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    assert by_kind["testharness"] == select_corpus.QUOTAS["testharness"]
    assert by_kind["idl"] == 1
    assert shortfalls["idl"] == select_corpus.QUOTAS["idl"] - 1
    assert "testharness" not in shortfalls


def test_sample_spreads_across_top_dirs() -> None:
    # 8 files, all under css/ except two; with per-top-dir spread the sample
    # must not be all-css when other dirs exist.
    cands = _candidates(
        [(f"css/m{i}/th-{i}.html", "testharness") for i in range(8)]
        + [("dom/th-a.html", "testharness"), ("html/th-b.html", "testharness")]
    )
    selected, _ = select_corpus.sample(cands, rng_seed=1)
    top_dirs = {c.path.split("/", 1)[0] for c in selected}
    # dom and html each contribute at least once before css repeats.
    assert "dom" in top_dirs
    assert "html" in top_dirs


# --- render_yaml (manifest-ready output) ------------------------------------


def test_render_yaml_parses_as_corpus() -> None:
    selected = _candidates(
        [
            ("css/css-grid/grid-align-001.html", "reftest"),
            ("fetch/api/response-null-body.any.js", "testharness"),
        ]
    )
    text = select_corpus.render_yaml(selected)
    raw = yaml.safe_load(text)
    assert "corpus" in raw
    entries = [_parse_corpus(e, i) for i, e in enumerate(raw["corpus"])]
    assert len(entries) == 2
    # ids are unique and prefixed.
    ids = [e.entry_id for e in entries]
    assert all(i.startswith("corpus-") for i in ids)
    assert len(set(ids)) == len(ids)
    # kind + path round-trip.
    assert entries[0].kind == "reftest"
    assert entries[1].path == "fetch/api/response-null-body.any.js"

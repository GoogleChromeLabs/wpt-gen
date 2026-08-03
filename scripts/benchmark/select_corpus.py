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
"""Consistency-corpus selector for the WPT evaluator benchmark.

Emits a stratified random sample of *real* merged wpt files — the consistency
corpus (no gold labels; it measures run-to-run judge variance). This is a
one-time, reproducible procedure: the output is meant to be reviewed by a
maintainer and then pinned verbatim into ``benchmarks/manifest.yaml`` under
``corpus:``.

    python scripts/benchmark/select_corpus.py \\
      [--wpt-dir ../wpt] \\
      [--rng-seed 1] \\
      [--min-bytes 1024] [--max-bytes 15360] \\
      [--out benchmarks/corpus.candidate.yaml]
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

# Puts scripts/ on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wpt_utils import (  # noqa: E402
    EXTENSIONS,
    is_manual_test,
    is_worker_js,
    is_wpt_test_file,
)

# --- Stratification target --------------------------------------------------
# Per-kind quotas (20-40 files total). A kind that
# cannot fill its quota from the checkout yields fewer; that shortfall is
# surfaced in the summary rather than silently back-filled from another kind.
QUOTAS: dict[str, int] = {
    "testharness": 8,
    "reftest": 6,
    "visual": 4,
    "manual": 4,
    "idl": 4,
    "crashtest": 3,
}

# Directories whose contents are tooling/resources/support, never tests.
_EXCLUDED_TOPLEVEL = frozenset(
    {
        "tools",
        "docs",
        "resources",
        "infrastructure",
        "common",
        "conformance-checkers",
        "css/tools",
        "fonts",
        "images",
        "media",
        "support",
    }
)

# Path segments that mark a file as generated/vendored/support rather than an
# authored test. A file whose path contains any of these (as a segment) is
# skipped.
_SUPPORT_SEGMENTS = frozenset(
    {"support", "resources", "reference", "references", "tentative-ref"}
)


@dataclass(frozen=True)
class Candidate:
    """A file that passed the mechanical filters, ready to be sampled."""

    # wpt-root-relative POSIX path — exactly what goes in the manifest.
    path: str
    kind: str
    size: int


# --- Classification ---------------------------------------------------------


def _base_stem(base: str) -> str:
    """The filename with its *entire* extension chain stripped.

    ``bar-crash.https.html`` -> ``bar-crash``. Unlike ``os.path.splitext``
    (which strips only ``.html``), this handles wpt's compound extensions
    (``.https.html``, ``.sub.html``, ``.any.js``) so that flag tokens like
    ``-crash`` / ``-ref`` are found even when secondary flags follow them.
    """
    return base.split(".", 1)[0]


def _pre_ext_stem(base: str) -> str:
    """The filename with only its *final* extension stripped.

    ``foo.pattern-expected.html`` -> ``foo.pattern-expected``. Catches markers
    that sit on the last dot-segment (e.g. gentest ``…-expected.html`` canvas
    references) which ``_base_stem`` (first-dot split) would miss.
    """
    dot = base.rfind(".")
    return base[:dot] if dot != -1 else base


def _has_reftest_link(head: bytes) -> bool:
    """True if the markup declares a reftest relationship near its top.

    Cheap sniff, not a parse: reftests put ``<link rel="match">`` /
    ``rel="mismatch">`` in the head. We lowercase and look for the token pair;
    attribute order/quoting varies, so match on ``rel`` + the value.
    """
    lowered = head.lower()
    if b"rel=" not in lowered:
        return False
    return (
        b'"match"' in lowered
        or b"'match'" in lowered
        or (b'"mismatch"' in lowered or b"'mismatch'" in lowered)
    )


def classify(path: str, sniff: bytes | None = None) -> str | None:
    """Classifies a wpt-root-relative path into a benchmark test kind.

    Returns one of the QUOTAS keys, or ``None`` for files that are not one of
    the sampled kinds (helpers, ``-ref`` references, unsupported types).

    ``sniff`` is the first chunk of the file's bytes, used only to split
    markup into reftest vs. testharness/visual; pass ``None`` to skip the
    content check (path-only classification, for tests).
    """
    base = path.rsplit("/", 1)[-1]
    stem_lower = base.lower()
    ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    stem = _base_stem(base)

    # References/expected files are never sampled as tests in their own right.
    # ``-expected`` sits on the final dot-segment (gentest canvas refs), so it
    # needs the pre-extension stem, not the first-dot ``stem``.
    if stem.endswith("-ref") or stem.endswith("-notref"):
        return None
    if _pre_ext_stem(base).endswith("-expected"):
        return None

    # JS globals (worker/any/window) and plain .js harness tests.
    if is_worker_js(path) or base.endswith((".any.js", ".window.js")):
        # idlharness helpers are conventionally named idlharness{,.*}.
        if "idlharness" in stem_lower or "idl-harness" in stem_lower:
            return "idl"
        return "testharness"
    if ext in EXTENSIONS["js"]:
        return None

    if ext in EXTENSIONS["markup"]:
        if stem.endswith("-crash"):
            return "crashtest"
        if is_manual_test(path):
            return "manual"
        if "idlharness" in stem_lower:
            return "idl"
        if sniff is not None:
            if _has_reftest_link(sniff):
                return "reftest"
            if b"testharness.js" in sniff:
                return "testharness"
            # Markup that imports neither harness nor a ref link: treat as a
            # visual test (self-describing rendered page).
            return "visual"
        # Path-only mode (no sniff): cannot split markup further.
        return None

    return None


# --- Enumeration + filtering ------------------------------------------------


def _is_excluded_dir(rel_parts: tuple[str, ...]) -> bool:
    """True if the file lives under an excluded top-level/support directory."""
    if not rel_parts:
        return True
    top = rel_parts[0]
    two = "/".join(rel_parts[:2])
    if top in _EXCLUDED_TOPLEVEL or two in _EXCLUDED_TOPLEVEL:
        return True
    # A `support`/`resources`/`reference` segment anywhere marks a helper tree.
    return any(seg in _SUPPORT_SEGMENTS for seg in rel_parts[:-1])


_SNIFF_BYTES = 4096


def enumerate_candidates(
    wpt_dir: Path, min_bytes: int, max_bytes: int
) -> list[Candidate]:
    """Walks the checkout and returns sorted, filtered, classified candidates.

    Deterministic: paths are collected then sorted before classification, so
    the result does not depend on directory-iteration order.
    """
    # Collect every file first (sorted) so enumeration is filesystem-order
    # independent.
    all_paths = sorted(p for p in wpt_dir.rglob("*") if p.is_file())

    candidates: list[Candidate] = []
    for p in all_paths:
        if not is_wpt_test_file(p):
            continue
        rel = p.relative_to(wpt_dir)
        rel_parts = rel.parts
        if _is_excluded_dir(rel_parts):
            continue

        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size < min_bytes or size > max_bytes:
            continue

        rel_posix = rel.as_posix()
        # Only read bytes for markup (the only kind whose class needs a sniff).
        ext = p.suffix.lower()
        sniff: bytes | None = None
        if ext in EXTENSIONS["markup"]:
            try:
                sniff = p.read_bytes()[:_SNIFF_BYTES]
            except OSError:
                continue

        kind = classify(rel_posix, sniff)
        if kind is None:
            continue
        candidates.append(Candidate(path=rel_posix, kind=kind, size=size))

    return candidates


# --- Sampling ---------------------------------------------------------------


def _top_dir(path: str) -> str:
    return path.split("/", 1)[0]


def sample(
    candidates: list[Candidate], rng_seed: int
) -> tuple[list[Candidate], dict[str, int]]:
    """Draws the stratified sample. Returns (selected, shortfalls).

    Within each kind, shuffles with a fixed-seed RNG and then greedily picks
    while spreading across top-level directories: a file is skipped on the
    first pass if its top-level dir is already represented for that kind, so
    no single feature area (e.g. ``css/``) dominates a kind. A second pass
    back-fills from the remainder if the diversity pass under-filled.
    """
    by_kind: dict[str, list[Candidate]] = {k: [] for k in QUOTAS}
    for c in candidates:
        # candidates only ever carry a QUOTAS kind, but guard anyway.
        if c.kind in by_kind:
            by_kind[c.kind].append(c)

    rng = random.Random(rng_seed)
    selected: list[Candidate] = []
    shortfalls: dict[str, int] = {}

    for kind, quota in QUOTAS.items():
        pool = sorted(by_kind[kind], key=lambda c: c.path)
        rng.shuffle(pool)

        picked: list[Candidate] = []
        seen_dirs: set[str] = set()
        # Pass 1: at most one per top-level dir, for spread.
        for c in pool:
            if len(picked) >= quota:
                break
            d = _top_dir(c.path)
            if d in seen_dirs:
                continue
            seen_dirs.add(d)
            picked.append(c)
        # Pass 2: back-fill from whatever is left, in shuffled order.
        if len(picked) < quota:
            remaining = [c for c in pool if c not in picked]
            for c in remaining:
                if len(picked) >= quota:
                    break
                picked.append(c)

        if len(picked) < quota:
            shortfalls[kind] = quota - len(picked)
        # Stable, readable output: sort the kind's picks by path.
        selected.extend(sorted(picked, key=lambda c: c.path))

    return selected, shortfalls


# --- Output -----------------------------------------------------------------


def _entry_id(path: str) -> str:
    """A stable, readable corpus id derived from the path.

    ``css/css-grid/foo-001.html`` -> ``corpus-css-grid-foo-001``.
    """
    stem = path.rsplit("/", 1)[-1]
    # Strip compound extensions (.https.any.js, .html, ...).
    stem = stem.split(".", 1)[0]
    parts = [seg for seg in path.split("/")[:-1] if seg]
    slug = "-".join([*parts[-2:], stem]) if parts else stem
    slug = slug.replace("_", "-")
    return f"corpus-{slug}"


def render_yaml(selected: list[Candidate]) -> str:
    """Renders the selection as a manifest-ready ``corpus:`` block.

    Deliberately hand-rolled (not yaml.dump) so field order and comments match
    the existing manifest style and the block can be pasted verbatim.
    """
    lines = [
        "corpus:",
    ]
    for c in selected:
        lines.append(f"  - id: {_entry_id(c.path)}")
        lines.append(f"    path: {c.path}")
        lines.append(f"    kind: {c.kind}")
        lines.append(f"    # {c.size} bytes")
    return "\n".join(lines) + "\n"


def _summary(selected: list[Candidate], shortfalls: dict[str, int]) -> str:
    counts: dict[str, int] = dict.fromkeys(QUOTAS, 0)
    for c in selected:
        counts[c.kind] += 1
    rows = [
        f"  {kind:<12} {counts[kind]:>2} / {QUOTAS[kind]:<2}"
        + (f"   ⚠ short by {shortfalls[kind]}" if kind in shortfalls else "")
        for kind in QUOTAS
    ]
    total = len(selected)
    return f"Selected {total} files:\n" + "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select a stratified consistency corpus from a wpt "
        "checkout.",
    )
    parser.add_argument(
        "--wpt-dir",
        type=Path,
        default=Path("../wpt"),
        help="Path to the pinned wpt checkout (default: ../wpt).",
    )
    parser.add_argument(
        "--rng-seed",
        type=int,
        default=1,
        help="Seed for the sample's random number generator, fixed so the "
        "selection is reproducible. Named --rng-seed (not --seed) to avoid "
        "confusion with the manifest's seeded-defect files.",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=1024,
        help="Minimum file size, inclusive (default: 1024).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=15360,
        help="Maximum file size, inclusive (default: 15360 = 15 KiB).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the corpus YAML here (default: stdout).",
    )
    args = parser.parse_args(argv)

    wpt_dir = args.wpt_dir.resolve()
    if not wpt_dir.is_dir():
        print(f"error: --wpt-dir not found: {wpt_dir}", file=sys.stderr)
        return 2
    if args.min_bytes > args.max_bytes:
        print("error: --min-bytes exceeds --max-bytes", file=sys.stderr)
        return 2

    print("selecting tests...", file=sys.stderr, flush=True)
    candidates = enumerate_candidates(wpt_dir, args.min_bytes, args.max_bytes)
    selected, shortfalls = sample(candidates, args.rng_seed)

    yaml_text = render_yaml(selected)
    if args.out is not None:
        args.out.write_text(yaml_text, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(yaml_text)

    print(
        f"\n{len(candidates)} candidates after filtering.\n"
        + _summary(selected, shortfalls),
        file=sys.stderr,
    )
    if shortfalls:
        print(
            "\nnote: some kinds under-filled; widen --max-bytes or relax "
            "filters, or accept a smaller corpus.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

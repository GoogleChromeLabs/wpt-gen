# Upstream provenance

The rules in `references/rules.yaml` are currently derived from the `docs/`
tree of the upstream `web-platform-tests/wpt` repository. Rules from
wpt-gen's own style guides may be added in a later pass; provenance is
tracked per rule via the `source` field.

## Source path convention

The `source` field on each rule is a repo-root-relative path whose first
segment names the originating repository:

- `wpt/...` — paths into upstream `web-platform-tests/wpt` (e.g.,
  `wpt/docs/writing-tests/general-guidelines.md#L82-L87`).
- `wpt-gen/...` — paths into this repository (e.g.,
  `wpt-gen/wptgen/skills/wpt-generator/references/testharness_style_guide.md#L124`).

A `#L<start>-L<end>` line anchor is appended where the source location is
stable.

## Pinned upstream commit

- Repository: https://github.com/web-platform-tests/wpt
- Commit: `fbe57e07f26f4e9b45bdf7647b4cbf1e1a4563dd`
- Date: 2026-07-02

## Upstream source documents

Rules currently draw from:

- `wpt/docs/writing-tests/general-guidelines.md`
- `wpt/docs/writing-tests/testharness.md`
- `wpt/docs/writing-tests/file-names.md`
- `wpt/docs/writing-tests/reftests.md`
- `wpt/docs/writing-tests/print-reftests.md`
- `wpt/docs/writing-tests/idlharness.md`
- `wpt/docs/writing-tests/manual.md`
- `wpt/docs/writing-tests/crashtest.md`
- `wpt/docs/writing-tests/visual.md`
- `wpt/docs/writing-tests/wdspec.md`
- `wpt/docs/writing-tests/testdriver.md`
- `wpt/docs/writing-tests/assumptions.md`
- `wpt/docs/writing-tests/rendering.md`
- `wpt/docs/writing-tests/server-features.md`
- `wpt/docs/writing-tests/css-metadata.md`
- `wpt/docs/reviewing-tests/checklist.md`

## Deterministic rules and the linter extension

Each rule carries a `layer` field: `deterministic` (mechanically checkable
from a file's bytes, structure, or path) or `semantic` (requires rendering
or judgment). The deterministic rules split further by whether upstream
`wpt lint` already enforces them — those it covers are skipped by the
evaluator; those it does not are the "gap set" implemented in
`wptgen/lint_ext.py`, each check named with its `rules.yaml` id.

The full mapping (covered / gap / reclassified-to-semantic) is documented
in [`references/linter-gap-analysis.md`](references/linter-gap-analysis.md).
It was determined against upstream's rule inventory at
`wpt/tools/lint/rules.py` and `lint.py` as of the pinned commit above. Both
the corpus and the upstream linter can change independently, so the mapping
is not permanent — it must be re-checked on every refresh.

## Refresh procedure

When upgrading to a newer upstream commit:

1. `git -C ../wpt pull`
2. Re-read each source document listed above; check for added, removed, or
   reworded normative statements.
3. Update `references/rules.yaml`: add new rules, deprecate removed ones, and
   reword existing ones whose source language has changed. Bump the `source`
   line numbers if they have shifted. Set each rule's `layer` correctly
   (`deterministic` only if decidable from bytes/structure/path — not if it
   needs rendering or judgment).
4. **Re-run the linter gap analysis.** Compare the current
   `layer: deterministic` rules against upstream's rule inventory
   (`wpt/tools/lint/rules.py` and `lint.py`). If upstream added a check that
   now covers a gap rule, remove the corresponding check from
   `wptgen/lint_ext.py` (and its test) to avoid double-flagging. If a newly
   added or newly-`deterministic` corpus rule is NOT covered upstream, add it
   to the gap set for implementation in `lint_ext.py`.
5. Update the tables in
   [`references/linter-gap-analysis.md`](references/linter-gap-analysis.md)
   if the mapping changed.
6. Update the pinned commit hash and date in this file.

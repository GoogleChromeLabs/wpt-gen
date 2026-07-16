# Evaluator benchmark corpus

The data the evaluator benchmark runs against. The harness that consumes it
is `scripts/benchmark/run_benchmark.py` (not yet implemented); the design
lives in [`docs/benchmarking-implementation-plan.md`](../docs/benchmarking-implementation-plan.md).

## Layout

```
benchmarks/
  manifest.yaml   # the benchmark definition — the harness's only entry point
  seeds/          # seeded-defect + known-clean files, checked in
    testharness/  # one deliberate violation per file
    reftest/
    clean/        # well-formed files; any finding is a false positive
  golden/
    candidates/   # harvested PR snapshots (Phase 6); holdout-window
                  # annotations live in a private location, not here
```

## Datasets

| dataset | ground truth | measures |
| --- | --- | --- |
| consistency corpus (`role: corpus`) | none | run-to-run variance per finding key |
| seeded-defect set (`role: seed`, non-empty `expect`) | exact (injected) | precision / recall |
| known-clean (`role: seed`, empty `expect`) | exact (no findings) | precision |

Corpus entries are real merged wpt files referenced by path inside the
checkout. Seeds live here and are copied into `<wpt_dir>/wpt-gen-bench/` by
the harness, because `run_evaluation` requires the test under evaluation to
live inside the wpt checkout.

## Manifest schema

- `canary` — training-data canary GUID (BIG-bench convention), also embedded
  in every seed file. Lets responsible training pipelines filter this
  benchmark out.
- `version` — manifest schema version.
- `rules_version` — `null` until `rules.yaml` merges; then set to that
  corpus's version so the harness can error on a mismatch. This is the
  staleness tripwire for `expect` labels.
- `wpt_upstream_commit` — the checkout corpus entries are pinned to. Corpus
  files must be byte-identical across runs or consistency numbers are not
  comparable. The harness warns (not fails) on mismatch and records the
  actual commit in run metadata.
- `entries[]`:
  - `id` — stable identifier; the harness uses it for run output dirs.
  - `kind` — test kind (`testharness`, `reftest`, …); supports `--filter`.
  - `role` — `corpus` (consistency only) or `seed` (labeled).
  - `path` — corpus entries: path relative to the wpt root.
  - `seed` — seed entries: path relative to `benchmarks/seeds/`.
  - `dest` — seed entries: subdir created inside the checkout.
  - `expect[]` — gold labels: finding keys that MUST fire.
    - `source_doc` — the finding key today (see below); a path *into the
      wpt docs*.
    - `rule_id` — `null` until the rules work lands.
    - `test_file_lines` — acceptable line window **in the seed test file**
      (not in the source doc), inclusive. This is where the finding should
      anchor; a prediction whose `test_line` falls outside the window does
      not match this label.
  - `forbid[]` — finding keys that must NOT fire (regression pins for known
    false positives).

## Finding keys: doc paths now, rule ids later

The harness keys metrics on a **finding key**: the finding's `rule_id` when
it has one, otherwise its `source` citation with the `#L…` line anchor
stripped (anchors vary run-to-run; the doc path is stable).

Today the evaluator emits no rule ids — the `source` citation *is* the
identifier — so `expect` entries are keyed on `source_doc`. When the
rules-distillation work merges, `rules.yaml`'s `source` field maps each rule
id back to its doc path + line anchor, so these labels can be translated to
`rule_id`s **by a script, with no re-annotation**. That is why every
`expect` entry carries both fields.

The cost of doc keys in the meantime: they are coarser than rule ids (one
doc holds many rules), so two findings citing the same doc collapse into one
key unless their line windows separate them. Choose seed violations whose
governing docs are distinct enough that the key is unambiguous.

## Seed authoring rules

- **Exactly one deliberate violation per seed** (plus the clean set).
  Multi-violation files make recall attribution murky.
- **Defect-neutral naming, always.** Name the file for its *subject* — what
  the test ostensibly tests, in normal WPT style — never for its defect:
  `response-json-basic.html`, not `missing-testharnessreport.html`. The
  manifest is the only place the label appears. (Contamination policy: a
  model could otherwise memorize which violation each seed carries.)
- **Pick violations the linter does not already catch, and verify it.** The
  skill instructs the evaluator to skip anything `wpt lint` enforces, so a
  lint-covered defect tests nothing — the agent is *correct* to stay silent,
  and the seed would score as a false recall failure. Every seed must be
  lint-clean; check before adding it:

  ```
  cp -R benchmarks/seeds/* <wpt_dir>/wpt-gen-bench/
  cd <wpt_dir> && ./wpt lint ./wpt-gen-bench/<path>   # must report no errors
  ```

- Embed the canary GUID in a comment. In `.js` seeds it must come *after*
  any `// META:` lines and the `importScripts(...)` call — a comment before
  the `// META:` block trips the linter's `STRAY-METADATA` rule.
- Re-review seeds whenever `rules.yaml` bumps its version.

## Current status: proof of concept

The seeds here are a deliberately small proof of concept — enough to wire up
and test the harness, not the full stratified set. Two reasons to keep it
small for now:

1. Seed authoring is the expensive, judgment-heavy part of this work, and it
   gets substantially cheaper once `rules.yaml` lands: each rule already
   names its violation and its source anchor, so seeds (and their `expect`
   labels) can be **generated from the rules corpus** and then translated
   back to doc keys for the pre-merge baseline.
2. The stratified corpus (20–40 files across every kind) is selected by a
   scripted, fixed-seed procedure and pinned after maintainer review — see
   the implementation plan's Phase 2.

So the current entries exercise the schema end to end (a violation seed with
a doc-keyed label, a reference-quality seed, a clean file, and two real
corpus files) without pre-committing to hand-authored labels that the rules
work will supersede.

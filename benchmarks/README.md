# Benchmarking the WPT Evaluator

Measures how well the WPT Docs Eval agent finds seeded defects and how
consistently it fires on a WPT checkout across repeats.

## Running

```
python scripts/benchmark/run_benchmark.py --repeats 3 [--filter role=seed]
```

With no other flags the harness defaults `--manifest` to
`benchmarks/manifest.yaml`, `--wpt-dir` to the `wpt_path` in `wpt-gen.yml`,
and `--out` to a timestamped `bench-runs/<date>-<time>/`. All are
overridable; other flags are `--provider`, `--config`, `--filter` (e.g.
`role=seed`, `role=corpus`, `kind=reftest`), and `--score-only`.


The harness validates the manifest against the checkout, stages seeds into
`<wpt-dir>/wpt-gen-bench/`, runs
`wpt-gen evaluate` `--repeats` times per entry into
`<out>/runs/<entry-id>/rep-<i>/`, then scores every entry and writes
`<out>/report.md` + `<out>/report.json`. `--score-only` re-scores existing
run dirs without invoking the agent (pass the same `--out`). Scoring itself lives in
`scripts/benchmark/scoring.py` and is covered by
`tests/benchmark/test_run_benchmark.py`, which runs entirely on synthetic run
dirs (no agent calls).

## Reading a benchmark report

Each run writes `report.md` (this section is what it links to) and an
identical-content `report.json`. Precision and Recall metrics are computed only over `seed`
entries.

**Precision** — of the findings the evaluator emitted, the fraction that
were expected. Target **1.0** (no false positives). 

**Recall** — of the
seeded defects, the fraction the evaluator caught. Target **1.0** (nothing
missed).

Abbreviations in the seed scores:

- **TP** — true positive: an expected finding fired.
- **FP** — false positive: an unexpected finding fired (including any
  finding on a known-clean seed).
- **FN** — false negative: an expected finding was missed.

**Advisory notes** — findings whose `source` cites an upstream doc that is
*not* on the evaluator's curated reading list (parsed from the evaluator
SKILL.md), which suggests an invented citation. This is *advisory only*, not
a pass/fail gate: the report counts them and annotates each finding's row,
but they do not count against any score. This check is meaningful while the
evaluator reads the raw curated docs; a future rules-based strategy would
replace it with a rule-id validity check.

The **Aggregate** table rolls the seed scores up across all seeds:

| metric | value | target |
| --- | --- | --- |
| seed precision | 0.83 | 1.0 |
| seed recall | 1.0 | 1.0 |
| seed TP / FP / FN | 5 / 1 / 0 | FP=0, FN=0 |

 `corpus` entries are measured for
consistency only.

**Consistency** — how often each finding fires across the repeats. There is
no single target: a finding *should* sit at an extreme (**always** or
**never**); the **mid** band is the flaky zone to drive out. The report
buckets every finding's firing rate:

| bucket | firing rate | meaning |
| --- | --- | --- |
| always | 1.0 | fires every repeat - trustworthy |
| high | ≥0.75 | usually fires |
| mid | 0.25–0.75 | flaky zone |
| low | >0 | rarely fires |
| never | 0.0 | never fires |

Each entry then lists its own findings as a table. **Seed** entries split
their findings into **True positives** (matched a gold label) and **False
positives** (did not); **corpus** entries, which have no labels, show one
**Findings** table. The `firing rate` column is `firings/repeats (rate)`,
and `warnings` counts that finding's advisory notes (e.g. `⚠ source ×2`).
A per-entry example:

```
### `seed-worker-missing-done` (seed/testharness)

- Seed: precision 0.5, recall 1.0 (TP 1, FP 1, FN 0)

**True positives**

| title | source | firing rate | warnings |
| --- | --- | --- | --- |
| Missing `done()` call | `wpt/docs/writing-tests/testharness.md` @ L15-16 | 3/3 (1.0) | ⚠ source ×3 |

**False positives**

| title | source | firing rate | warnings |
| --- | --- | --- | --- |
| Test not in spec directory | `wpt/docs/reviewing-tests/checklist.md` @ L1-1 | 1/3 (0.333) |  |
```

Here the intended defect (`testharness.md`) is a true positive that fired
every repeat, while a noisy `checklist.md` finding is a false positive that
also fired only once — flaky *and* spurious.

## Layout

```
benchmarks/
  manifest.yaml   # the benchmark definition — the harness's only entry point
  seeds/          # seeded-defect + known-clean files, checked in
    testharness/  # one deliberate violation per file
    reftest/
    clean/        # well-formed files; any finding is a false positive
  golden/
    candidates/   # harvested PR snapshots (Not Yet Implemented)); holdout-window
                  # annotations live in a private location, not here
```

## Datasets

| dataset | ground truth | measures |
| --- | --- | --- |
| consistency corpus (`corpus:` entries) | none | run-to-run variance per finding key |
| seeded-defect set (`seeds:` with non-empty `expect`) | exact (injected) | precision / recall |
| known-clean (`seeds:` with empty `expect`) | exact (no findings) | precision |

Corpus entries are real merged wpt files referenced by path inside the
checkout. 

Seeds live here and are copied into `<wpt_dir>/wpt-gen-bench/` by
the harness, because `run_evaluation` requires the test under evaluation to
live inside the wpt checkout. The harness stages them **flattened** — the
category subdir (`testharness/`, `reftest/`, `clean/`) is dropped so it does
not leak the defect class into the checkout the evaluator can list; a reftest
seed's sibling `references/` dir is carried along so its `<link rel=match>`
still resolves.

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

Entries live in two top-level lists — `corpus:` and `seeds:` — so each entry
has a single, total shape (no `role` tag, no fields that apply to only half
the cases). Both share `id` and `kind`:

- `id` — stable identifier; the harness uses it for run output dirs. Must be
  unique across both lists.
- `kind` — test kind (`testharness`, `reftest`, …); supports `--filter`.

- `corpus[]` — real merged wpt files, measured for consistency only:
  - `path` — path relative to the wpt root.

- `seeds[]` — checked-in seed files with gold labels:
  - `seed` — path relative to `benchmarks/seeds/`.
  - `expect[]` — gold labels: finding keys that MUST fire (empty `[]` for a
    known-clean seed).
    - `source_doc` — the finding key today (see below); a path *into the
      wpt docs*. May carry a trailing `:L…` doc-line anchor, which is
      **documentation only** — the harness strips it before matching (it
      keys on the bare doc path). Recording the passage a seed targets lets
      you eyeball raw `source` citations across a multi-repeat run for
      citation jitter without a dedicated metric.
    - `rule_id` — `null` until the rules work lands.
    - `test_file_lines` — acceptable line window **in the seed test file**
      (not in the source doc), inclusive. This is where the finding should
      anchor; a prediction whose `test_line` falls outside the window does
      not match this label.

### Future idea: a `forbid` list for known false positives

Not implemented. A per-seed `forbid` list
could file and categorize *repeated, known* false positives seen in the wild
(distinct from novel ones), so a regression that re-introduces a catalogued
FP is flagged on its own rather than folded into the aggregate. Worth adding
when the benchmark runs continuously and an FP backlog accumulates.

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
  lint-clean; check before adding it (the harness stages seeds flattened, so
  copy the bare file, not its category dir):

  ```
  cp benchmarks/seeds/<category>/<file> <wpt_dir>/wpt-gen-bench/<file>
  cd <wpt_dir> && ./wpt lint ./wpt-gen-bench/<file>   # must report no errors
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
2. The "consistency corpus" (20–40 files across every kind) should be selected by a
   scripted, fixed-seed procedure and pinned after maintainer review.

The current entries exercise the schema end to end (a violation seed with
a doc-keyed label, a reference-quality seed, a clean file, and two real
corpus files).

The benchmark runs the WPT Docs Eval agent only; the --spec conformance check is 
out of scope until spec requirements XML can be pinned per test.

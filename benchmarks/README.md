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
overridable. Other flags:

- `--provider`, `--config` — passed through to each `wpt-gen evaluate`.
- `--filter field=value` — `role=` (`seed`/`corpus`/`golden`) or `kind=`.
- `--jobs N` — concurrent evaluator runs (default 1; the bound is provider
  rate limits, not cores).
- `--smoke` — the regression tier: run only the manifest's `smoke` sets
  (see [Tiers](#tiers)). Composes with `--filter`.
- `--golden-set NAME` / `--golden-prs 43400,…` — select golden entries.
- `--min-precision` / `--min-recall` / `--min-golden-recall` / `--max-fn` /
  `--min-stability` — CI quality gates (see [Quality gates](#quality-gates)).
- `--score-only` — re-score existing run dirs in `--out` without the agent.

The harness stages seeds/golden into `<wpt-dir>/wpt-gen-bench/`, runs
`wpt-gen evaluate` `--repeats` times per entry into
`<out>/runs/<entry-id>/rep-<i>/`, then scores and writes `<out>/report.md`
+ `<out>/report.json`.

Scoring lives in `scripts/benchmark/scoring.py`, covered by
`tests/benchmark/` on synthetic run dirs (no agent calls).

### Tiers

Two suggestions for how to run, differing only in selection and repeats:

- **Release** — full manifest, 8 repeats (`run_benchmark.py`). Establishes
  the consistency band; run before a corpus/skill release or after a model
  change.
- **Regression** — `--smoke --repeats 3`. Runs the manifest's `smoke`
  corpus/seed/golden sets only; a fast guard for skill/evaluator changes.

Tiers are selection, not schema: the manifest defines which entries are in
`smoke` (see [Manifest schema](#manifest-schema)); `--repeats` and any
quality gate stay on the command line.

### Quality gates

For CI. A gate lets a build **fail on a quality regression** — e.g. a skill
change that drops seed recall — so the drop blocks the change instead of
landing silently. The report is always written *first*, so a failing build
can still post its full table onto the PR.

The `--min-*`/`--max-fn` flags gate the **exit code**: any breach exits
non-zero. Omitting a flag leaves that check off, so by default a run always
exits 0. `--max-fn` sums seed and golden false negatives.

`--min-stability` gates the corpus **stability score** (see
[Consistency](#consistency)). It takes either a fixed floor (e.g.
`--min-stability 0.7`) or `auto`. **Prefer `auto`** — it gates on the run's
own repeat-aware target (`warn_at`), so the bar matches the ✅/⚠️/❌ status the
summary already shows and tightens automatically with more repeats (≈0.61 at 3
reps, ≈0.72 at 8).

## Reading a benchmark report

Each run writes `report.md` (this section is what it links to) and an
identical-content `report.json`. It opens with a **scope** line (entry counts
per type and repeats),
then a per-dataset **summary**, then a **per-entry** breakdown. Which numbers
an entry contributes to the report depends on its type — seed precision/recall over `seed`
entries, golden recall over `golden` entries, and `corpus` entries feed
consistency only.

### The summary table

One row per dataset present in the run — its headline number and status:

| dataset | what it measures | score / value | target | status |
| --- | --- | --- | --- | --- |
| seed | injected-defect detection & false alarms | 0.83 precision / 1.0 recall | 1.0 recall | ✅ Pass |
| golden | agreement with human review | 0.75 recall | Informational | ℹ️ Tracked |
| corpus | run-to-run detection stability | 0.94 stability · 3 label-churn (advisory) | ≥0.72 (@8 reps) | ✅ Stable |

**Precision** — of the findings the evaluator emitted, the fraction that were
expected. Target **1.0** (no false positives).

**Recall** — of the expected findings, the fraction the evaluator caught.
Target **1.0** (nothing missed).

**Stability** — corpus is unlabeled, so it is scored on *detection*
consistency, not correctness: a 0.0–1.0 score (1.0 = every finding fires
deterministically across repeats) — see [Consistency](#consistency). Label
churn (a location detected every repeat but labeled with competing rules) is a
rule-taxonomy issue, **reported but not scored**. A one-line caveat under the
table surfaces the other counted-but-not-scored signals (golden unmatched
predictions, advisory notes).

The seed scores abbreviate as:

- **TP** — true positive: an expected finding fired.
- **FP** — false positive: an unexpected finding fired (including any
  finding on a known-clean seed).
- **FN** — false negative: an expected finding was missed.

**The two recall 1.0s are not the same kind of target.** Seed recall is 1.0
against a defect *you injected* — an exact, fixed answer key. Golden recall is
1.0 against a *human-derived, hand-annotated* denominator: which PRs are in the
set and how each comment is annotated are both judgment calls, still iterating.
So golden recall is a target on a moving denominator — a miss may mean the
evaluator regressed *or* that a label needs re-annotation — where seed recall
is more of a hard invariant. Golden also has no precision number yet: unmatched
predictions are counted but not charged, since one may be a valid finding the
reviewer missed rather than a false positive.

### Per-entry findings

Each entry then lists the findings it produced as a table:
`title | source | firing rate | warnings`. The `firing rate` column is
`firings/repeats (rate)`, and `warnings` counts that finding's advisory notes
(e.g. `⚠ source ×2`, see [Advisory notes](#advisory-notes)). What differs by
entry type is how those findings are scored.

A **corpus** entry has no labels, so it shows a single **Findings** table —
every finding read for its firing rate, none scored:

```
### `corpus-url-data-uri-fragment` (corpus/testharness)

**Findings**

| title | source | firing rate | warnings |
| --- | --- | --- | --- |
| Missing metadata comment | `GENERAL-004` @ L1-1 | 3/3 (1.0) |  |
| Ambiguous assertion message | `TESTHARNESS-006` @ L22-22 | 2/3 (0.667) |  |
```

The `GENERAL-004` finding is stable (**always**); the flaky `TESTHARNESS-006`
one (2/3) sits in the **mid** band (see [Consistency](#consistency)).

A **seed** entry splits its findings into **True positives** (matched a gold
label) and **False positives** (did not):

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

The intended defect (`testharness.md`) is a true positive that fired every
repeat; the noisy `checklist.md` finding is a false positive that fired only
once — flaky *and* spurious.

A **golden** entry reports recall against its annotated labels. It splits its
findings into **True positives** (matched an annotated label) and **Unmatched**
(did not) — the same shape as a seed, but the unmatched bucket is *not* charged
against a score (a golden unmatched finding may be a real issue the reviewer
missed, not a false positive):

```
### `golden-43400-afe0767a` (golden/testharness)

- Golden: recall 0.5 (TP 1, FN 1, unmatched 1)

**True positives**

| title | source | firing rate | warnings |
| --- | --- | --- | --- |
| X25519 derivation length | `CHECKLIST-005` @ L32-32 | 3/3 (1.0) |  |

**Unmatched**

| title | source | firing rate | warnings |
| --- | --- | --- | --- |
| Redundant length assertion | `CHECKLIST-002` @ L18-18 | 2/3 (0.667) |  |
```

This PR carried two annotated `CHECKLIST-005` labels (L32 and L4). The
evaluator caught the L32 one every repeat (the true positive) and never the L4
one (recall 0.5). A never-fired label has no row — it appears only in the
`FN 1` of the recall line. The `CHECKLIST-002` finding matched no annotated
label, so it lands under **Unmatched** — the `unmatched 1`, counted but not
charged.

### Consistency

Every finding carries a **firing rate** — how often it fired across the
repeats. A finding *should* sit at an extreme (**always** or **never**); the
**mid** band is the flaky zone. The histogram buckets each finding's rate, keyed
on **line** (a location the agent flagged) rather than rule id, so a line that
draws two competing rules is one stable detection, not two flaky ones:

| bucket | firing rate | meaning |
| --- | --- | --- |
| always | 1.0 | fires every repeat - trustworthy |
| high | ≥0.75 | usually fires |
| mid | 0.25–0.75 | flaky zone |
| low | >0 | rarely fires |
| never | 0.0 | never fires |

**Two kinds of instability.** The report separates them, because they have
different causes and fixes (both surface in the Action Items):

- **Detection instability** — a *line* the agent flagged inconsistently
  (mid-band detection rate). Genuine agent flakiness. This is what the corpus
  **stability score** measures — `1 − mean flakiness` over detected lines,
  from **0.0 (maximally flaky)** to **1.0 (perfectly stable, the target)**.
  Each line is weighted by *how* flaky its **detection** was — how often *any*
  finding landed there across repeats (rule id aside). Detected half the time
  is maximally flaky; 1-of-4 counts as half. This is a continuous weight, not
  just a yes/no mid-band check.

  That makes the score repeat-aware: a 3-repeat smoke run literally can't
  produce as flaky a rate as an 8-repeat release run, so the pass/warn/fail
  bands widen when repeats are low — you can't confidently fail flakiness on
  few samples. The summary shows the effective threshold for the run:

  | run | repeats | ✅ pass ≥ |
  | --- | --- | --- |
  | smoke | 3 | 0.61 |
  | release | 8 | 0.72 |
- **Label churn** — a line detected *every* repeat but labeled with competing
  rule ids (e.g. `CHECKLIST-004` one run, `GENERAL-007` the next). This is a
  rule-taxonomy overlap the benchmark introduces, not agent flakiness, so it is
  **reported (with the competing rules listed) but not scored** against
  stability.

`corpus` entries are scored on stability *only* — a corpus file is a known-real
merged test, so it carries no gold labels (precision/recall need labels). Seed
and golden entries also carry a stability signal, but their headline metric is
precision/recall.

### Advisory notes

Findings whose `source` cites an upstream doc *not* on the evaluator's curated
reading list (parsed from the evaluator SKILL.md), suggesting an invented or
off-list source. This guards the `source` field (which doc the finding cites);
the separate `citation` field — the verbatim snippet and its line — is verified
deterministically at evaluation time, so a fabricated line number never reaches
the report.

Advisory notes are *advisory only*, not a pass/fail gate: the report counts
them and annotates each finding's row (the `⚠` in the `warnings` column), but
they do not count against any score. Most meaningful while the evaluator reads
the raw curated docs; a `rules.yaml` strategy would replace it with a rule-id
validity check.

## Directory Layout

```
benchmarks/
  manifest.yaml   # the benchmark definition — the harness's only entry point
  seeds/          # seeded-defect + known-clean files, checked in
    testharness/  # one deliberate violation per file
    reftest/
    clean/        # well-formed files; any finding is a false positive
  golden/
    candidates/   # harvested merged-PR snapshots (public)
    annotated/    # human-review answer keys (dev-window set; see golden/README.md)
```

The golden set (real merged PRs scored for recall vs. human review) has its
own workflow — harvest, annotate, score — documented in
[`golden/README.md`](golden/README.md), including the dev-window vs. holdout
split for annotations.

## Datasets

| dataset | ground truth | measures |
| --- | --- | --- |
| consistency corpus (`corpus:` entries) | none | run-to-run detection stability (0.0–1.0) |
| seeded-defect set (`seeds:` with non-empty `expect`) | exact (injected) | precision / recall |
| known-clean (`seeds:` with empty `expect`) | exact (no findings) | precision |
| golden set (`golden/`) | human PR review | recall vs. review (see `golden/README.md`) |

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
- `rules_version` — the `rules.yaml` corpus version the `expect` labels were
  authored against (currently `0.2.0`). The staleness tripwire for the
  labels: re-review the seeds when `rules.yaml` bumps its version. (An
  automatic harness cross-check against `rules.yaml`'s own version is not yet
  implemented.)
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
    known-clean seed). Fields:
    - `source_doc` — a path *into the wpt docs* naming the passage this seed
      targets. The finding key when `rule_id` is null; once `rule_id` is set,
      it becomes documentation only. May carry a trailing `:L…` doc-line
      anchor, which is **always** documentation only — the harness strips it
      before matching. Recording the passage lets you eyeball raw `source`
      citations across a multi-repeat run for citation jitter.
    - `rule_id` — the finding key, from `rules.yaml` (e.g. `TESTHARNESS-005`).
      When set, it is what predictions are matched against; `validate` errors
      if it is not a real id in `rules.yaml`.
    - `test_file_lines` — acceptable line window **in the seed test file**
      (not in the source doc), inclusive. This is where the finding should
      anchor; a prediction whose `test_line` falls outside the window does
      not match this label.

## Finding keys: rule ids

The harness keys metrics on a **finding key**: the finding's `rule_id` when
it has one, otherwise its `source` citation with the `#L…` line anchor
stripped (anchors vary run-to-run; the doc path is stable).

The rules corpus has landed, so `expect` entries key on `rule_id` (e.g.
`TESTHARNESS-005`) — precise, one key per rule rather than one per doc. Each
label also carries `source_doc` (the passage the rule was distilled from), so
labels remain translatable in either direction and stay eyeball-checkable
against the raw `source` citations a run emits.

A doc-path key (`rule_id: null`) is still supported for any label not yet
tied to a rule; it is coarser (one doc holds many rules), so two findings
citing the same doc collapse into one key unless their line windows separate
them.

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

## Current status

The consistency corpus is a stratified, maintainer-reviewed set (across every
kind), suggested by `scripts/benchmark/select_corpus.py` and pinned via
`wpt_upstream_commit`. The golden dev set is in place (see `golden/README.md`).

Seeds remain a deliberately small proof of concept — enough to exercise the
schema, not the full set. Seed authoring is the expensive, judgment-heavy
part; it gets cheaper now that `rules.yaml` has landed, since each rule names
its violation and source anchor, so seeds and their `expect` labels can be
generated from the rules corpus.

The benchmark runs the WPT Docs Eval agent only; the --spec conformance check is 
out of scope until spec requirements XML can be pinned per test.

### Future idea: a `forbid` list for known false positives

Not implemented. A per-seed `forbid` list
could file and categorize *repeated, known* false positives seen in the wild
(distinct from novel ones), so a regression that re-introduces a catalogued
FP is flagged on its own rather than folded into the aggregate. Worth adding
when the benchmark runs continuously and an FP backlog accumulates.

### Future idea: rate-limit backoff for `--jobs`

Not implemented, and a prerequisite for trusting `--jobs > 1`. Each run is an
LLM agent call, so the concurrency bound is the provider's rate limit — and the harness has no 429 retry. A throttled run currently records a
nonzero exit but still scores as an **empty result** (no findings, counted in
the denominator), so heavy parallelism can silently corrupt the numbers rather
than failing loudly. Needs bounded exponential backoff per task plus a way to
distinguish a throttled run from a genuinely empty one. Until then, raise
`--jobs` cautiously and watch for `FAILED` lines / unexpectedly empty entries.

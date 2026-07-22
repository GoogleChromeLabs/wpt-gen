---
name: wpt-evaluator
description: Evaluate the quality of a WPT test file against guidance derived from the upstream WPT documentation. Use when reviewing a generated or submitted test before merge.
---

# WPT Evaluator

This skill evaluates a single WPT test file against upstream
`web-platform-tests/wpt` guidance. It is an **advisory signal** for human
reviewers, not a merge gate.

## Strategy

This skill runs in one of two strategies. The strategy you are running is
stated in the task prompt as `strategy: distilled` or `strategy: raw`.
Follow the correspondingly-labelled subsection wherever this skill
branches (in **Corpus** and in the **Procedure**). Everything else in this
skill is shared and applies to both strategies.

- **`distilled`** — judge the test against a distilled rules corpus
  (`references/rules.yaml`), reporting a stable `rule_id` per finding.
- **`raw`** — read a curated reading list of upstream docs live and flag
  violations directly, citing the source doc + line range per finding.

## When to use

- Reviewing a test file, before opening a pull request.
- Reviewing a submitted pull request to surface deterministic and semantic
  issues a human reviewer might otherwise have to catch by hand.

Do **not** use this skill as a substitute for running `wpt lint`, running the
test, or human review. It complements those steps; it does not replace them.

## Inputs

- The path to a single WPT test file.

## Outputs

For each issue, a finding with these fields:

- `severity`: `error`, `warn`, `info`, or `nit`.
- `test_line`: a line reference into the test file under evaluation.
- `evidence`: a short verbatim quote from the test file.
- `source`: provenance for the finding (see the strategy-specific note
  below).
- `summary`: a one-sentence paraphrase of what the guidance requires.

Strategy-specific fields:

- **`distilled`**: also include `rule_id` (the `rules.yaml` rule violated,
  e.g. `CHECKLIST-017`). `severity` is taken from the rule. `source` is the
  rule's `source` provenance, copied through from the rule.
- **`raw`**: `source` is the upstream doc path + line range that prompted
  the finding (e.g., `wpt/docs/writing-tests/general-guidelines.md:L82-L87`).
  Infer `severity` from upstream language — "MUST"/"required" → `error`;
  "should"/"recommended" → `warn`; "may"/"preferred" → `info`; "nit"
  prefixed in the source → `nit`.

### Prohibited outputs

The following are **hard prohibitions**, not preferences:

1. **No composite score.** Do not aggregate findings into a single
   number, grade, or pass/fail verdict. Report each finding on its
   own.
2. **No proposed fixes.** Findings describe **what** is wrong and
   **why**, never **how to fix it**. The following all count as
   proposed fixes and must not appear in a report:
   - "Should use X instead." / "The test should..."
   - "Suggested title:" / "Suggested replacement:" / "Suggested
     rewrite:"
   - "Could be improved by..." / "Consider..."
   - Concrete code rewrites or before/after snippets.
   - A code block that is not present in the test file as written.
   Evidence quotes (verbatim from the test) are not fixes and are
   allowed.
3. **No invented identifiers.** For `distilled`, every finding's
   `rule_id` must be an existing ID from `references/rules.yaml`, and if
   a problem is covered by no rule, do not report it. For `raw`, the
   source citation (upstream doc path + line range) is the identifier —
   do not invent rule IDs.

If you find yourself writing "should be X" or attaching a code
suggestion, stop. State the problem and cite the source; the human
reviewer decides the remediation.

## Procedure

1. **Detect test kind** from the file path and contents. Possible
   kinds: `testharness`, `reftest`, `print-reftest`, `crashtest`,
   `manual`, `visual`, `idl`, `wdspec`, `css`. A test can carry more
   than one kind (e.g., `testharness` + `css`).
2. **Gather guidance for that kind**, per your strategy:
   - **`distilled`**: load applicable rules from
     `references/rules.yaml`, filtering to rules whose `applies_to`
     includes the detected kind(s) and any matching format tags
     (`html`, `js`, `css`, `worker`, `any`, etc.). See **Corpus:
     distilled** below.
   - **`raw`**: load the curated reading list for that kind and read
     each listed doc in full, identifying normative statements (MUST,
     SHOULD, MAY, required, must not, etc., plus reviewer-checklist
     items). See **Corpus: raw** below.
3. **(`distilled` only) Run the linters first.** Call `run_wpt_lint`
   and `run_lint_ext` on the test file. Together these own the
   `layer: deterministic` rules: `run_wpt_lint` covers the checks
   upstream WPT enforces, and `run_lint_ext` covers the deterministic
   rules from `rules.yaml` that upstream does not (each `run_lint_ext`
   finding already carries the `rule_id`). Any finding they report is
   authoritative; carry it through to your submission as-is. The exact
   division — which rule id each linter owns, and which
   deterministic-looking rules are left to you because they have no
   clean mechanical check — is documented in
   [`references/linter-gap-analysis.md`](references/linter-gap-analysis.md).
   (For `raw`, still skip anything `wpt lint` already enforces — no
   tabs, no trailing whitespace, no `setTimeout`,
   `assert_throws`/`promise_rejects` deprecation, filename duplicate /
   case-collision rules — to avoid double-flagging.)
4. **Evaluate the test.**
   - **`distilled`**: evaluate against the `layer: semantic` rules
     only. Do **not** re-judge deterministic rules by hand — they are
     the linters' job (running the linters and independently reasoning
     about the same rule risks contradictory or duplicate findings). If
     you believe a deterministic rule is violated but neither linter
     flagged it, trust the linters and move on.
   - **`raw`**: evaluate the test against each normative statement you
     identified.
5. **Consult the source only to disambiguate** (`distilled`): the rule
   `rule` text is self-contained; read the upstream doc at the rule's
   `source` anchor only when a rule's applicability is genuinely
   ambiguous. This should be the exception, not the norm.
6. **Follow declared dependencies as needed** (see below) when reading
   them would inform a specific finding.
7. **Submit findings** by calling `report_evaluation_complete` with
   `findings` and `input_scope` payloads. For `distilled`, combine your
   semantic findings with the linter findings from step 3. Each finding
   object must populate the fields described in the Outputs section
   above. Before submitting, verify no finding violates the prohibited
   outputs: no composite score, no proposed fix, no invented
   identifier. The wpt-gen CLI renders the final Markdown report and
   writes it to disk; do NOT format or write the report yourself.

## Dependency reading (as-needed)

The test file may declare dependencies on other local files. List every
declared dependency you detect, but only **read** a dependency when
doing so is necessary to evaluate a specific finding. The goal is to
keep the corpus small unless the contents of a dependency actually
matter for a finding.

### What counts as a declared dependency

Detect these forms in the test file's source:

- `<script src="...">` — JS includes.
- `<link rel="match" href="...">` and `<link rel="mismatch" href="...">`
  — reftest reference files.
- `<link rel="stylesheet" href="...">` — CSS includes.
- `<link rel="help" href="...">` — spec URL (external; do not read).
- `<img src="...">`, `<iframe src="...">`, `<source src="...">`,
  `<video src="...">`, `<audio src="...">` — embedded resources.
- `// META: script=...` — JS dependency (testharness JS-only tests).
- `importScripts("...")` — worker script imports.
- `fetch("...")` and similar runtime fetches to local paths.

For each dependency, note the path it points to. Classify it as:

- **Framework** if it begins with `/resources/`, `/common/`, `/fonts/`,
  or `/media/`. These are WPT-provided and should be **listed but not
  read**.
- **External** if it's an absolute URL (`http(s)://`) or starts with
  `//`. **List only**; do not fetch.
- **Local** otherwise. May be **read on demand** per the criteria
  below.

### When to read a local dependency

Read a local dependency only if at least one of these applies:

- **Reftest reference verification**: the test is a reftest and the
  guidance about the reference's content (e.g., the reference "should
  not use the technology under test" / "should use a different
  technique that won't fail in the same way") cannot be evaluated
  without comparing the two files. Read the reference file.
- **Reference existence**: a `<link rel="match">` or `<link
  rel="mismatch">` points at a path. Verify the file exists
  (directory listing is sufficient; reading is not required unless
  the previous bullet applies).
- **META script existence**: a `// META: script=...` points at a
  local path (not under `/resources/` or `/common/`). Verify the
  file exists.
- **Specific guidance requires it**: a rule or normative statement can
  only be evaluated by inspecting the dependency's contents. State
  which one, and why the dependency's contents are needed, when
  emitting the finding.

Do **not** read a local dependency:

- To explore the broader test ecosystem.
- To look for similar tests or patterns.
- To check for duplicates (lint already covers basename and
  case-collision duplication).
- Because it "might be relevant" without specific guidance that
  requires it.

All dependencies you read must appear in the input scope you report
(see below), with their byte sizes, alongside the test file and the
corpus you used.

## Corpus: distilled

Applies when `strategy: distilled`. All rules live in
[`references/rules.yaml`](references/rules.yaml). Each rule carries:

- `id`: stable identifier, prefixed with the category code (e.g.,
  `CHECKLIST-017`, `CHECKLIST-012`). This is what you report as a finding's
  `rule_id`.
- `source`: provenance — a repo-root-relative path whose first segment
  identifies the originating repository (`wpt/...` for upstream
  `web-platform-tests/wpt`, `wpt-gen/...` for this repository), with a
  `#L<start>-L<end>` line anchor where the location is stable. Copy this
  through to a finding's `source`. See [`UPSTREAM.md`](UPSTREAM.md) for
  the convention.
- `category`: the topic of the rule. Categories describe *what kind of issue*
  the rule covers, never *what kind of test* it applies to. See the list
  below.
- `applies_to`: which test kinds the rule is relevant to (e.g.,
  `testharness`, `reftest`, `manual`, `idl`, `visual`, `js`, `html`, `css`,
  `any`, `worker`). Used for filtering the corpus when loading into context.
- `severity`: `error`, `warn`, `info`, or `nit`.
- `layer`: `deterministic` (mechanically checkable — owned by the
  linters, `run_wpt_lint` and `run_lint_ext`; do not re-judge these by
  hand) or `semantic` (requires the judge — these are yours to evaluate).
- `rule`: the normative statement. This is the self-contained text you
  evaluate the test against.

### Categories

| Code     | Category       | Covers                                                       |
| -------- | -------------- | ------------------------------------------------------------ |
| `FMT`    | `file-format`  | File format, encoding, boilerplate and harness inclusion.    |
| `NAME`   | `filename`     | Filename, path length, suffix flags and their ordering.      |
| `META`   | `metadata`     | `<meta>` elements and `// META:` comment directives.         |
| `ASSERT` | `assertions`   | Choice and specificity of test assertions.                   |
| `ASYNC`  | `async-timing` | Timing, timeouts, event-based waits, animation frames.       |
| `INDEP`  | `independence` | Test isolation, cleanup, and consistency across runs.        |
| `STRUCT` | `structure`    | Structural shape of a test (e.g., reftest links, refs, instructions). |
| `API`    | `api-usage`    | Correct use of WPT harness APIs (`idlharness`, `setup()`, etc.). |
| `PORT`   | `portability`  | Cross-platform and self-containment requirements.            |
| `FOCUS`  | `focus`        | Test scope, conservatism, and self-description.              |
| `REV`    | `review`       | General reviewer checklist items not covered above.          |

The full corpus is small enough to load once. Upstream provenance for the
rule set is documented in [`UPSTREAM.md`](UPSTREAM.md).

## Corpus: raw

Applies when `strategy: raw`. Read the curated reading list for the test
kind — the "all kinds" baseline plus any kind-specific docs — in full,
and flag violations directly against the upstream language.

### All kinds (baseline — always read)

- `wpt/docs/writing-tests/general-guidelines.md`
- `wpt/docs/writing-tests/file-names.md`
- `wpt/docs/writing-tests/assumptions.md`
- `wpt/docs/writing-tests/server-features.md`
- `wpt/docs/reviewing-tests/checklist.md` (read the **All tests**
  section; the kind-specific sections are loaded below)

### testharness

- `wpt/docs/writing-tests/testharness.md`
- `wpt/docs/reviewing-tests/checklist.md` (**Script Tests Only** section)
- For testdriver-driven tests: `wpt/docs/writing-tests/testdriver.md`

### reftest / print-reftest

- `wpt/docs/writing-tests/reftests.md`
- `wpt/docs/writing-tests/rendering.md`
- `wpt/docs/reviewing-tests/checklist.md` (**Reftests Only** section)
- If the file is a print reftest: `wpt/docs/writing-tests/print-reftests.md`

### crashtest

- `wpt/docs/writing-tests/crashtest.md`

### manual

- `wpt/docs/writing-tests/manual.md`

### visual

- `wpt/docs/writing-tests/visual.md`
- `wpt/docs/writing-tests/rendering.md`
- `wpt/docs/reviewing-tests/checklist.md` (**Visual Tests Only** section)

### idl

- `wpt/docs/writing-tests/idlharness.md`
- `wpt/docs/writing-tests/testharness.md` (idlharness builds on testharness)

### wdspec

- `wpt/docs/writing-tests/wdspec.md`

### css (additive — read on top of whatever else applies)

- `wpt/docs/writing-tests/css-metadata.md`

## Reporting input scope

While running the evaluation, record every file you opened in service
of the evaluation, along with its byte size (`wc -c <path>`). Include
the test file itself. Do NOT count files only used for navigation
(directory listings, this skill itself, etc.).

For each tracked file, classify its `role` as one of:

- `skill` — this SKILL.md.
- `rules` — `references/rules.yaml` (`distilled`).
- `reading-list` — a doc from the curated reading lists (`raw`).
- `test` — the test file under evaluation.
- `dependency` — a file referenced by the test and read on demand per
  "Dependency reading (as-needed)" above.

Separately, list any declared dependencies that you detected but did
NOT open (framework + external dependencies — `/resources/*`,
`/common/*`, absolute URLs).

You submit this data as part of the `input_scope` payload to the
`report_evaluation_complete` tool: `files` (a list of
`{path, bytes, role}` rows), `dependencies_not_read`, and `strategy`
(set to the strategy you are running — `"distilled"` or `"raw"`). The
wpt-gen CLI uses this to report input scope and token usage for the
pass; it does **not** appear in the findings report. Do NOT compute
totals or token figures yourself — just report what you opened.

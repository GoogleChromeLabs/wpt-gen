---
name: wpt-evaluator-conformance
description: Evaluate a WPT test file against extracted normative requirements from its governing spec. Use when a spec URL is available and conformance to the spec needs to be judged. Pairs with the wpt-evaluator skill, which checks against WPT documentation guidance rather than spec conformance.
---

# WPT Evaluator — Spec Conformance

This skill evaluates a single WPT test file against a list of normative
requirements that have already been extracted from the test's governing
specification. It is an **advisory signal** for human reviewers, not a
merge gate.

The requirements list is provided to you as XML in the prompt. Each
`<requirement>` carries an `id` (e.g. `R3`), a category, and the
normative statement itself. Your job is to read the test file and judge
whether the test's assertions align with each requirement.

## When to use

- A spec URL was provided for the test under evaluation, and a
  requirements XML has already been extracted from it.
- Use alongside the `wpt-evaluator` skill (the docs/style pass), not in
  place of it.

Do **not** use this skill as a substitute for human review, running the
test, or running `wpt lint`.

## Inputs

- The path to a single WPT test file.
- A `<requirements_list>` XML block in the prompt, containing one or
  more `<requirement id="...">` elements.

## Outputs

For each finding:

- **Severity**:
  - `error` — the test contains an assertion that **contradicts** a
    normative requirement (the test asserts behavior the spec
    explicitly forbids, or asserts the opposite of what the spec
    requires).
  - `warn` — the test contains an assertion about behavior that is
    **not normatively specified** in the provided requirements. There
    may be legitimate reasons for such tests, but the absence of a
    matching requirement is worth surfacing.
  - `info` and `nit` are not used by this skill.
- **Line reference** into the test file under evaluation.
- **Short evidence quote** from the test file (the assertion in
  question).
- **Source citation**: the requirement ID (e.g. `R3`) that the finding
  relates to, formatted as `requirements.xml#R3`. For `warn` findings
  where no requirement matches, use `requirements.xml#none-matched`.
- **One-sentence summary** of the contradiction or gap.

### Prohibited outputs

The same hard prohibitions apply as in the `wpt-evaluator` skill:

1. **No composite score.** Do not aggregate findings into a single
   number, grade, or pass/fail verdict.
2. **No proposed fixes.** Findings describe what is wrong and why,
   never how to fix it. No "should use X instead", no suggested
   rewrites, no concrete code blocks that are not already in the
   test file.
3. **No invented requirement IDs.** Cite only IDs that appear in the
   provided `<requirements_list>`, or use `requirements.xml#none-matched`
   for `warn` findings.

If you find yourself writing "should be X" or attaching a code
suggestion, stop. State the problem and cite the requirement; the
human reviewer decides the remediation.

## Procedure

1. **Read the test file** at the provided path.
2. **Identify the test's assertions.** For a testharness test these
   are typically `assert_*` calls inside `test()` / `promise_test()`
   blocks. For a reftest, the assertion is the visual comparison
   between test and reference. For an idl test, the assertions are
   produced by `IdlArray.test()`. Note the line numbers.
3. **For each assertion**, judge whether it aligns with the
   `<requirements_list>`:
   - **Contradicts a requirement** → emit an `error` finding, citing
     the requirement ID.
   - **Matches a requirement** → no finding (this is the expected
     case).
   - **Does not correspond to any requirement** in the list → emit a
     `warn` finding, citing `requirements.xml#none-matched`.
4. **For each requirement in the list** that is not exercised by any
   assertion, do **not** emit a finding. Coverage gaps are out of
   scope for this skill — we are judging the test as-written, not
   what is missing.
5. **Submit findings** by calling `report_conformance_complete` with
   `findings` and `input_scope` payloads. Each finding must populate
   the fields described in the Outputs section above. Before
   submitting, verify no finding violates the prohibited outputs.

## Tracking input scope

Record every file you opened in service of the evaluation, along with
its byte size (`wc -c <path>`). Include the test file itself. Do NOT
count files only used for navigation.

For each tracked file, classify it as one of:

- `skill` — this SKILL.md.
- `test` — the test file under evaluation.
- `requirements` — the requirements XML (passed in the prompt, not
  read from disk; report its byte size as the byte length of the
  XML string).
- `dependency` — a file referenced by the test and read on demand.

You submit this data as part of the `input_scope` payload to the
`report_conformance_complete` tool. The wpt-gen CLI renders the final
Input scope table; do NOT format any of this yourself.

---
name: golden-pr-annotation
description: Turn a harvested golden-PR candidate (a candidates/<pr>.json record of CHANGES_REQUESTED review comments on WPT test files) into a gold answer key, mapping each comment to a rules.yaml rule id or no-rule. Use when annotating a candidate produced by scripts/benchmark/harvest_wpt_prs.py.
---

# Golden-PR annotation

Map the human review comments in one harvested candidate to the evaluator's
rule vocabulary, producing the gold answer key the benchmark scores against.
The candidate is machine input; **your YAML output is verified by a human
before it becomes an answer key.** Annotate faithfully and mark uncertainty
as `no-rule` rather than guessing — a wrong `rule_id` silently poisons the
key.

Harvesting is automated
([`scripts/benchmark/harvest_wpt_prs.py`](../../scripts/benchmark/harvest_wpt_prs.py));
this annotation step is the judgment the harvester cannot do.

## Inputs

- One candidate file: `candidates/<pr>.json`. The harvester already filtered
  to substantive feedback — only `CHANGES_REQUESTED` comments left by a
  reviewer (not the PR author) on a test file survive. There is no chatter to
  discard.
- The rule vocabulary:
  [`rules.yaml`](../../wptgen/skills/wpt-evaluator/references/rules.yaml).
  Only its **`layer: semantic`** rules are annotation targets — the
  `deterministic` rules are enforced by linters, not judged from review
  comments.

### Candidate schema

```json
{
  "pr": 61309,
  "pr_url": "https://github.com/web-platform-tests/wpt/pull/61309",
  "merged_at": "2026-07-...",
  "reviewed_commits": [
    {
      "commit_id": "<sha>",
      "test_files": [{"path": "...", "content_b64": "<file @ commit_id>"}],
      "comments": [
        {
          "author": "...", "path": "...", "line": 26,
          "review_state": "CHANGES_REQUESTED",
          "fixed_before_merge": true,
          "html_url": "https://.../pull/61309#discussion_r...",
          "body": "..."
        }
      ]
    }
  ],
  "final_diff_paths": ["..."]
}
```

Each `reviewed_commits` block is one scoring unit: the `test_files` are the
bytes **at `commit_id`** (base64-decode to read them), and each comment's
`line` is relative to that revision. Decode the relevant file to judge whether
a comment's point maps to a rule — you cannot tell whether "use a more
specific assert" applies without seeing the code.

## Output

One file: `annotated/<pr>.yaml`, one `labels` entry per comment in the
candidate (annotate **every** comment, so the key is provably complete).

```yaml
pr: 61309
labels:
  - html_url: https://github.com/web-platform-tests/wpt/pull/61309#discussion_r3591041714
    commit_id: <sha>                       # REQUIRED, copied from the comment
    excerpt: "promise_test callbacks run asynchronously... will hang"
    rule_id: CHECKLIST-016                  # a rules.yaml semantic id, or no-rule
    source_doc: wpt/docs/reviewing-tests/checklist.md   # the rule's source
    path: fetch/compression-dictionary/dictionary-fetch-with-link-connect-src.tentative.https.html
    lines: [26, 26]
  - html_url: https://github.com/web-platform-tests/wpt/pull/61309#discussion_r3591117333
    commit_id: <sha>
    excerpt: "use a reporting observer instead which gives buffered events"
    rule_id: no-rule                        # reviewer point maps to no rule
    path: fetch/compression-dictionary/dictionary-fetch-with-link-connect-src.tentative.https.html
    lines: [20, 20]
```

### Output fields

- **`html_url`** — copy from the comment; anchors the label.
- **`commit_id`** — **required**; copy exactly from the comment. It pins the
  label to the revision its `line` refers to — the bytes the harness fetches
  and scores. A label without it cannot be scored.
- **`excerpt`** — a short quote (or paraphrase, `...`-elided) of the comment
  body, so a reviewer can judge the label without opening the candidate JSON.
  For human readability only; not used by scoring.
- **`rule_id`** — a `rules.yaml` **semantic** id (e.g. `CHECKLIST-016`), or
  the literal `no-rule`. A real id must exist in `rules.yaml`.
- **`source_doc`** — the matched rule's `source` doc path. Omit for
  `no-rule`.
- **`path` / `lines`** — from the comment; `[start, end]` inclusive. Widen
  beyond the single `line` only when the point genuinely spans lines.

## Procedure

For each comment in each `reviewed_commits` block:

1. **Read the point.** Base64-decode the block's `test_files` entry for the
   comment's `path` and read around its `line` so the comment is concrete, not
   just its prose.
2. **Match against the semantic rules.** Find the `rules.yaml` semantic rule
   whose `rule` text the comment's guidance expresses. Match the *rule*, not
   the wording: "wrap this in a promise test" and "this should be a
   `promise_test`" are the same rule.
3. **Emit a label.** If a rule fits, use its `id` + `source`. If none fits,
   use `rule_id: no-rule`.
4. **Split** a comment raising distinct findings at distinct lines into
   multiple labels.

### Decision criteria

- **Prefer `no-rule` under uncertainty.** A wrong `rule_id` poisons the answer
  key; `no-rule` is harmless. Under-claiming is the safe error.
- **`no-rule` for points outside the evaluator's remit** — spec
  disagreements, cross-PR logistics ("add a follow-up test"), housekeeping
  ("accidental duplicate link?"), and pure code-style suggestions with no
  governing rule ("use a reporting observer").
- **`no-rule` for novel harness types.** Comments specific to test kinds the
  rules were not distilled for (e.g. `core-aam` accessibility-API assertions)
  usually map to nothing; do not force a general rule onto them.
- **`fixed_before_merge: false` still counts.** A valid finding the author
  declined or deferred is still a finding. The flag informs scoring weight,
  not inclusion.

## Human verification

The generated `annotated/<pr>.yaml` is a *proposal*. A maintainer reviews it —
spot-checking `rule_id` matches and `no-rule` calls against the comments —
before it is accepted as an answer key. Make the reasoning inspectable: keep
`source_doc` on every mapped label, and (optionally) a trailing `# why`
comment on non-obvious matches.

## Contamination: where annotations live

The **holdout window's** annotations must stay **out of this public repo** —
they are the answer key and exist nowhere else (unlike the candidates, which
mirror already-public GitHub data). Keep them in the maintainer-private
location. An annotation set is published here only once its window rotates
into the dev set, where contamination is harmless by design. See
[`README.md`](README.md) for the full policy.

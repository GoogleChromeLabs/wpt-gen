# Golden PR set

Harvested snapshots of recently merged wpt PRs that received substantive
human review — the dataset that measures whether the evaluator matches or
exceeds a human reviewer.

```
golden/
  candidates/     # <pr>.json snapshots, one per PR, written by
                  # scripts/benchmark/harvest_wpt_prs.py
  annotated/      # <pr>.yaml answer keys; see ANNOTATION.md
  watermark.json  # last merged_at processed
```

Harvesting is automated; annotation maps each candidate's review comments to
rule ids — see [`ANNOTATION.md`](ANNOTATION.md) (an LLM skill; a human
verifies its output). Run `harvest_wpt_prs.py --dry-run` to preview candidates
without writing.

## Contamination policy

The snapshots themselves carry near-zero *marginal* exposure: the PRs,
diffs, and review comments are already public on GitHub and get crawled
whether or not we mirror them here. Secrecy is not the defense — the rolling
window and the pre/post-training-cutoff time split are.

**Annotations are different.** They are the answer key, and they are new
information that exists nowhere else. The holdout window's annotations must
stay **out of this public repo** (maintainer-private repo or bucket). A
window's annotations get published here only once it rotates into the dev
set, where contamination is harmless by design.

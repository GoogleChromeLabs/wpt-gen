# Golden PR set

Harvested snapshots of recently merged wpt PRs that received substantive
human review — the dataset that measures whether the evaluator matches or
exceeds a human reviewer. Not yet populated; see Phases 6–7 of
[`docs/benchmarking-implementation-plan.md`](../../docs/benchmarking-implementation-plan.md).

```
golden/
  candidates/     # <YYYY-MM>.jsonl snapshots, written by
                  # scripts/benchmark/harvest_wpt_prs.py (weekly cron)
  watermark.json  # last merged_at processed
```

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

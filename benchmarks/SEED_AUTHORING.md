# Authoring benchmark seeds

Start every seed as a **real test you would submit to WPT**, then introduce
the single defect with the smallest possible edit. If planting the defect
forces you to write code you would never ship, that rule will most likely be a poor seed
candidate — note it and move on.

## The authoring loop (do this per seed, before committing)

1. Write a genuinely good test of some neutral subject (real assertions,
   honest name, correct flags, all recommended directives).
2. Introduce the single target defect with the minimal edit.
3. **Lint both layers**: `wpt lint` and `wptgen.lint_ext.check_file`. The
   defect must not be lint-covered (or the evaluator correctly stays silent).
4. **Run the evaluator against the staged seed** and read every finding.
5. Triage each non-target finding:
   - The evaluator finds valid additional defects → fix the seed, go to step 3.
   - The edited seed consistently violates overlapping or additional rules → the seed may be unviable for the targeted rule; record why.
6. Only when the evaluator returns *just* the target finding (across a
   couple of runs) is the seed done. Then set its `test_file_lines` window
   and `rule_id` in the manifest.

Recompute `test_file_lines` after *any* edit — removing a comment or line
shifts the window, and a stale window scores real hits as misses.

## Contamination hygiene 

- Use **Defect-neutral names**, always — name the file for its subject, never
  its defect. Rename when a rewrite changes the subject.
- **Canary comment** in every seed (after the `// META:` block in JS files).
- **No comments describing the defect** — they hint the answer to the
  evaluator and are un-WPT-like. Strip all descriptive prose.

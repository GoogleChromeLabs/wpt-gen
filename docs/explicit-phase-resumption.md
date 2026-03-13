# Explicit Workflow Phase Resumption and State Checkpointing

WPT-Gen's test generation pipeline is composed of several major phases (Context Assembly, Requirements Extraction, Coverage Audit, Test Generation, Evaluation, and Test Execution). By default, running the `generate` command starts this workflow from the beginning. 

However, there are many scenarios where you might want to skip earlier, time-consuming phases and start directly from a specific point. For example:
- You want to retry generating tests without re-running the expensive requirements extraction and coverage audit LLM calls.
- You have manually written or modified a directory of WPT `.html` tests and want to run them through the WPT-Gen Test Execution (self-correction) loop.
- A workflow was interrupted, and you want to resume exactly where it left off.

To support this, WPT-Gen automatically checkpoints its state after every major phase and provides CLI flags to explicitly resume the workflow.

## Automatic State Checkpointing

As WPT-Gen completes each major phase, it automatically serializes the structured output to your system's cache directory (or a custom directory if provided). The key artifacts saved include:

1. **`requirements.json`**: Saved after Phase 2 (Requirements Extraction). Contains the extracted technical requirements from the specification.
2. **`blueprints.json`**: Saved after Phase 3 (Coverage Audit). Contains the gap analysis and proposed test blueprints.
3. **`generated_tests.json`**: Saved after Phase 4 (Test Generation). Contains the raw generated test code and file paths.

These artifacts act as the "memory" of the workflow, allowing `wpt-gen` to seamlessly pick up where it left off.

## CLI Usage

You can explicitly resume a workflow using the `--resume-from` and `--state-dir` flags on the `generate` or `audit` commands.

### `--resume-from <phase>`

This flag tells WPT-Gen to skip all phases prior to the specified phase and begin execution there. Valid phases are:
- `context_assembly` (Phase 1)
- `requirements_extraction` (Phase 2)
- `coverage_audit` (Phase 3)
- `generation` (Phase 4)
- `evaluation` (Phase 5)
- `execution` (Phase 6)

### `--state-dir` (or `--tests-dir`)

This optional flag allows you to explicitly specify the directory where WPT-Gen should look for the checkpointed artifacts. If omitted, WPT-Gen will look in its default internal cache directory.

## Common Workflows & Examples

### Example 1: Resuming from the Audit Phase
If you've already extracted requirements but want to re-run the Coverage Audit (perhaps with a different LLM or temperature), you can point `wpt-gen` to the directory containing your `requirements.json`:

```bash
wpt-gen generate popover \
  --resume-from coverage_audit \
  --state-dir ./my-saved-state/
```

WPT-Gen will load the requirements, skip Phase 1 and 2, and immediately begin Phase 3 (Coverage Audit).

### Example 2: Running the Execution Loop on Existing Tests
You can use the execution phase's self-correction loop on tests that you wrote manually or modified locally. 

If you point `--state-dir` (using its alias `--tests-dir` for clarity) to a folder containing `.html` files, WPT-Gen will automatically "hydrate" its internal state with those files and begin the `./wpt run` execution loop:

```bash
wpt-gen generate popover \
  --resume-from execution \
  --tests-dir ./my-manual-tests/
```

WPT-Gen will skip all generation steps, load the `.html` files from `./my-manual-tests/`, and immediately start running them against the local browser, attempting to automatically fix any test failures it encounters.

### Example 3: Implicit Resumption
If a workflow fails unexpectedly (e.g., due to a network error or API timeout), you can simply use the `--resume` flag without specifying a phase. WPT-Gen will look at its default cache, figure out which phases completed successfully, and automatically resume from the next logical step.

```bash
wpt-gen generate popover --resume
```

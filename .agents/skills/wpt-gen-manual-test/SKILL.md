---
name: wpt-gen-manual-test
description: Instructions to manually test the generate workflow of WPT-Gen to verify system integrity.
---

# WPT-Gen Manual Test

This skill provides step-by-step instructions to manually test the `generate` workflow of WPT-Gen. This acts as a robust smoke test to catch regressions and verify the system's integrity during development.

## Test Case

We will use a small, stable web feature for this test: `abortable-fetch`.

## Execution Steps

1. **Run the Generate Workflow**:
   Execute the following CLI command to trigger the `generate` workflow for `abortable-fetch`:
   ```bash
   wpt-gen generate abortable-fetch
   ```

2. **Wait for Generation**:
   Allow the workflow to complete. It should read blueprints and generate tests autonomously.

## Verification Steps

1. **Locate Generated Output**:
   Check the `out/` or `generated/` directory for the output tests related to `abortable-fetch`. You can also check the local WPT directory if it outputs there.

2. **Inspect Generated Files**:
   - Check that the required boilerplate (like `testharness.js` and `testharnessreport.js` inclusions) is present.
   - Verify correct syntax and structure for a Web Platform Test.
   - Check for expected test assertions (e.g., using `AbortController` and `fetch`).

3. **Check for Regressions**:
   - The test generation must not crash or hang.
   - A valid test file must be created.
   - If any of these fail, report a regression.

## Cleanup Steps

After successfully verifying the generated tests, you must clean up the workspace to ensure no residual files interfere with future tests or get accidentally committed to the WPT repository.

1. **Delete Generated Test Files**:
   Read the `~/.cache/wpt-gen/generated_tests.json` file. Parse the `path` for each generated test and delete those specific files from the file system to safely remove untracked generated files without affecting the user's other work.
   
2. **Revert Tracked Changes in WPT**:
   Navigate to the configured WPT repository and safely revert only the files that were modified during the generation step (such as `WEB_FEATURES.yml`) by running:
   ```bash
   WPT_DIR="${WPT_DIR:-../wpt}"
   git -C "$WPT_DIR" restore WEB_FEATURES.yml
   ```

3. **Clear State Artifacts**:
   Remove the JSON artifact to fully reset the test state:
   ```bash
   rm -f ~/.cache/wpt-gen/generated_tests.json
   ```

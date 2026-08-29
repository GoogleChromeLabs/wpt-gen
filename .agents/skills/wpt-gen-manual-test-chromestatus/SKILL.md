---
name: wpt-gen-manual-test-chromestatus
description: Instructions to manually test the chromestatus workflow of WPT-Gen to verify ChromeStatus integration.
---

# WPT-Gen Manual Test for ChromeStatus

This skill provides step-by-step instructions to manually test the `chromestatus` workflow of WPT-Gen. This acts as a smoke test to verify metadata fetching from ChromeStatus API and the subsequent audit/generation phases.

## Test Case

We will use a stable ChromeStatus feature ID for this test: `5159559872249856` (CSS Anchor Positioning).

## Preparation Steps

1. **Configure Valid Models**:
   The default models in `wpt-gen.yml` (e.g., `gemini-3.1-pro-preview`) may not be available in your API version. Temporarily update `wpt-gen.yml` to use stable models:
   ```bash
   # Update gemini models to stable versions
   sed -i 's/gemini-3.1-pro-preview/gemini-1.5-pro/g' wpt-gen.yml
   sed -i 's/gemini-3-flash-preview/gemini-1.5-flash/g' wpt-gen.yml
   ```

## Execution Steps

1. **Run the ChromeStatus Workflow**:
   Execute the following CLI command to trigger the `chromestatus` workflow:
   ```bash
   wpt-gen chromestatus 5159559872249856
   ```

2. **Wait for Metadata Fetching**:
   The tool will fetch feature metadata from `chromestatus.com`. Ensure this step completes successfully.

3. **Respond to Coverage Audit Worksheet**:
   To save tokens during the manual test:
   - Say `y` only to the **first** and **last** uncovered tests in the worksheet.
   - Say `n` for all other tests.
   - If only one test is uncovered, say `y` for that one.

## Verification Steps

1. **Confirm Successful Completion**:
   The audit and generation phases should complete without errors.

2. **Inspect Generated Output**:
   Check the `out/` or `generated/` directory for the generated tests.
   - Verify that the test content is consistent with the feature (CSS Anchor Positioning).
   - Check for proper `testharness.js` inclusions and valid HTML/JS structure.

3. **Check for Errors**:
   The process must not crash or hang during metadata fetching, auditing, or generation.

## Cleanup Steps

After verification, clean up any generated artifacts and revert configuration changes to keep the workspace clean.

1. **Revert Configuration Changes**:
   Restore the original model names in `wpt-gen.yml`:
   ```bash
   # Revert gemini models to preview versions
   sed -i 's/gemini-1.5-pro/gemini-3.1-pro-preview/g' wpt-gen.yml
   sed -i 's/gemini-1.5-flash/gemini-3-flash-preview/g' wpt-gen.yml
   ```

2. **Delete Generated Artifacts**:
   Remove any files generated in the `out/` or `generated/` directories:
   ```bash
   rm -rf out/* generated/*
   ```

3. **Remove Cached State**:
   Clear the cached workflow state to reset the test environment:
   ```bash
   rm -f ~/.cache/wpt-gen/generated_tests.json
   rm -f ~/.cache/wpt-gen/resume_5159559872249856.json
   ```

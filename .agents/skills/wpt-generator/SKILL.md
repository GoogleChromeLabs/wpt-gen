---
name: wpt-generator
description: Generate Web Platform Tests (WPT) from minimal XML blueprints. The agent will autonomously determine the test type and implementation details by analyzing existing repository paradigms. Use when the user asks to generate a Web Platform Test based on a blueprint.
---
# Web Platform Test Generator

This skill enables an ADK agent to generate Web Platform Tests (WPT) from minimal XML blueprints. Because the blueprint only contains high-level requirements, you must rely on existing codebase paradigms to determine how the test should be written.

## Workflow

**Temporary Files Policy:** If you need to create any temporary files during research, prototyping, or debugging, use the `write_file` tool to place them exclusively inside a `.wpt-generator-tmp/` directory at the root of the repository. Do not scatter temporary files across the codebase.

When asked to generate a WPT from an XML blueprint, follow these steps:

### 1. Parse the Blueprint
Extract the following elements from the `<test_suggestion>` XML snippet provided by the user:
- `<web_feature_id>`: Used to find where the test should live.
- `<description>`: The underlying requirement or specification behavior to test.
- `<spec_url>` (can be multiple): A link to the specification. You MUST include these exact URLs in the generated test (using `<link rel="help" href="...">` for HTML tests, or as a single-line comment for `.js` tests).

### 2. Locate the Test Directory
Determine where this test belongs in the repository by finding the corresponding `WEB_FEATURES.yml` file.
1. Use the `search_feature_tests` tool with the `<web_feature_id>` to find existing tests for this feature.
2. Review the output to determine the target directory.

### 3. Research Existing Paradigms & Determine Test Type
Since you are not provided with explicit steps or a test type, you MUST research how similar tests are written for this feature, both in the target directory and across the broader codebase. **Avoid "Tunnel Vision":** Do not restrict your research solely to the output of `search_feature_tests`.
1. Use the `list_directory` and `search_files` tools to explore existing tests in the target directory.
2. Broaden your search: Search the broader repository (or related parent directories) for the API name or feature (e.g., `fetchLater`) to find existing test ecosystems, helper files (`resources/`), or data-driven testing paradigms that might live in adjacent directories.
3. **IDL Check:** If the `<description>` involves testing interface exposure, attributes, or methods, you MUST check the repository's `interfaces/` directory for a corresponding `.idl` file (e.g., `interfaces/crash-reporting.idl`). If it exists, this strongly indicates you should use `idlharness.js` instead of manual boolean assertions.
4. Read 1 or 2 existing tests that seem related to the `<description>`. Treat these as "Golden Examples".
5. Based on the requirement and the golden examples, decide on the best **Test Type**:
   - **Testharness test**: Best for JS APIs, parsing, DOM manipulation, or computed CSS values.
   - **Reftest**: Best for visual/rendering layout matching.
   - **Crashtest**: Best for ensuring no browser crash occurs.
   - **wdspec test**: Best for verifying WebDriver Classic or WebDriver BiDi protocols. Written in **Python** using pytest.
   - **Manual test (ABSOLUTE LAST RESORT)**: You MUST NOT write a manual test unless it is fundamentally impossible to test the behavior using current automated tooling (e.g., standard JS, `testharness.js`, or `testdriver.js`). This format is strictly reserved for behaviors that require unavoidable physical human interaction or OS-level interventions (e.g., forcefully crashing a browser process via the OS task manager). If automation is possible, you MUST automate it.

### 4. Determine the Appropriate File(s) & Name
Before creating a new file, rigorously check if the test logic belongs in existing files. **Minimize boilerplate by reusing existing files whenever possible.**
1. **Analyze Directory Paradigms:** Check if the target directory splits tests by category (e.g., separating valid vs. invalid values, or computed vs. parsing behavior).
2. **Split the Blueprint if Necessary:** A single XML blueprint might encompass multiple test categories. If the directory separates testing into distinct files (e.g., `feature-valid.html` and `feature-invalid.html`), **you MUST split the test logic across the respective existing files** rather than creating a single, monolithic new file.
3. **Reftest Reference Search:** If you selected **Reftest**, you MUST search the target directory (and any `reference/` subdirectories) for existing reusable reference files (e.g., `ref-filled-green-100px-square.xht`) before deciding to create a new one. Do NOT generate a duplicate reference file if a suitable one exists.
4. **Create New Only When Necessary:** Only if no logical match is found (even after considering splitting and manual consolidation), plan to create a new file. **Consult `references/wpt_style_guide.md` to determine the correct filename extension and suffixes** (e.g., `.html`, `.window.js`, `.any.js`) based on your chosen test type. Name the file logically based on the `<web_feature_id>`.
5. **File Existence Check:** Before using `write_file` to create a new test file, you MUST verify that the proposed filename does not already exist in the target directory (e.g., by using the `list_directory` tool).
6. **Naming Conflicts:** If a file with the proposed name already exists, you MUST either append the new test logic to the existing file (if logically appropriate) or generate a new unique filename by incrementing a numerical suffix (e.g., changing `-001.html` to `-002.html`) to prevent overwriting existing work.
7. **Existing Test Expansion:** If you detect that the core assertion of the WPT blueprint is already present in an existing test (i.e. a test perfectly matching the blueprint exists), you MUST ensure all specification edge cases, permutations, or multi-level DOM configurations are thoroughly exercised, and expand the existing test file as necessary instead of creating a redundant new test.
   - **Handling `.tentative` files:** If an existing `.tentative` file matches your blueprint, append your new test cases directly to it. **Do NOT remove the `.tentative` suffix or rename the file** to "upgrade" it unless explicitly instructed to do so by the user.

### 5. Load References & Generate the Test
**Before writing any code**, you MUST read the appropriate style guides to ensure correct formatting and syntax:
- For general guidelines (apply to all): See [wpt_style_guide.md](references/wpt_style_guide.md)
- If Testharness: See [testharness_style_guide.md](references/testharness_style_guide.md)
- If Reftest: See [reftest_style_guide.md](references/reftest_style_guide.md)
- If Crashtest: See [crashtest_style_guide.md](references/crashtest_style_guide.md)
- If the test requires simulated user interaction (clicks, typing, gestures) or tests hardware/device APIs (like Web MIDI, Web Bluetooth): See [automation_guide.md](references/automation_guide.md)
- If the test is a wdspec test (testing the WebDriver protocol itself): See [wdspec_guide.md](references/wdspec_guide.md)
- If the test strictly requires a human operator and cannot be automated: See [manual_test_style_guide.md](references/manual_test_style_guide.md)
- If the test involves Web IDL interfaces (e.g., testing `[Exposed]` attributes, method existence, or interface exposure): See [idlharness_guide.md](references/idlharness_guide.md)
- If the test requires cross-origin requests, custom HTTP headers, specific status codes, or dynamic server logic: See [server_features_guide.md](references/server_features_guide.md)

Write the appropriate WPT test to strictly satisfy the `<description>` using the `write_file` tool:
- **CRITICAL RULE: Style Guides > Golden Examples:** Existing tests ("Golden Examples") sometimes contain legacy code and violate current best practices. You should prioritize the explicit rules in the style guides over the paradigms found in surrounding files. Use existing files to understand the *domain logic*, but rely exclusively on the style guides for the *implementation syntax*.
- **Omit HTML Boilerplate:** Unless the test strictly requires attaching attributes to the root elements, you MUST omit standard `<html>`, `<head>`, and `<body>` tags in your generated `.html` files (including references) to keep tests focused and concise, even if "Golden Examples" include them. Start directly with `<!DOCTYPE html>` and `<meta charset="utf-8">`.
- **Deduce Expectations:** Carefully deduce the exact pass/fail condition and assertions from the `<description>`. If the requirement is highly complex or vague, use the `fetch_spec_content` tool to fetch the `<spec_url>` text to gain deeper context before writing the test.
- **CRITICAL RULE: Minimize Specification Boilerplate:** Only use the APIs strictly required to trigger the behavior described in the `<description>`. Do not include optional features or initialization boilerplate from the spec unless explicitly required by the core assertion.
- **CRITICAL RULE: Domain Helpers > Golden Examples:** Check if a built-in helper exists in the local `resources/` directory to avoid repetitive boilerplate. Even if your "Golden Example" writes out boilerplate logic manually (e.g., manually polling, fetching, resolving a sequence of events, or establishing positive controls), you MUST aggressively replace that boilerplate if a higher-level abstraction exists in a local helper file. **When you identify a helper file, you MUST perform an exhaustive audit of its entire exported API (e.g., reading the whole `helper.js` file using `read_file`) to discover all available utilities (like `wait()`, `delay()`, or custom assertions). Do not restrict your usage only to the specific functions the Golden Example used.**
   - If testing CSS property parsing, descriptor parsing (e.g., `@font-face` descriptors), at-rules, inheritance, computed values, or shorthands: See [css_testcommon.md](references/domain_helpers/css_testcommon.md)
   - If testing CSS Fonts, typography, or synthetic glyph metrics: See [css_fonts.md](references/domain_helpers/css_fonts.md)
   - If testing CSS property animatability, interpolation, or discrete flips: See [css_animations.md](references/domain_helpers/css_animations.md)
   - If testing cross-origin network or fetch behaviors via Javascript: See [get_host_info.md](references/domain_helpers/get_host_info.md)
   - If testing features controlled by Permissions Policy (formerly Feature Policy): See [permissions_policy.md](references/domain_helpers/permissions_policy.md)
- **Implementation:** Write the test logic, setup, and assertions autonomously. When generating tests for multiple permutations or variations of an API, you should consider writing a data-driven test using arrays and loops, as described in `testharness_style_guide.md`. However, do not over-engineer simple, isolated features. *Note: If the target directory lacks examples of your chosen Test Type, rely entirely on the style guides.*

### 6. Validation & Self-Correction (CRITICAL)
Before completing the task, you MUST validate that the code you generated is syntactically correct, properly formatted, and functions as intended.

1. **Linting:** Use the `run_wpt_lint` tool on the file you created/modified.
   - If the linter reports errors (e.g., `TRAILING WHITESPACE`, `INDENT TABS`), you MUST use the `replace_in_file` tool to fix the errors and re-run the linter until it passes cleanly. This saves context tokens compared to rewriting the entire file.

2. **Execution:** Use the `run_wpt_test` tool on the file you created/modified.
   - **CRITICAL RULE - Manual Tests:** If the test you created or modified is a manual test (e.g., ends in `-manual.html` or requires human intervention), you **MUST SKIP** this execution step entirely. Rely strictly on the linter for manual tests.
   - **Analyze the Output:** Read the test runner's output carefully.
   - **Self-Correct:** If the runner reports a `Harness Error`, `SyntaxError`, a timeout, or a failure that indicates a flaw in your test logic (e.g., calling an undefined helper function or making an incorrect assertion), you MUST use the `replace_in_file` or `write_file` tools to fix the bug, and re-run the test. Use `replace_in_file` whenever possible.
   - Repeat this execute-and-fix loop until the test executes successfully without syntax or harness errors. **Maximum 3 attempts.** If the test still fails after 3 correction attempts, stop debugging and proceed to finalize. *(Note: If the test fails because the browser genuinely does not support the feature, that is acceptable—your goal is to ensure the **test code** itself is valid.)*

### 7. Map the Test in WEB_FEATURES.yml
Every generated test file MUST be explicitly mapped to the target `<web_feature_id>` (from Step 1) in the directory's `WEB_FEATURES.yml` file.
1. **Check for File:** Look for `WEB_FEATURES.yml` in the directory where you created or modified the test using the `list_directory` tool.
2. **Create if Missing:** If the file does not exist, create it using the `write_file` tool with the following structure:
   ```yaml
   features:
   - name: <web_feature_id>
     files:
     - <new_test_file_name>
   ```
3. **Update if Existing:** If it exists, read it using `read_file` and update it using `write_file` to append your new test file name to the `files:` list under the matching `<web_feature_id>`. (If the test is already covered by an existing wildcard pattern belonging to the correct feature, you don't need to list it individually).
4. **Prevent Collisions (CRITICAL):** Carefully review the other web feature IDs defined in the same `WEB_FEATURES.yml` file. If another feature uses a wildcard (like `- "**"` or `- "*.html"`) that would accidentally match your newly created test file, you MUST explicitly exclude your test from that feature by adding a negation line (e.g., `- "!<new_test_file_name>"`) to its `files:` list.

### 8. Finalizing
- Ensure standard WPT scripts are included properly (if applicable) using absolute paths from the root server.
- Ensure crashtests end with `-crash.html` if creating a new crashtest file.
- **Clean Up:** You MUST explicitly delete any temporary files you created in `.wpt-generator-tmp/` using the `delete_file` tool to ensure no temporary prototypes, scripts, or intermediate files are left behind in the repository.
- Once the test is validated and the `WEB_FEATURES.yml` file is mapped, your task is complete.

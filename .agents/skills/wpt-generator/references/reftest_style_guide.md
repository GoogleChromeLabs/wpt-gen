Reftests (reference tests) are one of the primary tools in Web Platform Tests (WPT) for verifying rendering and layout. They work by comparing the visual output of a **test file** against one or more **reference files**. If the pixels match (or mismatch, as specified), the test passes.

This guide provides a comprehensive overview of best practices for writing high-quality, maintainable, and robust reftests.

## 1. Anatomy of a Reftest

A reftest requires at least two files: the test file and the reference file. 

**CRITICAL RULE FOR AI GENERATION:** Before writing a new reference file, you MUST rigorously search the target directory (and its `reference/` subdirectories) for existing reference files that match your expected output (e.g., `ref-filled-green-100px-square.xht`). 
- **If a suitable reference exists:** Use a `<link rel="match">` tag pointing to that existing file. Do NOT generate a duplicate reference file.
- **If NO suitable reference exists:** You MUST generate BOTH your new test file AND a new reference file (e.g., `my-test-ref.html`). Never create a `<link rel="match" href="ref.html">` tag without ensuring `ref.html` actually exists!

### The Test File
The test file employs the technology being tested. It must include a `<link>` element that points to the reference file.

```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>CSS Grid: basic template-areas</title>
<link rel="help" href="https://www.w3.org/TR/css-grid-1/#grid-template-areas-property">
<link rel="match" href="grid-template-areas-ref.html">
<meta name="assert" content="Basic check that grid-template-areas correctly positions items.">

<p>Test passes if there is a green square below and no red.</p>
<div style="display: grid; grid-template-areas: 'a'; width: 100px; height: 100px;">
  <div style="grid-area: a; background: green; width: 100%; height: 100%;"></div>
</div>
```

### The Reference File
The reference file describes the *expected* output. **Crucially, it should not use the technology under test.** It should be as simple as possible so that it renders correctly even in browsers with poor support for newer features.

```html
<!-- grid-template-areas-ref.html -->
<!DOCTYPE html>
<meta charset="utf-8">
<title>CSS Grid: basic template-areas reference</title>
<p>Test passes if there is a green square below and no red.</p>
<div style="width: 100px; height: 100px; background: green;"></div>
```

### Match vs. Mismatch
- `<link rel="match" href="...">`: The test passes if it renders **pixel-for-pixel identically** to the reference.
- `<link rel="mismatch" href="...">`: The test passes if it renders **differently** from the reference.

## 2. Naming and Organization

- **File Names**: Use descriptive names. A common pattern is `feature-subfeature-001.html`.
- **Reference Suffix**: For references specific to one test, use the `-ref` suffix: `my-test.html` -> `my-test-ref.html`.
- **Shared References**: If a reference is shared across many tests, place it in a `references` directory (either local or at the top level for generic references).
- **Path Lengths**: Keep paths under 150 characters relative to the test root to avoid Windows limitations.
- **CSS Uniqueness**: In the `css/` directory, filenames must be unique across the entire `css/` tree.

## 3. Reusing Reference Files (CRITICAL)

Before creating a new reference file, **you MUST check if an existing reference file can be reused**. Reusing references is highly preferred because it reduces repository bloat and speeds up automated test runners.

- Look in the current directory and any `reference/`, `references/`, or `support/` subdirectories.
- Look for standard WPT shared references (e.g., `../reference/ref-filled-green-100px-square.xht`).
- If an existing file produces the exact same visual rendering (e.g., a simple green square or a blank white page), link to it using `<link rel="match" href="...">` instead of creating a new `-ref.html` file.

### 3.1 Designing Tests for Reference Reuse

**CRITICAL RULE:** Design your test's output to match an existing reference, rather than designing a bespoke reference to match your test's output.

When testing multiple independent permutations (e.g., verifying that `display: none` and `content: none` both have no effect on a property), **do not** generate independent, sequential visual outputs for each permutation (e.g., outputting `1`, `1`, `1` in a list). This anti-pattern forces the creation of a bespoke, duplicate reference file.

Instead, consolidate the permutations sequentially into a single layout that evaluates to a standard output (e.g., a final integer like `7`, or a single green square). Let each permutation attempt its operation; if they behave correctly, the final evaluated state should match an already existing reference (like `counter-7-ref.html` or a generic green square).

## 4. The Golden Rule of References

**References must be simple.** If you are testing CSS Grid, your reference should use absolute positioning, floats, or simple block layout to achieve the same visual result. This ensures that a failure in the reference doesn't cause a false positive or negative in the test.

## 5. Visual Patterns for Success and Failure

Tests should be "self-describing" so a human can easily verify them.

### 5.1 Pruning Redundant Scaffolding (Crucial for Blueprints)
When generating a Reftest from a blueprint, treat the `<pre_conditions>` as structural guidelines, not strict requirements. If the `<pre_conditions>` request multiple HTML elements (like a container with multiple children), but assigning explicit CSS dimensions or applying standard visual patterns (like a single 100x100 green square) makes some of those requested DOM elements visually or geometrically redundant, you **MUST** remove them to minimize boilerplate. Do not blindly copy HTML elements from a blueprint or from legacy "Golden Examples" if they do not participate in the layout or the interaction being tested.
- **Prefer Pseudo-Elements:** Whenever a test requires verifying a behavior on pseudo-elements, or for visual tricks like "Red-Under-Green" and stacking context triggers, you MUST attach those pseudo-elements directly to pre-existing structural container nodes. Do not introduce new, dedicated, empty DOM elements purely to host them.

- **The Green Square**: A very common pattern. The test passes if it produces a 100x100 green square.
- **Color Meanings**:
    - **Green**: Success.
    - **Red**: Failure. Often placed *under* the test content so it only appears if something is misaligned or paints incorrectly.
    - **Black**: Descriptive text.
    - **Silver/Gray**: Irrelevant filler content.
- **No Scrollbars**: Avoid scrollbars at an 800x600 window size unless testing scrolling itself.

### Example: The Optimized Red-Under-Green Pattern
```html
<style>
.test-box, .test-box::before {
  width: 100px;
  height: 100px;
}
.test-box {
  background: green;
}
.test-box::before {
  content: "";
  position: absolute; /* or negative z-index depending on test goals */
  background: red;
}
</style>
<div class="test-box"></div>
```

## 6. Using the Ahem Font

When testing text layout, standard fonts are unreliable due to platform differences. Use the **Ahem font**, which has precise, square metrics.

- **Link the stylesheet**: `<link rel="stylesheet" href="/fonts/ahem.css">`
- **Sizing**: Use a multiple of 5px (20px or 25px is recommended).
- **Line-Height**: Use an explicit `line-height` (e.g., `1` or a value where `line-height - font-size` is divisible by 2).
- **Shorthand**: Use the `font` shorthand to ensure default values for weight/style.

```css
.test {
  font: 25px/1 Ahem;
}
```

## 7. Advanced Reftest Features

### Asynchronous Tests (`reftest-wait`)
If your test requires DOM manipulation or animation before the screenshot, use the `reftest-wait` class on the root element.

```html
<html class="reftest-wait">
<link rel="match" href="ref.html">
<script>
  // The harness fires a 'TestRendered' event when it's ready.
  document.documentElement.addEventListener('TestRendered', () => {
    document.getElementById('target').style.background = 'green';
    document.documentElement.classList.remove('reftest-wait');
  });
</script>
```

**Waiting for events and avoiding timers:**
The use of `setTimeout` in tests is strictly prohibited because it is an observed source of instability when running in CI. Instead, prefer event-driven approaches: wait for an event (e.g., `load`, `DOMContentLoaded`, or custom events) to indicate readiness, or use two `requestAnimationFrame` calls to ensure rendering steps have completed. These alternatives improve reliability and consistency across different environments.

In some cases, such as reftests that compare frames after a specific animation duration (e.g., APNG tests), the use of a timeout may be acceptable. When doing so, consider documenting the reason.

**DO NOT** Use `setTimeout` in your tests.

The harness follows this sequence:
1. Wait for `load` and fonts.
2. Fire `TestRendered` on the root element.
3. Wait for `reftest-wait` class to be removed.
4. Wait for pending paints to complete.
5. Screenshot the viewport.

### Fuzzy Matching
If subtle anti-aliasing differences are expected, use the `fuzzy` meta tag.

```html
<!-- Allow up to 15 per-channel color difference and 300 total different pixels -->
<meta name="fuzzy" content="maxDifference=15;totalPixels=300">
```

### Multiple References
- If multiple `rel="match"` links are present, the test passes if **at least one** matches.
- If multiple `rel="mismatch"` links are present, the test passes if **all** mismatch.

## 8. Print Reftests

Print reftests verify paginated output.
- **Naming**: Use the `-print` suffix or place in a `print/` directory.
- **Comparison**: Pages are compared one-by-one.
- **Page Size**: The default page size is 12.7 cm by 7.62 cm (5x3 inches) with 12.7 mm (0.5 inch) margins.
- **Page Range**: Use `<meta name="reftest-pages" content="1-2, 5">` to limit comparison.

## 9. General Requirements and Metadata

### Essential Metadata
- **Charset**: Always include `<meta charset="utf-8">`.
- **Conciseness**: Omit `<html>` and `<head>` tags if possible to keep the test focused.
- **Timeouts**: Execution of tests is subject to a global timeout. Long-running tests may opt into a longer timeout by providing a `<meta>` element: `<meta name="timeout" content="long">`.
- **Specification Links**:
    - **Required for CSS tests**, recommended for others.
    - Use `<link rel="help" href="...">` to link to the relevant spec section.
    - List the primary section being tested first.
- **Test Assertions**:
    - Use `<meta name="assert" content="...">` to describe exactly what the test is proving.
    - Avoid repeating the title; be specific (e.g., "Checks that 'text-indent' affects only the first line of a block container").

### Requirement Flags (CSS-Specific)
For CSS tests, you can use `<meta name="flags" content="...">` to specify requirements. Common tokens include:
- `asis`: The test cannot be re-serialized (formatting is critical).
- `may`: Testing optional behavior.
- `should`: Testing recommended behavior.
- `paged`: Only valid for paged media.
- `scroll`: Only valid for scrolling media.

Example:
```html
<meta name="flags" content="may paged">
```

### Avoiding Global Dependencies
- **Avoid Edge Cases**: Don't rely on unrelated features that might fail in some browsers.
- **No External Resources**: Tests must be self-contained; do not link to external CDNs or images.
- **Cross-Platform**: Ensure the test doesn't rely on specific screen resolutions or installed system fonts (use Ahem instead).

## 10. Validation and Running

- **Linting**: Always run the `run_wpt_lint` tool before submitting. It catches metadata errors, trailing whitespace, and more.
- **Running**: Use the `run_wpt_test` tool on your test file to verify it locally.

By following these best practices, you ensure your reftests are a reliable part of the Web Platform Tests suite.

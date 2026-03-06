# Reftest Best Practices

Reftests (reference tests) are one of the primary tools in Web Platform Tests (WPT) for verifying rendering and layout. They work by comparing the visual output of a **test file** against one or more **reference files**. If the pixels match (or mismatch, as specified), the test passes.

This guide provides a comprehensive overview of best practices for writing high-quality, maintainable, and robust reftests.

## 1. Anatomy of a Reftest

A reftest consists of at least two files: the test file and the reference file.

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

## 3. The Golden Rule of References

**References must be simple.** If you are testing CSS Grid, your reference should use absolute positioning, floats, or simple block layout to achieve the same visual result. This ensures that a failure in the reference doesn't cause a false positive or negative in the test.

## 4. Visual Patterns for Success and Failure

Tests should be "self-describing" so a human can easily verify them.

- **The Green Square**: A very common pattern. The test passes if it produces a 100x100 green square.
- **Color Meanings**:
    - **Green**: Success.
    - **Red**: Failure. Often placed *under* the test content so it only appears if something is misaligned.
    - **Black**: Descriptive text.
    - **Silver/Gray**: Irrelevant filler content.
- **No Scrollbars**: Avoid scrollbars at an 800x600 window size unless testing scrolling itself.

### Example: The Red-Under-Green Pattern
```html
<div style="width: 100px; height: 100px; background: red;">
  <!-- This green box should perfectly cover the red box -->
  <div style="width: 100px; height: 100px; background: green; margin-top: -100px;"></div>
</div>
```

## 5. Using the Ahem Font

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

## 6. Advanced Reftest Features

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

## 7. Print Reftests

Print reftests verify paginated output.
- **Naming**: Use the `-print` suffix or place in a `print/` directory.
- **Comparison**: Pages are compared one-by-one.
- **Page Size**: The default page size is 12.7 cm by 7.62 cm (5x3 inches) with 12.7 mm (0.5 inch) margins.
- **Page Range**: Use `<meta name="reftest-pages" content="1-2, 5">` to limit comparison.

## 8. General Requirements and Metadata

### Essential Metadata
- **Charset**: Always include `<meta charset="utf-8">`.
- **Conciseness**: Omit `<html>` and `<head>` tags if possible to keep the test focused.
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

## 9. Validation and Running

- **Linting**: Always run `./wpt lint` before submitting. It catches metadata errors, trailing whitespace, and more.
- **Running**: Use `wpt run <browser> <path/to/test>` to verify your test locally.
  ```bash
  python ./wpt run chrome html/semantics/text-level-semantics/the-bdo-element/rtl.html
  ```

By following these best practices, you ensure your reftests are a reliable part of the Web Platform Tests suite.

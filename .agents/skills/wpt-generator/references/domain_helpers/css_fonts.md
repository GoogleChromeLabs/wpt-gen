# CSS Fonts Testing (`css/css-fonts/*`)

Testing typography and fonts in WPT requires a solid understanding of how browsers asynchronously load resources, how standard WPT fonts behave, and when to use Reftests versus `testharness.js`.

## 1. Standard WPT Fonts

WPT provides a suite of reliable, deterministic fonts for testing in `fonts/` (or `support/fonts/` depending on the directory). You MUST use these instead of system fonts to ensure cross-platform consistency.

*   **`Ahem.ttf`:** The canonical testing font. Every character renders as a solid square block matching its em-size.
    *   **Predictable Metrics:** `1ex = 0.8em`, `1ch = 1em`.
    *   **Linter Warning (`AHEM SYSTEM FONT`):** The WPT linter strictly forbids the word "Ahem" from appearing in CSS to prevent accidentally falling back to the system's Ahem font instead of the web font. If you get an `AHEM SYSTEM FONT` lint error when writing an `@font-face` rule, **do NOT try to obfuscate the font name in the code.** You MUST append the file path to the repository's `lint.ignore` file exactly as instructed by the WPT runner output.
*   **`pass.woff` / `fail.woff`:** Incredibly powerful tools for CSS font rendering/matching testing. These fonts use ligature replacement to visually render the strings "PASS" or "FAIL" when a specific single letter (like `P` or `F`) is typed in the HTML. Use these in Reftests instead of relying solely on Ahem blocks for complex matching algorithms.
*   **`FontWithFancyFeatures.otf`:** Use this when you specifically need to trigger OpenType features (like `sups` and `subs` for superscript/subscript) or synthesis fallbacks. Ahem inherently lacks these features.

## 2. Asynchronous Font Loading (`testharness.js`)

If you are writing a `testharness.js` test that relies on the dimensions of a loaded font, you **MUST NOT** synchronously measure DOM elements (e.g., using `getBoundingClientRect()`) immediately after appending them.

`document.fonts.ready` only resolves for *requested* fonts. You must explicitly ensure the font is loaded before measuring:

```javascript
promise_test(async t => {
  const div = document.createElement('div');
  div.style.fontFamily = 'Ahem';
  div.textContent = 'X';
  document.body.appendChild(div);

  // CRITICAL: Await the explicit load of the font metrics before measuring
  await document.fonts.load('10px Ahem');
  
  const rect = div.getBoundingClientRect();
  assert_equals(rect.width, 10);
}, "Font metrics are measured after explicit load");
```

## 3. Synthetic Glyphs (Mandatory Reftests)

If you are testing properties that affect synthetic glyph geometries or metrics overrides (such as `font-variant-position` synthesizing superscript/subscript, or `@font-face` descriptor adjustments like `size-adjust` or `ascent-override`), you generally **MUST use Reftests**.

**Why?** Standard line-box heights and `.getBoundingClientRect()` often remain unaffected by synthetic glyph alterations. The inline bounding box does not accurately map the ink bounds of the synthesized glyph, making `testharness.js` measurements unreliable.

Compare the visual layout output to a hardcoded text reference, often utilizing `Ahem` and absolute CSS positioning equivalents (e.g., `position: relative; top: -0.5em`) to verify the exact mathematical shift of the glyph.
# CSS Property & Parsing Helpers (`css/support/*-testcommon.js`)

## CSS Test Structure Rules (CRITICAL)
When generating tests within the `css/` directory, you MUST obey the following structural rules. These rules **override** general WPT style guidelines:

1.  **Unrolled Parsing Tests (No Loops):** When writing parsing, computed value, or inheritance tests using the `*-testcommon.js` helpers in a **new file**, you MUST NOT use arrays or loops to iterate over test cases. The preferred style is to repeat the function calls on consecutive lines:
    ```javascript
    test_valid_value("will-change", "scroll-position");
    test_valid_value("will-change", "contents");
    test_valid_value("will-change", "transform");
    ```
    *Caveat:* If you are appending to an *existing* file, you MUST conform to the paradigm of that specific file (i.e., if the existing file uses arrays/loops, you must append to the array; if it uses flat lines, add new flat lines).
2.  **Single Behavior Per File:** General CSS tests (non-parsing, non-API tests like animations, flexbox layouts, or rendering edge cases) should be kept extremely short and focused on exactly **ONE specific behavior or edge case per file**. Do not consolidate multiple different rendering behaviors or edge cases into a single large test file.

---

When writing WPTs for CSS APIs (such as testing property parsing, computed values, inheritance, or shorthands), **do not manually write out the Javascript to set styles, read `getComputedStyle`, and compare values**. Instead, you **MUST** use the robust canonical testing framework located in the `/css/support/` directory.

## Including the Frameworks
Since you are testing CSS, you **MUST** use an `.html` file because the CSS linter requires a `<link rel="help">` tag.

```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>My CSS Test</title>
<link rel="help" href="https://drafts.csswg.org/css-align/">
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<script src="/css/support/parsing-testcommon.js"></script>
<script src="/css/support/computed-testcommon.js"></script>
<script src="/css/support/inheritance-testcommon.js"></script>
<script src="/css/support/shorthand-testcommon.js"></script>

<!-- A #target element is required by most of these helpers! -->
<!-- For inheritance tests, it MUST be inside a #container -->
<div id="container">
  <div id="target"></div>
</div>
```

## Parsing (`parsing-testcommon.js`)
Use these to test whether a browser correctly parses (or rejects) a specified CSS value for a property.
*   `test_valid_value(property, specified, serializedValue)`: Tests that setting the property to `specified` succeeds, and that reading it back (serialization) matches `serializedValue`. If `serializedValue` is omitted, it defaults to `specified`.
*   `test_invalid_value(property, specified)`: Tests that the browser correctly rejects the `specified` value as invalid.

**Example:**
```javascript
// Consider using data-driven arrays/loops for multiple values.
const valid_values = [
  { specified: 'center' },
  { specified: 'flex-start', expected: 'start' }
];
for (const { specified, expected } of valid_values) {
  test_valid_value('align-items', specified, expected);
}

const invalid_values = ['10px', 'auto', 'none'];
for (const value of invalid_values) {
  test_invalid_value('align-items', value);
}
```

**Validation Reassurance (Unimplemented Grammar):**
When writing tests for newly specified grammar (e.g., a new 2-value syntax for a property), it is common for the test runner to report a failure because the browser engine hasn't implemented the new spec syntax yet. **Do not endlessly attempt to "fix" your code if it correctly matches the specification.** Write tests strictly to the spec. If the browser rejects valid grammar because it is unimplemented, accept the failure and finalize the test.

## Computed Style (`computed-testcommon.js`)
Use these to test how a specified CSS value resolves in `getComputedStyle`.
*   `test_computed_value(property, specified, computed)`: Tests that setting the property to `specified` results in a `getComputedStyle` value of `computed`. If `computed` is omitted, it defaults to `specified`.

**CRITICAL WARNING: CSS Counters**
Do NOT use `getComputedStyle` (or `test_computed_value`) to verify the mathematical evaluation or output of CSS counters (e.g., `counter-set`, `counter-increment`). The `getComputedStyle(element, '::before').content` API is unreliable for this purpose; many browser engines will return the raw functional value (e.g., `"counter(c)"`) instead of the computed integer string (e.g., `"1"`). **You MUST use Reftests to verify CSS counter outputs.** See `reftest_style_guide.md`.

**Example:**
```javascript
// Consider using data-driven arrays/loops for multiple values.
const computed_values = [
  { specified: 'auto' },
  { specified: '100px' },
  { specified: '10%', expected: '50px' } // Assuming parent width is 500px
];
for (const { specified, expected } of computed_values) {
  test_computed_value('width', specified, expected); // Example assumes same property
}
```

## Inheritance (`inheritance-testcommon.js`)
Use these to test whether a CSS property correctly inherits from its parent element.
*Note: This helper strictly requires BOTH a `#container` and `#target` element in the DOM.*
*   `assert_inherited(property, initial, other)`: Tests that the property inherits. `initial` is the computed initial value of the property, and `other` is a distinct valid value.
*   `assert_not_inherited(property, initial, other)`: Tests that the property does NOT inherit.

**Example:**
```javascript
// Color inherits by default. 'canvastext' is the initial value in many UAs.
assert_inherited('color', 'canvastext', 'red');

// Margin does not inherit. '0px' is the initial value.
assert_not_inherited('margin', '0px', '10px');
```

## Shorthands (`shorthand-testcommon.js`)
Use this to test that setting a shorthand property correctly sets the underlying longhand properties.
*   `test_shorthand_value(property, value, longhands)`: Tests that setting `property` to `value` correctly sets all the corresponding `longhands` (provided as an object mapping longhand names to expected values).

**Example:**
```javascript
test_shorthand_value('margin', '10px 20px', {
  'margin-top': '10px',
  'margin-right': '20px',
  'margin-bottom': '10px',
  'margin-left': '20px'
});
```

## At-Rules & Descriptors (e.g., `@font-face`)

To test parsing of at-rules and their descriptors, you **MUST** use `test_valid_rule(rule, serialized)` from `parsing-testcommon.js`.

Because invalid descriptors inside a valid at-rule do *not* cause `insertRule()` to throw a `DOMException` (the CSS parser simply drops the invalid descriptor), you **cannot** use `test_invalid_rule()` to test invalid descriptors. Instead, you must use `test_valid_rule()` for BOTH valid and invalid descriptors by leveraging the `serialized` parameter:

*   **For valid descriptors:** `test_valid_rule('@font-face { descriptor: value; }');` (asserts that the rule parses and serializes identically).
*   **For invalid descriptors:** `test_valid_rule('@font-face { descriptor: invalid-value; }', '@font-face { }');` (asserts that the rule parses but the invalid descriptor is dropped during serialization).

**CRITICAL MANDATE - Data-Driven Testing:** You **MUST NOT** copy-paste flat, repetitive `test_valid_rule()` calls for every permutation. You **MUST** use data-driven loops (arrays of test cases), just as you would for `test()` or `promise_test()` blocks. Do not blindly copy legacy code from adjacent files that violates this.

**CRITICAL MANDATE - Canonical Serialization:** When testing descriptors or properties that accept multiple values where the second value might default to the first (e.g., `normal normal` serializing to `normal`), or when testing `calc()` values, you **MUST** use an array of objects containing `specified` and `expected` properties to handle canonical serializations accurately. Combine all valid values into a single array to reduce boilerplate. Do not use flat arrays of strings unless you are absolutely certain all values serialize exactly as specified.

**Example (Data-Driven - Required):**
```javascript
const valid_values = [
  { specified: 'normal' },
  { specified: '50% 150%' },
  { specified: 'normal normal', expected: 'normal' }, // Canonical serialization
  { specified: 'calc(50% + 50%)', expected: 'calc(100%)' }
];
for (const { specified, expected } of valid_values) {
  test_valid_rule(
    `@font-face { line-gap-override: ${specified}; }`,
    `@font-face { line-gap-override: ${expected || specified}; }`
  );
}

const invalid_values = [
  '100',
  '10% 20% 30%'
];
for (const value of invalid_values) {
  test_valid_rule(
    `@font-face { line-gap-override: ${value}; }`,
    '@font-face { }' // Invalid descriptors are dropped
  );
}
```
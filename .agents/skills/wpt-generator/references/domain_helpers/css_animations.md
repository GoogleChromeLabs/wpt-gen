# CSS Animation & Interpolation Helpers

When writing tests in WPT that verify whether a CSS property is animatable or how its values interpolate, **do not manually write out the steps to set up transitions or the Web Animations API (WAAPI)**. Instead, use the robust testing framework located at `/css/support/interpolation-testcommon.js`.

## Including the Framework
**Important:** Tests inside the `css/` directory are subject to strict linting rules (specifically the `MISSING-LINK` rule) that require an explicit `<link rel="help" href="...">` HTML tag. Therefore, **you MUST use the standard HTML format (`.html`)** instead of the JavaScript-only format (`.window.js`) for CSS tests to pass the linter.

Include the script after `testharness.js`:

```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>My Animation Test</title>
<link rel="help" href="https://drafts.csswg.org/css-align/">
<meta name="assert" content="Description of assertion.">
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<script src="/css/support/interpolation-testcommon.js"></script>
<body>
<script>
// Your animation test code here
</script>
</body>
```

## `test_not_animatable(options)`
Verifies that a property cannot be animated using CSS Transitions, `transition: all`, CSS Animations, or WAAPI.

**Arguments:**
An object with the following properties:
*   `property`: The CSS property name (e.g., `'will-change'`, `'transition-duration'`).
*   `from`: The starting value of the property (e.g., `'opacity'`).
*   `to`: The ending value of the property (e.g., `'transform'`).
*   `underlying` (Optional but recommended): A default value used to test discrete animation steps (e.g., `'auto'`).

**Example:**
```javascript
test_not_animatable({
  property: 'will-change',
  from: 'opacity',
  to: 'transform',
  underlying: 'auto',
});
```

## `test_interpolation(options, expectations)`
Verifies how a property's value changes between two states.

**Arguments:**
*   `options`: An object specifying the `property`, `from`, and `to` values.
*   `expectations`: An array of objects representing expected values at specific points (`at`) in the animation timeline.

**Example:**
```javascript
test_interpolation({
  property: 'opacity',
  from: '0',
  to: '1'
}, [
  {at: -0.5, expect: '0'}, // Clamped to 0
  {at: 0, expect: '0'},
  {at: 0.5, expect: '0.5'},
  {at: 1, expect: '1'},
  {at: 1.5, expect: '1'} // Clamped to 1
]);
```

## `test_no_interpolation(options)`
Verifies that a property is "animatable" but uses a **discrete** flip at `50%` of the animation timeline (i.e., it doesn't smoothly interpolate). 

**Example:**
```javascript
test_no_interpolation({
  property: 'display',
  from: 'none',
  to: 'block'
});
```

## Why use these?
These functions automatically generate comprehensive subtests across all possible animation avenues (CSS Transitions, `transition: all`, CSS Keyframes, Web Animations API), ensuring exhaustive coverage without writing redundant boilerplate logic.

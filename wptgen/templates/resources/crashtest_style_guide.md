Crash tests are a vital part of the Web Platform Tests (WPT) suite. They ensure that the browser can load a document without crashing, hanging, or triggering low-level issues like assertions, memory leaks, or sanitizer failures.

This guide provides a deep dive into the best practices for writing high-quality crashtests that conform to WPT standards.

---

## 1. Core Concepts

A crashtest is the simplest type of test in WPT.
- **Success Criteria**: The test passes if the document completes loading and finishing its initial paint without the browser terminating or hanging.
- **No Harness Needed**: Unlike `testharness.js` tests, crashtests do **not** require any specialized unit testing framework. You do not need to include `testharness.js` or `testharnessreport.js`.

---

## 2. Naming and Location

WPT identifies crashtests based on their filename or their directory.

### Filename Convention
Add the `-crash` suffix immediately before the file extension.
- **Correct**: `css/css-foo/bar-crash.html`
- **Incorrect**: `css/css-foo/bar-crash-001.html` (The suffix must be immediately before the extension).

### Directory Convention
Place the test inside a directory named `crashtests`.
- **Example**: `css/css-foo/crashtests/bar.html`
- Any file within a `crashtests` directory is treated as a crashtest, regardless of its filename.

---

## 3. Test Structure

### Keep it Minimal
The most effective crashtests are the most minimal. Avoid any extraneous HTML, CSS, or JavaScript that isn't directly related to triggering the crash.

### Basic Template
```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>Short descriptive title of the crash scenario</title>
<link rel="author" title="Your Name" href="mailto:your-email@example.com">
<link rel="help" href="https://link-to-spec-or-bug-report">
<meta name="assert" content="Detailed description of what should not crash.">

<!-- Minimal markup to trigger the crash -->
<div style="columns: 3;">
  <span>Triggering content</span>
</div>
```

---

## 4. Handling Asynchrony

By default, the test runner finishes a crashtest once the `load` event fires and the initial paint is complete. If your test needs to perform work after the initial load, use `test-wait`.

### The `test-wait` Class
Add the `test-wait` class to the root element (`<html>`). The test will remain active until this class is removed.

```html
<html class="test-wait">
<script>
  requestAnimationFrame(() => {
    // Perform async work
    document.documentElement.classList.remove("test-wait");
  });
</script>
</html>
```

### The `TestRendered` Event
The test runner fires a `TestRendered` event at the root element when it's ready to finish the test (after `load` and initial paint). Use this to perform modifications that must not be batched with the initial paint.

```html
<html class="test-wait">
<script>
  document.documentElement.addEventListener("TestRendered", () => {
    // Modify the DOM after initial render
    document.getElementById("target").style.display = "none";
    document.documentElement.classList.remove("test-wait");
  });
</script>
</html>
```

---

## 5. Advanced Features

### User Interactions (`testdriver.js`)
If a crash is triggered by user interaction, use `testdriver.js`.

```html
<html class="test-wait">
<script src="/resources/testdriver.js"></script>
<script src="/resources/testdriver-vendor.js"></script>
<button id="btn">Click me</button>
<script>
  const btn = document.getElementById("btn");
  btn.onclick = () => document.documentElement.classList.remove("test-wait");
  test_driver.click(btn);
</script>
</html>
```

### File Name Flags
You can use standard WPT filename flags with crashtests:
- **HTTPS**: `foo-crash.https.html`
- **Server Substitution**: `foo-crash.sub.html`
- **HTTP/2**: `foo-crash.h2.html`

---

## 6. Best Practices Checklist

- [ ] **Descriptive Filenames**: Use a concise, descriptive name (e.g., `flex-direction-change-crash.html`).
- [ ] **UTF-8 Encoding**: Always include `<meta charset="utf-8">`.
- [ ] **Cross-Browser Compatibility**: Ensure the test doesn't rely on features exclusive to one browser, unless testing that specific browser's behavior.
- [ ] **Regressions**: If the test is a fix for a bug, include a `link` with `rel="help"` pointing to the bug report.
- [ ] **CSS Metadata**: For tests in the `css/` directory, a `link` with `rel="help"` pointing to the relevant specification section is **required**.
- [ ] **Lint Your Test**: Run `./wpt lint` before submitting to ensure your test follows all style and formatting rules.

---

## 7. Examples

### Simple Static Crash
Triggers a crash during the initial layout.
```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>CSS Grid: Nested grid item crash</title>
<link rel="help" href="https://drafts.csswg.org/css-grid/">
<div style="display: grid;">
  <div style="display: grid; grid-template-columns: repeat(100, 1fr);"></div>
</div>
```

### Scripted Dynamic Crash
Triggers a crash by modifying the DOM after load.
```html
<!DOCTYPE html>
<html class="test-wait">
<meta charset="utf-8">
<title>DOM: removeChild on detached iframe</title>
<link rel="help" href="https://dom.spec.whatwg.org/#dom-node-removechild">
<iframe></iframe>
<script>
  const frame = document.querySelector("iframe");
  const doc = frame.contentDocument;
  const div = doc.createElement("div");
  doc.body.appendChild(div);
  frame.remove();
  div.remove();
  document.documentElement.classList.remove("test-wait");
</script>
</html>
```

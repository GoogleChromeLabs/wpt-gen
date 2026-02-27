This guide provides comprehensive instructions and best practices for generating high-quality Web Platform Tests. It is optimized for use by LLMs to understand the structure, APIs, and conventions of the WPT project.

---

## 1. Core Philosophy
*   **Be Short:** Tests should be as concise as possible. Avoid extraneous elements.
*   **Be Self-Contained:** No external network dependencies.
*   **Be Cross-Platform:** Work across devices, resolutions, and OSs.
*   **Be Conservative:** Avoid edge cases of features not being tested. Use standard features supported by major browsers (Chrome, Firefox, Safari).
*   **Be Self-Describing:** It should be obvious if a test passes or fails without reading the spec.

---

## 2. Test Types & File Naming
The file extension and name flags determine how the test is run.

### A. JavaScript Tests (`testharness.js`)
Used for testing APIs and logic.
*   `.any.js`: Runs in multiple globals (Window, Workers).
*   `.window.js`: Runs in a Window global.
*   `.worker.js`: Runs in a Dedicated Worker.
*   **Boilerplate:** For `.js` files, WPT generates the HTML. For `.html` files, you must include:
    ```html
    <script src="/resources/testharness.js"></script>
    <script src="/resources/testharnessreport.js"></script>
    ```

### B. Reftests (Rendering Tests)
Compares the rendering of two files.
*   **Structure:** A test file and a reference file.
*   **Link:** `<link rel="match" href="reference.html">` (or `rel="mismatch"`).
*   **Pass Condition:** Pixel-perfect match (800x600 viewport).

### C. Crashtests
Checks if a page crashes or leaks.
*   **Naming:** Ends in `-crash.html` or located in a `crashtests/` directory.
*   **Pass Condition:** Page loads and paints without crashing. No `testharness.js` required.

### D. Naming Conventions & Flags
*   **Format:** `{test-topic}-{index}.html` (e.g., `flexbox-layout-001.html`). Use descriptive names.
*   `.https.html`: Requires HTTPS.
*   `.h2.html`: Requires HTTP/2.
*   `.sub.html`: Enables server-side substitution.
*   `.tentative.html`: For experimental/non-standard features.
*   `.optional.html`: For optional spec features (RFC 2119 "MAY").

---

## 3. The `testharness.js` API

### Subtest Types
1.  **`test(fn, name)`**: For synchronous tests.
    ```javascript
    test(() => {
      assert_equals(1 + 1, 2);
    }, "Addition works");
    ```
2.  **`promise_test(fn, name)`**: For asynchronous code using Promises (preferred).
    ```javascript
    promise_test(async t => {
      const result = await fetch("/data");
      assert_true(result.ok);
    }, "Fetch works");
    ```
3.  **`async_test(fn, name)`**: For callback-based asynchronous code.
    ```javascript
    async_test(t => {
      document.onclick = t.step_func_done(e => {
        assert_true(e.isTrusted);
      });
    }, "Click is trusted");
    ```

### Key Assertions
*   `assert_equals(actual, expected, description)`
*   `assert_true(actual, description)`
*   `assert_throws_dom(type, fn, description)`: For DOMExceptions (e.g., "IndexSizeError").
*   `assert_throws_js(type, fn, description)`: For JS errors (e.g., `TypeError`).
*   `promise_rejects_dom(t, type, promise)`: For promises that should fail.

### Event Handling
Use `EventWatcher` for sequenced events:
```javascript
const watcher = new EventWatcher(t, element, ["start", "end"]);
await watcher.wait_for("start");
// ... action ...
await watcher.wait_for("end");
```

---

## 4. Metadata & Inclusion
### JavaScript Meta Tags
Use `// META` comments at the top of `.js` files:
*   `// META: title=Test Title`
*   `// META: script=/common/utils.js` (Include helper scripts)
*   `// META: global=window,worker` (Define execution scopes)

### HTML Metadata
*   `<link rel="help" href="https://spec.whatwg.org/#feature">`: Links to the specification.
*   `<meta name="timeout" content="long">`: For slow tests.

---

## 5. User Interaction (`testdriver.js`)
Always include both scripts. Use `test_driver` for actions requiring user activation or privileged access.
```html
<script src="/resources/testdriver.js"></script>
<script src="/resources/testdriver-vendor.js"></script>
```
Example:
```javascript
await test_driver.bless("permission request");
await test_driver.click(button);
```

---

## 6. Server-Side Features
### Substitution (`.sub.html`)
Use {% raw %}`{{host}}`, `{{ports[http][0]}}`, or `{{domains[www]}}`{% endraw %}.
### Pipes (`?pipe=...`)
*   `status(404)`: Return 404.
*   `header(Name, Value)`: Set response header.
*   `trickle(100:d1:r2)`: Send 100 bytes, delay 1s, repeat.

---

## 7. Rendering & SVG
### Ahem Font
Essential for predictable text rendering in reftests.
```html
<link rel="stylesheet" href="/fonts/ahem.css">
<style>
  .test { font: 20px/1 Ahem; color: green; }
</style>
```

### SVG Tests
SVG files are supported and can include `testharness.js` via `<h:script>`.
```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:h="http://www.w3.org/1999/xhtml">
  <h:script src="/resources/testharness.js"/>
  <h:script src="/resources/testharnessreport.js"/>
</svg>
```

---

## 8. Summary Checklist for LLM Generation
1.  **Type:** API (testharness), Rendering (reftest), or Crash?
2.  **Environment:** Window, Worker, or both (`.any.js`)?
3.  **Security:** Does it need `.https`?
4.  **Async:** Use `promise_test` and `add_cleanup`.
5.  **Aesthetics:** For reftests, use Ahem and 800x600 layout.
6.  **Spec Link:** Always include a `<link rel="help">`.

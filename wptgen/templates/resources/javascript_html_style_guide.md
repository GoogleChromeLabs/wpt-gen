# WPT JavaScript & HTML Test Best Practices

This guide provides a comprehensive overview of best practices for writing JavaScript and HTML tests in Web Platform Tests (WPT) using the `testharness.js` framework.

---

## 1. Introduction to `testharness.js`

`testharness.js` is the standard framework for testing APIs and logic in WPT. It provides a convenient API for making assertions and supports synchronous, asynchronous, and promise-based tests.

Each test document is considered a "test," and individual `test()`, `promise_test()`, or `async_test()` calls within it are referred to as "subtests."

---

## 2. Choosing a Test Format

WPT supports several ways to structure your tests. Prefer the simplest format that meets your needs.

### 2.1 JavaScript-Only Tests (Recommended)
These formats automatically generate the necessary HTML boilerplate, making tests cleaner and easier to maintain.

*   **`.window.js`**: Runs in a standard Window environment.
*   **`.worker.js`**: Runs in a Dedicated Worker.
*   **`.any.js`**: Runs in multiple global scopes (default: Window and Dedicated Worker). You can customize this using metadata.

**Example (`example.window.js`):**
```javascript
test(() => {
  assert_true(true);
}, "A simple window test");
```

### 2.2 HTML Tests
Use this format if you need specific HTML structure (e.g., custom DOM elements) or if the test is complex.

**Example (`example.html`):**
```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>Example Test</title>
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<script>
test(() => {
  assert_equals(document.title, "Example Test");
}, "Check document title");
</script>
```

---

## 3. Metadata and File Naming

Metadata and file names communicate critical information to the WPT server and runners.

### 3.1 File Name Flags
*   `.https`: Loads the test over HTTPS.
*   `.h2`: Loads the test over HTTP/2.
*   `.sub`: Enables server-side substitution (e.g., using `{{host}}`).
*   `.tentative`: Indicates the test is for a feature still under discussion or not yet standardized.

### 3.2 `// META` Comments (for `.js` files)
*   `// META: title=Test Title`: Sets the document title.
*   `// META: script=/common/utils.js`: Includes external scripts.
*   `// META: global=window,worker`: Specifies which globals to run in (for `.any.js`).
*   `// META: timeout=long`: Increases the test timeout (standard is 10s, long is 60s).
*   `// META: variant=?wss`: Defines test variants.

---

## 4. Defining Tests

### 4.1 Synchronous Tests (`test`)
Use for logic that completes immediately.
```javascript
test(() => {
  const result = 1 + 1;
  assert_equals(result, 2);
}, "Simple addition test");
```

### 4.2 Promise-Based Tests (`promise_test`) - **Preferred**
Use for asynchronous logic. Returning a promise allows the harness to manage the test lifecycle automatically.
```javascript
promise_test(async t => {
  const response = await fetch("data.json");
  assert_true(response.ok);
}, "Fetch data test");
```

### 4.3 Asynchronous Tests (`async_test`)
Use for callback-based APIs. You must manually manage `step`, `done`, and `step_func`.
```javascript
async_test(t => {
  document.addEventListener("DOMContentLoaded", t.step_func_done(e => {
    assert_true(e.bubbles);
  }));
}, "DOMContentLoaded event");
```

---

## 5. Assertions and Exception Testing

### 5.1 Common Assertions
*   `assert_equals(actual, expected, message)`: Check for equality.
*   `assert_true(actual, message)` / `assert_false(actual, message)`: Check boolean values.
*   `assert_unreached(message)`: Fail if this point is reached.

### 5.2 Testing for Exceptions
*   **Synchronous**: `assert_throws_js(ErrorType, () => { ... })` or `assert_throws_dom("IndexSizeError", () => { ... })`.
*   **Promises**: `promise_rejects_js(t, ErrorType, promise)` or `promise_rejects_dom(t, "NetworkError", promise)`.

---

## 6. Core Best Practices

### 6.1 State Cleanup
Always clean up global state (DOM, cookies, storage) to ensure test independence. Use `add_cleanup()`.
```javascript
promise_test(async t => {
  const el = document.createElement("div");
  document.body.appendChild(el);
  t.add_cleanup(() => el.remove());

  assert_true(document.body.contains(el));
}, "DOM cleanup example");
```

### 6.2 Avoid Timers
Never use `setTimeout` with a hardcoded delay to "wait" for something.
*   **Wait for an event**: Use `EventWatcher` or a Promise.
*   **Check a condition**: Use `t.step_wait(() => condition)`.
*   **Necessary delays**: Use `t.step_timeout(callback, delay)`.

### 6.3 Cross-Platform & Conservative
*   **UTF-8**: Always use UTF-8 (and `<meta charset=utf-8>` in HTML).
*   **Independence**: Tests should not rely on external network resources or specific fonts (use [Ahem](/docs/writing-tests/ahem.md) for font testing).
*   **Short & Focused**: Keep tests as concise as possible. Avoid testing unrelated features.

---

## 7. Automation with `testdriver.js`

For actions that cannot be performed via standard APIs (e.g., mouse clicks, key presses, permissions), use `test_driver`.

**Setup (HTML):**
```html
<script src="/resources/testdriver.js"></script>
<script src="/resources/testdriver-vendor.js"></script>
```

**Example:**
```javascript
promise_test(async t => {
  const button = document.getElementById("myButton");
  await test_driver.click(button);
  // Verify click result
}, "User click automation");
```

---

## 8. IDL Testing with `idlharness.js`

For testing Web IDL interfaces, use `idlharness.js`. This ensures that your implementation matches the specification's IDL (attributes, methods, types, etc.).

**Example (`idlharness.window.js`):**
```javascript
// META: script=/resources/WebIDLParser.js
// META: script=/resources/idlharness.js

idl_test(
  ['my-spec'],
  ['dom', 'html'], // dependencies
  idl_array => {
    idl_array.add_objects({
      MyInterface: ['new MyInterface()']
    });
  }
);
```

---

## 9. Advanced Server Features

WPT's server (`wptserve`) provides powerful features for tests that need more than static files.

### 9.1 Server-Side Substitution (`.sub`)
Use `.sub` in the filename to use `{{ }}` placeholders.
*   `{{host}}`: The main host.
*   `{{hosts[alt][www]}}`: Cross-origin host.
*   `{{ports[http][0]}}`: The first HTTP port.

### 9.2 Custom Headers (`.headers`)
Create a file with the same name as your test but ending in `.headers` to specify custom HTTP headers.
```text
Content-Type: text/html; charset=big5
Cache-Control: no-cache
```

### 9.3 Static Responses (`.asis`)
Use `.asis` files for byte-for-byte literal HTTP responses (including status line and headers). This is useful for testing invalid or edge-case HTTP responses.

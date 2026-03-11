This guide provides a comprehensive overview of best practices for writing JavaScript and HTML tests in Web Platform Tests (WPT) using the `testharness.js` framework.

---

## 1. Introduction to `testharness.js`

`testharness.js` is the standard framework for testing APIs and logic in WPT. It provides a convenient API for making assertions and supports synchronous, asynchronous, and promise-based tests.

Each test document is considered a "test," and individual `test()`, `promise_test()`, or `async_test()` calls within it are referred to as "subtests."

---

## 2. Choosing a Test Format and Boilerplate (CRITICAL)

WPT supports several ways to structure your tests. Prefer the simplest format that meets your needs. **When writing tests, the file format dictates how `testharness.js` must be imported.**

### 2.1 JavaScript-Only Tests (Recommended)
These formats **automatically generate** the necessary HTML boilerplate.

*   **`.window.js`**: Runs in a standard Window environment.
*   **`.worker.js`**: Runs in a Dedicated Worker.
*   **`.any.js`**: Runs in multiple global scopes (default: Window and Dedicated Worker). You can customize this using metadata.
*   **`.extension.js`**: Runs as a Web Extension using the `browser.test` API.

**IMPORTANT BOILERPLATE RULES FOR JS-ONLY TESTS:**
*   **DO NOT** manually include or import `testharness.js` or `testharnessreport.js` for `.window.js`, `.any.js`, or `.extension.js` files. The `wptserve` server automatically generates the HTML wrapper (e.g., `.window.html`) and injects these scripts.
*   *Worker Exception:* A `.worker.js` script natively requires `importScripts("/resources/testharness.js");` at the top and a call to `done();` at the end (though an effort to remove this requirement is ongoing). Note that `.any.js` tests running in a worker context automatically handle the `done()` call.
*   If you only need to test a single thing without a `test()` wrapper in `.window.js`, use: `setup({ single_test: true }); ... done();` with `// META: title=Your Test Title` at the top of the file.

**Example (`example.window.js`):**
```javascript
// META: title=A simple window test
test(() => {
  assert_true(true);
}, "A simple window test");
```

### 2.2 HTML Tests
Use this format if you need specific HTML structure (e.g., custom DOM elements) or if the test is complex.

**IMPORTANT BOILERPLATE RULES FOR HTML TESTS:**
*   You **MUST** explicitly include both `testharness.js` and `testharnessreport.js` in your HTML document.
*   Always include `<meta charset="utf-8">` and a `<title>` for the test.

**Example (`example.html`):**
```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>Example Test</title>
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<body>
  <script>
    test(() => {
      assert_equals(document.title, "Example Test");
    }, "Check document title");
  </script>
</body>
```

**Single Page HTML Test Example:**
If the test logic is straightforward and a wrapper isn't needed, you can use `single_test` mode. The title of the test will be taken from the `<title>` element.
```html
<!DOCTYPE html>
<meta charset="utf-8">
<title>Ensure single test works</title>
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<body>
  <script>
    setup({ single_test: true });
    assert_equals(document.characterSet, "UTF-8");
    done();
  </script>
</body>
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

**Important Rules for Promise Tests:**
*   **Sequential Execution:** Unlike asynchronous tests, `testharness.js` queues promise tests so the next test won't start until the previous one finishes.
*   **Do Not Mix with Async Steps:** Avoid mixing `promise_test` logic with callback functions like `t.step_func()`. This produces confusing tests and can cause the next test to begin before the promise settles. Wrap asynchronous behaviors into the promise chain instead.

### 4.3 Asynchronous Tests (`async_test`)
Use for callback-based APIs. You must manually manage `step`, `done`, and `step_func`.
```javascript
async_test(t => {
  document.addEventListener("DOMContentLoaded", t.step_func_done(e => {
    assert_true(e.bubbles);
  }));
}, "DOMContentLoaded event");
```

**Important Rules for Async Tests:**
*   **Concurrency:** `testharness.js` doesn't impose scheduling on async tests; they run whenever step functions are invoked. Multiple tests in the same global can run concurrently. Take care not to let them interfere with each other.
*   **Unreached Code:** For asynchronous callbacks that should never execute, use `t.unreached_func("Reason")`.

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
Always clean up global state (DOM, cookies, storage) to ensure test independence. Use `add_cleanup()`. If the test was created using `promise_test`, cleanup functions may optionally return a Promise to delay the completion of the test until the cleanup promise settles.
```javascript
promise_test(async t => {
  const el = document.createElement("div");
  document.body.appendChild(el);
  t.add_cleanup(() => el.remove());

  assert_true(document.body.contains(el));
}, "DOM cleanup example");
```

### 6.2 Avoid Timers
**DO NOT** use `setTimeout` with a hardcoded delay to "wait" for something.
*   **Wait for an event**: Use `EventWatcher` or a Promise.
*   **Check a condition**: Use `t.step_wait(() => condition)`.
*   **Necessary delays**: Use `t.step_timeout(callback, delay)`.

### 6.3 Cross-Platform & Conservative
*   **UTF-8**: Always use UTF-8 (and `<meta charset=utf-8>` in HTML).
*   **Independence**: Tests should not rely on external network resources or specific fonts (use [Ahem](/docs/writing-tests/ahem.md) for font testing).
*   **Short & Focused**: Keep tests as concise as possible. Avoid testing unrelated features.


### 6.4 AbortSignal Support
Use `t.get_signal()` to get an `AbortSignal` that is automatically aborted when the test finishes. This is highly recommended when testing APIs that support `AbortSignal` to automatically clean up event listeners or fetch requests.
```javascript
promise_test(async t => {
  const signal = t.get_signal();
  document.body.addEventListener('click', () => {}, { once: true, signal });
}, 'AbortSignal example');
```

### 6.5 Fetching JSON Data
Use the helper `fetch_json('data.json')` instead of `fetch('data.json').then(r => r.json())`. This ensures compatibility with environments where `fetch()` is not exposed, such as `ShadowRealm`.

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

---

## 10. Testing Across Globals

You can consolidate tests from other documents or Web Workers into your main test document.

### 10.1 Consolidating from other documents
Use `fetch_tests_from_window(child_window)` to run tests in a child window or iframe and report them in the current context.

### 10.2 Web Workers
Use `fetch_tests_from_worker(worker)` to fetch test results from a worker. This function returns a promise that resolves once all remote tests have completed.

```javascript
(async function() {
  await fetch_tests_from_worker(new Worker("worker-1.js"));
  await fetch_tests_from_worker(new Worker("worker-2.js"));
})();
```

**Worker Testing Quirks:**
*   Workers rely on the client HTML document for reporting.
*   The client document controls the test timeout.
*   Dedicated and shared workers behave as if the `explicit_done` setup option is true, meaning `done()` must be called in the worker script to indicate completion (except for Service Workers which rely on the `install` event).

---

## 11. Harness Configuration (`setup()`)

The `setup(options)` or `promise_setup(func)` functions configure the global test harness.

**Common Options:**
*   `explicit_done`: Wait for a manual call to `done()` before declaring all tests complete.
*   `single_test`: Enables Single Page Test mode.
*   `allow_uncaught_exception`: Disables treating uncaught exceptions as errors (useful when testing `window.onerror`).
*   `hide_test_state`: Hides the test state UI during execution to prevent interference with visual tests.

**Managing Timeouts Manually:**
If a test has a race condition between the harness timing out and the test failing (e.g., waiting for an event that never occurs), you can use `t.force_timeout()` instead of `assert_unreached()`. This immediately fails the test with a status of `TIMEOUT` and should only be used as a last resort.

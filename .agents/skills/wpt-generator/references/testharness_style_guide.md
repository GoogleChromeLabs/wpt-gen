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

**CRITICAL MANDATE:** You **MUST** default to creating a `.window.js`, `.any.js`, or `.worker.js` file and use dynamic DOM generation (via `document.createElement()`) rather than creating an `.html` file, **UNLESS** you are creating a test within the `css/` directory. The CSS build tool (`test.csswg.org`) does not support `wptserve` automatic boilerplate generation or `.window.js` files, and requires a `<link rel="help">` tag. Therefore, for all CSS tests, you must stick with the `.html` equivalent.

*   **`.window.js`**: Runs in a standard Window environment.
*   **`.worker.js`**: Runs in a Dedicated Worker.
*   **`.any.js`**: Runs the same test code in multiple execution scopes. By default, it runs in `window` and `dedicatedworker` contexts. You can extensively customize this using the `// META: global=` header. For example: `// META: global=window,worker,serviceworker,sharedworker,shadowrealm-in-window`. A massive advantage of using `.any.js` (the multi-global pattern) over `.worker.js` is that the harness automatically handles `done()` calls across all worker scopes, eliminating boilerplate.
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
*   `-manual`: Indicates the test requires manual user interaction and should not be run in an automated runner without specific configuration. Must appear right before the extension.
*   `.tentative`: Indicates the test is for a feature still under discussion or not yet standardized.

### 3.2 `// META` Comments and Spec Links (for `.js` files)
*   `// META: title=Test Title`: Sets the document title.
*   **Spec URLs:** To include a specification link in a `.js` test (like `.window.js` or `.any.js`), you MUST use a standard JavaScript comment, e.g., `// https://spec.url/path`.
    *   **CRITICAL RULE:** Do NOT attempt to use `// META: help=...`. The `help` metadata tag is illegal and unsupported by `wptserve` for `.js` files, and it will trigger an `UNKNOWN-METADATA` linter error. Use `// https://...` instead.
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
});
```

### 4.3 Assertion Minimalism and Strictness (CRITICAL)
WPT's `assert_true(actual)` and `assert_false(actual)` perform **strict equality checks** (`actual === true` and `actual === false`).

Because of this strictness, you **MUST NOT** write redundant `typeof` or existence assertions if you are immediately going to assert the boolean value itself.

**Incorrect (Redundant):**
```javascript
const myObj = { is_active: false };
assert_true(!!myObj, "Object exists"); // Redundant if checking properties
assert_own_property(myObj, 'is_active');
assert_equals(typeof myObj.is_active, 'boolean'); // Redundant! assert_false already enforces this.
assert_false(myObj.is_active);
```

**Correct (Minimal & Strict):**
```javascript
const myObj = { is_active: false };
assert_own_property(myObj, 'is_active');
// Implicitly verifies both the type (boolean) AND the value (false) in one strict check.
assert_false(myObj.is_active);
```

**Important Rules for Promise Tests:**
*   **Sequential Execution:** Unlike asynchronous tests, `testharness.js` queues promise tests so the next test won't start until the previous one finishes.
*   **Do Not Mix with Async Steps:** Avoid mixing `promise_test` logic with callback functions like `t.step_func()`. This produces confusing tests and can cause the next test to begin before the promise settles. Wrap asynchronous behaviors into the promise chain instead.

### 4.4 Asynchronous Tests (`async_test`)
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

### 4.5 Data-Driven Testing (Parameterization)
When testing multiple permutations of an API (e.g., testing different method signatures like an object vs. an initializer dictionary, testing combinations of options, or iterating over a list of valid/invalid inputs), it is recommended to use a **data-driven approach**.

Define an array of test cases (`const testCases = [...]`) and iterate over them using a loop (e.g., `for (const { ... } of testCases)`) to dynamically generate the `test()` or `promise_test()` blocks. This removes redundant JavaScript boilerplate, ensures consistent coverage across all permutations (e.g., testing both `AbortError` and a custom error for every scenario), and makes the test ecosystem scalable and maintainable. However, do not over-engineer loops for simple, one-off behaviors that don't share setup logic.

*(Note: There is a strictly enforced exception to this rule for CSS parsing tests. See [css_testcommon.md](domain_helpers/css_testcommon.md) for details).*

#### 4.5.1 Modifying Existing Files (Matrix Expansion)
When adding a new test case to an *existing* file that already employs a data-driven loop, you **MUST NOT** append new standalone `test()` blocks or create a second loop at the bottom of the file. You must analyze the existing data structure (e.g., `const testCases = [...]`) and inject your new test case into that array. This prevents redundant setup/teardown execution and often provides "free" coverage by running your new input against multiple existing configurations (like different environments or states) established by the existing matrix.

**Example of Parameterization:**
```javascript
const customError = new Error('custom');
const testCases = [
  { desc: 'Request object', getArgs: (signal) => [new Request('/', { signal })] },
  { desc: 'URL and init object', getArgs: (signal) => ['/', { signal }] }
];

for (const { desc, getArgs } of testCases) {
  test(() => {
    const controller = new AbortController();
    controller.abort(customError);
    assert_throws_exactly(customError, () => myApi(...getArgs(controller.signal)));
  }, `myApi() throws custom reason when called with aborted ${desc}`);

  test(() => {
    const controller = new AbortController();
    controller.abort();
    assert_throws_dom("AbortError", () => myApi(...getArgs(controller.signal)));
  }, `myApi() throws AbortError when called with aborted ${desc} without specific reason`);
}
```

---

## 5. Assertions and Exception Testing

### 5.1 Common Assertions
*   `assert_equals(actual, expected, message)`: Check for equality.
*   `assert_true(actual, message)` / `assert_false(actual, message)`: Check boolean values.
*   `assert_unreached(message)`: Fail if this point is reached.

#### 5.1.1 Advanced Assertions (CRITICAL MANDATE)
You **MUST** use precise, specialized assertions rather than writing manual JavaScript logic or conditionals evaluated by a generic `assert_true` or `assert_false`. Precise assertions provide significantly better failure messages in the test runner, pinpointing the exact missing key or mismatched value rather than a generic "expected true got false".

Before writing a custom conditional, you MUST use the following built-in helpers if applicable:
*   **Property Existence:** Use `assert_own_property(object, property_name, message)` or `assert_inherits(object, property_name, message)` instead of `assert_true('prop' in obj)`.
*   **Array Inclusion:** Use `assert_in_array(actual, expected_array, message)` instead of `assert_true(array.includes(val))`.
*   **Type Checking:** Use `assert_class_string(object, class_name, message)` (e.g., checking `[object Array]`) instead of manual `typeof` or `instanceof` checks where appropriate.
*   **IDL Attributes:** When writing IDL API tests, you MUST use `assert_readonly(object, property_name)` to test `readonly` attributes, and `assert_idl_attribute(object, property_name)` to ensure the attribute exists on the prototype chain.
*   **Boolean Collapse Anti-Pattern:** Do not evaluate a condition to a boolean and assert against that (e.g., `const isValid = val !== ""; assert_equals(isValid, true);`). This destroys diagnostic output on failure. You MUST assert the raw values directly (e.g., `assert_not_equals(val, "");` for valid cases and `assert_equals(val, "");` for invalid cases).

If your use case is not listed here, you MUST read or `grep` through the `resources/testharness.js` file for built-in `assert_*` methods that simplify your boilerplate before falling back to `assert_true`.

### 5.2 Testing for Exceptions
*   **Synchronous**: `assert_throws_js(ErrorType, () => { ... })` or `assert_throws_dom("IndexSizeError", () => { ... })`.
*   **Promises**: `promise_rejects_js(t, ErrorType, promise)` or `promise_rejects_dom(t, "NetworkError", promise)`.
*   **Exact Object Instances**: Use `assert_throws_exactly(exception, () => { ... })` or `promise_rejects_exactly(t, exception, promise)` when verifying that the exact same exception object instance is thrown, rather than just matching the type or name.

### 5.3 Asynchronous Negative Assertions (Sentinel Pattern)
When testing that an asynchronous event (like a network request, a fired event, or a DOM mutation) did *not* occur, **DO NOT** use unbounded polling for a negative state (e.g., polling until a timeout to prove an array length is `0`). This forces the test runner to wait for the maximum timeout, artificially inflating test suite execution time.

Instead, you **MUST** use the **Sentinel Pattern** (a positive control):
1. Perform the action that should *not* cause the side-effect.
2. Immediately perform a secondary, guaranteed-to-succeed action (the "sentinel") that triggers the same tracker.
3. Assert that the tracker receives *exactly* the expected state from the sentinel action alone.

This guarantees instant test success if the negative condition holds, and instant failure if the forbidden side-effect incorrectly occurs.

**Example (Network Request):**
```javascript
// BAD: Polling for 0 forces a 3+ second timeout on success.
controller.abort();
await expectBeacon(uuid, { count: 0 });

// GOOD: Sentinel pattern returns instantly on success.
controller.abort();
// 1. Fire a sentinel request that we know will succeed.
fetchLater(url, { method: 'POST' });
// 2. We now expect EXACTLY 1 beacon (the sentinel) to arrive.
await expectBeacon(uuid, { count: 1 });
```

### 5.4 Modern JavaScript for Assertions
When validating conditions against arrays, collections, or object properties, you **MUST NOT** blindly copy verbose boilerplate from older "Golden Examples". Specifically:
1. **Array Iteration:** Do not use manual `for...of` loops with internal boolean flags or redundant `assert_equals` checks. Use modern, concise JavaScript array methods (`Array.prototype.some()`, `Array.prototype.every()`, `Array.prototype.find()`, `Array.prototype.forEach()`) combined with a single assertion.
2. **Property Checking:** Do not use verbose inequality checks like `if (obj.property !== undefined)` to test for property existence or to handle optional/omitted fields. You MUST use the idiomatic `in` operator (`if ('property' in obj)`).
3. **Redundant Assertions:** Do not add filler assertions (like `assert_true(array.length > 0)`) simply to register a `testharness.js` assertion if the surrounding test flow (e.g., a promise resolving only when an array is populated) already guarantees that condition.

**Example (BAD - Verbose, Redundant, Legacy Style):**
```javascript
let found = false;
for (const report of reports) {
  if (report.body && report.body.reason !== undefined) {
    found = true;
    assert_true(['oom', 'unresponsive'].includes(report.body.reason));
  }
}
assert_true(found, "Crash report was delivered.");
```

**Example (GOOD - Concise, Modern):**
```javascript
reports.filter(r => r.type === 'crash').forEach(r => {
  if ('reason' in r.body) {
    assert_in_array(r.body.reason, ['oom', 'unresponsive']);
  }
});
// (Assuming the caller already awaited the existence of a crash report)
```

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

### 6.2 Pre-conditions and Scaffolding
Avoid writing redundant static HTML scaffolding (e.g., `<div id="container"></div>`) directly into the `<body>` of HTML test files just to satisfy general preconditions. Do not blindly copy such legacy scaffolding from older "Golden Examples".
*   **Prefer Dynamic Setup:** Dynamically generate necessary elements within the JavaScript test loop (`document.createElement()`), append them to `document.body`, and clean them up afterward.
*   **Inline Data:** Map arrays or test scenarios inline to avoid polluting the global scope with intermediate variables.
*   **Exception:** Only use static HTML structures if the exact feature being tested requires a strict DOM configuration to be parsed natively by the browser prior to script execution.

### 6.3 Avoid Timers & Wait for Events
**DO NOT** use `setTimeout` with a hardcoded delay to "wait" for something.

**EventWatcher:** The best and least bug-prone way to wait for a sequence of events is the built-in `EventWatcher` class. It simplifies listening for single or multiple events and handles cleanup automatically.
```javascript
promise_test(async t => {
  const watcher = new EventWatcher(t, document, ['DOMContentLoaded', 'load']);
  await watcher.wait_for(['DOMContentLoaded', 'load']); // Waits for both in sequence
  assert_true(true);
}, "EventWatcher example");
```
*   **Check a condition**: Use `t.step_wait(() => condition)`.
*   **Necessary delays**: Use `t.step_timeout(callback, delay)`.

### 6.4 Cross-Platform & Conservative
*   **UTF-8**: Always use UTF-8 (and `<meta charset=utf-8>` in HTML).
*   **Independence**: Tests should not rely on external network resources or specific fonts (use [Ahem](/docs/writing-tests/ahem.md) for font testing).
*   **Short & Focused**: Keep tests as concise as possible. Avoid testing unrelated features.


### 6.5 AbortSignal Support
Use `t.get_signal()` to get an `AbortSignal` that is automatically aborted when the test finishes. This is highly recommended when testing APIs that support `AbortSignal` to automatically clean up event listeners or fetch requests.
```javascript
promise_test(async t => {
  const signal = t.get_signal();
  document.body.addEventListener('click', () => {}, { once: true, signal });
}, 'AbortSignal example');
```

**Pre-aborted Signals:** When a test requires providing an already-aborted signal or a signal that aborts after a specific duration, you **MUST** use the static `AbortSignal.abort(reason)` or `AbortSignal.timeout(ms)` methods. **DO NOT** manually instantiate an `AbortController` just to abort it.

**Example (BAD - Legacy):**
```javascript
const controller = new AbortController();
controller.abort(customReason);
doSomething({ signal: controller.signal });
```

**Example (GOOD - Modern):**
```javascript
doSomething({ signal: AbortSignal.abort(customReason) });
```

### 6.6 Fetching JSON Data
Use the helper `fetch_json('data.json')` instead of `fetch('data.json').then(r => r.json())`. This ensures compatibility with environments where `fetch()` is not exposed, such as `ShadowRealm`.

### 6.7 File Organization & Splitting (Valid vs. Invalid)
When generating or appending to tests—especially for CSS parsing or API validation—observe the directory's existing paradigm. It is extremely common in WPT to separate tests for **valid** inputs from tests for **invalid** inputs into distinct files (e.g., `property-valid.html` and `property-invalid.html`).
*   **Do not create a new monolithic file** with redundant boilerplate if you can logically split your test assertions and append them to these existing category files.
*   **Split your logic:** If a single requirement dictates both valid and invalid behaviors, put the `test_valid_value` (or equivalent) assertions in the valid file, and the `test_invalid_value` assertions in the invalid file.

### 6.8 Interacting Features & Support Libraries
Web platform features do not exist in isolation. Many directories contain canonical support libraries intended to decouple tests from the specifics of another feature. Before writing manual integration logic from scratch, check for these standard libraries:
*   **Cookies:** `cookies/resources/` (scripts to control cookies set on a request)
*   **Permissions Policy:** `permissions-policy.js`
*   **Reporting API:** `reporting/resources/` (common report collector service)

---

## 7. Automation & Manual Tests

If your test requires user interaction (clicks, key presses, permission dialogs) or complex browser state manipulation (window resizing, cookies), you **MUST NOT** use manual tests simply because it's difficult. Instead, you must automate the interaction using `test_driver`.

*   **For comprehensive instructions on setting up and configuring `testdriver.js`, you MUST refer to the [automation_guide.md](automation_guide.md).**
*   If (and only if) the test strictly requires a human operator (e.g., unplugging a monitor), see **[manual_test_style_guide.md](manual_test_style_guide.md)**.

---

## 8. IDL Testing with `idlharness.js`

For testing Web IDL interfaces (e.g., interface exposure, presence of attributes, existence of methods), you **MUST NOT** use manual boolean assertions (like `assert_true('MyInterface' in window)`).

Instead, you **MUST** use `idlharness.js`. This ensures that your implementation precisely matches the specification's IDL (attributes, methods, types, inheritance, etc.). Before writing an API exposure test, check the repository's `interfaces/` directory for a corresponding `.idl` file (e.g., `interfaces/my-spec.idl`).

**For comprehensive instructions on setting up and configuring `idlharness.js`, you MUST refer to the [idlharness_guide.md](idlharness_guide.md).**

**Brief Example (`idlharness.window.js`):**
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

WPT's server (`wptserve`) provides powerful features for tests that need more than static files (e.g., cross-origin requests, custom HTTP headers, specific status codes, or dynamic server logic via Python handlers).

**For comprehensive instructions on setting up and configuring advanced server features, including `?pipe=` commands, `.sub` templates, and `.py` handlers, you MUST refer to the [server_features_guide.md](server_features_guide.md).**

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

### 10.3 Message Channels (`channels.sub.js`)

When you need to communicate between globals that do not have a client-side mechanism to establish a channel (e.g., globals in different browsing context groups like in `rel="noopener"` or COOP/COEP tests), you **MUST** use the WPT Message Channels API instead of `postMessage`.

**Setup:** Include the script in both the test document and the remote document:
```html
<script src="/resources/channels.sub.js"></script>
```

**Usage Example:**
*Main Document:*
```javascript
promise_test(async t => {
  let remote = new RemoteGlobal();
  window.open(`child.html?uuid=${remote.uuid}`, "_blank", "noopener");
  let result = await remote.call(id => {
    return document.getElementById(id).textContent;
  }, "test-element-id");
  assert_equals(result, "PASS");
});
```

*Child Document (`child.html`):*
```html
<!doctype html>
<script src="/resources/channels.sub.js"></script>
<p id="test-element-id">PASS</p>
<script>
  // Initializes the channel using the uuid from the query parameter
  start_global_channel();
</script>
```

---

## 11. Harness Configuration (`setup()`)

The `setup(options)` or `promise_setup(func)` functions configure the global test harness.

**Common Options:**
*   `explicit_done`: Wait for a manual call to `done()` before declaring all tests complete.
*   `explicit_timeout`: Disable the test runner timeout (essential for `-manual` tests).
*   `single_test`: Enables Single Page Test mode.
*   `allow_uncaught_exception`: Disables treating uncaught exceptions as errors (useful when testing `window.onerror`).
*   `hide_test_state`: Hides the test state UI during execution to prevent interference with visual tests.

**Managing Timeouts Manually:**
If a test has a race condition between the harness timing out and the test failing (e.g., waiting for an event that never occurs), you can use `t.force_timeout()` instead of `assert_unreached()`. This immediately fails the test with a status of `TIMEOUT` and should only be used as a last resort.

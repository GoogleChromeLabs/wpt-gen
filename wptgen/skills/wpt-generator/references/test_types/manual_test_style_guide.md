# Manual Test Style Guide

Manual tests are a **LAST RESORT** for testing scenarios that are intrinsically difficult to automate and strictly require a human to run the test and check the pass condition.

**Common use cases:**
* Tests requiring physical interaction with a device (e.g., plugging in a monitor, disconnecting a network cable).
* Observing an OS-level UI dialog (e.g., printing dialogs, file picker UI behavior).
* Observing complex visual animations or video playback that cannot be verified via automated screenshots.

## 1. File Naming (CRITICAL)

Manual tests **must** have filenames ending in `-manual` immediately before the extension. This tells the WPT runners to skip the test in automated CI environments.
* **Correct:** `print-dialog-manual.html`
* **Correct:** `drag-drop-desktop-manual.https.html`
* **Incorrect:** `manual-print-dialog.html` (The suffix must be `-manual`)

## 2. Self-Describing UI and Tester UX (CRITICAL)

Manual tests must be fully self-describing. You cannot rely on an automated runner to determine the outcome.
* Provide clear, step-by-step instructions on the page for the human tester.
* Provide a clear statement of exactly how the human tester should determine the outcome (PASS/FAIL).

**Tester UX and OS Visibility:**
When a manual test requires the human tester to identify a specific window, popup, or iframe outside of the browser's main document (e.g., using an OS task manager to forcefully crash a process, or interacting with OS-level UI), you **MUST** ensure the target is easily identifiable. 
*   **Window Titles:** Any spawned popup windows or top-level frames MUST have a clearly defined `<title>` tag (e.g., `<title>Crash me!</title>`). If the window has no title, task managers often display a convoluted URL or query string, drastically increasing tester fatigue.
*   **Distinctive Characteristics:** If spawning multiple targets, give them visually distinct characteristics or explicit titles so the human operator knows exactly which one to interact with.

## 3. Using `testharness.js` for Manual Tests

The most robust way to write a manual test is to use `testharness.js` to report the result *after* the manual setup steps are completed by the human operator.

If you use `testharness.js` in a manual test, you **MUST** pass `{explicit_timeout: true}` to the `setup()` function. This disables the automatic 10-second test runner timeout, giving the human operator as much time as they need to perform the steps.

```html
<!doctype html>
<meta charset="utf-8">
<title>Manual Test: Fullscreen</title>
<link rel="author" title="Your Name" href="mailto:your-email@example.com">
<link rel="help" href="https://fullscreen.spec.whatwg.org/">
<meta name="assert" content="Clicking the button puts the element in fullscreen mode.">

<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>

<style>
  #target { width: 100px; height: 100px; background: blue; }
  :fullscreen { background: green; }
</style>

<h1>Test Instructions</h1>
<p>1. Click the "Enter Fullscreen" button below.</p>
<p>2. If the blue square becomes green and fills the screen, click "Pass". If not, click "Fail".</p>

<div id="target"></div>
<button id="start-btn">Enter Fullscreen</button>
<button id="pass-btn">Pass</button>
<button id="fail-btn">Fail</button>

<script>
setup({explicit_timeout: true});

const test = async_test("Manual fullscreen check");

document.getElementById('start-btn').onclick = () => {
  document.getElementById('target').requestFullscreen();
};

document.getElementById('pass-btn').onclick = () => {
  test.step(() => assert_true(true)); // Test passed!
  test.done();
};

document.getElementById('fail-btn').onclick = () => {
  test.step(() => assert_unreached("The element did not enter fullscreen correctly."));
  test.done();
};
</script>
```
# Automation Guide (`testdriver.js`)

For tests requiring user interaction (clicks, key presses, permissions, etc.) that cannot be triggered via standard DOM APIs, you MUST use `testdriver.js`. This is supported by JS tests, reftests, and crashtests.

**CRITICAL RULE:** Do NOT use `testdriver.js` if you are writing a `-manual` test designed for a human operator. Automation is specifically for allowing automated test runners to simulate human actions.

## 1. Setup

You must include the following scripts in your HTML file before your test logic:

```html
<script src="/resources/testdriver.js"></script>
<script src="/resources/testdriver-vendor.js"></script>
```

## 2. Usage Examples

Because `test_driver` methods simulate complex asynchronous operations, they return Promises. You must `await` them inside a `promise_test` or an async function.

### Simulating a Click
```javascript
promise_test(async t => {
  const button = document.getElementById("target");
  await test_driver.click(button);
  // Verify click result
}, "User click automation");
```

### Simulating Key Presses
```javascript
promise_test(async t => {
  const input = document.getElementById("myInput");
  await test_driver.send_keys(input, "hello");
  assert_equals(input.value, "hello");
}, "User typing automation");
```

### Complex Action Sequences (Drag & Drop, Hover)
For more complex pointer actions, you must include `testdriver-actions.js`:
```html
<script src="/resources/testdriver-actions.js"></script>
```

```javascript
promise_test(async t => {
  const actions = new test_driver.Actions()
    .pointerMove(0, 0, {origin: element})
    .pointerDown()
    .pointerMove(100, 100)
    .pointerUp();
  await actions.send();
}, "Drag and drop automation");
```

## 3. Bless (Transient Activation)
Some APIs (like `window.open` or playing audio) require a user gesture (Transient Activation). Instead of simulating a full click, you can use `test_driver.bless()` to grant the window transient activation directly.

```javascript
promise_test(async t => {
  await test_driver.bless("Open a popup", () => {
    window.open("popup.html");
  });
}, "Bypass popup blocker");
```

## 4. Extended Capabilities

`testdriver.js` supports a broad API surface for automating complex interactions and browser states. You MUST use these instead of resorting to manual tests.

### Cookies & Permissions
```javascript
promise_test(async t => {
  await test_driver.delete_all_cookies();
  await test_driver.set_permission({ name: "background-fetch" }, "denied");
  const cookie = await test_driver.get_named_cookie("my_cookie");
}, "Permissions and cookies");
```

### Window State
```javascript
promise_test(async t => {
  await test_driver.minimize_window();
  await test_driver.set_window_rect(100, 100, 800, 600);
}, "Window manipulation");
```

### WebDriver BiDi Support
To use WebDriver BiDi, you must enable the `bidi` feature in `testdriver.js` by adding the `feature=bidi` query string parameter:
```html
<script src="/resources/testdriver.js?feature=bidi"></script>
```
For `.js` tests: `// META: script=/resources/testdriver.js?feature=bidi`

You can then access the BiDi API via `test_driver.bidi`. For example, listening to logs:
```javascript
await test_driver.bidi.log.entry_added.subscribe();
const log_entry_promise = test_driver.bidi.log.entry_added.once();
console.log("some message");
const event = await log_entry_promise;
```

### Emulation & Hardware
`test_driver` provides extensive emulation capabilities, including:
*   **Virtual Authenticators:** `test_driver.add_virtual_authenticator(...)`
*   **Sensors:** `test_driver.create_virtual_sensor(...)`
*   **Compute Pressure & Device Posture:** `test_driver.create_virtual_pressure_source(...)`, `test_driver.set_device_posture(...)`

### Cross-Context Execution
For tests involving popups or iframes, you can target actions at specific contexts. For same-origin, pass the `WindowProxy` as the `context` argument. For cross-origin, you must set the context explicitly.

```javascript
// Cross-origin example in an auxiliary browsing context (e.g., popup)
test_driver.set_test_context(window.opener);
await test_driver.click(document.getElementById("btn"));
test_driver.message_test("action complete");
```

## 5. Hardware & Device APIs (Web MIDI, WebUSB, Web Bluetooth, Gamepads)

Testing hardware-oriented specifications often requires special handling because standard headless runners lack physical devices or OS-level drivers.

### Granting Permissions
Most device-level APIs require explicit permissions. You MUST use `testdriver.js` to grant these permissions before interacting with the API to prevent automatic rejections.
```javascript
promise_test(async t => {
  // Example for Web MIDI
  await test_driver.set_permission({name: 'midi', sysex: true}, 'granted');
  const access = await navigator.requestMIDIAccess({sysex: true});
  assert_true(access instanceof MIDIAccess);
}, "MIDI access granted via testdriver");
```

### Handling Missing Hardware (Best Effort Testing)
When true end-to-end testing requires physical hardware (or virtual loopback interfaces) that do not exist in the standard WPT environment, you should write "best effort" tests.
- **Structural Validity:** Assert that the API methods and attributes exist and have the correct IDL types.
- **Method Acceptance (No-Throw):** Assert that methods can be called with valid arguments without throwing exceptions (if permitted by the spec when disconnected).
- **Graceful Degradation:** If an API throws an initialization error (e.g., `NotSupportedError`, `NotFoundError`, or `InvalidStateError`) purely due to the runner lacking OS-level driver configurations or physical devices, your test MUST catch and handle this gracefully rather than failing the test suite completely (e.g., by skipping the test or asserting the specific expected `DOMException` for a disconnected state).

```javascript
promise_test(async t => {
  await test_driver.set_permission({name: 'bluetooth'}, 'granted');
  try {
    const device = await navigator.bluetooth.requestDevice({acceptAllDevices: true});
    // If a mock device is present, assert on it
    assert_true(device !== null);
  } catch (e) {
    // Gracefully handle environments without physical bluetooth radios or mock drivers
    assert_equals(e.name, 'NotFoundError');
  }
}, "requestDevice handles missing hardware gracefully");
```

### When to use Manual Tests (`-manual`)
If the blueprint specifically requires simulating OS-level hardware interventions (e.g., physically unplugging a USB device, locking a device, or simulating a hardware fault) AND you have verified that no `testdriver.js` extension or `wdspec` backend exists to mock this specific state, you MUST default to a `-manual` test. Do not attempt to automate physical hardware manipulations if the testing infrastructure lacks a mock interface for it.
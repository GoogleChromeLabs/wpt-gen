# Permissions Policy Testing (`permissions-policy.js`)

When testing features controlled by the Permissions Policy (formerly Feature Policy), you MUST use the established testing framework located in `/permissions-policy/resources/permissions-policy.js`.

## 1. Setup

Include the helper script in your HTML test file:
```html
<script src="/permissions-policy/resources/permissions-policy.js"></script>
```

## 2. Testing Feature Availability

The primary utility is `test_feature_availability(test_promise_or_func, description, expected_availability, iframe_src, [feature_name])`.

This helper creates an iframe (using the provided `iframe_src`), applies the permissions policy, and verifies if the feature is available or blocked.

### Handling Asynchronous APIs
If the API being tested is asynchronous (returns a Promise), you must ensure your helper iframe correctly awaits the result and posts the success or failure back via `postMessage`.

## 3. Helper Iframes (`permissions-policy-*.html`)

You will typically need to create or use an existing cross-origin helper iframe HTML file. This file attempts to use the feature and reports back to the parent using `window.parent.postMessage`.

**Example Helper (`permissions-policy-midi.html`):**
```html
<!DOCTYPE html>
<script>
  Promise.resolve().then(async () => {
    try {
      await navigator.requestMIDIAccess();
      window.parent.postMessage({ type: 'availability', enabled: true }, '*');
    } catch (e) {
      if (e.name === 'NotAllowedError' || e.name === 'SecurityError') {
        window.parent.postMessage({ type: 'availability', enabled: false }, '*');
      } else {
        // Unexpected error
        window.parent.postMessage({ type: 'availability', enabled: false, error: e.name }, '*');
      }
    }
  });
</script>
```
*CRITICAL RULE:* Do not update core exception types in canonical helper resources unless the test suite expects immediate failure on older engines.

## 4. Policy Denial vs. User Permission Denial

When testing Permissions Policy, it is critical to isolate the policy block from a standard user permission denial.

*   **User Permission Denial:** Simulating a user clicking "Block" on a permission prompt. Done via `test_driver.set_permission({ name: 'feature' }, 'denied')`.
*   **Policy Block Denial:** The feature is disabled by the `Permissions-Policy` HTTP header or the `allow=""` attribute on an iframe (e.g., `<iframe allow="midi 'none'">`).

Both scenarios often result in the exact same exception (e.g., `NotAllowedError` or `SecurityError`).

**CRITICAL RULE:** To accurately test that a feature is blocked *by the Permissions Policy*, you MUST first grant the user permission using `testdriver.js` before running the policy test. Otherwise, you cannot be sure which mechanism blocked the feature.

```javascript
promise_test(async t => {
  // 1. Grant user permission first to isolate the policy test
  // Note: Permission descriptor can be a complex dictionary, e.g., {name: 'midi', sysex: false}
  await test_driver.set_permission({name: 'midi', sysex: false}, 'granted');

  // 2. Test the policy block
  // test_feature_availability will create the iframe and manage the postMessage lifecycle
  test_feature_availability(
    null,
    "MIDI is blocked by permissions policy",
    false, // expected_availability
    "resources/permissions-policy-midi.html"
  );
}, "Permissions Policy properly blocks Web MIDI");
```
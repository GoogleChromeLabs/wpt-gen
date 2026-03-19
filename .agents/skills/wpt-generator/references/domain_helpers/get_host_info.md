# Cross-Origin Networking Helpers (`get-host-info.sub.js`)

When writing WPTs for networking, fetch, CORS, WebSockets, or any APIs that require testing cross-origin behaviors via Javascript, **do not manually construct or hardcode cross-origin URLs**. Instead, you **MUST** use the canonical helper script located at `/common/get-host-info.sub.js`.

## Including the Framework
Include the script in your test file before your test logic.

```html
<script src="/resources/testharness.js"></script>
<script src="/resources/testharnessreport.js"></script>
<script src="/common/get-host-info.sub.js"></script>
```
*Note: Because the script name ends in `.sub.js`, the WPT server will automatically substitute the correct ports and hostnames when it is served.*

## Usage
The script exposes a global `get_host_info()` function that returns an object containing the precise origins and hostnames of the WPT test servers for the current environment.

**Example:**
```javascript
const host_info = get_host_info();

// Construct a URL for a cross-origin fetch request
const crossOriginUrl = host_info.HTTP_REMOTE_ORIGIN + '/fetch/api/basic/set-cookie.asis';

promise_test(async t => {
  const response = await fetch(crossOriginUrl);
  assert_true(response.ok);
}, "Cross-origin fetch succeeds");
```

## Key Properties
The returned object contains many properties. The most commonly used origins are:

*   **`HTTP_ORIGIN`**: The same origin as the default server (e.g., `http://web-platform.test:8000`).
*   **`HTTPS_ORIGIN`**: The secure equivalent of the same origin.
*   **`HTTP_REMOTE_ORIGIN`**: A cross-origin remote host (e.g., `http://www1.web-platform.test:8000`).
*   **`HTTPS_REMOTE_ORIGIN`**: A secure cross-origin remote host.
*   **`HTTP_NOTSAMESITE_ORIGIN`**: An origin that is entirely cross-site (not just cross-origin) to the default server (e.g., `http://not-web-platform.test:8000`). This is crucial for testing `SameSite` cookie behaviors or isolation policies.
*   **`HTTP_ORIGIN_WITH_DIFFERENT_PORT`**: Same host, different port.

*You can also access the raw hostnames (e.g., `host_info.ORIGINAL_HOST`, `host_info.REMOTE_HOST`) if you need to construct a URL manually.*
# Server Features & Cross-Origin Testing

WPT includes a custom Python HTTP server (`wptserve`) designed to make it easy to manipulate the precise details of responses. When your test requires cross-domain access, specific headers, dynamic status codes, or precise response timing, you **MUST** use these server features rather than attempting to mock them purely in the client.

## 1. Server Substitutions (`.sub`)

To test cross-origin behaviors without hardcoding hostnames or ports (which vary depending on the test environment), you MUST use server substitutions.

**Enabling Substitutions:**
*   Append `.sub` to your filename before the extension (e.g., `my-test.sub.html`, `worker.sub.js`).
*   Alternatively, append `?pipe=sub` to the URL.

**Template Syntax:**
Inside the file, use `{{ }}` to substitute environment variables:
*   `{{host}}`: The main host name (excluding subdomains).
*   `{{hosts[][www]}}`: A specific subdomain on the default host (e.g., `www`, `www1`, `www2`).
*   `{{hosts[alt][]}}`: The alternate host (used for cross-origin tests).
*   `{{hosts[alt][www]}}`: A specific subdomain on the alternate host.
*   `{{ports[http][0]}}`: The primary HTTP port.
*   `{{ports[ws][0]}}`: The primary WebSocket port.
*   `{{headers[X-Test]}}`: The value of an HTTP request header.

**Example (`cross-origin.sub.html`):**
```html
<script>
  // Dynamically constructs a cross-origin URL
  const crossOriginUrl = "http://{{hosts[alt][www]}}:{{ports[http][0]}}/path/to/resource";
  fetch(crossOriginUrl);
</script>
```

## 2. wptserve Pipes (`?pipe=`)

Pipes allow simple, on-the-fly manipulation of static files without writing custom code. You MUST use pipes to alter HTTP responses before resorting to writing custom `.asis` or Python handlers.

Pipes are added as a query parameter and are applied from left to right, separated by `|`.
`GET /sample.txt?pipe=slice(1,200)|status(404)`

### Built-In Pipes

*   **`status(code)`**: Sets the HTTP status of the response.
    *   `example.js?pipe=status(410)`
*   **`header(name,value,append)`**: Adds or replaces HTTP headers.
    *   `example.html?pipe=header(Content-Type,text/plain)` (Replaces)
    *   `example.html?pipe=header(Content-Type,text/plain,True)` (Appends)
    *   *Note: Commas `,` and closing parentheses `)` in the value must be escaped with a backslash `\`.*
*   **`slice(start,end)`**: Sends only part of a response body.
    *   `example.txt?pipe=slice(10,20)` (Bytes 10 to 19)
    *   `example.txt?pipe=slice(null,20)` (First 20 bytes)
*   **`trickle(commands)`**: Sends the body in chunks with delays (forces a connection close). Commands are colon-separated:
    *   Bare number: Bytes to send.
    *   `d` prefix: Delay in seconds.
    *   `example.txt?pipe=trickle(100:d1)` (Sends 100 bytes, waits 1s, sends remainder)

## 3. Python Handlers (`.py`)

For full control over the request and response, you can write a Python script. The server treats any `.py` file requested via HTTP as a handler.

**CRITICAL MANDATE:** You MUST define a `main(request, response)` function.

The function can return a tuple containing the status code, headers, and content:
```python
def main(request, response):
    # Read query parameters
    content_type = request.GET.first(b'content-type', b'text/plain')
    
    # Read request headers
    custom_header = request.headers.get(b'X-Custom', b'default')

    headers = [(b'Content-Type', content_type)]
    content = b"Dynamic response content based on: " + custom_header

    return (200, b'OK'), headers, content
```

*Note: WPT Python handlers typically deal with byte strings (`b'...'`) for headers and parameters.*

## 4. Static Responses (`.asis` and `.headers`)

*   **`.headers`**: To set static headers for an existing file without using pipes, create a companion file. For `test.html`, create `test.html.headers`.
    *   **Directory-wide headers**: To apply headers to *all* files within a specific directory, create a `__dir__.headers` file.
    ```text
    Content-Type: text/html; charset=big5
    Cache-Control: no-cache
    ```
*   **`.asis`**: For byte-for-byte literal HTTP responses (including the status line and headers), use the `.asis` extension. This is useful for testing malformed HTTP responses.

## 5. Test Features specified as query params

You can enable server features like HTTPS or HTTP/2 dynamically using the `wpt_flags` variant parameter, which is useful for data-driven testing:
```html
<meta name="variant" content="?wpt_flags=https">
<meta name="variant" content="?wpt_flags=www&wpt_flags=https">
```
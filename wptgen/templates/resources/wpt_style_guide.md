This guide provides a detailed overview of the best practices that apply in Web Platform Tests (WPT).

Following these guidelines ensures that your tests are robust, cross-platform, and maintainable.

---

## 1. File Organization and Naming

WPT uses file names and directory structures to determine how tests are run.

### 1.1 Universal Filename Flags
Flags are added to the filename to enable specific server features. These apply to all three test types:
*   `.https`: Loads the test over HTTPS (e.g., `my-test.https.html`).
*   `.h2`: Loads the test over HTTP/2.
*   `.sub`: Enables [server-side substitution](https://web-platform-tests.org/writing-tests/server-pipes.html#sub), allowing placeholders like `{{host}}`.
*   `.tentative`: Indicates the test is for a feature not yet fully standardized.

### 1.2 How to Choose WPT Test File Suffixes

Follow these steps to determine the correct filename suffix for a test. The goal is to assemble a filename suffix in the following format:
`[.features].{extension}`

#### Step 1: Choose the Base Extension
Determine the primary file format based on the content of your test:
- **`.html`**: Use for standard web-based tests (HTML/XHTML/SVG/XML).
- **`.js`**: Use for pure JavaScript tests, especially if you want to use the automated boilerplate generation (see Step 4).
- **`.py`**: Use ONLY for `wdspec` (WebDriver protocol) tests.

#### Step 2: Choose Test Feature Flags (Optional)
If your test requires specific server features or environment settings, append these flags (preceded and followed by a `.`). These come **after** any test type flag.

##### Environment Requirements
- **`.https`**: The test must be loaded over HTTPS.
- **`.h2`**: The test must be loaded over HTTP/2.
- **`.www`**: The test must run on the `www` subdomain.

##### Server Features
- **`.sub`**: The test uses server-side substitution (e.g., `{{host}}`).
- **`.headers`**: Not a flag for the test itself, but a suffix for a companion file (e.g., `.html.headers`) to set custom HTTP headers.

#### Step 3: Handle JavaScript Boilerplate (For `.js` files)
If you chose `.js` in Step 1, you MUST include one of these scope flags to tell WPT how to generate the HTML wrapper. These are technically feature flags and should be placed before the `.js` extension.

- **`.window.js`**: Generates a test that runs in a standard Window global.
- **`.worker.js`**: Generates a test that runs in a Dedicated Worker.
- **`.any.js`**: Generates multiple tests covering different scopes (Window, Worker, etc.).
- **`.extension.js`**: Generates a WebExtension test.

#### Step 4: Assemble and Verify Order
Assemble the parts in this specific order:
1.  **Features** (delimited by `.`): `.https.sub`
2.  **Extension**: `.html`

**Result**: `.https.sub.html`

##### Quick Check Table for LLMs:
| If the test contains... | Use Suffix... |
| :--- | :--- |
| WebDriver Protocol (Python) | `.py` |
| Needs HTTPS | `.https.html` |
| JS test running in multiple scopes | `.any.js` |
| Server-side `{{variable}}` substitution | `.sub.html` |
| HTTP/2 required | `.h2.html` |

---

## 2. Core Metadata

Every test file should contain metadata to describe its purpose and requirements.

### 2.1 Character Encoding
All tests must be encoded in **UTF-8**.
*   **Requirement**: Include `<meta charset="utf-8">` as the first tag in the `<head>` of HTML files.

### 2.2 Documentation Links
Link to the relevant specification using `<link rel="help">`. This is required for CSS tests and highly recommended for all others.
```html
<link rel="help" href="https://www.w3.org/TR/css-flexbox-1/#flex-direction-property">
```

### 2.3 Test Assertions
Use a `<meta name="assert">` tag to provide a concise description of what the test is verifying.
```html
<meta name="assert" content="Checks that flex-direction: row-reverse correctly mirrors the main axis.">
```

---

## 3. General Principles

### 3.1 Be Short and Focused
Tests should be as minimal as possible.
*   Avoid extraneous HTML tags (like `<html>` or `<body>` if they aren't strictly necessary).
*   Ensure the test only verifies the specific feature intended.

### 3.2 Be Conservative
Avoid depending on edge-case behavior of unrelated features.
*   Ensure there are **no parse errors**.
*   Only use features that are broadly supported across major browser engines (Safari, Chrome, Firefox) unless they are the subject of the test.

### 3.3 Be Cross-Platform
Assume the following defaults:
*   Viewport dimensions of at least 800px by 600px.
*   Canvas background is `white`, and initial `color` is `black`.
*   No specific system fonts are installed. Use the **Ahem font** for tests requiring precise text metrics.

### 3.4 Be Self-Contained
Tests **must not** depend on external network resources. Use local support files or WPT's cross-origin host features if multiple domains are needed.

### 3.5 Be Self-Describing
It should be obvious to a human reviewer whether the test passed or failed.

---

## 4. Automation with `testdriver.js`

For tests requiring user interaction (clicks, key presses, etc.) that cannot be triggered via standard APIs, use `testdriver.js`. This is supported by JS tests, reftests, and crashtests.

### 4.1 Setup
Include the following scripts in your HTML:
```html
<script src="/resources/testdriver.js"></script>
<script src="/resources/testdriver-vendor.js"></script>
```

### 4.2 Usage Example
```html
<script>
  async function performAction() {
    const button = document.getElementById("target");
    await test_driver.click(button);
    // Continue with test logic or remove wait classes
  }
  performAction();
</script>
```
*Note: While the automation API is universal, each test type has its own specific mechanism for managing asynchrony and signaling test completion.*

---

## 5. Style and Linting

Consistent style is enforced across the entire WPT repository.

### 5.1 Formatting Rules
*   **Indentation**: Use spaces, not tabs.
*   **Whitespace**: No trailing whitespace.
*   **Line Endings**: Use UNIX-style (LF) line endings.

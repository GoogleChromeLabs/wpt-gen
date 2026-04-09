# IDL Testing Guide (`idlharness.js`)

`idlharness.js` generates tests for Web IDL fragments using the `testharness.js` infrastructure. It automatically verifies that an implementation precisely matches the specification's IDL (attributes, methods, types, inheritance, etc.) without requiring manual boolean assertions.

**CRITICAL MANDATE:** For testing Web IDL interfaces (e.g., interface exposure, presence of attributes, existence of methods), you **MUST NOT** use manual assertions (like `assert_true('MyInterface' in window)`). You **MUST** use `idlharness.js`.

## 1. File Format & Boilerplate

You typically want to use `.any.js` or `.window.js` for IDL tests to avoid writing unnecessary HTML boilerplate.

You must include the WebIDL parser and `idlharness.js` scripts using metadata comments at the top of your file. Because IDL tests execute hundreds of assertions, they often exceed the default test timeout, so it is highly recommended to include `timeout=long`:
```javascript
// META: script=/resources/WebIDLParser.js
// META: script=/resources/idlharness.js
// META: timeout=long
```
*Note: If your test requires multiple environments (e.g., Window and Worker), use `// META: global=window,worker` in an `.any.js` file.*

## 2. Using `idl_test`

The core function to execute IDL tests is `idl_test(srcs, deps, setup_func)`:

*   **`srcs`**: An array of strings. These are the names of the specifications whose IDL you want to test. The names **must match** the filenames (excluding the `.idl` extension) found in the WPT `/interfaces/` directory (e.g., `['fetch']`).
*   **`deps`**: An array of strings. These are the specifications the IDL listed in `srcs` depends upon (e.g., `['referrer-policy', 'html', 'dom']`). Be careful to list them in the order that the dependencies are revealed.
*   **`setup_func`**: A function (or async function) that receives an `IdlArray` object. This is where you configure the specific objects the harness should test.

## 3. Configuring `IdlArray`

Inside the `setup_func`, you use the `IdlArray` object to register instances of your interfaces so the harness can test them against the IDL definitions.

### `add_objects(dict)`

Registers objects to be tested against their interfaces.
*   `dict`: An object where keys are the names of interfaces (or exceptions), and values are arrays of strings. Each string is a JavaScript expression that will be evaluated to produce an instance. This is the **only** way to test anything about `[LegacyNoInterfaceObject]` interfaces.
*   **Primary Interface Rule**: The interface used as the key must be the *primary* interface of the provided objects. For example, use `{Document: ["document"]}`, not `{Node: ["document"]}`. The harness will automatically test inherited interfaces (like `Node`).
*   **Warning (Side-Effects)**: The harness will actively call methods on the provided objects (e.g., with missing mandatory arguments) to verify exceptions. Ensure your provided instances won't cause destructive side-effects that break the test suite.

```javascript
idl_test(
  ['fetch'],
  ['referrer-policy', 'html', 'dom'],
  idl_array => {
    idl_array.add_objects({
      Headers: ["new Headers()"],
      Request: ["new Request('about:blank')"],
      Response: ["new Response()"]
    });
    
    // Example of conditional objects based on global scope
    if (self.GLOBAL.isWindow()) {
      idl_array.add_objects({ Window: ['window'] });
    } else if (self.GLOBAL.isWorker()) {
      idl_array.add_objects({ WorkerGlobalScope: ['self'] });
    }
  }
);
```

### `prevent_multiple_testing(name)`

A specialized method to avoid redundant testing when many objects implement the same base interfaces.
*   **Use Case**: If testing dozens of HTML elements (`HTMLHtmlElement`, `HTMLHeadElement`, etc.), they all inherit from `HTMLElement`, `Element`, and `Node`. This would lead to thousands of redundant tests.
*   Calling `idl_array.prevent_multiple_testing("HTMLElement")` ensures that once one object has been tested for `HTMLElement` and its ancestors, subsequent objects won't be re-tested for those base interfaces.

```javascript
idl_test(
  ['html'],
  ['dom'],
  idl_array => {
    idl_array.add_objects({
      HTMLHtmlElement: ['document.documentElement'],
      HTMLHeadElement: ['document.head'],
      HTMLBodyElement: ['document.body']
    });
    // Prevent re-testing HTMLElement and its ancestors for every element type
    idl_array.prevent_multiple_testing("HTMLElement");
  }
);
```

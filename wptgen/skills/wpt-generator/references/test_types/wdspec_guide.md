# wdspec Tests (WebDriver Protocol)

"wdspec" tests are a specialized type of WPT test used to verify the behavior of the **WebDriver Classic** and **WebDriver BiDi** protocols. 

**CRITICAL MANDATE:** Unlike standard web platform tests, wdspec tests are written in **Python** using the **pytest** framework. Do NOT write HTML or JavaScript files when asked to test a WebDriver endpoint or protocol command.

## 1. File Organization
wdspec tests are located in subdirectories based on the WebDriver command under test.
*   **Classic:** `webdriver/tests/classic/{command}/` (e.g., `close_window/`)
*   **BiDi:** `webdriver/tests/bidi/{module}/{method}/` (e.g., `bidi/external/permissions/set_permission/`)

Test files should contain Python functions whose names begin with `test_` (e.g., `test_stale_element`).

## 2. Writing a Classic wdspec Test

WPT provides a `webdriver` client library. You MUST use Pytest fixtures (like `session` and `inline`) to set up the browser state. 

However, when issuing the specific command under test, you **MUST NOT** use the high-level convenience methods. Instead, you must explicitly construct and send the HTTP request using `session.transport.send()` to limit indirection and obfuscation.

**Example:**
```python
from tests.support.asserts import assert_success

def test_null_response_value(session, inline):
    # 1. High-level API used ONLY for setup
    session.url = inline("<p>foo")
    element = session.find.css("p", all=False)

    # 2. Explicit HTTP request constructed for the command UNDER TEST
    response = session.transport.send(
        "POST", "session/{session_id}/element/{element_id}/click".format(
            session_id=session.session_id,
            element_id=element.id))

    # 3. Assertion
    assert_success(response)
```

## 3. Writing a WebDriver BiDi wdspec Test

For WebDriver BiDi tests, use the `bidi_session` fixture. The `bidi_session` object exposes properties corresponding to the BiDi protocol modules (e.g., `bidi_session.permissions`, `bidi_session.script`).

Unlike Classic tests, BiDi tests DO use the module methods directly to send commands.

**Example:**
```python
import pytest

@pytest.mark.asyncio
async def test_set_permission(bidi_session):
    # BiDi commands are sent via their respective module
    result = await bidi_session.permissions.set_permission(
        descriptor={"name": "geolocation"},
        state="granted",
        origin="https://example.com"
    )
    
    assert result == {}
```

## 4. Execution & Validation
To run a wdspec test and validate your Python code, use the `run_wpt_test` tool on the specific Python file.
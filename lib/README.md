# WPT-Gen Library (`wpt-gen-lib`)

A lightweight, non-interactive core library for AI-powered Web Platform Test (WPT) analysis and gap detection, built specifically for integration with server-side services like **Chromium Dashboard** (`chromestatus.com`).

This library houses the core analytical engines of the **WPT-Gen** project, excluding the heavy autonomous agentic CLI components and their dependencies (e.g., `google-adk`).

---

## Key Capabilities

* **Context Assembly:** Programmatically scrapes W3C specifications, explainers, and existing WPT test suites.
* **Requirements Extraction:** Synthesizes spec normative text into structured, granular requirements.
* **Coverage Audit:** Compares technical requirements against current test suites to identify coverage gaps.
* **Markdown Report Generation:** Compiles findings into structured, premium-looking Markdown worksheets directly displayable in dashboard interfaces.
* **Non-Interactive Mode:** Utilizes standard Python logging (`LoggingUIProvider`) instead of a console terminal interface, making it perfect for server tasks.

---

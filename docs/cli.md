# CLI Command Reference

This document provides a detailed reference for all commands and options available in the `wpt-gen` CLI.

## `wpt-gen generate`

Generate Web Platform Tests for a specific web feature.

**Usage:**
```bash
wpt-gen generate [OPTIONS] WEB_FEATURE_ID
```

### Arguments

| Argument | Description |
| :--- | :--- |
| `WEB_FEATURE_ID` | **Required.** The ID of the feature (e.g., `grid`, `popover`) as defined in the `web-features` repository. |

### Options

#### General Options
| Option | Shorthand | Description | Default |
| :--- | :--- | :--- | :--- |
| `--provider` | `-p` | Override the default LLM provider (`gemini`, `openai`, `anthropic`). | From config |
| `--wpt-dir` | `-w` | Override the path to the local web-platform-tests repository. | From config |
| `--config` | `-c` | Path to a custom `wpt-gen.yml` file. | `~/.wpt-gen.yml` |
| `--output-dir` | `-o` | Directory where generated tests will be saved. | Local WPT repo |

#### Execution Control
| Option | Description |
| :--- | :--- |
| `--resume` | Resume the workflow from the last successful phase for this feature ID. |
| `--suggestions-only` | Stop after generating test blueprints/suggestions. Skip the actual test file generation. |
| `--yes-tokens` | Automatically confirm all prompts related to LLM token counts. |
| `--skip-evaluation`, `--no-eval` | Skip the Phase 5 (Evaluation) step. |
| `--skip-execution`, `--no-exec` | Skip the Phase 6 (Test Execution) step (useful if the browser implementation is not completed). |
| `--max-parallel-requests` | Limit the number of concurrent asynchronous LLM requests. |

#### Model Configuration
| Option | Description |
| :--- | :--- |
| `--use-lightweight` | Force the use of the provider's "lightweight" model for all phases. |
| `--use-reasoning` | Force the use of the provider's "reasoning" model for all phases. |
| `--show-responses`, `-s` | Print every raw LLM response to the console (useful for debugging). |
| `--max-retries` | Maximum number of retries for failed LLM calls. |
| `--timeout` | Timeout for individual LLM requests in seconds. |

#### Feature & Requirement Overrides
| Option | Shorthand | Description |
| :--- | :--- | :--- |
| `--spec-urls` | `-u` | Comma-separated list of W3C Spec URLs to use, bypassing automatic fetching. |
| `--description` | `-d` | Provide a manual description/summary of the feature to the agent. |
| `--detailed-requirements` | | Use an iterative process to extract highly granular requirements (slower). |
| `--draft` | | Enable fetching metadata from the draft features directory. |
| `--categorized-requirements` | | Extract requirements in parallel across technical categories (faster). |

---

## `wpt-gen clear-cache`

Clears the local cache of scraped specifications and LLM responses.

**Usage:**
```bash
wpt-gen clear-cache [OPTIONS]
```

### Options
| Option | Shorthand | Description |
| :--- | :--- | :--- |
| `--config` | `-c` | Path to a custom `wpt-gen.yml` file. |

---

## `wpt-gen version`

Print the current version of `wpt-gen`.

**Usage:**
```bash
wpt-gen version
```

---

## `wpt-gen config`

Manage WPT-Gen configuration without manually editing the YAML file. If run without subcommands, it displays the currently active configuration.

**Usage:**
```bash
wpt-gen config [COMMAND]
```

### Commands

| Command | Description |
| :--- | :--- |
| `show` | Display the currently active, fully resolved configuration. |
| `set` | Update an individual configuration setting using dot-notation. |

### `wpt-gen config set`

Update an individual configuration setting. Modifies the local or global `wpt-gen.yml` file.

**Usage:**
```bash
wpt-gen config set <KEY> <VALUE> [OPTIONS]
```

**Examples:**
```bash
wpt-gen config set default_provider openai
wpt-gen config set providers.gemini.default_model gemini-3.1-pro-preview
wpt-gen config set show_responses true
```

#### Options
| Option | Shorthand | Description |
| :--- | :--- | :--- |
| `--config` | `-c` | Path to a custom `wpt-gen.yml` file. |

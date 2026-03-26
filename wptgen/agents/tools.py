"""Module docstring."""

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from google.adk.tools.function_tool import FunctionTool

from wptgen.context import fetch_and_extract_text, find_feature_tests
from wptgen.ui import UIProvider

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".pyc",
    ".pyo",
    ".wasm",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
}


def _parse_test_results(log_path: str) -> dict[str, str]:
    """Parses the JSON log output to extract failing test IDs and error messages."""  # pylint: disable=line-too-long
    failing_tests: dict[str, str] = {}
    if not os.path.exists(log_path):
        return failing_tests

    test_messages: dict[str, list[str]] = {}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                test_id = event.get("test")
                if not test_id:
                    continue

                if test_id not in test_messages:
                    test_messages[test_id] = []

                action = event.get("action")
                status = event.get("status")

                if action == "test_status":
                    if status in (
                        "FAIL",
                        "ERROR",
                        "TIMEOUT",
                        "CRASH",
                        "PRECONDITION_FAILED",
                    ):
                        subtest_name = event.get("subtest", "unknown")
                        msg = event.get("message", "No message")
                        test_messages[test_id].append(
                            f"Subtest '{subtest_name}': {status} - {msg}"
                        )
                elif action == "test_end":
                    if status in ("FAIL", "ERROR", "TIMEOUT", "CRASH"):
                        msg = (
                            event.get("message")
                            or event.get("expected")
                            or f"Overall test {status}"
                        )
                        test_messages[test_id].insert(
                            0, f"Test: {status} - {msg}"
                        )
            except json.JSONDecodeError:
                pass

    for test_id, messages in test_messages.items():
        if messages:
            failing_tests[test_id] = "\n".join(messages)

    return failing_tests


WPT_LINT_TIMEOUT_SECONDS = 15
WPT_RUN_TIMEOUT_SECONDS = 60
WPT_GREP_TIMEOUT_SECONDS = 15


def _validate_safe_path(target_path: Path, wpt_root: Path) -> Path:
    """Validates that a target path resolves to within the WPT root directory.

    Args:
        target_path: The requested path to validate.
        wpt_root: The root WPT directory.

    Returns:
        The fully resolved path.

    Raises:
        ValueError: If the path attempts to break out of the WPT root.
    """
    if not target_path.is_absolute():
        target_path = wpt_root / target_path
    resolved_target = target_path.resolve()
    resolved_root = wpt_root.resolve()

    # Try to calculate relative path. If it raises ValueError, it's outside.
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as e:
        raise ValueError(
            f"Path '{target_path}' is outside the designated WPT repository root."  # pylint: disable=line-too-long
        ) from e

    return resolved_target


def create_agent_tools(
    wpt_path: Path, ui: UIProvider, browser: str, channel: str
) -> list[FunctionTool]:
    """Creates a suite of strictly validated tools for the ADK agent.

    All file operations performed by these tools are guaranteed to be restricted
    to the designated `wpt_path` or its subdirectories. It also includes tools
    for linting, running tests, and searching feature metadata.

    Args:
        wpt_path: The root directory of the WPT repository.
        ui: The UIProvider instance for printing output to the terminal.
        browser: The browser to use for testing.
        channel: The browser channel.

    Returns:
        A list of ADK `FunctionTool` objects.
    """

    def read_file(
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Reads the content of a file within the WPT repository.

        Use 'start_line' and 'end_line' for targeted, surgical reads of specific sections  # pylint: disable=line-too-long
        to maintain context efficiency.

        Args:
            file_path: The relative or absolute path to the file to read.
            start_line: Optional 1-based line number to start reading from.
            end_line: Optional 1-based line number to end reading at (inclusive).  # pylint: disable=line-too-long

        Returns:
            A dictionary containing the 'status' and the file 'content', or an 'error'.  # pylint: disable=line-too-long
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            if not target.is_file():
                return {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                }
            content = target.read_text(encoding="utf-8")

            if start_line is not None or end_line is not None:
                lines = content.splitlines(keepends=True)
                start = max(0, start_line - 1) if start_line is not None else 0
                end = (
                    min(len(lines), end_line)
                    if end_line is not None
                    else len(lines)
                )
                if start >= len(lines):
                    return {
                        "status": "error",
                        "error": f"start_line ({start_line}) is beyond EOF ({len(lines)} lines).",  # pylint: disable=line-too-long
                    }
                return {
                    "status": "success",
                    "content": "".join(lines[start:end]),
                }

            return {"status": "success", "content": content}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def write_file(file_path: str, content: str) -> dict[str, Any]:
        """Writes content to a file within the WPT repository, creating parent directories if needed.  # pylint: disable=line-too-long

        Args:
            file_path: The relative or absolute path where the file should be written.  # pylint: disable=line-too-long
            content: The text content to write.

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def search_files(directory: str, pattern: str) -> dict[str, Any]:
        """Recursively searches for files matching a glob pattern within a directory.  # pylint: disable=line-too-long

        Args:
            directory: The directory to search within.
            pattern: The glob pattern to match (e.g., '*.html', '**/*.js').

        Returns:
            A dictionary containing the 'status' and a list of matching 'files'.
        """
        try:
            target_dir = _validate_safe_path(Path(directory), wpt_path)
            if not target_dir.is_dir():
                return {
                    "status": "error",
                    "error": f"Directory not found: {directory}",
                }

            max_results = 100  # pylint: disable=unused-variable
            iterator = (
                p.relative_to(wpt_path).as_posix()
                for p in target_dir.rglob(pattern)
                if p.is_file()
            )
            matches = list(itertools.islice(iterator, max_results + 1))
            if len(matches) > max_results:
                return {
                    "status": "success",
                    "files": matches[:max_results],
                    "warning": f"Results truncated to the first {max_results} matches. Please refine your search pattern.",  # pylint: disable=line-too-long
                }
            return {"status": "success", "files": matches}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def list_directory(directory: str) -> dict[str, Any]:
        """Lists the contents of a directory.

        Args:
            directory: The directory to list.

        Returns:
            A dictionary containing the 'status' and a list of 'entries' (files and folders).  # pylint: disable=line-too-long
        """
        try:
            target_dir = _validate_safe_path(Path(directory), wpt_path)
            if not target_dir.is_dir():
                return {
                    "status": "error",
                    "error": f"Directory not found: {directory}",
                }

            max_results = 100  # pylint: disable=unused-variable
            iterator = (
                p.relative_to(wpt_path).as_posix() for p in target_dir.iterdir()
            )
            entries = list(itertools.islice(iterator, max_results + 1))
            if len(entries) > max_results:
                return {
                    "status": "success",
                    "entries": entries[:max_results],
                    "warning": f"Results truncated to the first {max_results} matches. Please use search_files if you are looking for specific content.",  # pylint: disable=line-too-long
                }
            return {"status": "success", "entries": entries}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def create_directory(directory_path: str) -> dict[str, Any]:
        """Creates a directory within the WPT repository, including any necessary parent directories.  # pylint: disable=line-too-long

        Args:
            directory_path: The relative or absolute path of the directory to create.  # pylint: disable=line-too-long

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            target = _validate_safe_path(Path(directory_path), wpt_path)
            target.mkdir(parents=True, exist_ok=True)
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def delete_directory(directory_path: str) -> dict[str, Any]:
        """Deletes a directory and all its contents within the WPT repository.

        Args:
            directory_path: The path to the directory to delete.

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            target = _validate_safe_path(Path(directory_path), wpt_path)
            if not target.is_dir():
                return {
                    "status": "error",
                    "error": f"Directory not found: {directory_path}",
                }
            import shutil  # pylint: disable=import-outside-toplevel

            shutil.rmtree(target)
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def delete_file(file_path: str) -> dict[str, Any]:
        """Deletes a specific file within the WPT repository.

        Args:
            file_path: The path to the file to delete.

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            if not target.is_file():
                return {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                }
            target.unlink()
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def move_file(source_path: str, destination_path: str) -> dict[str, Any]:
        """Moves or renames a file within the WPT repository.

        Args:
            source_path: The path to the file to move or rename.
            destination_path: The new path for the file.

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            source = _validate_safe_path(Path(source_path), wpt_path)
            if not source.is_file():
                return {
                    "status": "error",
                    "error": f"Source file not found: {source_path}",
                }

            destination = _validate_safe_path(Path(destination_path), wpt_path)
            destination.parent.mkdir(parents=True, exist_ok=True)

            import shutil  # pylint: disable=import-outside-toplevel

            shutil.move(source, destination)
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def run_wpt_lint(file_path: str) -> dict[str, Any]:
        """Runs the WPT linter on a specific file and returns any syntax or style errors.  # pylint: disable=line-too-long

        Args:
            file_path: The path to the file to lint.

        Returns:
            A dictionary containing the 'status' and the 'lint_output' if any errors exist.  # pylint: disable=line-too-long
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            if not target.is_file():
                return {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                }

            rel_path = target.relative_to(wpt_path).as_posix()

            # We use subprocess.run directly as these tools are executed
            # synchronously by ADK currently
            try:
                result = subprocess.run(
                    ["./wpt", "lint", rel_path],
                    cwd=str(wpt_path),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=WPT_LINT_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as e:
                return {
                    "status": "error",
                    "error": f"Command timed out after {e.timeout} seconds.",
                }

            if result.returncode == 0:
                return {"status": "success", "message": "No lint errors found."}
            else:
                # Provide the raw output which contains the linter error details
                return {
                    "status": "failed",
                    "lint_output": result.stdout.strip()
                    + "\n"
                    + result.stderr.strip(),
                }
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def run_wpt_test(file_path: str) -> dict[str, Any]:  # pylint: disable=line-too-long
        """Executes a specific test file using the local WPT test runner infrastructure.  # pylint: disable=line-too-long

        This command can take a while to complete (e.g. 10-20 seconds).

        Args:
            file_path: The path to the test file to run.

        Returns:
            A dictionary containing the 'status', any 'failing_tests' messages,
            and the full 'output' logs from the test runner.
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            if not target.is_file():
                return {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                }

            rel_path = target.relative_to(wpt_path).as_posix()

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                log_path = f.name

            try:
                # Use headless browser for testing
                cmd = [
                    "./wpt",
                    "run",
                    "--channel",
                    channel,
                    "--headless",
                    "--log-raw",
                    log_path,
                    browser,
                    rel_path,
                ]

                try:
                    result = subprocess.run(
                        cmd,
                        cwd=str(wpt_path),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=WPT_RUN_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired as e:
                    partial_stdout = (
                        e.stdout.decode("utf-8")
                        if isinstance(e.stdout, bytes)
                        else (e.stdout or "")
                    )
                    partial_stderr = (
                        e.stderr.decode("utf-8")
                        if isinstance(e.stderr, bytes)
                        else (e.stderr or "")
                    )
                    if partial_stdout:
                        ui.stream_text(partial_stdout)
                    if partial_stderr:
                        ui.stream_text(partial_stderr)
                    output_log = f"{partial_stdout}\n{partial_stderr}".strip()
                    return {
                        "status": "error",
                        "error": f"Timeout after {e.timeout}s.",
                        "output": output_log,
                    }

                if result.stdout:
                    ui.stream_text(result.stdout)
                if result.stderr:
                    ui.stream_text(result.stderr)

                output_log = f"{result.stdout}\n{result.stderr}".strip()

                if result.returncode == 0:
                    return {
                        "status": "success",
                        "message": "All assertions passed.",
                        "output": output_log,
                    }

                failing_tests = _parse_test_results(log_path)

                if not failing_tests:
                    return {
                        "status": "error",
                        "error": "Test runner crashed or failed. See output.",
                        "output": output_log,
                    }

                return {
                    "status": "failed",
                    "failing_tests": failing_tests,
                    "output": output_log,
                }
            finally:
                if os.path.exists(log_path):
                    os.remove(log_path)

        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def search_feature_tests(web_feature_id: str) -> dict[str, Any]:  # pylint: disable=line-too-long
        """Searches the WPT repository for all test files associated with a specific web_feature_id.
        # pylint: disable=line-too-long
              This utilizes the WEB_FEATURES.yml definitions spread throughout the repository.

              Args:
                  web_feature_id: The ID of the feature (e.g., 'popover').

              Returns:  # pylint: disable=line-too-long
                  A dictionary containing the 'status' and a list of 'test_files' mapped to that feature.
        """
        try:
            matches = find_feature_tests(str(wpt_path), web_feature_id)
            if matches:
                # Clean up paths to be relative for the agent's consumption
                rel_matches = [
                    Path(p).resolve().relative_to(wpt_path.resolve()).as_posix()
                    for p in matches
                ]
                return {"status": "success", "test_files": rel_matches}
            return {
                "status": "success",
                "test_files": [],
                "message": f"No existing tests found for feature {web_feature_id}",  # pylint: disable=line-too-long
            }
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def fetch_spec_content(url: str) -> dict[str, Any]:
        """Fetches and extracts the text content from a specification URL.

        Args:
            url: The URL of the specification to fetch.

        Returns:  # pylint: disable=line-too-long
            A dictionary containing the 'status' and the 'content' of the specification,
            or an 'error' message if the fetch fails.
        """
        try:
            content = fetch_and_extract_text(url)
            if content:
                return {"status": "success", "content": content}
            return {
                "status": "error",
                "error": "Failed to extract content or page was empty.",
            }
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def search_file_contents(directory: str, pattern: str) -> dict[str, Any]:  # pylint: disable=line-too-long
        """Searches for a string or regex pattern within the contents of files in a directory.  # pylint: disable=line-too-long

        Args:
            directory: The directory to search within.
            pattern: The grep-compatible regular expression to search for.

        Returns:
            A dictionary containing the 'status' and the 'search_output'.
        """
        try:
            target_dir = _validate_safe_path(Path(directory), wpt_path)
            if not target_dir.is_dir():
                return {
                    "status": "error",
                    "error": f"Directory not found: {directory}",
                }

            try:
                regex = re.compile(pattern)
            except re.error as e:
                return {
                    "status": "error",
                    "error": f"Invalid regular expression: {e}",
                }

            start_time = time.time()
            matches: list[str] = []
            max_matches = 100  # pylint: disable=unused-variable
            has_more_matches = False

            for root, dirs, files in os.walk(target_dir):
                if ".git" in dirs:
                    dirs.remove(".git")

                if time.time() - start_time > WPT_GREP_TIMEOUT_SECONDS:
                    return {
                        "status": "error",
                        "error": f"Command timed out after {WPT_GREP_TIMEOUT_SECONDS} seconds.",  # pylint: disable=line-too-long  # pylint: disable=line-too-long
                    }
                for file in files:
                    if time.time() - start_time > WPT_GREP_TIMEOUT_SECONDS:
                        return {
                            "status": "error",
                            "error": f"Command timed out after {WPT_GREP_TIMEOUT_SECONDS} seconds.",  # pylint: disable=line-too-long  # pylint: disable=line-too-long
                        }

                    file_path = Path(root) / file
                    if file_path.suffix.lower() in BINARY_EXTENSIONS:
                        continue

                    try:
                        with file_path.open("r", encoding="utf-8") as f:
                            for line_num, line in enumerate(f, start=1):
                                if (
                                    line_num % 10000 == 0
                                    and time.time() - start_time
                                    > WPT_GREP_TIMEOUT_SECONDS
                                ):
                                    return {
                                        "status": "error",
                                        "error": f"Command timed out after {WPT_GREP_TIMEOUT_SECONDS} seconds.",  # pylint: disable=line-too-long  # pylint: disable=line-too-long
                                    }

                                if regex.search(line):
                                    if len(matches) < max_matches:
                                        # Return path relative to wpt_root
                                        rel_path_str = file_path.relative_to(
                                            wpt_path
                                        ).as_posix()
                                        matches.append(  # pylint: disable=line-too-long
                                            f"{rel_path_str}:{line_num}:{line.rstrip(chr(10))}"  # pylint: disable=line-too-long
                                        )
                                    else:
                                        has_more_matches = True
                                        break
                    except (UnicodeDecodeError, OSError):
                        rel_path_str = file_path.relative_to(
                            wpt_path
                        ).as_posix()
                        matches = [
                            m
                            for m in matches
                            if not m.startswith(f"{rel_path_str}:")
                        ]
                        continue

                    if has_more_matches:
                        break
                if has_more_matches:
                    break

            if not matches:
                return {
                    "status": "success",
                    "search_output": "No matches found.",
                }

            output = "\n".join(matches)
            if has_more_matches:  # pylint: disable=line-too-long
                output += f"\n... (warning: more than {max_matches} matches found; results truncated)"  # pylint: disable=line-too-long
            return {"status": "success", "search_output": output}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def replace_in_file(
        file_path: str, old_string: str, new_string: str
    ) -> dict[str, Any]:  # pylint: disable=line-too-long
        """Replaces exactly one unique occurrence of a string in a file with a new string.  # pylint: disable=line-too-long

        Args:
            file_path: The path to the file to modify.
            old_string: The exact string to be replaced.
            new_string: The exact string to replace it with.

        Returns:
            A dictionary containing the 'status'.
        """
        try:
            target = _validate_safe_path(Path(file_path), wpt_path)
            if not target.is_file():
                return {
                    "status": "error",
                    "error": f"File not found: {file_path}",
                }
            content = target.read_text(encoding="utf-8")
            occurrences = content.count(old_string)
            if occurrences == 0:
                return {
                    "status": "error",
                    "error": "old_string not found in file.",
                }
            if occurrences > 1:
                return {
                    "status": "error",
                    "error": "old_string found multiple times. Please provide more surrounding context to make it unique.",  # pylint: disable=line-too-long  # pylint: disable=line-too-long
                }
            new_content = content.replace(old_string, new_string)
            target.write_text(new_content, encoding="utf-8")
            return {"status": "success"}
        except (OSError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    return [
        FunctionTool(func=read_file),
        FunctionTool(func=write_file),
        FunctionTool(func=search_files),
        FunctionTool(func=list_directory),
        FunctionTool(func=create_directory),
        FunctionTool(func=delete_directory),
        FunctionTool(func=delete_file),
        FunctionTool(func=move_file),
        FunctionTool(func=run_wpt_lint),
        FunctionTool(func=run_wpt_test),
        FunctionTool(func=search_feature_tests),
        FunctionTool(func=fetch_spec_content),
        FunctionTool(func=search_file_contents),
        FunctionTool(func=replace_in_file),
    ]

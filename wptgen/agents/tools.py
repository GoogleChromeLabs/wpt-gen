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
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from google.adk.tools.function_tool import FunctionTool

from wptgen.context import fetch_and_extract_text, find_feature_tests
from wptgen.phases.execution import _parse_test_results

WPT_LINT_TIMEOUT_SECONDS = 15
WPT_RUN_TIMEOUT_SECONDS = 60


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
  resolved_target = target_path.resolve()
  resolved_root = wpt_root.resolve()

  # Try to calculate relative path. If it raises ValueError, it's outside.
  try:
    resolved_target.relative_to(resolved_root)
  except ValueError as e:
    raise ValueError(f"Path '{target_path}' is outside the designated WPT repository root.") from e

  return resolved_target


def create_agent_tools(wpt_path: Path) -> list[FunctionTool]:
  """Creates a suite of strictly validated tools for the ADK agent.

  All file operations performed by these tools are guaranteed to be restricted
  to the designated `wpt_path` or its subdirectories. It also includes tools
  for linting, running tests, and searching feature metadata.

  Args:
      wpt_path: The root directory of the WPT repository.

  Returns:
      A list of ADK `FunctionTool` objects.
  """

  def read_file(file_path: str) -> dict[str, Any]:
    """Reads the content of a file within the WPT repository.

    Args:
        file_path: The relative or absolute path to the file to read.

    Returns:
        A dictionary containing the 'status' and the file 'content', or an 'error'.
    """
    try:
      target = _validate_safe_path(Path(file_path), wpt_path)
      if not target.is_file():
        return {'status': 'error', 'error': f'File not found: {file_path}'}
      content = target.read_text(encoding='utf-8')
      return {'status': 'success', 'content': content}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  def write_file(file_path: str, content: str) -> dict[str, Any]:
    """Writes content to a file within the WPT repository, creating parent directories if needed.

    Args:
        file_path: The relative or absolute path where the file should be written.
        content: The text content to write.

    Returns:
        A dictionary containing the 'status'.
    """
    try:
      target = _validate_safe_path(Path(file_path), wpt_path)
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(content, encoding='utf-8')
      return {'status': 'success'}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  def search_files(directory: str, pattern: str) -> dict[str, Any]:
    """Recursively searches for files matching a glob pattern within a directory.

    Args:
        directory: The directory to search within.
        pattern: The glob pattern to match (e.g., '*.html', '**/*.js').

    Returns:
        A dictionary containing the 'status' and a list of matching 'files'.
    """
    try:
      target_dir = _validate_safe_path(Path(directory), wpt_path)
      if not target_dir.is_dir():
        return {'status': 'error', 'error': f'Directory not found: {directory}'}

      MAX_RESULTS = 100
      iterator = (str(p.relative_to(wpt_path)) for p in target_dir.rglob(pattern) if p.is_file())
      matches = list(itertools.islice(iterator, MAX_RESULTS + 1))
      if len(matches) > MAX_RESULTS:
        return {
          'status': 'success',
          'files': matches[:MAX_RESULTS],
          'warning': f'Results truncated to the first {MAX_RESULTS} matches. Please refine your search pattern.',
        }
      return {'status': 'success', 'files': matches}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  def list_directory(directory: str) -> dict[str, Any]:
    """Lists the contents of a directory.

    Args:
        directory: The directory to list.

    Returns:
        A dictionary containing the 'status' and a list of 'entries' (files and folders).
    """
    try:
      target_dir = _validate_safe_path(Path(directory), wpt_path)
      if not target_dir.is_dir():
        return {'status': 'error', 'error': f'Directory not found: {directory}'}

      MAX_RESULTS = 100
      iterator = (str(p.relative_to(wpt_path)) for p in target_dir.iterdir())
      entries = list(itertools.islice(iterator, MAX_RESULTS + 1))
      if len(entries) > MAX_RESULTS:
        return {
          'status': 'success',
          'entries': entries[:MAX_RESULTS],
          'warning': f'Results truncated to the first {MAX_RESULTS} matches. Please use search_files if you are looking for specific content.',
        }
      return {'status': 'success', 'entries': entries}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

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
        return {'status': 'error', 'error': f'File not found: {file_path}'}
      target.unlink()
      return {'status': 'success'}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  def run_wpt_lint(file_path: str) -> dict[str, Any]:
    """Runs the WPT linter on a specific file and returns any syntax or style errors.

    Args:
        file_path: The path to the file to lint.

    Returns:
        A dictionary containing the 'status' and the 'lint_output' if any errors exist.
    """
    try:
      target = _validate_safe_path(Path(file_path), wpt_path)
      if not target.is_file():
        return {'status': 'error', 'error': f'File not found: {file_path}'}

      rel_path = str(target.relative_to(wpt_path))

      # We use subprocess.run directly as these tools are executed synchronously by ADK currently
      try:
        result = subprocess.run(
          ['./wpt', 'lint', rel_path],
          cwd=str(wpt_path),
          capture_output=True,
          text=True,
          timeout=WPT_LINT_TIMEOUT_SECONDS,
        )
      except subprocess.TimeoutExpired as e:
        return {
          'status': 'error',
          'error': f'Command timed out after {e.timeout} seconds.',
        }

      if result.returncode == 0:
        return {'status': 'success', 'message': 'No lint errors found.'}
      else:
        # Provide the raw output which contains the linter error details
        return {
          'status': 'failed',
          'lint_output': result.stdout.strip() + '\n' + result.stderr.strip(),
        }
    except (OSError, ValueError, subprocess.SubprocessError) as e:
      return {'status': 'error', 'error': str(e)}

  def run_wpt_test(file_path: str) -> dict[str, Any]:
    """Executes a specific test file using the local WPT test runner infrastructure.

    This command can take a while to complete (e.g. 10-20 seconds).

    Args:
        file_path: The path to the test file to run.

    Returns:
        A dictionary containing the 'status' and any 'failing_tests' messages,
        or 'success' if all assertions pass.
    """
    try:
      target = _validate_safe_path(Path(file_path), wpt_path)
      if not target.is_file():
        return {'status': 'error', 'error': f'File not found: {file_path}'}

      rel_path = str(target.relative_to(wpt_path))

      with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        log_path = f.name

      try:
        # Use headless chrome for testing
        cmd = ['./wpt', 'run', '--channel', 'canary', '--log-raw', log_path, 'chrome', rel_path]

        try:
          result = subprocess.run(
            cmd,
            cwd=str(wpt_path),
            capture_output=True,
            text=True,
            timeout=WPT_RUN_TIMEOUT_SECONDS,
          )
        except subprocess.TimeoutExpired as e:
          return {
            'status': 'error',
            'error': f'Command timed out after {e.timeout} seconds.',
          }

        if result.returncode == 0:
          return {'status': 'success', 'message': 'All assertions passed.'}

        failing_tests = _parse_test_results(log_path)

        if not failing_tests:
          return {
            'status': 'error',
            'error': f'Test runner crashed or failed. Output: {result.stderr.strip()}',
          }

        return {'status': 'failed', 'failing_tests': failing_tests}
      finally:
        if os.path.exists(log_path):
          os.remove(log_path)

    except (OSError, ValueError, subprocess.SubprocessError) as e:
      return {'status': 'error', 'error': str(e)}

  def search_feature_tests(web_feature_id: str) -> dict[str, Any]:
    """Searches the WPT repository for all test files associated with a specific web_feature_id.

    This utilizes the WEB_FEATURES.yml definitions spread throughout the repository.

    Args:
        web_feature_id: The ID of the feature (e.g., 'popover').

    Returns:
        A dictionary containing the 'status' and a list of 'test_files' mapped to that feature.
    """
    try:
      matches = find_feature_tests(str(wpt_path), web_feature_id)
      if matches:
        # Clean up paths to be relative for the agent's consumption
        rel_matches = [str(Path(p).resolve().relative_to(wpt_path.resolve())) for p in matches]
        return {'status': 'success', 'test_files': rel_matches}
      return {
        'status': 'success',
        'test_files': [],
        'message': f'No existing tests found for feature {web_feature_id}',
      }
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  def fetch_spec_content(url: str) -> dict[str, Any]:
    """Fetches and extracts the text content from a specification URL.

    Args:
        url: The URL of the specification to fetch.

    Returns:
        A dictionary containing the 'status' and the 'content' of the specification,
        or an 'error' message if the fetch fails.
    """
    try:
      content = fetch_and_extract_text(url)
      if content:
        return {'status': 'success', 'content': content}
      return {'status': 'error', 'error': 'Failed to extract content or page was empty.'}
    except (OSError, ValueError) as e:
      return {'status': 'error', 'error': str(e)}

  return [
    FunctionTool(func=read_file),
    FunctionTool(func=write_file),
    FunctionTool(func=search_files),
    FunctionTool(func=list_directory),
    FunctionTool(func=delete_file),
    FunctionTool(func=run_wpt_lint),
    FunctionTool(func=run_wpt_test),
    FunctionTool(func=search_feature_tests),
    FunctionTool(func=fetch_spec_content),
  ]

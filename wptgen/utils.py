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

import random
import re
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

T = TypeVar('T')
P = ParamSpec('P')

# Regular expressions for parsing and sanitization
SUGGESTION_BLOCK_RE = re.compile(r'<test_suggestion>.*?</test_suggestion>', re.DOTALL)
FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')
MARKDOWN_CODE_BLOCK_RE = re.compile(r'^```html\s*|^```\s*|\s*```$', re.MULTILINE)
MULTI_FILE_RE = re.compile(r'\[FILE_(\d+):\s*(.*?)\](.*?)\[/FILE_\1\]', re.DOTALL)

# Maximum delay between retries in seconds
MAX_DELAY = 60.0

# Default maximum number of retry attempts for transient failures
MAX_RETRIES = 5


def extract_xml_tag(text: str, tag: str) -> str | None:
  """Extracts the content of an XML-like tag from a string."""
  match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
  return match.group(1).strip() if match else None


def parse_suggestions(raw_text: str) -> list[str]:
  """Extracts all test suggestion blocks from a raw LLM response."""
  return SUGGESTION_BLOCK_RE.findall(raw_text)


def parse_multi_file_response(raw_text: str) -> list[tuple[str, str]]:
  """Extracts multiple files from a partitioned LLM response.

  Expected format:
  [FILE_1: .flags.html]
  content
  [/FILE_1]

  This function ensures the filename returned is a suffix (starting with a dot).
  If the LLM provides a full filename, it shaves off the start until the first dot.
  """
  files = []
  for match in MULTI_FILE_RE.finditer(raw_text):
    suffix = match.group(2).strip()
    # Shave off the start if it doesn't lead with a period
    if suffix and not suffix.startswith('.'):
      dot_idx = suffix.find('.')
      if dot_idx != -1:
        suffix = suffix[dot_idx:]
      else:
        # Fallback if no dot found at all - prepend a dot
        suffix = '.' + suffix

    content = match.group(3).strip()
    files.append((suffix, content))
  return files


def fix_reftest_link(test_content: str, ref_filename: str) -> str:
  """Verifies and updates the <link rel="match" href="..."> tag in a reftest.

  Args:
    test_content: The HTML content of the test file.
    ref_filename: The name of the reference file (e.g., 'counter-set-001-ref.html').

  Returns:
    The updated HTML content with the correct <link rel="match" href="..."> tag.
  """
  # Pattern to match the <link rel="match" href="..."> tag.
  # Flexible with single/double quotes, whitespace, and self-closing tags.
  link_re = re.compile(
    r'<link\s+[^>]*rel=["\']match["\'][^>]*href=["\'](.*?)["\'][^>]*\/?>'
    r'|<link\s+[^>]*href=["\'](.*?)["\'][^>]*rel=["\']match["\'][^>]*\/?>',
    re.IGNORECASE | re.DOTALL,
  )

  new_link = f'<link rel="match" href="{ref_filename}">'

  if link_re.search(test_content):
    # Update existing link
    return link_re.sub(new_link, test_content)

  # If no link tag exists, add it to the <head> section.
  head_re = re.compile(r'(<head.*?>)', re.IGNORECASE)
  if head_re.search(test_content):
    return head_re.sub(r'\1\n' + new_link, test_content, count=1)

  # Fallback: find <html> tag
  html_re = re.compile(r'(<html.*?>)', re.IGNORECASE)
  if html_re.search(test_content):
    return html_re.sub(r'\1\n' + new_link, test_content, count=1)

  # Absolute fallback: prepend to content
  return new_link + '\n' + test_content


def get_next_available_root(
  feature_id: str,
  output_dir: Path,
  used_names: set[str],
  max_len: int = 150,
) -> str:
  """Finds the next available root filename using the {feature_id}-{num} convention.

  Args:
    feature_id: The ID of the web feature.
    output_dir: The directory where tests are saved.
    used_names: A set of root names already planned to be used in this run.
    max_len: The maximum allowed length for the filename (including potential suffixes).

  Returns:
    The available root filename (e.g., 'feature-001').
  """
  safe_feature_id = FILENAME_SANITIZATION_RE.sub('_', feature_id.lower())

  # We reserve some space for suffixes like '.https.any.js' (~20 chars)
  # and potentially '-ref' for reftests (4 chars).
  suffix_buffer = 25
  allowed_feature_id_len = max_len - suffix_buffer - 4  # -4 for '-001'

  truncated_feature_id = safe_feature_id[:allowed_feature_id_len]

  n = 1
  while True:
    num_str = f'{n:03d}' if n < 1000 else str(n)
    root_name = f'{truncated_feature_id}-{num_str}'

    # Collision check:
    # 1. Check if we've already used this root in this run.
    if root_name in used_names:
      n += 1
      continue

    # 2. Check if any file in the output directory starts with this root name.
    # This is conservative but ensures we don't collide regardless of extension/flags.
    collision = False
    if output_dir.exists():
      for path in output_dir.iterdir():
        if path.name.startswith(root_name):
          collision = True
          break

    if not collision:
      used_names.add(root_name)
      return root_name

    n += 1


def retry(
  exceptions: type[Exception] | tuple[type[Exception], ...],
  max_attempts: int = 3,
  max_attempts_attr: str | None = None,
  initial_delay: float = 1.0,
  backoff_factor: float = 2.0,
  jitter: bool = True,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
  """
  A decorator that retries a function with exponential backoff.

  Args:
    exceptions: The exception(s) that should trigger a retry.
    max_attempts: Maximum number of attempts before giving up (static).
    max_attempts_attr: If provided, look up this attribute on 'self' for the max attempts.
      This takes precedence over 'max_attempts'.
    initial_delay: Initial delay between retries in seconds.
    backoff_factor: Multiplier for the delay after each attempt.
    jitter: Whether to add random jitter to the delay.
  """

  def decorator(func: Callable[P, T]) -> Callable[P, T]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
      # Determine the actual max attempts
      if max_attempts_attr is not None:
        if not args:
          raise ValueError(
            f"Cannot find attribute '{max_attempts_attr}' because 'self' is missing from arguments."
          )
        try:
          actual_max_attempts = getattr(args[0], max_attempts_attr)
        except AttributeError as e:
          raise ValueError(
            f"Argument 'self' (type {type(args[0]).__name__}) has no attribute '{max_attempts_attr}'."
          ) from e
      else:
        actual_max_attempts = max_attempts

      # Cap the max attempts at the global MAX_RETRIES limit
      actual_max_attempts = min(actual_max_attempts, MAX_RETRIES)

      # Validate max_attempts is a positive integer
      if not isinstance(actual_max_attempts, int) or actual_max_attempts < 1:
        raise ValueError(f'max_attempts must be an integer >= 1, got {actual_max_attempts}')

      delay = initial_delay

      for attempt in range(1, actual_max_attempts + 1):
        try:
          return func(*args, **kwargs)
        except exceptions:
          # If we've reached the maximum attempts, re-raise the caught exception natively
          if attempt == actual_max_attempts:
            raise

          sleep_time = min(delay, MAX_DELAY)
          if jitter:
            sleep_time *= random.uniform(0.5, 1.5)

          time.sleep(sleep_time)
          delay *= backoff_factor

      # Satisfy the type checker. This code is mathematically unreachable at runtime
      # because the loop will always either return or raise on its final iteration.
      raise AssertionError('Unreachable code reached in retry decorator')  # pragma: no cover

    return wrapper

  return decorator

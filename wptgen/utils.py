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
from typing import ParamSpec, TypeVar

T = TypeVar('T')
P = ParamSpec('P')

# Regular expressions for parsing and sanitization
SUGGESTION_BLOCK_RE = re.compile(r'<test_suggestion>.*?</test_suggestion>', re.DOTALL)
FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')
MARKDOWN_CODE_BLOCK_RE = re.compile(r'^```html\s*|^```\s*|\s*```$', re.MULTILINE)

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

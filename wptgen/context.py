# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from trafilatura import extract, fetch_url

logger = logging.getLogger(__name__)


def fetch_feature_yaml(web_feature_id: str) -> dict[str, Any] | None:
  """
  Fetches the YAML definition for a given web feature ID from the
  web-platform-dx/web-features repository.

  Returns the parsed YAML dictionary, or None if the feature ID is not found.
  """
  url = f'https://raw.githubusercontent.com/web-platform-dx/web-features/main/features/{web_feature_id}.yml'

  try:
    # Use standard library to avoid bloating dependencies
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
      yaml_content = response.read().decode('utf-8')

      # Use safe_load to securely parse the YAML string into a Python dictionary
      return yaml.safe_load(yaml_content)

  except urllib.error.HTTPError as e:
    if e.code == 404:
      # Feature ID doesn't exist in the repository
      return None
    # If it's a 500 error or rate limit, we want it to crash loudly so we know
    raise e


def extract_spec_url(feature_data: dict[str, Any]) -> str | None:
  """
  Safely extracts the primary specification URL from the parsed feature data.
  """
  spec = feature_data.get('spec')

  if not spec:
    return None

  # Sometimes the spec field is a single URL string
  if isinstance(spec, str):
    return spec

  # Sometimes it might be formatted as a list of URLs
  # TODO(DanielRyanSmith): Handle multiple specs.
  if isinstance(spec, list) and len(spec) > 0:
    return spec[0]

  return None


def fetch_and_extract_text(url: str) -> str | None:
  """
  Fetches the HTML content from a URL and extracts the core textual content,
  stripping away navigation, footers, and boilerplate.

  Returns the content formatted as Markdown.
  """
  logger.info(f'Fetching content from: {url}')

  # Fetch the raw HTML
  downloaded_html = fetch_url(url)

  if not downloaded_html:
    logger.error(f'Failed to download HTML from {url}')
    return None

  # Extract the core content
  content = extract(
    downloaded_html,
    output_format='markdown',
    include_comments=False,
    include_tables=True,  # Specs rely heavily on tables for state definitions
    include_links=False,  # Strip hyperlinks to save tokens
  )

  if not content:
    logger.warning(f'Could not extract meaningful text from {url}')
    return None

  return content


def find_feature_tests(target_directory: str, feature_id: str) -> list[str]:
  """
  Scans a directory recursively for test files relevant to a specific feature ID.
  """
  base_dir = Path(target_directory).resolve()
  if not base_dir.is_dir():
    raise ValueError(f'The directory provided does not exist: {base_dir}')

  relevant_files: set[str] = set()
  TARGET_METADATA_FILE = 'WEB_FEATURES.yml'

  # rglob recursively finds all WEB_FEATURES.yml files in the entire repository
  for yaml_path in base_dir.rglob(TARGET_METADATA_FILE):
    try:
      with open(yaml_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)

      if not data or 'features' not in data:
        continue

      feature_config = next((f for f in data['features'] if f.get('name') == feature_id), None)

      if feature_config:
        patterns = feature_config.get('files', [])
        # Pass the directory containing the YAML file
        matched_files = _resolve_patterns(yaml_path.parent, patterns)
        relevant_files.update(matched_files)

    except yaml.YAMLError:
      continue
    except Exception as e:
      print(f'Error processing {yaml_path}: {e}')

  # Convert back to a sorted list of absolute string paths
  return sorted(relevant_files)


def _resolve_patterns(directory: Path, patterns: list[str]) -> set[str]:
  """
  Helper function to match file patterns recursively against files in a directory.
  """
  all_files = [
    p for p in directory.rglob('*') if p.is_file() and p.suffix.lower() not in ('.yml', '.yaml')
  ]

  selected_files: set[Path] = set()

  for pattern in patterns:
    is_negative = pattern.startswith('!')
    clean_pattern = pattern[1:] if is_negative else pattern

    matches = set()
    for f in all_files:
      rel_path = f.relative_to(directory)

      # 1. Standard strict match
      is_match = rel_path.match(clean_pattern)

      # If pattern is `**/*.html`, it misses root files like `test.html`.
      # We strip `**/` and check if `test.html` matches `*.html`.
      if not is_match and clean_pattern.startswith('**/'):
        is_match = rel_path.match(clean_pattern[3:])

      if is_match:
        matches.add(f)

    if is_negative:
      selected_files.difference_update(matches)
    else:
      selected_files.update(matches)

  return {str(f) for f in selected_files}

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

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import markdownify
import yaml
from bs4 import BeautifulSoup

from wptgen.models import WebFeatureMetadata, WPTContext

__all__ = ['WebFeatureMetadata', 'WPTContext']

logger = logging.getLogger(__name__)

# Match <script src="...">
SCRIPT_DEPENDENCY_REGEX = re.compile(r'<script\s+[^>]*src=["\']([^"\']+)["\']')

# Match import/export ... from "..." or import "..."
IMPORT_DEPENDENCY_REGEX = re.compile(
  r'(?:import|export)\s+(?:[^"\']+\s+from\s+)?["\']([^"\']+)["\']'
)

# WPT infrastructure files that should not be aggregated as dependencies
IGNORED_DEPENDENCIES = {
  '/resources/testharness.js',
  '/resources/testharnessreport.js',
  '/resources/testdriver.js',
  '/resources/testdriver-vendor.js',
}
MDN_MAPPINGS_URL = 'https://raw.githubusercontent.com/web-platform-dx/web-features-mappings/main/mappings/mdn-docs.json'


def fetch_feature_yaml(web_feature_id: str, draft: bool = False) -> dict[str, Any] | None:
  """
  Fetches the YAML definition for a given web feature ID from the
  web-platform-dx/web-features repository.

  Returns the parsed YAML dictionary, or None if the feature ID is not found.
  """
  if draft:
    url = f'https://raw.githubusercontent.com/web-platform-dx/web-features/main/features/draft/spec/{web_feature_id}.yml'
  else:
    url = f'https://raw.githubusercontent.com/web-platform-dx/web-features/main/features/{web_feature_id}.yml'

  try:
    # Use standard library to avoid bloating dependencies
    # Set User-Agent to bypass generic bot filters and identify our crawler
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
      yaml_content = response.read().decode('utf-8')

      # Use safe_load to securely parse the YAML string into a Python dictionary
      data = yaml.safe_load(yaml_content)
      if data is None or isinstance(data, dict):
        return data
      return None

  except urllib.error.HTTPError as e:
    if e.code == 404:
      # Feature ID doesn't exist in the repository
      return None
    # If it's a 500 error or rate limit, we want it to crash loudly so we know
    raise e


def fetch_mdn_urls(web_feature_id: str) -> list[str]:
  """
  Fetches the MDN mapping for a given web feature ID from the
  web-platform-dx/web-features-mappings repository.

  Returns a list of MDN documentation URLs, or an empty list if not found.
  """

  try:
    # Set User-Agent to bypass generic bot filters and identify our crawler
    req = urllib.request.Request(MDN_MAPPINGS_URL)
    with urllib.request.urlopen(req) as response:
      json_content = response.read().decode('utf-8')
      data = json.loads(json_content)

      feature_mappings = data.get(web_feature_id, [])
      return [item['url'] for item in feature_mappings if 'url' in item]

  except (urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
    logger.warning(f'Could not fetch or parse MDN mapping: {e}')
    return []


def extract_feature_metadata(feature_data: dict[str, Any]) -> WebFeatureMetadata:
  """
  Extracts the high-level metadata (name and description) from the feature data.

  Returns:
    Dict containing important feature metadata.
  """
  spec_info = feature_data.get('spec')
  specs = []
  if isinstance(spec_info, list):
    specs = spec_info
  elif isinstance(spec_info, str):
    specs.append(spec_info)

  return WebFeatureMetadata(
    name=str(feature_data.get('name', 'Unknown Feature')),
    description=str(feature_data.get('description', '')),
    specs=specs,
  )


def fetch_and_extract_text(url: str) -> str | None:
  """
  Fetches the HTML content from a URL and extracts the core textual content,
  stripping away navigation, footers, and boilerplate.
  Returns the content formatted as Markdown.
  """
  logger.info(f'Fetching content from: {url}')

  try:
    # Set User-Agent to bypass generic bot filters and identify our crawler
    req = urllib.request.Request(
      url, headers={'User-Agent': 'Mozilla/5.0 (compatible; WPT-Gen/1.0)'}
    )
    with urllib.request.urlopen(req) as response:
      html = response.read().decode('utf-8')
  except Exception as e:
    logger.error(f'Failed to download HTML from {url}: {e}')
    return None

  soup = BeautifulSoup(html, 'lxml')

  # Strip out boilerplate that isn't spec content
  for element in soup(['nav', 'script', 'style', 'footer', 'head', 'link', 'meta', 'noscript']):
    element.extract()

  # Find the main content area. Specs usually use <main>, <div class="main">, or just body
  main_content = soup.find('main') or soup.find('div', class_='main') or soup.find('body')

  if not main_content:
    logger.warning(f'Could not find main content block in {url}')
    return None

  # Pre-process <a> tags to preserve internal specification links (fragments)
  # but strip external URLs to conserve token limits.
  for a_tag in main_content.find_all('a'):
    href = a_tag.get('href')
    if not isinstance(href, str) or not href.startswith('#'):
      a_tag.unwrap()

  # Convert the HTML tree to markdown, omitting external link URLs to save token space
  content = markdownify.markdownify(
    str(main_content),
    heading_style='ATX',
    strip=['img', 'picture', 'video', 'audio', 'iframe'],
  )

  content = content.strip()
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
  target_metadata_file = 'WEB_FEATURES.yml'

  # rglob recursively finds all WEB_FEATURES.yml files in the entire repository
  for yaml_path in base_dir.rglob(target_metadata_file):
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


def extract_dependencies(content: str) -> list[str]:
  """
  Scans file content for references to other files.
  """
  # Strip HTML comments to avoid picking up commented-out dependencies
  clean_content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)

  dependencies = set()
  dependencies.update(re.findall(SCRIPT_DEPENDENCY_REGEX, clean_content))
  dependencies.update(re.findall(IMPORT_DEPENDENCY_REGEX, clean_content))

  # Filter out common WPT infrastructure files that don't need to be aggregated
  return [d for d in dependencies if d not in IGNORED_DEPENDENCIES]


def resolve_dependency_path(current_file_path: Path, dep_ref: str, wpt_root: Path) -> Path | None:
  """
  Resolves a dependency reference to a concrete local WPT repository path.
  """
  if dep_ref.startswith(('http', '//', 'https')):
    return None

  current_dir = current_file_path.parent

  if dep_ref.startswith('/'):
    # Absolute path relative to repo root
    resolved = wpt_root / dep_ref.lstrip('/')
  else:
    # Relative path
    resolved = (current_dir / dep_ref).resolve()

  try:
    # Ensure it's still inside the WPT root
    resolved.relative_to(wpt_root)
    if resolved.is_file():
      return resolved
  except (ValueError, OSError):
    pass
  return None


def gather_local_test_context(test_paths: list[str], wpt_root: str) -> WPTContext:
  """
  Recursively gathers the content of test files and all their dependencies from the local disk.
  """
  root = Path(wpt_root).resolve()
  test_contents: dict[str, str] = {}
  dependency_contents: dict[str, str] = {}
  test_to_deps: dict[str, set[str]] = {}

  dependency_graph: dict[str, set[str]] = {}
  visited: set[str] = set()

  # Initialize queue with (absolute_path, is_test)
  queue: list[tuple[str, bool]] = []
  for p in test_paths:
    abs_p = str(Path(p).resolve())
    queue.append((abs_p, True))
    visited.add(abs_p)

  MAX_DEPS = 100
  idx = 0
  while idx < len(queue):
    curr_p_str, is_test = queue[idx]
    idx += 1

    curr_p = Path(curr_p_str)
    try:
      content = curr_p.read_text(encoding='utf-8')
      if is_test:
        test_contents[curr_p_str] = content
      else:
        dependency_contents[curr_p_str] = content

      deps = extract_dependencies(content)
      for dep_ref in deps:
        resolved = resolve_dependency_path(curr_p, dep_ref, root)
        if resolved:
          resolved_str = str(resolved)

          if curr_p_str not in dependency_graph:
            dependency_graph[curr_p_str] = set()
          dependency_graph[curr_p_str].add(resolved_str)

          if resolved_str not in visited:
            if len(visited) < (len(test_paths) + MAX_DEPS):
              visited.add(resolved_str)
              queue.append((resolved_str, False))
    except Exception as e:
      logger.warning(f'Error reading dependency {curr_p_str}: {e}')

  # Build the reachability map
  for test_p_str in test_contents:
    relevant_deps = set()
    stack = [test_p_str]
    seen_in_traversal = {test_p_str}

    while stack:
      curr = stack.pop()
      if curr != test_p_str:
        relevant_deps.add(curr)

      if curr in dependency_graph:
        for child in dependency_graph[curr]:
          if child not in seen_in_traversal:
            seen_in_traversal.add(child)
            stack.append(child)

    test_to_deps[test_p_str] = relevant_deps

  return WPTContext(
    test_contents=test_contents,
    dependency_contents=dependency_contents,
    test_to_deps=test_to_deps,
  )

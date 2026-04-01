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

"""Functions for assembly and management of web feature context."""

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import markdownify
import yaml
from bs4 import BeautifulSoup

from wptgen.models import DataSource, FeatureMetadata, WPTContext

__all__ = ["DataSource", "FeatureMetadata", "WPTContext"]

logger = logging.getLogger(__name__)

# Match <script src="...">
SCRIPT_DEPENDENCY_REGEX = re.compile(r'<script\s+[^>]*src=["\']([^"\']+)["\']')

# Match import/export ... from "..." or import "..."
IMPORT_DEPENDENCY_REGEX = re.compile(
    r'(?:import|export)\s+(?:[^"\']+\s+from\s+)?["\']([^"\']+)["\']'
)

# WPT infrastructure files that should not be aggregated as dependencies
IGNORED_DEPENDENCIES = {
    "/resources/testharness.js",
    "/resources/testharnessreport.js",
    "/resources/testdriver.js",
    "/resources/testdriver-vendor.js",
}

MAXIMUM_TEST_SUITE_SIZE = 50
MAXIMUM_FETCHED_DEPENDENCIES = 100

MDN_MAPPINGS_URL = (
    "https://raw.githubusercontent.com/web-platform-dx/"
    "web-features-mappings/main/mappings/mdn-docs.json"
)


def fetch_feature_yaml(
    web_feature_id: str, draft: bool = False
) -> dict[str, Any] | None:
    """
    Fetches the YAML definition for a given web feature ID from the
    web-platform-dx/web-features repository.

    Returns the parsed YAML dictionary, or None if the feature ID is not found.
    """
    if draft:
        url = (
            "https://raw.githubusercontent.com/web-platform-dx/web-features/"
            f"main/features/draft/spec/{web_feature_id}.yml"
        )
    else:
        url = (
            "https://raw.githubusercontent.com/web-platform-dx/web-features/"
            f"main/features/{web_feature_id}.yml"
        )

    try:
        # Use standard library to avoid bloating dependencies
        # Set User-Agent to bypass generic bot filters and identify our crawler
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            yaml_content = response.read().decode("utf-8")

            # Use safe_load to securely parse the YAML string into a Python dict
            data = yaml.safe_load(yaml_content)
            if data is None or isinstance(data, dict):
                return data
            return None

    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Feature ID doesn't exist in the repository
            return None
        # If it's a 500 error or rate limit, we want it to crash loudly so we
        # know.
        raise e


def fetch_chromestatus_metadata(feature_id: str) -> FeatureMetadata | None:
    """
    Fetches the metadata for a given feature ID from the ChromeStatus
    Features API.

    Returns a FeatureMetadata object, or None if the feature ID is not found.
    """
    url = f"https://chromestatus.com/api/v0/features/{feature_id}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WPT-Gen/1.0"})
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            # ChromeStatus API often prefixes JSON with a vulnerability
            # protection string.
            if content.startswith(")]}'\n"):
                content = content[5:]
            elif content.startswith(")]}'"):
                content = content[4:]

            data = json.loads(content)

            # Map ChromeStatus fields to FeatureMetadata
            # ChromeStatus API returns a single object for this endpoint.
            feature = data[0] if isinstance(data, list) else data

            name = feature.get("name", "Unknown Feature")
            description = feature.get("summary", "")
            explainer_links = feature.get("explainer_links", [])
            wpt_descr = feature.get("wpt_descr", "")

            # ChromeStatus usually has spec_link
            specs = []
            spec_link = feature.get("spec_link")
            if spec_link:
                specs.append(spec_link)

            return FeatureMetadata(
                name=name,
                description=description,
                specs=specs,
                source=DataSource.CHROMESTATUS,
                explainer_links=explainer_links,
                wpt_descr=wpt_descr,
            )

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.warning("ChromeStatus API error for %s: %s", feature_id, e)
        return None
    except (
        urllib.error.URLError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
    ) as e:
        logger.warning(
            "Could not fetch or parse ChromeStatus metadata for %s: %s",
            feature_id,
            e,
        )
        return None


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
            json_content = response.read().decode("utf-8")
            data = json.loads(json_content)

            feature_mappings = data.get(web_feature_id, [])
            return [item["url"] for item in feature_mappings if "url" in item]

    except (urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Could not fetch or parse MDN mapping: %s", e)
        return []


def fetch_explainer_contents(urls: list[str]) -> dict[str, str]:
    """
    Fetches and extracts text content from a list of explainer URLs.

    Returns:
      Dictionary mapping each URL to its extracted markdown content.
    """
    contents = {}
    for url in urls:
        res = fetch_and_extract_text(url)
        if res:
            contents[url] = res
    return contents


def extract_feature_metadata(feature_data: dict[str, Any]) -> FeatureMetadata:
    """Extracts high-level metadata (name and description) from feature data.

    Returns:
      Dict containing important feature metadata.
    """
    spec_info = feature_data.get("spec")
    specs = []
    if isinstance(spec_info, list):
        specs = spec_info
    elif isinstance(spec_info, str):
        specs.append(spec_info)

    return FeatureMetadata(
        name=str(feature_data.get("name", "Unknown Feature")),
        description=str(feature_data.get("description", "")),
        specs=specs,
    )


def fetch_and_extract_text(url: str) -> str | None:
    """
    Fetches the HTML content from a URL and extracts the core textual content,
    stripping away navigation, footers, and boilerplate.
    Returns the content formatted as Markdown.
    """
    logger.info("Fetching content from: %s", url)

    try:
        # Set User-Agent to bypass generic bot filters and identify our crawler
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; WPT-Gen/1.0)"}
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        logger.error("Failed to download HTML from %s: %s", url, e)
        return None

    soup = BeautifulSoup(html, "lxml")

    # Strip out boilerplate that isn't spec content
    for element in soup(
        ["nav", "script", "style", "footer", "head", "link", "meta", "noscript"]
    ):
        element.extract()

    # Find the main content area. Specs usually use <main>, <div class="main">,
    # or just body.
    main_content = (
        soup.find("main")
        or soup.find("div", class_="main")
        or soup.find("body")
    )

    if not main_content:
        logger.warning("Could not find main content block in %s", url)
        return None

    # Pre-process <a> tags to preserve internal specification links (fragments)
    # but strip external URLs to conserve token limits.
    for a_tag in main_content.find_all("a"):
        href = a_tag.get("href")
        if not isinstance(href, str) or not href.startswith("#"):
            a_tag.unwrap()

    # Convert HTML tree to markdown, omitting external link URLs to save tokens.
    content = markdownify.markdownify(
        str(main_content),
        heading_style="ATX",
        strip=["img", "picture", "video", "audio", "iframe"],
    )

    content = content.strip()
    if not content:
        logger.warning("Could not extract meaningful text from %s", url)
        return None

    return content


def extract_wpt_paths(wpt_descr: str) -> list[str]:
    """Extracts WPT paths from a ChromeStatus 'wpt_descr' string.

    Exclusively handles URLs from wpt.fyi.
    """
    if not wpt_descr:
        return []

    # Regex to match any URL-like structure starting with http/https
    url_pattern = r"https?://[^\s\n,]+"
    urls = re.findall(url_pattern, wpt_descr)

    extracted_paths: set[str] = set()

    # Process each found URL
    for url in urls:
        # Strip common punctuation that might be appended to URLs.
        clean_url = url.rstrip(".,;)]")
        try:
            parsed = urlparse(clean_url)
            if parsed.netloc == "wpt.fyi":
                # Logic mirroring ChromeStatus: extract path after '/results/'
                path_prefix = "/results/"
                if parsed.path.startswith(path_prefix):
                    path = parsed.path[len(path_prefix) :].strip("/")
                    if path:
                        extracted_paths.add(path)
        except (ValueError, AttributeError):
            # If URL parsing fails for any reason, skip and continue
            continue

    return sorted(extracted_paths)


def normalize_wpt_path(path: str) -> str:
    """Normalizes .any. variants to their source .any.js file."""
    if ".any." in path:
        # Matches '.../test.any.worker.html' -> '.../test.any.js'
        idx = path.find(".any.") + 5  # index after ".any."
        return path[:idx] + "js"
    return path


def is_wpt_test_file(path: Path) -> bool:
    """Checks if the file name matches conditions for a WPT test file.

    Filters out non-test files like .yml, .md, .py, .ini, .headers, and hidden.
    """
    filename = path.name
    suffix = path.suffix.lower()

    # Skip directories (this helper is for file-level checks)
    if path.is_dir():
        return False

    # Filter based on extension
    if suffix in (".yml", ".yaml", ".md", ".py", ".ini", ".headers", ".txt"):
        return False

    # Filter out special WPT files
    if filename in ("MANIFEST", "META.yml", "WEB_FEATURES.yml"):
        return False

    # Filter out reference files
    if "-ref." in filename:
        return False

    # Filter out hidden files
    if filename.startswith("."):
        return False

    return True


def validate_wpt_paths(
    paths: list[str], wpt_root: str
) -> tuple[list[str], list[str]]:
    """Validates that WPT paths exist in the local repository.

    Returns a tuple of (valid_paths, invalid_paths).
    If a path is a directory, it expands to tests within it (top-level only).
    Handles fallback from .html to .js if the file does not exist.
    Enforces MAXIMUM_TEST_SUITE_SIZE.
    """
    root = Path(wpt_root).resolve()
    valid_paths: set[str] = set()
    invalid_paths: list[str] = []

    for p in paths:
        # Normalize and Resolve
        normalized_p = normalize_wpt_path(p.lstrip("/"))
        abs_p = (root / normalized_p).resolve()

        try:
            # Ensure the path is within the WPT root
            abs_p.relative_to(root)
        except ValueError:
            invalid_paths.append(p)
            continue

        # 1. Handle HTML-to-JS fallback for files
        if not abs_p.exists() and abs_p.suffix == ".html":
            js_p = abs_p.with_suffix(".js")
            if js_p.exists():
                abs_p = js_p

        if abs_p.exists():
            if abs_p.is_file():
                if is_wpt_test_file(abs_p):
                    valid_paths.add(str(abs_p))
                else:
                    # If it is a known non-test file, ignore it
                    pass
            elif abs_p.is_dir():
                # Directory Scanning (Top-level only, matching ChromeStatus)
                for test_file in abs_p.iterdir():
                    if is_wpt_test_file(test_file):
                        # Apply normalization to files found in directory
                        normalized_file = normalize_wpt_path(str(test_file))
                        valid_paths.add(normalized_file)
            else:
                invalid_paths.append(p)
        else:
            invalid_paths.append(p)

    # CRITICAL: Safety limit check
    if len(valid_paths) > MAXIMUM_TEST_SUITE_SIZE:
        raise ValueError(
            f"Too many tests found ({len(valid_paths)}). "
            f"Max allowed is {MAXIMUM_TEST_SUITE_SIZE}."
        )

    return sorted(valid_paths), invalid_paths


def find_feature_tests(target_directory: str, feature_id: str) -> list[str]:
    """Scans a directory for test files relevant to a specific feature ID."""
    base_dir = Path(target_directory).resolve()
    if not base_dir.is_dir():
        raise ValueError(f"The directory provided does not exist: {base_dir}")

    relevant_files: set[str] = set()
    target_metadata_file = "WEB_FEATURES.yml"

    # rglob recursively finds all WEB_FEATURES.yml files in the repository
    for yaml_path in base_dir.rglob(target_metadata_file):
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "features" not in data:
                continue

            feature_config = next(
                (f for f in data["features"] if f.get("name") == feature_id),
                None,
            )

            if feature_config:
                patterns = feature_config.get("files", [])
                # Pass the directory containing the YAML file
                matched_files = _resolve_patterns(yaml_path.parent, patterns)
                relevant_files.update(matched_files)

        except yaml.YAMLError:
            continue
        except Exception as e:
            logger.warning("Error processing %s: %s", yaml_path, e)

    # Convert back to a sorted list of absolute string paths
    return sorted(relevant_files)


def _resolve_patterns(directory: Path, patterns: list[str]) -> set[str]:
    """Helper to match file patterns recursively against files in directory."""
    all_files = [
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() not in (".yml", ".yaml")
    ]

    selected_files: set[Path] = set()

    for pattern in patterns:
        is_negative = pattern.startswith("!")
        clean_pattern = pattern[1:] if is_negative else pattern

        matches = set()
        for f in all_files:
            rel_path = f.relative_to(directory)

            # 1. Standard strict match
            is_match = rel_path.match(clean_pattern)

            # If pattern is `**/*.html`, it misses root files like `test.html`.
            # We strip `**/` and check if `test.html` matches `*.html`.
            if not is_match and clean_pattern.startswith("**/"):
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
    clean_content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

    dependencies = set()
    dependencies.update(re.findall(SCRIPT_DEPENDENCY_REGEX, clean_content))
    dependencies.update(re.findall(IMPORT_DEPENDENCY_REGEX, clean_content))

    # Filter out common WPT infrastructure files
    return [d for d in dependencies if d not in IGNORED_DEPENDENCIES]


def resolve_dependency_path(
    current_file_path: Path, dep_ref: str, wpt_root: Path
) -> Path | None:
    """
    Resolves a dependency reference to a concrete local WPT repository path.
    """
    if dep_ref.startswith(("http", "//", "https")):
        return None

    current_dir = current_file_path.parent

    if dep_ref.startswith("/"):
        # Absolute path relative to repo root
        resolved = wpt_root / dep_ref.lstrip("/")
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


def gather_local_test_context(
    test_paths: list[str], wpt_root: str
) -> WPTContext:
    """Recursively gathers test files and dependencies from the local disk.

    Enforces MAXIMUM_FETCHED_DEPENDENCIES.
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

    initial_test_count = len(visited)
    idx = 0
    while idx < len(queue):
        curr_p_str, is_test = queue[idx]
        idx += 1

        curr_p = Path(curr_p_str)

        # Exclude reference files from context assembly
        if is_test and "-ref." in curr_p.name:
            continue

        try:
            content = curr_p.read_text(encoding="utf-8")
            if is_test:
                test_contents[curr_p_str] = content
            else:
                dependency_contents[curr_p_str] = content

            if len(dependency_contents) < MAXIMUM_FETCHED_DEPENDENCIES:
                deps = extract_dependencies(content)
                for dep_ref in deps:
                    resolved = resolve_dependency_path(curr_p, dep_ref, root)
                    if resolved:
                        resolved_str = str(resolved)

                        if curr_p_str not in dependency_graph:
                            dependency_graph[curr_p_str] = set()
                        dependency_graph[curr_p_str].add(resolved_str)

                        if resolved_str not in visited:
                            limit = (
                                initial_test_count
                                + MAXIMUM_FETCHED_DEPENDENCIES
                            )
                            if len(visited) < limit:
                                visited.add(resolved_str)
                                queue.append((resolved_str, False))
        except Exception as e:
            logger.warning("Error reading dependency %s: %s", curr_p_str, e)

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

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

import asyncio

from wptgen.config import Config
from wptgen.context import (
    FeatureMetadata,
    extract_feature_metadata,
    extract_wpt_paths,
    fetch_and_extract_text,
    fetch_chromestatus_metadata,
    fetch_feature_yaml,
    fetch_mdn_urls,
    find_feature_tests,
    gather_local_test_context,
    validate_wpt_paths,
)
from wptgen.models import WorkflowContext
from wptgen.ui import UIProvider


async def run_context_assembly(
    web_feature_id: str, config: Config, ui: UIProvider
) -> WorkflowContext | None:
    ui.on_phase_start(1, "Context Assembly")

    if config.chromestatus:
        metadata = await asyncio.to_thread(
            fetch_chromestatus_metadata, web_feature_id
        )
        if not metadata:
            ui.error(f"Feature {web_feature_id} not found on ChromeStatus.")
            return None
    else:
        feature_data = fetch_feature_yaml(web_feature_id, draft=config.draft)
        if not feature_data:
            if config.spec_urls and config.feature_description:
                ui.warning(
                    f"Feature {web_feature_id} not found in the web-features repository."
                )
                metadata = FeatureMetadata(
                    name=web_feature_id,
                    description=config.feature_description,
                    specs=config.spec_urls,
                )
            else:
                ui.error(f"Feature {web_feature_id} not found.")
                ui.print(
                    "To generate tests for an unregistered feature, please provide both a spec URL using --spec-urls "
                    "and a description using --description."
                )
                return None
        else:
            metadata = extract_feature_metadata(feature_data)

    if config.spec_urls:
        metadata.specs = config.spec_urls
    if config.feature_description:
        metadata.description = config.feature_description

    if not metadata.specs:
        ui.error("No specification URL found.")
        return None

    ui.report_metadata(metadata)

    ui.print("\nFetching spec content...")
    with ui.status("Fetching and extracting text..."):
        results = await asyncio.gather(
            *[
                asyncio.to_thread(fetch_and_extract_text, url)
                for url in metadata.specs
            ],
            return_exceptions=True,
        )
        spec_contents: dict[str, str] = {}
        for url, res in zip(metadata.specs, results, strict=True):
            if isinstance(res, Exception):
                ui.warning(f"Failed to fetch spec ({url}): {res}")
            elif isinstance(res, str):
                spec_contents[url] = res

    if not spec_contents:
        ui.error("Failed to extract spec content.")
        return None

    explainer_contents: dict[str, str] | None = None
    if metadata.explainer_links:
        ui.print("Fetching explainer content...")
        with ui.status("Fetching and extracting text from explainers..."):
            # Fetch all explainers concurrently using to_thread since fetch_and_extract_text is blocking
            results = await asyncio.gather(
                *[
                    asyncio.to_thread(fetch_and_extract_text, url)
                    for url in metadata.explainer_links
                ],
                return_exceptions=True,
            )
            explainer_contents = {}
            for url, res in zip(metadata.explainer_links, results, strict=True):
                if isinstance(res, Exception):
                    ui.warning(
                        f"Failed to fetch or extract content from explainer ({url}): {res}"
                    )
                elif isinstance(res, str):
                    explainer_contents[url] = res
                else:
                    ui.warning(
                        f"Failed to fetch or extract meaningful text from explainer: {url}"
                    )

    ui.print(
        "Scanning local WPT repository for existing tests and dependencies..."
    )
    test_paths = find_feature_tests(config.wpt_path, web_feature_id)
    extracted_wpt_urls: list[str] | None = None

    # If ChromeStatus is enabled, also extract and validate tests from wpt_descr
    if config.chromestatus and metadata.wpt_descr:
        with ui.status("Extracting tests from ChromeStatus..."):
            extracted_wpt_urls = extract_wpt_paths(metadata.wpt_descr)
            if extracted_wpt_urls:
                try:
                    valid_paths, invalid_paths = validate_wpt_paths(
                        extracted_wpt_urls, config.wpt_path
                    )
                    for invalid in invalid_paths:
                        ui.warning(
                            f"Referenced WPT test file could not be found or read: {invalid}"
                        )
                    # Merge unique valid paths
                    test_paths = sorted(set(test_paths) | set(valid_paths))
                except ValueError as e:
                    ui.warning(f"Skipping ChromeStatus tests: {e}")

    if not test_paths:
        ui.warning("No existing Web Platform Tests were successfully loaded.")

    wpt_context = gather_local_test_context(test_paths, config.wpt_path)

    mdn_contents: list[str] | None = None
    if config.include_mdn_docs and not config.chromestatus:
        ui.print("Fetching MDN documentation...")
        mdn_urls = fetch_mdn_urls(web_feature_id)
        if mdn_urls:
            with ui.status(f"Fetching {len(mdn_urls)} MDN pages..."):
                # Fetch all MDN pages asynchronously using to_thread for the synchronous fetch_and_extract_text
                results = await asyncio.gather(
                    *[
                        asyncio.to_thread(fetch_and_extract_text, url)
                        for url in mdn_urls
                    ],
                    return_exceptions=True,
                )
                mdn_contents = []
                for url, res in zip(mdn_urls, results, strict=True):
                    if isinstance(res, Exception):
                        ui.warning(f"Failed to fetch MDN page ({url}): {res}")
                    elif isinstance(res, str):
                        mdn_contents.append(
                            f"# Documentation from {url}\n\n{res}"
                        )
    elif config.chromestatus and config.include_mdn_docs:
        ui.print("Skipping MDN documentation fetch for ChromeStatus feature.")
    else:
        ui.print("Skipping MDN documentation fetch (not requested).")

    if config.chromestatus:
        ui.report_context_summary(
            spec_len=sum(len(content) for content in spec_contents.values()),
            explainer_count=len(explainer_contents)
            if explainer_contents
            else 0,
            test_count=len(wpt_context.test_contents),
        )
    else:
        ui.report_context_summary(
            spec_len=sum(len(content) for content in spec_contents.values()),
            mdn_count=len(mdn_contents) if mdn_contents else 0,
            test_count=len(wpt_context.test_contents),
            dep_count=len(wpt_context.dependency_contents),
        )

    return WorkflowContext(
        feature_id=web_feature_id,
        metadata=metadata,
        spec_contents=spec_contents,
        explainer_contents=explainer_contents,
        mdn_contents=mdn_contents,
        wpt_context=wpt_context,
        wpt_urls=extracted_wpt_urls,
    )

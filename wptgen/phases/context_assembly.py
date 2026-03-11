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
from pathlib import Path

from wptgen.config import Config
from wptgen.context import (
  WebFeatureMetadata,
  extract_chromestatus_metadata,
  extract_feature_metadata,
  extract_wpt_paths_from_descr,
  fetch_and_extract_text,
  fetch_chromestatus_feature,
  fetch_feature_yaml,
  fetch_mdn_urls,
  find_feature_tests,
  gather_local_test_context,
)
from wptgen.models import WorkflowContext
from wptgen.ui import UIProvider


async def run_context_assembly(
  web_feature_id: str, config: Config, ui: UIProvider
) -> WorkflowContext | None:
  ui.on_phase_start(1, 'Context Assembly')

  feature_data = fetch_feature_yaml(web_feature_id, draft=config.draft)
  if not feature_data:
    if config.spec_urls and config.feature_description:
      ui.warning(f'Feature {web_feature_id} not found in the web-features repository.')
      metadata = WebFeatureMetadata(
        name=web_feature_id,
        description=config.feature_description,
        specs=config.spec_urls,
      )
    else:
      ui.error(f'Feature {web_feature_id} not found.')
      ui.print(
        'To generate tests for an unregistered feature, please provide both a spec URL using --spec-urls '
        'and a description using --description.'
      )
      return None
  else:
    metadata = extract_feature_metadata(feature_data)
    if config.spec_urls:
      metadata.specs = config.spec_urls
    if config.feature_description:
      metadata.description = config.feature_description

  if not metadata.specs:
    ui.error('No specification URL found.')
    return None

  ui.report_metadata(metadata)

  ui.print('\nFetching spec content...')
  with ui.status('Fetching and extracting text...'):
    results = await asyncio.gather(
      *[asyncio.to_thread(fetch_and_extract_text, url) for url in metadata.specs]
    )
    spec_contents = {url: res for url, res in zip(metadata.specs, results, strict=True) if res}

  if not spec_contents:
    ui.error('Failed to extract spec content.')
    return None

  ui.print('Scanning local WPT repository for existing tests and dependencies...')
  test_paths = find_feature_tests(config.wpt_path, web_feature_id)
  wpt_context = gather_local_test_context(test_paths, config.wpt_path)

  ui.print('Fetching MDN documentation...')
  mdn_contents: list[str] | None = None
  mdn_urls = fetch_mdn_urls(web_feature_id)
  if mdn_urls:
    with ui.status(f'Fetching {len(mdn_urls)} MDN pages...'):
      # Fetch all MDN pages asynchronously using to_thread for the synchronous fetch_and_extract_text
      results = await asyncio.gather(
        *[asyncio.to_thread(fetch_and_extract_text, url) for url in mdn_urls]
      )
      mdn_contents = [
        f'# Documentation from {url}\n\n{res}'
        for url, res in zip(mdn_urls, results, strict=True)
        if res
      ]

  ui.report_context_summary(
    sum(len(content) for content in spec_contents.values()),
    len(mdn_contents) if mdn_contents else 0,
    len(wpt_context.test_contents),
    len(wpt_context.dependency_contents),
  )

  return WorkflowContext(
    feature_id=web_feature_id,
    metadata=metadata,
    spec_contents=spec_contents,
    mdn_contents=mdn_contents,
    wpt_context=wpt_context,
  )


async def run_chromestatus_context_assembly(
  feature_id: str, config: Config, ui: UIProvider
) -> WorkflowContext | None:
  ui.on_phase_start(1, 'ChromeStatus Context Assembly')

  feature_data = fetch_chromestatus_feature(feature_id)
  if not feature_data:
    ui.error(f'ChromeStatus feature {feature_id} not found.')
    return None

  metadata = extract_chromestatus_metadata(feature_data)

  # Override with CLI options if provided
  if config.spec_urls:
    metadata.specs = config.spec_urls
  if config.feature_description:
    metadata.description = config.feature_description

  if not metadata.specs:
    ui.error('No specification URL found in ChromeStatus data.')
    return None

  # Detailed resource discovery logging
  spec_link = feature_data.get('spec_link')
  standards_spec = (
    feature_data.get('standards', {}).get('spec')
    if isinstance(feature_data.get('standards'), dict)
    else None
  )
  found_specs = {s for s in [spec_link, standards_spec] if s}

  explainers = feature_data.get('explainer_links', [])
  if not isinstance(explainers, list):
    explainers = []

  wpt_descr = feature_data.get('wpt_descr', '')
  raw_test_paths = extract_wpt_paths_from_descr(wpt_descr)

  ui.print(
    f'Found [cyan]{len(found_specs)}[/cyan] spec links, '
    f"[cyan]{len(raw_test_paths)}[/cyan] test references in 'wpt_descr', and "
    f'[cyan]{len(explainers)}[/cyan] explainer links.'
  )

  ui.report_metadata(metadata)

  ui.print('\nFetching spec content...')
  with ui.status('Fetching and extracting text...'):
    results = await asyncio.gather(
      *[asyncio.to_thread(fetch_and_extract_text, url) for url in metadata.specs]
    )
    spec_contents = {url: res for url, res in zip(metadata.specs, results, strict=True) if res}

  if not spec_contents:
    ui.error('Failed to extract spec content.')
    return None

  # Use wpt_descr to find existing tests
  wpt_descr = feature_data.get('wpt_descr', '')
  test_paths = []
  if wpt_descr:
    ui.print("Extracting existing test paths from 'wpt_descr'...")
    raw_paths = extract_wpt_paths_from_descr(wpt_descr)
    if raw_paths:
      ui.print(f"Found {len(raw_paths)} test references in 'wpt_descr'.")
      for rp in raw_paths:
        local_path = Path(config.wpt_path) / rp.lstrip('/')
        if local_path.exists():
          if local_path.is_file():
            test_paths.append(str(local_path))
          elif local_path.is_dir():
            # If it's a directory, include all files inside
            test_paths.extend([str(f) for f in local_path.rglob('*') if f.is_file()])
    else:
      ui.print("No test references found in 'wpt_descr'.")

  if test_paths:
    ui.print(f'Gathering context for {len(test_paths)} local WPT test files...')
    wpt_context = gather_local_test_context(test_paths, config.wpt_path)
  else:
    ui.warning(
      "No local WPT files found for the references in 'wpt_descr'. Skipping local WPT scan."
    )
    wpt_context = gather_local_test_context([], config.wpt_path)

  ui.report_chromestatus_context_summary(
    sum(len(content) for content in spec_contents.values()),
    len(explainers),
    len(wpt_context.test_contents),
  )

  return WorkflowContext(
    feature_id=f'chromestatus_{feature_id}',
    metadata=metadata,
    spec_contents=spec_contents,
    mdn_contents=None,  # MDN docs are not used in ChromeStatus workflow
    wpt_context=wpt_context,
  )

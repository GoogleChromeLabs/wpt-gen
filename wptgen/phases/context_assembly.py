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
  WebFeatureMetadata,
  extract_feature_metadata,
  fetch_and_extract_text,
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

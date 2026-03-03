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

from rich.table import Table

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
  ui.rule('Phase 1: Context Assembly')

  feature_data = fetch_feature_yaml(web_feature_id)
  if not feature_data:
    if config.spec_urls and config.feature_description:
      ui.print(
        f'[yellow]Warning:[/yellow] Feature [bold]{web_feature_id}[/bold] not found in the web-features repository.'
      )
      metadata = WebFeatureMetadata(
        name=web_feature_id,
        description=config.feature_description,
        specs=config.spec_urls,
      )
    else:
      ui.print(f'[bold red]Error:[/bold red] Feature {web_feature_id} not found.')
      ui.print(
        'To generate tests for an unregistered feature, please provide both a spec URL using [bold]--spec-urls[/bold] '
        'and a description using [bold]--description[/bold].'
      )
      return None
  else:
    metadata = extract_feature_metadata(feature_data)
    if config.spec_urls:
      metadata.specs = config.spec_urls
    if config.feature_description:
      metadata.description = config.feature_description

  if not metadata.specs:
    ui.print('[bold red]Error:[/bold red] No specification URL found.')
    return None

  metadata_table = Table(show_header=False, box=None, padding=(0, 2))
  metadata_table.add_row('[bold]Web Feature Name:[/bold]', f'[cyan]{metadata.name}[/cyan]')
  metadata_table.add_row('[bold]Description:[/bold]', metadata.description)
  metadata_table.add_row('[bold]Spec URL:[/bold]', f'[blue]{metadata.specs[0]}[/blue]')

  ui.display_panel(metadata_table, title='Feature Metadata')

  ui.print('\nFetching spec content...')
  with ui.status('[blue]Fetching and extracting text...[/blue]'):
    spec_contents = fetch_and_extract_text(metadata.specs[0])

  if not spec_contents:
    ui.print('[bold red]Error:[/bold red] Failed to extract spec content.')
    return None

  ui.print('Scanning local WPT repository for existing tests and dependencies...')
  test_paths = find_feature_tests(config.wpt_path, web_feature_id)
  wpt_context = gather_local_test_context(test_paths, config.wpt_path)

  ui.print('Fetching MDN documentation...')
  mdn_contents: list[str] | None = None
  mdn_urls = fetch_mdn_urls(web_feature_id)
  if mdn_urls:
    with ui.status(f'[blue]Fetching {len(mdn_urls)} MDN pages...[/blue]'):
      # Fetch all MDN pages asynchronously using to_thread for the synchronous fetch_and_extract_text
      results = await asyncio.gather(
        *[asyncio.to_thread(fetch_and_extract_text, url) for url in mdn_urls]
      )
      mdn_contents = [
        f'# Documentation from {url}\n\n{res}'
        for url, res in zip(mdn_urls, results, strict=True)
        if res
      ]

  ui.print(
    f'✔ Context gathered: {len(spec_contents)} chars of spec, '
    f'{len(mdn_contents) if mdn_contents else 0} MDN pages, '
    f'{len(wpt_context.test_contents)} tests, '
    f'{len(wpt_context.dependency_contents)} dependency files.'
  )

  return WorkflowContext(
    feature_id=web_feature_id,
    metadata=metadata,
    spec_contents=spec_contents,
    mdn_contents=mdn_contents,
    wpt_context=wpt_context,
  )

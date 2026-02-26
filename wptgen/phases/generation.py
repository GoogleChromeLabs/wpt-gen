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

from jinja2 import Environment
from rich.table import Table

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import STYLE_GUIDE_MAP, TestType, WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import (
  FILENAME_SANITIZATION_RE,
  MARKDOWN_CODE_BLOCK_RE,
  extract_xml_tag,
  parse_suggestions,
)


async def run_test_generation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
  ui.rule('Phase 4: User Selection & Generation')

  assert context.audit_response is not None
  assert context.metadata is not None

  # Check for satisfaction status
  status = extract_xml_tag(context.audit_response, 'status')
  if status and status.strip() == 'SATISFIED':
    ui.display_panel(
      '[bold green]All identified test requirements have been satisfied.[/bold green]\n'
      '[italic]No new test suggestions were generated because existing coverage is sufficient.[/italic]',
      title='Status',
      border_style='green',
    )
    return []

  suggestions = parse_suggestions(context.audit_response)

  if not suggestions:
    ui.print('[yellow]No valid <test_suggestion> blocks found in the LLM response.[/yellow]')
    return []

  ui.print(f'[bold green]{len(suggestions)}[/bold green] new test suggestions found!\n')
  approved_suggestions_xml: list[str] = []

  for idx, xml_block in enumerate(suggestions):
    title = extract_xml_tag(xml_block, 'title') or f'Suggestion #{idx + 1}'
    desc = extract_xml_tag(xml_block, 'description') or 'No description available'

    ui.display_panel(
      f'[italic]{desc}[/italic]',
      title=f'Suggestion {idx + 1}: {title}',
      border_style='blue',
    )
    if ui.confirm('Generate this test?', default=True):
      approved_suggestions_xml.append(xml_block)
    ui.print()

  if not approved_suggestions_xml:
    ui.print('[yellow]No tests selected. Exiting.[/yellow]')
    return []

  # Load the general style guide
  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  # Prepare templates
  gen_template = jinja_env.get_template('test_generation.jinja')
  system_template = jinja_env.get_template('test_generation_system.jinja')

  prompts_to_confirm: list[tuple[str, str, str, str]] = []

  for idx, suggestion_xml in enumerate(approved_suggestions_xml):
    # Extract and normalize test type
    raw_test_type = extract_xml_tag(suggestion_xml, 'test_type') or 'JavaScript Test'
    test_type_enum = TestType.JAVASCRIPT
    for member in TestType:
      if member.value.lower() == raw_test_type.lower():
        test_type_enum = member
        break

    # Load the specific style guide for this test type
    guide_filename = STYLE_GUIDE_MAP.get(test_type_enum, 'javascript_html_style_guide.md')
    test_type_guide = (resources_path / guide_filename).read_text(encoding='utf-8')

    # Render the system instruction with both general and type-specific rules
    system_instruction = system_template.render(
      wpt_style_guide=wpt_style_guide,
      test_type=test_type_enum.value,
      test_type_guide=test_type_guide,
    )

    final_prompt = gen_template.render(
      feature_name=context.metadata.name,
      feature_description=context.metadata.description,
      test_suggestion_xml_block=suggestion_xml,
    )

    raw_title = extract_xml_tag(suggestion_xml, 'title') or 'file'
    # Include index to prevent filename collisions
    slug = FILENAME_SANITIZATION_RE.sub('_', raw_title.lower())
    safe_filename = f'{slug}__GENERATED_{idx + 1:02d}_.html'

    prompts_to_confirm.append((final_prompt, safe_filename, suggestion_xml, system_instruction))

  # Single confirmation for ALL tests
  await confirm_prompts(
    [(p, f) for p, f, s, si in prompts_to_confirm],
    f'Generate {len(prompts_to_confirm)} Tests',
    llm,
    ui,
    config,
    model=config.get_model_for_phase('generation'),
  )

  ui.print(f'\nGenerating [bold]{len(prompts_to_confirm)}[/bold] tests in parallel...')

  tasks = [
    _generate_and_save(
      prompt, filename, suggestion_xml, llm, ui, config, system_instruction, temperature=0.1
    )
    for prompt, filename, suggestion_xml, system_instruction in prompts_to_confirm
  ]
  results = await asyncio.gather(*tasks)

  # Filter out None values and show a final summary for this phase
  final_results = [r for r in results if r is not None]

  if final_results:
    summary_table = Table(
      title='Generated Tests Summary', show_header=True, header_style='bold green'
    )
    summary_table.add_column('File Name', style='cyan')
    summary_table.add_column('Full Path', style='dim')

    for p, _content, _s_xml in final_results:
      summary_table.add_row(p.name, str(p.absolute()))

    ui.print()
    ui.display_table(summary_table)
    ui.print(f'\n[bold green]✔ {len(final_results)} tests generated successfully.[/bold green]')
  else:
    ui.print('\n[bold red]✘ No tests were successfully generated.[/bold red]')

  return final_results


async def _generate_and_save(
  prompt: str,
  filename: str,
  suggestion_xml: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str | None = None,
  temperature: float | None = None,
) -> tuple[Path, str, str] | None:
  """Helper to generate a specific test and save it to disk."""
  ui.print(f'Starting generation for: [bold]{filename}[/bold]...')
  content = await generate_safe(
    prompt,
    f'Gen: {filename}',
    llm,
    ui,
    config,
    system_instruction,
    temperature,
    model=config.get_model_for_phase('generation'),
  )

  if content:
    # Strip Markdown code blocks if the LLM added them (common behavior)
    clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', content).strip()
    output_path = Path(config.output_dir or '.') / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(clean_content, encoding='utf-8')
    ui.print(f'[green]✔ Saved:[/green] {output_path.absolute()}')
    return output_path, clean_content, suggestion_xml
  return None

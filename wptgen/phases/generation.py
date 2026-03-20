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
from rich.rule import Rule

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import STYLE_GUIDE_MAP, TestType, WorkflowContext, WorkflowPhase
from wptgen.ui import UIProvider
from wptgen.utils import (
  extract_xml_tag,
  get_next_available_root,
  parse_suggestions,
)


async def run_test_generation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
  ui.on_phase_start(4, 'User Selection & Generation')

  assert context.audit_response is not None
  assert context.metadata is not None

  # Check for satisfaction status
  status = extract_xml_tag(context.audit_response, 'status')
  if status and status.strip() == 'SATISFIED':
    ui.success('All identified test requirements have been satisfied.')
    ui.info('No new test suggestions were generated because existing coverage is sufficient.')
    return []

  # Display the audit worksheet in a formatted table
  audit_worksheet = extract_xml_tag(context.audit_response, 'audit_worksheet')
  if audit_worksheet:
    ui.report_audit_worksheet(audit_worksheet)

  suggestions = parse_suggestions(context.audit_response)

  if not suggestions:
    ui.warning('No valid <test_suggestion> blocks found in the LLM response.')
    return []

  ui.success(f'{len(suggestions)} new test suggestions found!\n')

  approved_suggestions_xml = []
  for i, suggestion in enumerate(suggestions):
    title = extract_xml_tag(suggestion, 'title') or f'Suggestion #{i + 1}'
    description = extract_xml_tag(suggestion, 'description') or 'No description provided.'
    test_type = extract_xml_tag(suggestion, 'test_type')

    ui.report_test_suggestion(i + 1, title, description, test_type)
    if config.yes_tests or ui.confirm('Generate this test?'):
      approved_suggestions_xml.append(suggestion)

  if not approved_suggestions_xml:
    ui.warning('No tests selected. Exiting.')
    return []

  if config.agentic_generation:
    return await _generate_agentic_loop(approved_suggestions_xml, context, config, ui, jinja_env)

  return await _generate_adk_loop(approved_suggestions_xml, context, config, ui, jinja_env)


def _format_test_suggestion(
  suggestion_xml: str, feature_id: str, spec_urls: list[str], sanitize: bool = False
) -> str:
  if sanitize:
    description = extract_xml_tag(suggestion_xml, 'description') or 'No description provided.'
    lines = ['<test_suggestion>']
    lines.append(f'  <description>{description}</description>')
    for url in spec_urls:
      lines.append(f'  <spec_url>{url}</spec_url>')
    lines.append(f'  <web_feature_id>{feature_id}</web_feature_id>')
    lines.append('</test_suggestion>')
    return '\n'.join(lines)
  else:
    # Just inject spec_urls and web_feature_id into the existing XML
    lines = []
    for url in spec_urls:
      lines.append(f'  <spec_url>{url}</spec_url>')
    lines.append(f'  <web_feature_id>{feature_id}</web_feature_id>')
    additions = '\n'.join(lines)
    return suggestion_xml.replace('</test_suggestion>', f'{additions}\n</test_suggestion>')


async def _generate_agentic_loop(
  approved_suggestions_xml: list[str],
  context: WorkflowContext,
  config: Config,
  ui: UIProvider,
  jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
  """Runs the gemini CLI as a subprocess to handle test generation natively."""
  ui.report_generation_start(len(approved_suggestions_xml))

  model = config.get_model_for_phase(WorkflowPhase.GENERATION) or config.default_model
  agentic_template = jinja_env.get_template('agentic_test_generation.jinja')

  spec_urls = context.metadata.specs if context.metadata and context.metadata.specs else []

  for i, suggestion_xml in enumerate(approved_suggestions_xml):
    # Sanitize and strictly enforce the <test_suggestion> block structure
    modified_xml = _format_test_suggestion(
      suggestion_xml, context.feature_id, spec_urls, sanitize=True
    )

    prompt = agentic_template.render(
      test_suggestion_xml_block=modified_xml,
      is_interactive=not config.agentic_yolo,
    )

    if config.agentic_yolo:
      # Use bash -ic to force an interactive shell so it loads aliases/nvm.
      # -p ensures the CLI exits automatically after completion.
      cmd = ['bash', '-ic', f'gemini --yolo --model {model} -p "$0"', prompt]
    else:
      cmd = ['bash', '-ic', f'gemini --model {model} "$0"', prompt]

    ui.print(
      f'\n[bold blue]Starting Agentic Generation #{i + 1} for: {context.feature_id}[/bold blue]'
    )
    ui.print(Rule('[bold cyan]🤖 Gemini CLI[/bold cyan]', style='cyan', align='left'))

    process = await asyncio.create_subprocess_exec(
      *cmd,
      cwd=config.wpt_path,
      stdout=asyncio.subprocess.PIPE if config.agentic_yolo else None,
      stderr=asyncio.subprocess.PIPE if config.agentic_yolo else None,
    )

    if config.agentic_yolo:

      async def _stream_output(
        stream: asyncio.StreamReader | None, is_stderr: bool = False
      ) -> None:
        if not stream:
          return
        while True:
          line = await stream.readline()
          if not line:
            break
          text = line.decode('utf-8').rstrip()
          if is_stderr:
            ui.print(f'[cyan]│[/cyan] [white]{text}[/white]')
          else:
            ui.print(f'[cyan]│[/cyan] {text}')

      await asyncio.gather(
        _stream_output(process.stdout), _stream_output(process.stderr, is_stderr=True)
      )

    await process.wait()
    ui.print(Rule(style='cyan'))

    if process.returncode != 0:
      ui.error(
        f'Agentic generation for suggestion #{i + 1} failed with exit code {process.returncode}'
      )
    else:
      ui.success(f'Agentic generation for suggestion #{i + 1} completed successfully.')

  # Agentic generation handles saving natively, so we return an empty memory state.
  return []


async def _generate_adk_loop(
  approved_suggestions_xml: list[str],
  context: WorkflowContext,
  config: Config,
  ui: UIProvider,
  jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
  from wptgen.agents.adk_test_generator import generate_test_with_adk

  ui.report_generation_start(len(approved_suggestions_xml))

  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  spec_urls = context.metadata.specs if context.metadata and context.metadata.specs else []
  output_dir = Path(config.output_dir or '.')
  used_names: set[str] = set()

  tasks = []

  for suggestion_xml in approved_suggestions_xml:
    modified_xml = _format_test_suggestion(
      suggestion_xml, context.feature_id, spec_urls, sanitize=config.brief_suggestions
    )

    raw_test_type = extract_xml_tag(modified_xml, 'test_type') or 'JavaScript Test'
    test_type_enum = TestType.JAVASCRIPT
    for member in TestType:
      if member.value.lower() == raw_test_type.lower():
        test_type_enum = member
        break

    root_name = get_next_available_root(context.feature_id, output_dir, used_names)
    used_names.add(root_name)
    guide_filename = STYLE_GUIDE_MAP.get(test_type_enum, 'javascript_html_style_guide.md')
    test_type_guide = (resources_path / guide_filename).read_text(encoding='utf-8')

    tasks.append(
      generate_test_with_adk(
        modified_xml,
        root_name,
        test_type_enum,
        context,
        config,
        jinja_env,
        ui,
        wpt_style_guide,
        test_type_guide,
      )
    )

  results = []

  # Unlike standard generation, ADK streams its events to the UI directly.
  # So we await them sequentially here so the streaming output doesn't garble together.
  ui.print('\n[bold cyan]Starting ADK Test Generation...[/bold cyan]')

  for i, task in enumerate(tasks):
    ui.print(f'\n[bold yellow]--- Generating Test {i + 1} of {len(tasks)} ---[/bold yellow]')
    ui.print(Rule('[bold cyan]🤖 WPT-Gen Agent[/bold cyan]', style='cyan', align='left'))
    result = await task
    ui.print(Rule(style='cyan'))
    results.append(result)

  final_results = [r for sublist in results for r in sublist]

  ui.report_generation_summary(final_results)

  return final_results

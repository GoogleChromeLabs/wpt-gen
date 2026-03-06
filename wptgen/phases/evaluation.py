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
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import STYLE_GUIDE_MAP, TestType, WorkflowContext
from wptgen.phases.utils import generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import MARKDOWN_CODE_BLOCK_RE, extract_xml_tag, parse_multi_file_response


async def run_test_evaluation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  generated_tests: list[tuple[Path, str, str]],
) -> None:
  """Runs the evaluation phase for generated tests."""
  ui.rule('Phase 5: Evaluation')

  # Group tests by their suggestion XML to handle multi-file tests (Reftests) together
  grouped_tests: dict[str, list[tuple[Path, str]]] = defaultdict(list)
  for path, content, suggestion_xml in generated_tests:
    grouped_tests[suggestion_xml].append((path, content))

  ui.print(f'Evaluating [bold]{len(grouped_tests)}[/bold] test suggestions...')

  # Load the general style guide
  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  # Prepare templates
  evaluation_template = jinja_env.get_template('evaluation.jinja')
  system_template = jinja_env.get_template('evaluation_system.jinja')

  tasks = []
  for suggestion_xml, group in grouped_tests.items():
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

    # Determine filenames for reftests to pass to the system instruction
    safe_filename = None
    ref_filename = None
    if test_type_enum == TestType.REFTEST:
      for p, _ in group:
        if p.name.endswith('-ref.html'):
          ref_filename = p.name
        else:
          safe_filename = p.name
    elif len(group) == 1:
      safe_filename = group[0][0].name

    # Render the system instruction with both general and type-specific rules
    system_instruction = system_template.render(
      wpt_style_guide=wpt_style_guide,
      test_type=test_type_enum.value,
      test_type_guide=test_type_guide,
      safe_filename=safe_filename,
      ref_filename=ref_filename,
    )

    # Format the code content, using multi-file partitioning for Reftests
    if len(group) > 1:
      generated_code_content = ''
      for i, (p, c) in enumerate(group, 1):
        generated_code_content += f'[FILE_{i}: {p.name}]\n{c}\n[/FILE_{i}]\n\n'
    else:
      generated_code_content = group[0][1]

    prompt = evaluation_template.render(
      test_suggestion_xml=suggestion_xml,
      generated_code_content=generated_code_content.strip(),
    )
    tasks.append(_evaluate_and_update(group, prompt, llm, ui, config, system_instruction))

  await asyncio.gather(*tasks)
  ui.print('\n[bold green]✔ Evaluation phase complete.[/bold green]')


async def _evaluate_and_update(
  files: list[tuple[Path, str]],
  prompt: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str,
) -> None:
  """Evaluates a single test (or multi-file test) and updates the file(s) if needed."""
  display_names = ', '.join([p.name for p, _ in files])
  ui.print(f'Evaluating: [bold]{display_names}[/bold]...')

  response = await generate_safe(
    prompt,
    f'Eval: {display_names}',
    llm,
    ui,
    config,
    system_instruction,
    temperature=0.01,
    model=config.get_model_for_phase('evaluation'),
  )

  if not response:
    ui.print(f'[yellow]⚠ No response for evaluation of {display_names}. Keeping original.[/yellow]')
    return

  clean_response = response.strip()

  if clean_response == 'PASS':
    ui.print(f'[green]✔ {display_names} passed evaluation.[/green]')
  else:
    # If it's not PASS, it should be the corrected file content
    # Check if we have multiple files in the response
    multi_files = parse_multi_file_response(clean_response)
    if multi_files:
      for fname, fcontent in multi_files:
        # Find the matching path from our input files
        for path, _ in files:
          if path.name == fname:
            clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', fcontent).strip()
            path.write_text(clean_content, encoding='utf-8')
            ui.print(f'[cyan]ℹ {path.name} was corrected and updated.[/cyan]')
            break
    else:
      # If it's a single file correction
      if len(files) == 1:
        path = files[0][0]
        clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', clean_response).strip()
        path.write_text(clean_content, encoding='utf-8')
        ui.print(f'[cyan]ℹ {path.name} was corrected and updated.[/cyan]')
      else:
        ui.print(
          f'[yellow]⚠ Received single-file correction for multi-file test {display_names}. Skipping.[/yellow]'
        )

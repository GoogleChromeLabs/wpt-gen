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

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import MARKDOWN_CODE_BLOCK_RE


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
  ui.print(f'Evaluating [bold]{len(generated_tests)}[/bold] tests...')

  # Load the style guide
  style_guide_path = Path(__file__).parent.parent / 'templates' / 'resources' / 'wpt_style_guide.md'
  style_guide = style_guide_path.read_text(encoding='utf-8')

  # Prepare system instruction
  system_instruction = jinja_env.get_template('evaluation_system.jinja').render(
    wpt_style_guide=style_guide
  )

  evaluation_template = jinja_env.get_template('evaluation.jinja')

  tasks = []
  for path, content, suggestion_xml in generated_tests:
    prompt = evaluation_template.render(
      test_suggestion_xml=suggestion_xml,
      generated_code_content=content,
    )
    tasks.append(_evaluate_and_update(path, prompt, llm, ui, config, system_instruction))

  await asyncio.gather(*tasks)
  ui.print('\n[bold green]✔ Evaluation phase complete.[/bold green]')


async def _evaluate_and_update(
  path: Path,
  prompt: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str,
) -> None:
  """Evaluates a single test and updates the file if needed."""
  ui.print(f'Evaluating: [bold]{path.name}[/bold]...')

  response = await generate_safe(
    prompt,
    f'Eval: {path.name}',
    llm,
    ui,
    config,
    system_instruction,
    temperature=0.0,
    model=config.get_model_for_phase('evaluation'),
  )

  if not response:
    ui.print(f'[yellow]⚠ No response for evaluation of {path.name}. Keeping original.[/yellow]')
    return

  clean_response = response.strip()

  if clean_response == 'PASS':
    ui.print(f'[green]✔ {path.name} passed evaluation.[/green]')
  else:
    # If it's not PASS, it should be the corrected file content
    # Strip Markdown code blocks if the LLM added them
    clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', clean_response).strip()
    path.write_text(clean_content, encoding='utf-8')
    ui.print(f'[cyan]ℹ {path.name} was corrected and updated.[/cyan]')

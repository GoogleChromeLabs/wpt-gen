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

import re
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider

FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')


async def run_coverage_audit(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> str | None:
  ui.rule('Phase 3: Coverage Audit')

  audit_prompt = jinja_env.get_template('coverage_audit.jinja').render(
    requirements_list_xml=context.requirements_xml,
    wpt_context=context.wpt_context,
  )
  audit_system_prompt = jinja_env.get_template('coverage_audit_system.jinja').render()

  await confirm_prompts(
    [(audit_prompt, 'Coverage Audit')],
    'Coverage Audit',
    llm,
    ui,
    config,
    model=config.get_model_for_phase('coverage_audit'),
  )

  audit_response = await generate_safe(
    audit_prompt,
    'Coverage Audit',
    llm,
    ui,
    config,
    system_instruction=audit_system_prompt,
    temperature=0.01,
    model=config.get_model_for_phase('coverage_audit'),
  )

  context.audit_response = audit_response
  return audit_response


async def provide_coverage_report(context: WorkflowContext, config: Config, ui: UIProvider) -> None:
  """Prints the coverage audit report and optionally saves it to a file."""
  ui.rule('Coverage Audit Report')
  assert context.audit_response is not None
  ui.display_markdown(context.audit_response)
  ui.print()

  if ui.confirm('\nSave report to a file?'):
    # Create a sanitized filename from the feature ID
    safe_id = FILENAME_SANITIZATION_RE.sub('_', context.feature_id.lower())
    filename = f'{safe_id}_coverage_audit.md'

    output_path = Path(config.output_dir or '.') / filename
    try:
      output_path.parent.mkdir(parents=True, exist_ok=True)
      output_path.write_text(context.audit_response, encoding='utf-8')
      ui.print(f'[green]Saved:[/green] {output_path.absolute()}')
    except Exception as e:
      ui.print(f'[bold red]Error saving file:[/bold red] {e}')

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

from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider


async def run_requirements_extraction(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  cache_dir: Path,
) -> str | None:
  ui.rule('Phase 2: Requirements Extraction')

  assert context.metadata is not None

  web_feature_id = context.feature_id
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  requirements_xml = None

  if cache_file.exists():
    ui.print(f'[yellow]Found cached requirements for {web_feature_id}.[/yellow]')
    if ui.confirm('Use cached requirements?'):
      requirements_xml = cache_file.read_text(encoding='utf-8')
      ui.print('✔ Using cached requirements.')

  if not requirements_xml:
    extraction_prompt = jinja_env.get_template('requirements_extraction.jinja').render(
      feature_name=context.metadata.name,
      feature_description=context.metadata.description,
      spec_url=context.metadata.specs[0],
      spec_contents=context.spec_contents,
    )
    extraction_system_prompt = jinja_env.get_template(
      'requirements_extraction_system.jinja'
    ).render()

    await confirm_prompts(
      [(extraction_prompt, 'Requirements Extraction')],
      'Requirements Extraction',
      llm,
      ui,
      config,
      model=config.requirements_model,
    )

    requirements_xml = await generate_safe(
      extraction_prompt,
      'Requirements Extraction',
      llm,
      ui,
      config,
      system_instruction=extraction_system_prompt,
      temperature=0.0,
      model=config.requirements_model,
    )

    if not requirements_xml:
      return None

    # Save to cache
    cache_file.write_text(requirements_xml, encoding='utf-8')

  context.requirements_xml = requirements_xml
  return requirements_xml

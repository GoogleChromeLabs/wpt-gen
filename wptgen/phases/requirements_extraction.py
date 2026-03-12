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
import re
from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import REQUIREMENT_CATEGORIES, WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider


async def run_requirements_extraction(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  cache_dir: Path,
  save_state_callback: Callable[[WorkflowContext], None] | None = None,
) -> str | None:
  ui.on_phase_start(2, 'Requirements Extraction')

  assert context.metadata is not None

  web_feature_id = context.feature_id
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  requirements_xml = None

  if cache_file.exists():
    ui.info(f'Found cached requirements for {web_feature_id}.')
    if ui.confirm('Use cached requirements?'):
      requirements_xml = cache_file.read_text(encoding='utf-8')
      ui.success('Using cached requirements.')

  if not requirements_xml:
    extraction_prompt = jinja_env.get_template('requirements_extraction.jinja').render(
      feature_name=context.metadata.name,
      feature_description=context.metadata.description,
      specs=context.spec_contents,
      mdn_contents=context.mdn_contents,
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
      model=config.get_model_for_phase('requirements_extraction'),
    )

    requirements_xml = await generate_safe(
      extraction_prompt,
      'Requirements Extraction',
      llm,
      ui,
      config,
      system_instruction=extraction_system_prompt,
      temperature=0.01,
      model=config.get_model_for_phase('requirements_extraction'),
    )

    if not requirements_xml:
      return None

    # Save to cache
    cache_file.write_text(requirements_xml, encoding='utf-8')

  count = len(re.findall(r'<requirement\b[^>]*>', requirements_xml))
  ui.success(f'Extracted {count} test requirements.')

  context.requirements_xml = requirements_xml
  return requirements_xml


async def run_requirements_extraction_categorized(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  cache_dir: Path,
  save_state_callback: Callable[[WorkflowContext], None] | None = None,
) -> str | None:
  ui.on_phase_start(2, 'Requirements Extraction (Categorized)')

  assert context.metadata is not None

  web_feature_id = context.feature_id
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  requirements_xml = None

  if cache_file.exists():
    ui.info(f'Found cached requirements for {web_feature_id}.')
    if ui.confirm('Use cached requirements?'):
      requirements_xml = cache_file.read_text(encoding='utf-8')
      ui.success('Using cached requirements.')

  if not requirements_xml:
    metadata = context.metadata
    assert metadata is not None

    prompts_to_confirm = []
    category_prompts = []
    category_system_prompts = []

    for category_name, category_description in REQUIREMENT_CATEGORIES:
      extraction_prompt = jinja_env.get_template(
        'requirements_extraction_categorized.jinja'
      ).render(
        feature_name=metadata.name,
        feature_description=metadata.description,
        specs=context.spec_contents,
        mdn_contents=context.mdn_contents,
      )
      extraction_system_prompt = jinja_env.get_template(
        'requirements_extraction_categorized_system.jinja'
      ).render(
        category_name=category_name,
        category_description=category_description,
      )
      category_prompts.append(extraction_prompt)
      category_system_prompts.append(extraction_system_prompt)
      prompts_to_confirm.append((extraction_prompt, f'Requirements Extraction: {category_name}'))

    await confirm_prompts(
      prompts_to_confirm,
      'Requirements Extraction (Categorized Parallel)',
      llm,
      ui,
      config,
      model=config.get_model_for_phase('requirements_extraction'),
    )

    async def extract_for_category(
      category_name: str, extraction_prompt: str, extraction_system_prompt: str
    ) -> str | None:
      return await generate_safe(
        extraction_prompt,
        f'Requirements Extraction: {category_name}',
        llm,
        ui,
        config,
        system_instruction=extraction_system_prompt,
        temperature=0.01,
        model=config.get_model_for_phase('requirements_extraction'),
      )

    ui.info(f'Launching {len(REQUIREMENT_CATEGORIES)} parallel extraction requests...')
    total_tasks = len(REQUIREMENT_CATEGORIES)
    completed_count = 0

    async def wrap_with_progress(
      name: str, extraction_prompt: str, extraction_system_prompt: str
    ) -> str | None:
      nonlocal completed_count
      res = await extract_for_category(name, extraction_prompt, extraction_system_prompt)
      completed_count += 1
      remaining = total_tasks - completed_count
      progress.update(
        description='Extracting requirements...', outstanding=remaining if remaining > 0 else None
      )
      progress.advance()
      return res

    with ui.progress_indicator(
      f'Extracting requirements... ({total_tasks} outstanding)', total=total_tasks
    ) as progress:
      responses = await asyncio.gather(
        *[
          wrap_with_progress(cat[0], prompt, sys_prompt)
          for cat, prompt, sys_prompt in zip(
            REQUIREMENT_CATEGORIES, category_prompts, category_system_prompts, strict=True
          )
        ]
      )

    all_requirements: list[str] = []
    requirement_counter = 1

    for (name, _), response in zip(REQUIREMENT_CATEGORIES, responses, strict=True):
      if not response:
        continue

      # Extract individual <requirement> blocks.
      new_reqs = re.findall(r'(<requirement\b[^>]*>.*?</requirement>)', response, re.DOTALL)

      if not new_reqs:
        # If no requirements, look for a rationale.
        rationale_match = re.search(r'<rationale>(.*?)</rationale>', response, re.DOTALL)
        if rationale_match:
          ui.info(f'No requirements found for category [{name}] {rationale_match.group(1).strip()}')
        continue

      for req in new_reqs:
        # Re-index requirements as they come out
        re_indexed = re.sub(
          r'(<requirement[^>]*?)id="[^"]+"', f'\\1id="R{requirement_counter}"', req
        )
        all_requirements.append(re_indexed)
        requirement_counter += 1

    if not all_requirements:
      ui.error('No requirements extracted.')
      return None

    requirements_xml = (
      '<requirements_list>\n  ' + '\n  '.join(all_requirements) + '\n</requirements_list>'
    )

    # Save to cache
    cache_file.write_text(requirements_xml, encoding='utf-8')

  count = len(re.findall(r'<requirement\b[^>]*>', requirements_xml))
  ui.success(f'Extracted {count} test requirements.')
  context.requirements_xml = requirements_xml
  return requirements_xml


async def run_requirements_extraction_iterative(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  cache_dir: Path,
  save_state_callback: Callable[[WorkflowContext], None] | None = None,
) -> str | None:
  ui.on_phase_start(2, 'Requirements Extraction (Iterative)')

  assert context.metadata is not None

  web_feature_id = context.feature_id
  cache_file = cache_dir / f'{web_feature_id}__requirements.xml'
  requirements_xml = None

  if cache_file.exists():
    ui.info(f'Found cached requirements for {web_feature_id}.')
    if ui.confirm('Use cached requirements?'):
      requirements_xml = cache_file.read_text(encoding='utf-8')
      ui.success('Using cached requirements.')

  if not requirements_xml:
    all_requirements: list[str] = []
    iteration = 1
    max_iterations = 10
    requirement_counter = 1

    while iteration <= max_iterations:
      existing_requirements_xml = '\n'.join(all_requirements)

      extraction_prompt = jinja_env.get_template('requirements_extraction_iterative.jinja').render(
        feature_name=context.metadata.name,
        feature_description=context.metadata.description,
        specs=context.spec_contents,
        mdn_contents=context.mdn_contents,
        existing_requirements_xml=existing_requirements_xml,
      )
      extraction_system_prompt = jinja_env.get_template(
        'requirements_extraction_iterative_system.jinja'
      ).render()

      if iteration == 1:
        await confirm_prompts(
          [(extraction_prompt, 'Requirements Extraction (Iterative)')],
          'Requirements Extraction',
          llm,
          ui,
          config,
          model=config.get_model_for_phase('requirements_extraction'),
        )

      response = await generate_safe(
        extraction_prompt,
        f'Requirements Extraction (Iteration {iteration})',
        llm,
        ui,
        config,
        system_instruction=extraction_system_prompt,
        temperature=0.01,
        model=config.get_model_for_phase('requirements_extraction'),
      )

      if not response:
        break

      if '<status>EXHAUSTED</status>' in response:
        ui.success(f'Extraction complete: LLM signaled exhaustion at iteration {iteration}.')
        break

      # Extract individual <requirement> blocks.
      new_reqs = re.findall(r'(<requirement\b[^>]*>.*?</requirement>)', response, re.DOTALL)

      if not new_reqs:
        ui.warning('No new requirements found in this iteration. Stopping.')
        break

      ui.print(f'  - Found {len(new_reqs)} new requirements.')

      # Re-index requirements as they come out
      for req in new_reqs:
        re_indexed = re.sub(
          r'(<requirement[^>]*?)id="[^"]+"', f'\\1id="R{requirement_counter}"', req
        )
        all_requirements.append(re_indexed)
        requirement_counter += 1

      context.requirements_xml = (
        '<requirements_list>\n  ' + '\n  '.join(all_requirements) + '\n</requirements_list>'
      )
      if save_state_callback:
        save_state_callback(context)

      iteration += 1
    else:
      if iteration > max_iterations:
        ui.warning(f'Reached maximum iterations ({max_iterations}).')

    if not all_requirements:
      ui.error('No requirements extracted.')
      return None

    requirements_xml = (
      '<requirements_list>\n  ' + '\n  '.join(all_requirements) + '\n</requirements_list>'
    )

    # Save to cache
    cache_file.write_text(requirements_xml, encoding='utf-8')

  count = len(re.findall(r'<requirement\b[^>]*>', requirements_xml))
  ui.success(f'Extracted {count} test requirements.')
  context.requirements_xml = requirements_xml
  return requirements_xml

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
import math
import re
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import extract_xml_tag, parse_suggestions

FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')


def _partition_requirements(reqs_xml: str, max_per_chunk: int = 40) -> list[str]:
  if not reqs_xml:
    return []
  reqs = re.findall(r'<requirement.*?>.*?</requirement>', reqs_xml, re.DOTALL)
  total = len(reqs)
  if total == 0:
    return [reqs_xml]
  if total <= max_per_chunk:
    return [reqs_xml]

  num_chunks = math.ceil(total / max_per_chunk)
  base_size = total // num_chunks
  remainder = total % num_chunks

  chunks = []
  start = 0
  for i in range(num_chunks):
    size = base_size + 1 if i < remainder else base_size
    chunk_reqs = reqs[start : start + size]
    chunks.append('<requirements_list>\n  ' + '\n  '.join(chunk_reqs) + '\n</requirements_list>')
    start += size

  return chunks


async def run_coverage_audit(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> str | None:
  ui.on_phase_start(3, 'Coverage Audit')

  req_chunks = _partition_requirements(context.requirements_xml or '', max_per_chunk=40)
  if not req_chunks:
    ui.error('No requirements to audit.')
    return None

  audit_system_prompt = jinja_env.get_template('coverage_audit_system.jinja').render()

  prompts_to_confirm = []
  for i, chunk in enumerate(req_chunks):
    audit_prompt = jinja_env.get_template('coverage_audit.jinja').render(
      requirements_list_xml=chunk,
      wpt_context=context.wpt_context,
    )
    desc = (
      f'Coverage Audit (Chunk {i + 1}/{len(req_chunks)})'
      if len(req_chunks) > 1
      else 'Coverage Audit'
    )
    prompts_to_confirm.append((audit_prompt, desc))

  await confirm_prompts(
    prompts_to_confirm,
    'Coverage Audit',
    llm,
    ui,
    config,
    model=config.get_model_for_phase('coverage_audit'),
  )

  async def process_chunk(prompt_text: str, description: str) -> str | None:
    return await generate_safe(
      prompt_text,
      description,
      llm,
      ui,
      config,
      system_instruction=audit_system_prompt,
      temperature=0.01,
      model=config.get_model_for_phase('coverage_audit'),
    )

  if len(req_chunks) == 1:
    audit_response = await process_chunk(prompts_to_confirm[0][0], prompts_to_confirm[0][1])
    if not audit_response:
      return None
    context.audit_response = audit_response
    return audit_response

  ui.info(f'Launching {len(req_chunks)} parallel coverage audit requests...')
  total_tasks = len(req_chunks)
  completed_count = 0

  async def wrap_with_progress(prompt_text: str, description: str) -> str | None:
    nonlocal completed_count
    res = await process_chunk(prompt_text, description)
    completed_count += 1
    remaining = total_tasks - completed_count
    progress.update(
      description='Auditing coverage...', outstanding=remaining if remaining > 0 else None
    )
    progress.advance()
    return res

  with ui.progress_indicator(
    f'Auditing coverage... ({total_tasks} outstanding)', total=total_tasks
  ) as progress:
    responses = await asyncio.gather(*[wrap_with_progress(p, d) for p, d in prompts_to_confirm])

  combined_worksheets = []
  combined_suggestions = []
  all_satisfied = True

  for response in responses:
    if not response:
      continue

    ws = extract_xml_tag(response, 'audit_worksheet')
    if ws:
      combined_worksheets.append(ws)

    status = extract_xml_tag(response, 'status')
    if not status or status.strip() != 'SATISFIED':
      all_satisfied = False

    suggestions = parse_suggestions(response)
    if suggestions:
      combined_suggestions.extend(suggestions)

  final_response = (
    '<audit_worksheet>\n' + '\n\n'.join(combined_worksheets) + '\n</audit_worksheet>\n\n'
  )

  if all_satisfied and not combined_suggestions:
    final_response += '<test_suggestions>\n  <status>SATISFIED</status>\n</test_suggestions>'
  else:
    final_response += (
      '<test_suggestions>\n' + '\n'.join(combined_suggestions) + '\n</test_suggestions>'
    )

  context.audit_response = final_response
  return final_response


async def provide_coverage_report(context: WorkflowContext, config: Config, ui: UIProvider) -> None:
  """Prints the coverage audit report and optionally saves it to a file."""
  assert context.audit_response is not None
  ui.report_coverage_audit(context.audit_response)

  if ui.confirm('\nSave report to a file?'):
    # Create a sanitized filename from the feature ID
    safe_id = FILENAME_SANITIZATION_RE.sub('_', context.feature_id.lower())
    filename = f'{safe_id}_coverage_audit.md'

    output_path = Path(config.output_dir or '.') / filename
    try:
      output_path.parent.mkdir(parents=True, exist_ok=True)
      output_path.write_text(context.audit_response, encoding='utf-8')
      ui.success(f'Saved: {output_path.absolute()}')
    except Exception as e:
      ui.error(f'Error saving file: {e}')

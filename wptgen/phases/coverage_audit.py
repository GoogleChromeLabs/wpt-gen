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


def partition_requirements_xml(xml_string: str, max_threshold: int = 40) -> list[str]:
  if not xml_string:
    return []
  matches = list(re.finditer(r'(?s)<requirement.*?>.*?</requirement>', xml_string))
  if not matches:
    return [xml_string] if xml_string.strip() else []

  if len(matches) <= max_threshold:
    return [xml_string]

  num_chunks = math.ceil(len(matches) / max_threshold)
  chunk_size, remainder = divmod(len(matches), num_chunks)

  partitions = []
  start_idx = 0
  for i in range(num_chunks):
    end_idx = start_idx + chunk_size + (1 if i < remainder else 0)
    chunk_matches = matches[start_idx:end_idx]
    chunk_str = '\n'.join(m.group(0) for m in chunk_matches)
    partitions.append(f'<requirements_list>\n{chunk_str}\n</requirements_list>')
    start_idx = end_idx

  return partitions


def combine_audit_responses(responses: list[str]) -> str:
  overall_status = 'SATISFIED'
  combined_worksheets = []
  combined_suggestions = []

  for resp in responses:
    status = extract_xml_tag(resp, 'status')
    if status == 'TESTS_NEEDED':
      overall_status = 'TESTS_NEEDED'

    worksheet = extract_xml_tag(resp, 'audit_worksheet')
    if worksheet:
      combined_worksheets.append(worksheet.strip())

    suggestions = parse_suggestions(resp)
    combined_suggestions.extend(suggestions)

  final_response = f'<status>{overall_status}</status>\n'
  final_response += (
    '<audit_worksheet>\n' + '\n'.join(combined_worksheets) + '\n</audit_worksheet>\n'
  )
  if combined_suggestions:
    final_response += '\n'.join(combined_suggestions)

  return final_response


async def run_coverage_audit(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> str | None:
  ui.on_phase_start(3, 'Coverage Audit')

  req_partitions = partition_requirements_xml(context.requirements_xml or '', max_threshold=40)

  prompts = []
  for i, req_xml in enumerate(req_partitions):
    prompt = jinja_env.get_template('coverage_audit.jinja').render(
      requirements_list_xml=req_xml,
      wpt_context=context.wpt_context,
    )
    task_name = (
      f'Coverage Audit (Partition {i + 1}/{len(req_partitions)})'
      if len(req_partitions) > 1
      else 'Coverage Audit'
    )
    prompts.append((prompt, task_name))

  audit_system_prompt = jinja_env.get_template('coverage_audit_system.jinja').render()

  await confirm_prompts(
    prompts,
    'Coverage Audit',
    llm,
    ui,
    config,
    model=config.get_model_for_phase('coverage_audit'),
  )

  # Execute all partitions asynchronously
  tasks = []
  for prompt, task_name in prompts:
    tasks.append(
      generate_safe(
        prompt,
        task_name,
        llm,
        ui,
        config,
        system_instruction=audit_system_prompt,
        temperature=0.01,
        model=config.get_model_for_phase('coverage_audit'),
      )
    )

  responses = await asyncio.gather(*tasks)

  if len(responses) == 1:
    audit_response = responses[0]
  else:
    audit_response = combine_audit_responses(responses)

  context.audit_response = audit_response
  return audit_response


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

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
from wptgen.utils import (
  MARKDOWN_CODE_BLOCK_RE,
  extract_xml_tag,
  fix_reftest_link,
  parse_multi_file_response,
)


async def run_test_evaluation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  generated_tests: list[tuple[Path, str, str]],
) -> None:
  """Runs the evaluation phase for generated tests."""
  ui.on_phase_start(5, 'Evaluation')

  # Group tests by their suggestion XML to handle multi-file tests (Reftests) together
  grouped_tests: dict[str, list[tuple[Path, str]]] = defaultdict(list)
  for path, content, suggestion_xml in generated_tests:
    grouped_tests[suggestion_xml].append((path, content))

  ui.report_evaluation_start(len(grouped_tests))

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

    # Render the system instruction with both general and type-specific rules
    system_instruction = system_template.render(
      wpt_style_guide=wpt_style_guide,
      test_type=test_type_enum.value,
      test_type_guide=test_type_guide,
    )

    # Format the code content, using multi-file partitioning for Reftests ONLY
    if test_type_enum == TestType.REFTEST and len(group) > 1:
      # Sort to ensure FILE_1 is test and FILE_2 is ref
      test_item = next((item for item in group if '-ref.' not in item[0].name), None)
      ref_item = next((item for item in group if '-ref.' in item[0].name), None)

      if test_item and ref_item:
        p_test, c_test = test_item
        p_ref, c_ref = ref_item
        # Suffix is everything from the first dot
        suffix_test = '.' + p_test.name.split('.', 1)[1] if '.' in p_test.name else '.html'
        suffix_ref = '.' + p_ref.name.split('.', 1)[1] if '.' in p_ref.name else '.html'

        generated_code_content = (
          f'[FILE_1: {suffix_test}]\n{c_test}\n[/FILE_1]\n\n'
          f'[FILE_2: {suffix_ref}]\n{c_ref}\n[/FILE_2]'
        )
      else:
        generated_code_content = '\n\n'.join([c for p, c in group])
    else:
      # For non-reftests, pass raw content without tags
      generated_code_content = group[0][1]

    prompt = evaluation_template.render(
      test_suggestion_xml=suggestion_xml,
      generated_code_content=generated_code_content.strip(),
    )
    tasks.append(
      _evaluate_and_update(group, prompt, llm, ui, config, system_instruction, test_type_enum)
    )

  total_tasks = len(tasks)
  completed_tasks = 0
  with ui.progress_indicator(
    f'Evaluating tests... ({total_tasks} outstanding)', total=total_tasks
  ) as progress:
    for future in asyncio.as_completed(tasks):
      await future
      completed_tasks += 1
      remaining = total_tasks - completed_tasks
      progress.update(
        description='Evaluating tests...', outstanding=remaining if remaining > 0 else None
      )
      progress.advance()

  ui.on_phase_complete('Evaluation')


async def _evaluate_and_update(
  files: list[tuple[Path, str]],
  prompt: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str,
  test_type_enum: TestType,
) -> None:
  """Evaluates a single test (or multi-file test) and updates the file(s) if needed."""
  display_names = ', '.join([p.name for p, _ in files])
  ui.print(f'Evaluating: {display_names}...')

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
    ui.report_evaluation_result(
      display_names, success=False, message=f'No response for evaluation of {display_names}.'
    )
    return

  clean_response = response.strip()

  if clean_response == 'PASS':
    ui.report_evaluation_result(display_names, success=True)
  else:
    # If it's not PASS, it should be the corrected file content
    # Check if we have multiple files in the response
    multi_files = parse_multi_file_response(clean_response)
    if multi_files:
      # For Reftests, we expect FILE_1 to be test and FILE_2 to be ref
      # We need to find which path is which
      test_path_item = next((item for item in files if '-ref.' not in item[0].name), None)
      ref_path_item = next((item for item in files if '-ref.' in item[0].name), None)

      p_test_new = None
      p_ref_new = None
      c_test_new = None
      c_ref_new = None

      if len(multi_files) >= 1 and test_path_item:
        p_old, _ = test_path_item
        new_suffix, fcontent = multi_files[0]
        root = p_old.name.split('.', 1)[0]
        p_test_new = p_old.with_name(f'{root}{new_suffix}')
        c_test_new = MARKDOWN_CODE_BLOCK_RE.sub('', fcontent).strip()

      if len(multi_files) >= 2 and ref_path_item:
        p_old, _ = ref_path_item
        new_suffix, fcontent = multi_files[1]
        root = p_old.name.split('.', 1)[0]
        p_ref_new = p_old.with_name(f'{root}{new_suffix}')
        c_ref_new = MARKDOWN_CODE_BLOCK_RE.sub('', fcontent).strip()

      # If it's a reftest, fix the link in test content
      if test_type_enum == TestType.REFTEST and c_test_new and p_ref_new:
        c_test_new = fix_reftest_link(c_test_new, p_ref_new.name)

      # Now save
      if p_test_new and test_path_item and c_test_new is not None:
        if p_test_new != test_path_item[0]:
          test_path_item[0].unlink(missing_ok=True)
        p_test_new.write_text(c_test_new, encoding='utf-8')
        ui.report_evaluation_result(p_test_new.name, success=True, updated=True)

      if p_ref_new and ref_path_item and c_ref_new is not None:
        if p_ref_new != ref_path_item[0]:
          ref_path_item[0].unlink(missing_ok=True)
        p_ref_new.write_text(c_ref_new, encoding='utf-8')
        ui.report_evaluation_result(p_ref_new.name, success=True, updated=True)
    else:
      # If it's a single file correction
      if len(files) == 1:
        path = files[0][0]
        clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', clean_response).strip()
        path.write_text(clean_content, encoding='utf-8')
        ui.report_evaluation_result(path.name, success=True, updated=True)
      else:
        ui.report_evaluation_result(
          display_names,
          success=False,
          message=f'Received single-file correction for multi-file test {display_names}. Skipping.',
        )

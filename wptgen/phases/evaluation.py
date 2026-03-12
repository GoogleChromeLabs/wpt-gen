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
import hashlib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import STYLE_GUIDE_MAP, TestType, WorkflowContext
from wptgen.phases.utils import generate_safe, validate_requirements_preserved
from wptgen.ui import UIProvider
from wptgen.utils import (
  MARKDOWN_CODE_BLOCK_RE,
  clean_file_content,
  extract_xml_tag,
  fix_reftest_link,
  parse_multi_file_response,
)


async def _run_wpt_lint(path: Path, wpt_dir: Path) -> str | None:
  """Runs ./wpt lint on the given path and returns the error output if any."""
  try:
    # Use path relative to wpt_dir for cleaner output
    rel_path = str(path.resolve().relative_to(wpt_dir.resolve()))
    process = await asyncio.create_subprocess_exec(
      './wpt',
      'lint',
      rel_path,
      cwd=wpt_dir,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
      return stdout.decode('utf-8').strip()
    return None
  except Exception as e:
    return f'Failed to run ./wpt lint: {e}'


async def run_test_evaluation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  generated_tests: list[tuple[Path, str, str]],
  save_state_callback: Callable[[WorkflowContext], None] | None = None,
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

  ui.print('Running `./wpt lint` on generated tests.')
  tasks = []
  for suggestion_xml, group in grouped_tests.items():
    task_id = f'eval_{hashlib.md5(suggestion_xml.encode("utf-8")).hexdigest()}'
    if context.is_sub_task_complete(task_id):
      ui.info('Skipping already evaluated group.')
      continue

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

    # Run linting for the grouped test paths
    lint_errors_dict = {}
    for p, _ in group:
      errs = await _run_wpt_lint(p, Path(config.wpt_path))
      if errs:
        ui.print(f'[yellow]Lint errors found for {p.name}:[/yellow]\n{errs}')
        lint_errors_dict[p] = errs
      else:
        ui.print(f'[green]No lint errors found for {p.name}![/green]')

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

        formatted_lint_errors = []
        if p_test in lint_errors_dict:
          formatted_lint_errors.append(f'[FILE_1: {suffix_test}]\n{lint_errors_dict[p_test]}')
        if p_ref in lint_errors_dict:
          formatted_lint_errors.append(f'[FILE_2: {suffix_ref}]\n{lint_errors_dict[p_ref]}')
        lint_errors_str = '\n\n'.join(formatted_lint_errors) if formatted_lint_errors else None
      else:
        generated_code_content = '\n\n'.join([c for p, c in group])
        formatted_lint_errors = []
        for p, errs in lint_errors_dict.items():
          formatted_lint_errors.append(f'[{p.name}]\n{errs}')
        lint_errors_str = '\n\n'.join(formatted_lint_errors) if formatted_lint_errors else None
    else:
      # For non-reftests, pass raw content without tags
      generated_code_content = group[0][1]
      formatted_lint_errors = []
      for p, errs in lint_errors_dict.items():
        if len(group) > 1:
          formatted_lint_errors.append(f'[{p.name}]\n{errs}')
        else:
          formatted_lint_errors.append(errs)
      lint_errors_str = '\n\n'.join(formatted_lint_errors) if formatted_lint_errors else None

    # Render the system instruction with both general and type-specific rules
    system_instruction = system_template.render(
      wpt_style_guide=wpt_style_guide,
      test_type=test_type_enum.value,
      test_type_guide=test_type_guide,
      has_lint_errors=bool(lint_errors_str),
    )

    prompt = evaluation_template.render(
      test_suggestion_xml=suggestion_xml,
      generated_code_content=generated_code_content.strip(),
      lint_errors=lint_errors_str,
    )

    async def evaluate_and_update_wrapper(
      g: list[tuple[Path, str]], p: str, si: str, tt: TestType, tid: str
    ) -> None:
      await _evaluate_and_update(g, p, llm, ui, config, si, tt)
      context.mark_sub_task_complete(tid)
      if save_state_callback:
        save_state_callback(context)

    tasks.append(
      evaluate_and_update_wrapper(group, prompt, system_instruction, test_type_enum, task_id)
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
    multi_files = parse_multi_file_response(clean_response, strip_tentative=not config.tentative)
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
        p_old, old_content = test_path_item
        if not validate_requirements_preserved(old_content, c_test_new):
          ui.warning(
            f'LLM altered requirement comments in {p_old.name}. Rejecting evaluation change.'
          )
          return
        if p_test_new != p_old:
          p_old.unlink(missing_ok=True)
        p_test_new.write_text(clean_file_content(c_test_new), encoding='utf-8')
        ui.report_evaluation_result(p_test_new.name, success=True, updated=True)
        ui.print_diff(old_content, c_test_new, p_test_new.name)

      if p_ref_new and ref_path_item and c_ref_new is not None:
        p_old, old_content = ref_path_item
        if not validate_requirements_preserved(old_content, c_ref_new):
          ui.warning(
            f'LLM altered requirement comments in {p_old.name}. Rejecting evaluation change.'
          )
          return
        if p_ref_new != p_old:
          p_old.unlink(missing_ok=True)
        p_ref_new.write_text(clean_file_content(c_ref_new), encoding='utf-8')
        ui.report_evaluation_result(p_ref_new.name, success=True, updated=True)
        ui.print_diff(old_content, c_ref_new, p_ref_new.name)
    else:
      # If it's a single file correction
      if len(files) == 1:
        path, old_content = files[0]

        # If the LLM returned it as a multi-file block for some reason (e.g. [FILE_1: .https.html])
        if multi_files:
          new_suffix, fcontent = multi_files[0]
          clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', fcontent).strip()

          # Rename the file if the suffix changed
          root = path.name.split('.', 1)[0]
          new_path = path.with_name(f'{root}{new_suffix}')

          if new_path != path:
            path.unlink(missing_ok=True)
            path = new_path
        else:
          clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', clean_response).strip()

        if not validate_requirements_preserved(old_content, clean_content):
          ui.warning(
            f'LLM altered requirement comments in {path.name}. Rejecting evaluation change.'
          )
          return

        path.write_text(clean_file_content(clean_content), encoding='utf-8')
        ui.report_evaluation_result(path.name, success=True, updated=True)
        ui.print_diff(old_content, clean_content, path.name)
      else:
        ui.report_evaluation_result(
          display_names,
          success=False,
          message=f'Received single-file correction for multi-file test {display_names}. Skipping.',
        )

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
import json
import os
import tempfile
from pathlib import Path

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import MARKDOWN_CODE_BLOCK_RE, parse_multi_file_response


async def run_test_execution(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  generated_tests: list[tuple[Path, str, str]],
) -> None:
  """Runs the execution phase for generated tests using ./wpt run."""
  ui.on_phase_start(6, 'Test Execution')

  if not generated_tests:
    ui.info('No tests to execute.')
    return

  ui.print(f'Executing [bold]{len(generated_tests)}[/bold] generated files...')

  wpt_root = Path(config.wpt_path).resolve()
  wpt_executable = wpt_root / 'wpt'

  if not wpt_executable.exists():
    ui.error(f'Could not find wpt executable at {wpt_executable}. Skipping execution.')
    return

  valid_rel_paths: list[str] = []
  for path, _content, _xml in generated_tests:
    # Skip reference files for reftests
    if '-ref' in path.name:
      continue

    resolved_path = path.resolve()
    try:
      rel_path = resolved_path.relative_to(wpt_root)
      valid_rel_paths.append(str(rel_path))
    except ValueError:
      ui.warning(
        f'Test {path.name} is not located under wpt root ({wpt_root}). Cannot execute via wpt run.'
      )
      continue

  if not valid_rel_paths:
    ui.info('No valid test files to execute (all might be references or outside WPT root).')
    return

  correction_template = jinja_env.get_template('correction.jinja')
  correction_system = jinja_env.get_template('correction_system.jinja')
  max_retries = getattr(config, 'max_correction_retries', 2)

  # Load the general style guide
  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  for retry in range(max_retries + 1):
    if retry > 0:
      ui.print(
        f'\n[bold yellow]Automatic Test Correction (Attempt {retry}/{max_retries})[/bold yellow]'
      )

    ui.print(
      f'Running [cyan]{len(valid_rel_paths)}[/cyan] tests with {config.wpt_browser} {config.wpt_channel} '
      f'(timeout: {config.execution_timeout}s)...'
    )

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
      log_path = f.name

    cmd = [
      str(wpt_executable),
      'run',
      '--channel',
      config.wpt_channel,
      '--log-raw',
      log_path,
      config.wpt_browser,
    ] + valid_rel_paths

    process = await asyncio.create_subprocess_exec(
      *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(wpt_root)
    )

    try:
      stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=config.execution_timeout
      )
    except asyncio.TimeoutError:
      process.kill()
      await process.wait()
      ui.error(f'Test execution timed out after {config.execution_timeout}s.')
      if os.path.exists(log_path):
        os.remove(log_path)
      return

    output = ''
    if stdout:
      output += stdout.decode('utf-8', errors='replace')
    if stderr:
      if output:
        output += '\n'
      output += stderr.decode('utf-8', errors='replace')

    if process.returncode == 0:
      ui.success(f'Test execution succeeded for all {len(valid_rel_paths)} tests.')
      if os.path.exists(log_path):
        os.remove(log_path)
      break

    # If it failed, we parse the raw log
    failing_tests = {}
    if os.path.exists(log_path):
      with open(log_path, encoding='utf-8') as f:
        for line in f:
          try:
            event = json.loads(line)
            if event.get('action') == 'test_end' and event.get('status') in (
              'FAIL',
              'ERROR',
              'TIMEOUT',
              'CRASH',
            ):
              test_id = event.get('test', '')
              msg = event.get('message') or event.get('expected') or 'No error message provided'
              subtest_failures = []
              if 'subtests' in event:
                for subtest in event['subtests']:
                  if subtest.get('status') in ('FAIL', 'ERROR', 'TIMEOUT', 'CRASH'):
                    subtest_failures.append(
                      f'{subtest.get("name", "unknown")}: {subtest.get("message", "FAIL")}'
                    )
              if subtest_failures:
                msg += '\nSubtest Failures:\n' + '\n'.join(subtest_failures)
              failing_tests[test_id] = msg
          except json.JSONDecodeError:
            pass
      os.remove(log_path)

    # If we couldn't parse any specific failures but it failed, something else went wrong
    if not failing_tests:
      ui.error(f'Test execution failed with exit code {process.returncode}.')
      if output.strip():
        ui.print(output.strip())
      break

    if retry == max_retries:
      ui.error(f'Test execution failed after {max_retries} correction attempts.')
      break

    # Correction loop
    for test_id, error_log in failing_tests.items():
      # Match test_id (e.g., /html/semantics/...) back to our valid_rel_paths
      matched_path: str | None = None
      for valid_path in valid_rel_paths:
        # WPT test IDs usually start with / and don't include the local wpt_root
        if valid_path in test_id or test_id.lstrip('/') in valid_path:
          matched_path = valid_path
          break

      if not matched_path:
        continue

      full_path = wpt_root / matched_path
      if not full_path.exists():
        continue

      test_source_code = full_path.read_text(encoding='utf-8')
      prompt = correction_template.render(error_log=error_log, test_source_code=test_source_code)

      system_instruction = correction_system.render(wpt_style_guide=wpt_style_guide)

      ui.print(f'Attempting to correct [bold cyan]{matched_path}[/bold cyan]...')

      corrected_content = await generate_safe(
        prompt=prompt,
        task_name=f'Correcting {matched_path}',
        llm=llm,
        ui=ui,
        config=config,
        system_instruction=system_instruction,
      )

      if not corrected_content:
        continue

      # Extract using multi file response or regex fallback
      multi_files = parse_multi_file_response(corrected_content)
      if multi_files:
        final_content = multi_files[0][1]
      else:
        final_content = MARKDOWN_CODE_BLOCK_RE.sub('', corrected_content).strip()

      if final_content:
        full_path.write_text(final_content, encoding='utf-8')
        ui.success(f'Updated {matched_path}')

  ui.on_phase_complete('Test Execution')

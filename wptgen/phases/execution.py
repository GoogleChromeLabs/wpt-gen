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

from jinja2 import Environment, Template

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import WorkflowContext
from wptgen.phases.utils import generate_safe, validate_requirements_preserved
from wptgen.ui import UIProvider
from wptgen.utils import (
  MARKDOWN_CODE_BLOCK_RE,
  clean_file_content,
  parse_multi_file_response,
)


def _match_test_id_to_path(test_id: str, valid_rel_paths: list[str]) -> str | None:
  """Matches a test ID (e.g., /fetch/.../test.any.html) to its local source file."""
  clean_test_id = test_id.split('?')[0]
  for valid_path in valid_rel_paths:
    # 1. Exact or partial match
    if valid_path in clean_test_id or clean_test_id.lstrip('/') in valid_path:
      return valid_path

    # 2. Handle cases where the test runner generates an .html wrapper for a .js file
    base_test_id = clean_test_id.rsplit('.', 1)[0]
    base_valid_path = valid_path.rsplit('.', 1)[0]
    if base_valid_path in base_test_id or base_test_id.lstrip('/') in base_valid_path:
      return valid_path

  return None


def _filter_executable_tests(
  generated_tests: list[tuple[Path, str, str]], wpt_root: Path, ui: UIProvider
) -> list[str]:
  """Filters generated tests to remove references and ensure they are within the WPT root."""
  valid_rel_paths: list[str] = []
  for path, _content, _xml in generated_tests:
    # Skip reference files for reftests
    if '-ref' in path.name:
      continue

    resolved_path = path.resolve()
    try:
      rel_path = resolved_path.relative_to(wpt_root)
      valid_rel_paths.append(rel_path.as_posix())
    except ValueError:
      ui.warning(
        f'Test {path.name} is not located under wpt root ({wpt_root}). Cannot execute via wpt run.'
      )
  return valid_rel_paths


async def _execute_wpt_run(
  wpt_executable: Path,
  wpt_root: Path,
  valid_rel_paths: list[str],
  log_path: str,
  config: Config,
  ui: UIProvider,
  execution_timeout: int | float,
) -> tuple[int, str]:
  """Executes the `wpt run` subprocess and captures output."""
  cmd = [
    str(wpt_executable),
    'run',
    '--channel',
    config.wpt_channel,
    '--log-raw',
    log_path,
  ]
  if config.wpt_binary:
    cmd.extend(['--binary', config.wpt_binary])
  cmd.extend([config.wpt_browser] + valid_rel_paths)

  process = await asyncio.create_subprocess_exec(
    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(wpt_root)
  )

  stdout_chunks: list[str] = []
  stderr_chunks: list[str] = []

  async def stream_output(
    stream: asyncio.StreamReader | None, chunks: list[str], style: str | None = None
  ) -> None:
    if stream is None:
      return
    async for line in stream:
      decoded_line = line.decode('utf-8', errors='replace')
      chunks.append(decoded_line)
      ui.print(decoded_line.rstrip('\n'), style=style)

  async def communicate_and_stream() -> None:
    await asyncio.gather(
      stream_output(process.stdout, stdout_chunks, style='dim'),
      stream_output(process.stderr, stderr_chunks, style='dim red'),
    )
    await process.wait()

  try:
    await asyncio.wait_for(communicate_and_stream(), timeout=execution_timeout)
  except asyncio.TimeoutError:
    process.kill()
    await process.wait()
    ui.error(f'Test execution timed out after {execution_timeout}s.')
    return -1, ''

  output = ''
  if stdout_chunks:
    output += ''.join(stdout_chunks)
  if stderr_chunks:
    if output:
      output += '\n'
    output += ''.join(stderr_chunks)

  return process.returncode if process.returncode is not None else -1, output


def _parse_test_results(log_path: str) -> dict[str, str]:
  """Parses the JSON log output to extract failing test IDs and error messages."""
  failing_tests: dict[str, str] = {}
  if not os.path.exists(log_path):
    return failing_tests

  test_messages: dict[str, list[str]] = {}
  with open(log_path, encoding='utf-8') as f:
    for line in f:
      try:
        event = json.loads(line)
        test_id = event.get('test')
        if not test_id:
          continue

        if test_id not in test_messages:
          test_messages[test_id] = []

        action = event.get('action')
        status = event.get('status')

        if action == 'test_status':
          if status in ('FAIL', 'ERROR', 'TIMEOUT', 'CRASH', 'PRECONDITION_FAILED'):
            subtest_name = event.get('subtest', 'unknown')
            msg = event.get('message', 'No message')
            test_messages[test_id].append(f"Subtest '{subtest_name}': {status} - {msg}")
        elif action == 'test_end':
          if status in ('FAIL', 'ERROR', 'TIMEOUT', 'CRASH'):
            msg = event.get('message') or event.get('expected') or f'Overall test {status}'
            test_messages[test_id].insert(0, f'Test: {status} - {msg}')
      except json.JSONDecodeError:
        pass

  for test_id, messages in test_messages.items():
    if messages:
      failing_tests[test_id] = '\n'.join(messages)

  return failing_tests


async def _correct_test(
  test_id: str,
  error_log: str,
  valid_rel_paths: list[str],
  wpt_root: Path,
  correction_template: Template,
  correction_system: Template,
  wpt_style_guide: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  semaphore: asyncio.Semaphore,
) -> None:
  """Helper function to correct a single failing test file concurrently."""
  async with semaphore:
    matched_path = _match_test_id_to_path(test_id, valid_rel_paths)
    if not matched_path:
      ui.warning(f'Could not find local source file to correct for test ID: {test_id}')
      return

    full_path = wpt_root / matched_path
    if not full_path.exists():
      return

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
      return

    # Extract using multi file response or regex fallback
    multi_files = parse_multi_file_response(corrected_content)
    if multi_files:
      final_content = multi_files[0][1]
    else:
      final_content = MARKDOWN_CODE_BLOCK_RE.sub('', corrected_content).strip()

    if final_content:
      if not validate_requirements_preserved(test_source_code, final_content):
        ui.warning(f'LLM altered requirement comments in {matched_path}. Rejecting change.')
        return

      full_path.write_text(clean_file_content(final_content), encoding='utf-8')
      ui.success(f'Updated {matched_path}')
      ui.print_diff(test_source_code, final_content, matched_path)


async def _correct_failing_tests(
  failing_tests: dict[str, str],
  valid_rel_paths: list[str],
  wpt_root: Path,
  correction_template: Template,
  correction_system: Template,
  wpt_style_guide: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
) -> None:
  """Handles the loop that renders templates and corrects failing tests concurrently."""
  semaphore = asyncio.Semaphore(getattr(config, 'max_parallel_requests', 5))
  tasks = []
  for test_id, error_log in failing_tests.items():
    tasks.append(
      _correct_test(
        test_id=test_id,
        error_log=error_log,
        valid_rel_paths=valid_rel_paths,
        wpt_root=wpt_root,
        correction_template=correction_template,
        correction_system=correction_system,
        wpt_style_guide=wpt_style_guide,
        llm=llm,
        ui=ui,
        config=config,
        semaphore=semaphore,
      )
    )

  total_tasks = len(tasks)
  completed_tasks = 0

  with ui.progress_indicator(
    f'Correcting tests... ({total_tasks} outstanding)', total=total_tasks
  ) as progress:
    for future in asyncio.as_completed(tasks):
      await future
      completed_tasks += 1
      remaining = total_tasks - completed_tasks
      progress.update(
        description='Correcting tests...', outstanding=remaining if remaining > 0 else None
      )
      progress.advance()


async def run_test_execution(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
  generated_tests: list[tuple[Path, str, str]],
) -> bool:
  """
  Runs the execution phase for generated tests using ./wpt run.

  Returns:
    True if all tests passed (possibly after correction), False otherwise.
  """
  ui.on_phase_start(6, 'Test Execution')

  if not generated_tests:
    ui.info('No tests to execute.')
    return True

  ui.print(f'Executing [bold]{len(generated_tests)}[/bold] generated files...')

  wpt_root = Path(config.wpt_path).resolve()
  wpt_executable = wpt_root / 'wpt'

  if not wpt_executable.exists():
    ui.error(f'Could not find wpt executable at {wpt_executable}. Skipping execution.')
    return False

  valid_rel_paths = _filter_executable_tests(generated_tests, wpt_root, ui)

  if not valid_rel_paths:
    ui.info('No valid test files to execute (all might be references or outside WPT root).')
    return True

  correction_template = jinja_env.get_template('correction.jinja')
  correction_system = jinja_env.get_template('correction_system.jinja')
  max_retries = getattr(config, 'max_correction_retries', 2)

  # Load the general style guide
  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  success = False
  for retry in range(max_retries + 1):
    if retry > 0:
      ui.print(
        f'\n[bold yellow]Automatic Test Correction (Attempt {retry}/{max_retries})[/bold yellow]'
      )

    execution_timeout = min(30 * len(valid_rel_paths), 900)

    ui.print(
      f'Running [cyan]{len(valid_rel_paths)}[/cyan] tests with {config.wpt_browser} {config.wpt_channel} '
      f'(timeout: {execution_timeout}s)...'
    )

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
      log_path = f.name

    returncode, output = await _execute_wpt_run(
      wpt_executable, wpt_root, valid_rel_paths, log_path, config, ui, execution_timeout
    )

    if returncode == -1 and not output:
      if os.path.exists(log_path):
        os.remove(log_path)
      return False

    if returncode == 0:
      ui.success(f'Test execution succeeded for all {len(valid_rel_paths)} tests.')
      if os.path.exists(log_path):
        os.remove(log_path)
      success = True
      break

    failing_tests = _parse_test_results(log_path)
    if os.path.exists(log_path):
      os.remove(log_path)

    # If we couldn't parse any specific failures but it failed, something else went wrong
    if not failing_tests:
      ui.error(f'Test execution failed with exit code {returncode}.')
      if output.strip():
        ui.print(output.strip())
      return False

    if retry == max_retries:
      ui.error(f'Test execution failed after {max_retries} correction attempts.')
      success = False
      break

    passed_count = len(valid_rel_paths) - len(failing_tests)
    if passed_count > 0:
      ui.success(f'{passed_count} test(s) passed successfully.')

    ui.print(f'\n[bold red]Found {len(failing_tests)} failing test(s):[/bold red]')
    for test_id, error_msg in failing_tests.items():
      ui.print(f'[red]✗ {test_id}[/red]')
      indented_msg = '\n'.join(f'    {line}' for line in error_msg.splitlines())
      ui.print(f'[dim]{indented_msg}[/dim]')

    await _correct_failing_tests(
      failing_tests,
      valid_rel_paths,
      wpt_root,
      correction_template,
      correction_system,
      wpt_style_guide,
      llm,
      ui,
      config,
    )

  ui.on_phase_complete('Test Execution')
  return success

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

from wptgen.config import Config
from wptgen.models import WorkflowContext
from wptgen.ui import UIProvider


async def run_test_execution(
  context: WorkflowContext,
  config: Config,
  ui: UIProvider,
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

  valid_rel_paths = []
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

  ui.print(
    f'Running [cyan]{len(valid_rel_paths)}[/cyan] tests with {config.wpt_browser} {config.wpt_channel} '
    f'(timeout: {config.execution_timeout}s)...'
  )

  # Command: ./wpt run --channel <channel> <browser> <path1> <path2> ...
  cmd = [
    str(wpt_executable),
    'run',
    '--channel',
    config.wpt_channel,
    config.wpt_browser,
  ] + valid_rel_paths

  # Execute the command
  process = await asyncio.create_subprocess_exec(
    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(wpt_root)
  )

  try:
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=config.execution_timeout)
  except asyncio.TimeoutError:
    process.kill()
    await process.wait()
    ui.error(f'Test execution timed out after {config.execution_timeout}s.')
  else:
    if process.returncode != 0:
      ui.error(f'Test execution failed with exit code {process.returncode}.')

      # Print output
      output = ''
      if stdout:
        output += stdout.decode('utf-8', errors='replace')
      if stderr:
        if output:
          output += '\n'
        output += stderr.decode('utf-8', errors='replace')

      if output.strip():
        ui.print(output.strip())

    else:
      ui.success(f'Test execution succeeded for all {len(valid_rel_paths)} tests.')

  ui.on_phase_complete('Test Execution')

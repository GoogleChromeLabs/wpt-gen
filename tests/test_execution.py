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
import signal
import typing
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wptgen.config import Config
from wptgen.models import WorkflowContext
from wptgen.phases.execution import (
  _execute_wpt_run,
  _filter_executable_tests,
  _match_test_id_to_path,
  _parse_test_results,
  run_test_execution,
)


async def _mock_stream(data: bytes) -> typing.AsyncGenerator[bytes, None]:
  if data:
    for line in data.splitlines(keepends=True):
      yield line


@pytest.fixture
def mock_ui() -> MagicMock:
  """Fixture that provides a mocked UI provider."""
  return MagicMock()


@pytest.fixture
def mock_llm() -> MagicMock:
  return MagicMock()


@pytest.fixture
def mock_jinja_env() -> MagicMock:
  env = MagicMock()
  env.get_template.return_value = MagicMock()
  return env


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  """Fixture that provides a basic test configuration."""
  return Config(
    provider='test',
    default_model='test-model',
    api_key='test-key',
    categories={'lightweight': 'test-model', 'reasoning': 'test-model'},
    phase_model_mapping={},
    wpt_path=str(tmp_path / 'wpt'),
    cache_path=str(tmp_path / 'cache'),
    output_dir=str(tmp_path / 'output'),
    wpt_browser='chrome',
    wpt_channel='canary',
  )


@pytest.mark.asyncio
async def test_run_test_execution_success_batch(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True)
  wpt_executable = wpt_root / 'wpt'
  wpt_executable.touch()

  test1 = wpt_root / 'test1.html'
  test2 = wpt_root / 'test2.html'
  generated_tests = [
    (test1, 'content1', 'xml1'),
    (test2, 'content2', 'xml2'),
  ]

  context = WorkflowContext(feature_id='feat')

  mock_process = AsyncMock()
  mock_process.stdout = _mock_stream(b'stdout')
  mock_process.stderr = _mock_stream(b'stderr')
  mock_process.returncode = 0

  with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_exec:
    await run_test_execution(
      context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests
    )

    mock_exec.assert_called_once()
    args = mock_exec.call_args[0]
    assert args[0] == str(wpt_executable)
    assert 'run' in args
    assert 'chrome' in args
    assert 'canary' in args
    # Verify both tests are in the command line
    assert test1.relative_to(wpt_root).as_posix() in args
    assert test2.relative_to(wpt_root).as_posix() in args

    mock_ui.success.assert_called_with('Test execution succeeded for all 2 tests.')


@pytest.mark.asyncio
async def test_run_test_execution_skips_references(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True)
  wpt_executable = wpt_root / 'wpt'
  wpt_executable.touch()

  test1 = wpt_root / 'test1.html'
  ref1 = wpt_root / 'test1-ref.html'
  generated_tests = [
    (test1, 'content', 'xml'),
    (ref1, 'ref content', 'xml'),
  ]

  context = WorkflowContext(feature_id='feat')

  mock_process = AsyncMock()
  mock_process.stdout = _mock_stream(b'stdout')
  mock_process.stderr = _mock_stream(b'stderr')
  mock_process.returncode = 0

  with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_exec:
    await run_test_execution(
      context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests
    )

    mock_exec.assert_called_once()
    args = mock_exec.call_args[0]
    assert test1.relative_to(wpt_root).as_posix() in args
    assert ref1.relative_to(wpt_root).as_posix() not in args

    mock_ui.success.assert_called_with('Test execution succeeded for all 1 tests.')


@pytest.mark.asyncio
async def test_run_test_execution_failure(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True)
  (wpt_root / 'wpt').touch()

  test_path = wpt_root / 'test.html'
  generated_tests = [(test_path, 'content', 'xml')]

  context = WorkflowContext(feature_id='feat')

  mock_process = AsyncMock()
  mock_process.stdout = _mock_stream(b'some output')
  mock_process.stderr = _mock_stream(b'some error')
  mock_process.returncode = 1

  with patch('asyncio.create_subprocess_exec', return_value=mock_process):
    await run_test_execution(
      context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests
    )

    mock_ui.error.assert_any_call('Test execution failed with exit code 1.')
    mock_ui.print.assert_any_call('some output\nsome error')


@pytest.mark.asyncio
async def test_run_test_execution_timeout(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True)
  (wpt_root / 'wpt').touch()

  test_path = wpt_root / 'test.html'
  generated_tests = [(test_path, 'content', 'xml')]

  context = WorkflowContext(feature_id='feat')

  mock_process = AsyncMock()
  mock_process.pid = 9999
  mock_process.communicate = AsyncMock()

  with patch('asyncio.create_subprocess_exec', return_value=mock_process):
    with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError):
      with patch('sys.platform', 'linux'):
        with patch('os.getpgid', return_value=12345, create=True) as mock_getpgid:
          with patch('os.killpg', create=True) as mock_killpg:
            await run_test_execution(
              context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests
            )

            mock_getpgid.assert_called_once_with(9999)
            sig = getattr(signal, 'SIGKILL', 9)
            mock_killpg.assert_called_once_with(12345, sig)
            mock_ui.error.assert_called_with('Test execution timed out after 30s.')


@pytest.mark.asyncio
async def test_run_test_execution_all_filtered(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True)
  (wpt_root / 'wpt').touch()

  ref1 = wpt_root / 'test1-ref.html'
  generated_tests = [(ref1, 'content', 'xml')]

  context = WorkflowContext(feature_id='feat')

  await run_test_execution(context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests)

  mock_ui.info.assert_called_with(
    'No valid test files to execute (all might be references or outside WPT root).'
  )


@pytest.mark.asyncio
async def test_run_test_execution_missing_executable(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, mock_jinja_env: MagicMock
) -> None:
  generated_tests = [(Path('test.html'), 'content', 'xml')]
  context = WorkflowContext(feature_id='feat')

  await run_test_execution(context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests)

  mock_ui.error.assert_called()
  assert 'Could not find wpt executable' in mock_ui.error.call_args[0][0]


@pytest.mark.asyncio
async def test_run_test_execution_empty(
  mock_config: Config, mock_ui: MagicMock, mock_llm: MagicMock, mock_jinja_env: MagicMock
) -> None:
  await run_test_execution(
    WorkflowContext(feature_id='feat'), mock_config, mock_llm, mock_ui, mock_jinja_env, []
  )
  mock_ui.info.assert_called_with('No tests to execute.')


@pytest.mark.asyncio
async def test_run_test_execution_correction_loop_and_diff(
  mock_config: Config,
  mock_ui: MagicMock,
  mock_llm: MagicMock,
  mock_jinja_env: MagicMock,
  tmp_path: Path,
) -> None:
  wpt_root = Path(mock_config.wpt_path)
  wpt_root.mkdir(parents=True, exist_ok=True)
  (wpt_root / 'wpt').touch()

  test_path = wpt_root / 'test_fail.html'
  test_path.write_text('old code\n', encoding='utf-8')

  generated_tests = [(test_path, 'content', 'xml')]
  context = WorkflowContext(feature_id='feat')

  # First run fails, second run succeeds
  mock_process_fail = AsyncMock()
  mock_process_fail.communicate.return_value = (b'failed', b'')
  mock_process_fail.returncode = 1

  mock_process_success = AsyncMock()
  mock_process_success.communicate.return_value = (b'success', b'')
  mock_process_success.returncode = 0

  call_count = 0

  async def side_effect_exec(*args: Any, **kwargs: Any) -> AsyncMock:
    nonlocal call_count
    call_count += 1

    if call_count == 1:
      # Find the log file argument
      log_path = None
      for i, arg in enumerate(args):
        if arg == '--log-raw':
          log_path = args[i + 1]
          break

      if log_path:
        import json

        with open(log_path, 'w', encoding='utf-8') as f:
          event = {
            'action': 'test_status',
            'test': '/test_fail.html',
            'subtest': 'sub1',
            'status': 'FAIL',
            'message': 'broken',
          }
          f.write(json.dumps(event) + '\n')

      return mock_process_fail
    else:
      return mock_process_success

  with patch('asyncio.create_subprocess_exec', side_effect=side_effect_exec):
    with patch(
      'wptgen.phases.execution.generate_safe', new_callable=AsyncMock
    ) as mock_generate_safe:
      mock_generate_safe.return_value = '[FILE_1: .html]\nnew code\n[/FILE_1]'

      await run_test_execution(
        context, mock_config, mock_llm, mock_ui, mock_jinja_env, generated_tests
      )

      # Assert generate_safe was called for correction
      mock_generate_safe.assert_called_once()

      # Assert the file was updated
      assert test_path.read_text(encoding='utf-8') == 'new code\n'

      # Assert ui.print_diff was called
      mock_ui.print_diff.assert_called_once_with('old code\n', 'new code', 'test_fail.html')


def test_match_test_id_to_path() -> None:
  valid_paths = [
    'fetch/api/request/request-keepalive.html',
    'html/semantics/scripting-1/the-script-element/script-type-module.js',
  ]
  assert (
    _match_test_id_to_path('/fetch/api/request/request-keepalive.html', valid_paths)
    == valid_paths[0]
  )
  assert (
    _match_test_id_to_path('/fetch/api/request/request-keepalive.html?foo=bar', valid_paths)
    == valid_paths[0]
  )
  assert (
    _match_test_id_to_path(
      '/html/semantics/scripting-1/the-script-element/script-type-module.html', valid_paths
    )
    == valid_paths[1]
  )
  assert _match_test_id_to_path('/css/css-grid/grid-model.html', valid_paths) is None


def test_filter_executable_tests(mock_ui: MagicMock, tmp_path: Path) -> None:
  wpt_root = tmp_path / 'fake' / 'wpt' / 'root'
  wpt_root.mkdir(parents=True)
  wpt_root = wpt_root.resolve()
  generated_tests = [
    (wpt_root / 'test1.html', 'content1', 'xml1'),
    (wpt_root / 'test2-ref.html', 'content2', 'xml2'),
    (tmp_path / 'some' / 'other' / 'path' / 'test3.html', 'content3', 'xml3'),
  ]
  valid_paths = _filter_executable_tests(generated_tests, wpt_root, mock_ui)
  assert len(valid_paths) == 1
  assert valid_paths[0] == 'test1.html'
  mock_ui.warning.assert_called_once()


def test_parse_test_results(tmp_path: Path) -> None:
  log_file = tmp_path / 'wpt_run.json'
  log_data = [
    {
      'action': 'test_status',
      'test': '/test1.html',
      'subtest': 'sub1',
      'status': 'FAIL',
      'message': 'Expected A got B',
    },
    {'action': 'test_end', 'test': '/test1.html', 'status': 'ERROR', 'message': 'Unhandled error'},
    {'action': 'test_status', 'test': '/test2.html', 'subtest': 'sub2', 'status': 'PASS'},
    {'action': 'test_end', 'test': '/test2.html', 'status': 'OK'},
  ]
  with open(log_file, 'w') as f:
    for event in log_data:
      f.write(json.dumps(event) + '\n')
  failing_tests = _parse_test_results(str(log_file))
  assert len(failing_tests) == 1
  assert '/test1.html' in failing_tests
  assert _parse_test_results(str(tmp_path / 'non_existent.json')) == {}


@pytest.mark.asyncio
async def test_execute_wpt_run_success(
  mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  wpt_executable = wpt_root / 'wpt'
  mock_process = AsyncMock()
  mock_process.stdout = _mock_stream(b'stdout_data')
  mock_process.stderr = _mock_stream(b'stderr_data')
  mock_process.returncode = 0
  with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_exec:
    returncode, output = await _execute_wpt_run(
      wpt_executable, wpt_root, ['test1.html'], '/tmp/log.json', mock_config, mock_ui, 30
    )
    mock_exec.assert_called_once()
    assert returncode == 0
    assert 'stdout_data\nstderr_data' in output


@pytest.mark.asyncio
async def test_execute_wpt_run_timeout(
  mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  wpt_executable = wpt_root / 'wpt'

  mock_process = AsyncMock()
  mock_process.pid = 8888

  async def slow_wait() -> int:
    await asyncio.sleep(0.02)
    return 0

  mock_process.wait = slow_wait
  mock_process.stdout = _mock_stream(b'')
  mock_process.stderr = _mock_stream(b'')
  with patch('asyncio.create_subprocess_exec', return_value=mock_process):
    with patch('sys.platform', 'linux'):
      with patch('os.getpgid', return_value=54321, create=True) as mock_getpgid:
        with patch('os.killpg', create=True) as mock_killpg:
          returncode, output = await _execute_wpt_run(
            wpt_executable, wpt_root, ['test1.html'], '/tmp/log.json', mock_config, mock_ui, 0.01
          )
          assert returncode == -1
          mock_getpgid.assert_called_once_with(8888)
          sig = getattr(signal, 'SIGKILL', 9)
          mock_killpg.assert_called_once_with(54321, sig)


@pytest.mark.asyncio
async def test_execute_wpt_run_timeout_windows(
  mock_config: Config, mock_ui: MagicMock, tmp_path: Path
) -> None:
  wpt_root = tmp_path / 'wpt'
  wpt_root.mkdir()
  wpt_executable = wpt_root / 'wpt'

  mock_process = AsyncMock()
  mock_process.pid = 8888

  async def slow_wait() -> int:
    await asyncio.sleep(0.02)
    return 0

  mock_process.wait = slow_wait
  mock_process.stdout = _mock_stream(b'')
  mock_process.stderr = _mock_stream(b'')
  with patch('asyncio.create_subprocess_exec', return_value=mock_process):
    with patch('sys.platform', 'win32'):
      with patch('subprocess.run') as mock_run:
        returncode, output = await _execute_wpt_run(
          wpt_executable, wpt_root, ['test1.html'], '/tmp/log.json', mock_config, mock_ui, 0.01
        )
        assert returncode == -1
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert 'taskkill' in args
        assert '/T' in args
        assert '8888' in args

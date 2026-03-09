import os
from pathlib import Path

import pytest

from wptgen.config import load_config
from wptgen.llm import get_llm_client
from wptgen.mock import MockLLMClient, ReplayFile, ReplayInteraction


def test_mock_provider_initialization(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  """Tests that the mock provider can be initialized without an API key."""
  # Unset any real API keys to ensure we aren't relying on them
  for key in ['GEMINI_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'MOCK_API_KEY']:
    if key in os.environ:
      del os.environ[key]

  monkeypatch.setenv('WPT_GEN_MOCK_MODE', 'auto')
  monkeypatch.setenv('WPT_GEN_REPLAYS_DIRECTORY', str(tmp_path))

  config = load_config(provider_override='mock', require_api_key=True)
  assert config.provider == 'mock'
  assert config.api_key == 'mock_key'

  client = get_llm_client(config)
  assert isinstance(client, MockLLMClient)
  assert client.mode == 'auto'


def test_mock_client_record_and_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  """Tests the recording and replaying capabilities of MockLLMClient."""
  replays_dir = tmp_path / 'replays'
  replays_dir.mkdir()

  monkeypatch.setenv('WPT_GEN_REPLAYS_DIRECTORY', str(replays_dir))
  monkeypatch.setenv('WPT_GEN_REPLAY_ID', 'test_replay')

  # 1. Create a dummy interaction file directly to simulate a recorded session
  # We do this instead of actually recording to avoid needing a real LLM API
  interaction = ReplayInteraction(
    prompt='Test prompt',
    system_instruction='System instruction',
    model='mock-model',
    response='Mocked response',
    token_count=42,
  )
  replay_file = ReplayFile(replay_id='test_replay', interactions=[interaction])

  file_path = replays_dir / 'test_replay.json'
  with open(file_path, 'w', encoding='utf-8') as f:
    f.write(replay_file.model_dump_json())

  # 2. Test replaying
  monkeypatch.setenv('WPT_GEN_MOCK_MODE', 'replay')

  config = load_config(provider_override='mock')
  client = get_llm_client(config)

  assert isinstance(client, MockLLMClient)
  assert client.mode == 'replay'

  response = client.generate_content(
    prompt='Test prompt', system_instruction='System instruction', model='mock-model'
  )
  assert response == 'Mocked response'
  assert client.count_tokens('Test prompt') == 100  # Default for replay

  # 3. Test replay exact prompt matching failure
  client._replay_index = 0  # reset
  with pytest.raises(AssertionError, match='Prompt mismatch'):
    client.generate_content(prompt='Different prompt')


def test_mock_client_auto_mode(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: pytest.MonkeyPatch
) -> None:
  """Tests auto mode falls back to recording or replaying based on file existence."""
  replays_dir = tmp_path / 'replays'
  replays_dir.mkdir()

  monkeypatch.setenv('WPT_GEN_REPLAYS_DIRECTORY', str(replays_dir))
  monkeypatch.setenv('WPT_GEN_REPLAY_ID', 'auto_test')
  monkeypatch.setenv('WPT_GEN_MOCK_MODE', 'auto')
  monkeypatch.setenv('GEMINI_API_KEY', 'fake_key_for_recording')

  # We mock get_llm_client so we don't need real API keys for recording setup
  mock_real_client = mocker.MagicMock()  # type: ignore
  mock_real_client.model = 'gemini-3.1-pro-preview'
  mock_real_client.generate_content.return_value = 'Real recorded response'
  mock_real_client.count_tokens.return_value = 50

  mocker.patch('wptgen.llm.GeminiClient', return_value=mock_real_client)  # type: ignore

  config = load_config(provider_override='mock')
  client = get_llm_client(config)

  assert isinstance(client, MockLLMClient)
  assert client.mode == 'auto'
  assert client._should_call_api() is True  # File doesn't exist yet

  response = client.generate_content(prompt='Auto prompt')
  assert response == 'Real recorded response'

  # Verify file was saved
  file_path = replays_dir / 'auto_test.json'
  assert file_path.exists()

  # Create a new client in auto mode, it should now replay
  client2 = get_llm_client(config)
  assert isinstance(client2, MockLLMClient)
  assert client2._should_call_api() is False

  # The mock real client should NOT be called this time
  mock_real_client.generate_content.reset_mock()
  response2 = client2.generate_content(prompt='Auto prompt')
  assert response2 == 'Real recorded response'
  mock_real_client.generate_content.assert_not_called()

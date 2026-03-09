import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from wptgen.config import DEFAULT_LLM_TIMEOUT, Config
from wptgen.llm import MAX_RETRIES, LLMClient


class ReplayInteraction(BaseModel):
  prompt: str
  system_instruction: str | None
  model: str | None
  response: str
  token_count: int | None


class ReplayFile(BaseModel):
  replay_id: str
  interactions: list[ReplayInteraction]


class MockLLMClient(LLMClient):
  """
  A mock LLM client that records and replays API responses for offline testing.
  Inspired by ReplayApiClient from google-genai.
  """

  def __init__(
    self,
    mode: Literal['record', 'replay', 'auto'] = 'replay',
    replay_id: str = 'default',
    replays_directory: str | None = None,
    real_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
    timeout: int = DEFAULT_LLM_TIMEOUT,
  ):
    super().__init__('mock_key', 'mock-model', max_retries, timeout)
    self.mode = mode
    self.replay_id = replay_id
    if not replays_directory:
      replays_directory = os.environ.get('WPT_GEN_REPLAYS_DIRECTORY', '.replays')
    self.replays_directory = Path(replays_directory)
    self.real_client = real_client

    self.replay_session: ReplayFile | None = None
    self._replay_index = 0
    self._initialize_replay_session()

  def _get_replay_file_path(self) -> Path:
    return self.replays_directory / f'{self.replay_id}.json'

  def _should_call_api(self) -> bool:
    return self.mode == 'record' or (
      self.mode == 'auto' and not self._get_replay_file_path().exists()
    )

  def _should_update_replay(self) -> bool:
    return self._should_call_api()

  def _initialize_replay_session(self) -> None:
    self._replay_index = 0
    replay_file_path = self._get_replay_file_path()
    replay_file_exists = replay_file_path.exists()

    if self.mode == 'replay' and not replay_file_exists:
      # If we are strictly in replay mode and no file exists, fail.
      raise ValueError(f'Replay file does not exist for replay id: {self.replay_id}')

    if self.mode in ['replay', 'auto'] and replay_file_exists:
      with open(replay_file_path, encoding='utf-8') as f:
        self.replay_session = ReplayFile.model_validate(json.loads(f.read()))

    if self._should_update_replay():
      self.replay_session = ReplayFile(replay_id=self.replay_id, interactions=[])

  def _save_replay_session(self) -> None:
    if not self._should_update_replay() or not self.replay_session:
      return
    replay_file_path = self._get_replay_file_path()
    replay_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(replay_file_path, 'w', encoding='utf-8') as f:
      f.write(self.replay_session.model_dump_json(exclude_unset=True, indent=2))

  def _record_interaction(
    self,
    prompt: str,
    system_instruction: str | None,
    model: str | None,
    response: str,
    token_count: int | None,
  ) -> None:
    if not self._should_update_replay() or self.replay_session is None:
      return
    interaction = ReplayInteraction(
      prompt=prompt,
      system_instruction=system_instruction,
      model=model,
      response=response,
      token_count=token_count,
    )
    self.replay_session.interactions.append(interaction)
    # Save incrementally to avoid needing a close() hook
    self._save_replay_session()

  def count_tokens(self, prompt: str, model: str | None = None) -> int:
    if self._should_call_api():
      if not self.real_client:
        raise ValueError('Real client is required for recording API calls')
      real_model = model
      if model == 'mock-model' or model is None:
        real_model = self.real_client.model
      return self.real_client.count_tokens(prompt, real_model)
    else:
      # In replay mode, return a dummy token count if not recording
      return 100

  def generate_content(
    self,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
  ) -> str:
    if self._should_call_api():
      if not self.real_client:
        raise ValueError('Real client is required for recording API calls')

      # Use the real client's default model if we receive a mock one
      real_model = model
      if model == 'mock-model' or model is None:
        real_model = self.real_client.model

      response = self.real_client.generate_content(
        prompt, system_instruction, temperature, real_model
      )
      token_count = self.real_client.count_tokens(prompt, real_model)
      self._record_interaction(prompt, system_instruction, real_model, response, token_count)
      return response
    else:
      if self.replay_session is None:
        raise ValueError('No replay session found.')
      if self._replay_index >= len(self.replay_session.interactions):
        raise ValueError(f'Replay session out of interactions at index {self._replay_index}')

      interaction = self.replay_session.interactions[self._replay_index]

      # Assert to ensure deterministic execution
      # We skip system_instruction / model assertion to be more flexible, but
      # prompt assertion ensures we're generally matching the flow.
      # For a strict replay, we would assert prompt exactly.
      # In this MockLLMClient we'll just log or loosely assert if needed,
      # but let's strictly assert like ReplayApiClient.
      assert prompt == interaction.prompt, f'Prompt mismatch at index {self._replay_index}'

      self._replay_index += 1
      return interaction.response

  def prompt_exceeds_input_token_limit(self, prompt: str, model: str | None = None) -> bool:
    if self._should_call_api():
      if not self.real_client:
        raise ValueError('Real client is required for recording API calls')
      real_model = model
      if model == 'mock-model' or model is None:
        real_model = self.real_client.model
      return self.real_client.prompt_exceeds_input_token_limit(prompt, real_model)
    return False


def get_mock_client(config: Config) -> MockLLMClient:
  """Creates a MockLLMClient, optionally wrapping a real provider for recording."""
  mode = os.environ.get('WPT_GEN_MOCK_MODE', 'replay')
  # Default to 'auto' if not specified, but let's use what the env var says
  if mode not in ['record', 'replay', 'auto']:
    raise ValueError(f'Invalid MOCK_MODE: {mode}')

  replay_id = os.environ.get('WPT_GEN_REPLAY_ID', 'default_mock')

  real_client = None
  if mode in ['record', 'auto']:
    # Try to initialize a real client for recording
    # MOCK_REAL_PROVIDER allows specifying which provider to record from
    real_provider = os.environ.get('WPT_GEN_MOCK_REAL_PROVIDER', 'gemini')
    # Make a copy of config and set provider back to the real one
    import copy

    from wptgen.llm import get_llm_client

    real_config = copy.copy(config)
    real_config.provider = real_provider
    # This might fail if the user didn't set API key, which is correct for recording.
    try:
      # re-load just enough for the real provider
      if real_provider == 'gemini':
        real_config.api_key = os.environ.get('GEMINI_API_KEY')
        real_config.default_model = 'gemini-3.1-pro-preview'
        real_config.categories = {
          'lightweight': 'gemini-3-flash-preview',
          'reasoning': 'gemini-3.1-pro-preview',
        }
      elif real_provider == 'openai':
        real_config.api_key = os.environ.get('OPENAI_API_KEY')
        real_config.default_model = 'gpt-5.2-high'
        real_config.categories = {'lightweight': 'gpt-5-mini', 'reasoning': 'gpt-5.2-high'}
      elif real_provider == 'anthropic':
        real_config.api_key = os.environ.get('ANTHROPIC_API_KEY')
        real_config.default_model = 'claude-opus-4-6'
        real_config.categories = {
          'lightweight': 'claude-sonnet-4-6',
          'reasoning': 'claude-opus-4-6',
        }

      real_client = get_llm_client(real_config)
    except Exception as e:
      if mode == 'record':
        raise ValueError(f'Failed to initialize real client for recording: {e}') from e

  return MockLLMClient(
    mode=mode,  # type: ignore
    replay_id=replay_id,
    real_client=real_client,
    max_retries=config.max_retries,
    timeout=config.timeout,
  )

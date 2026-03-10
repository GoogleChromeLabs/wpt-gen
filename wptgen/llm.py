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

import logging
from abc import ABC, abstractmethod
from typing import Any

import anthropic
import httpx
import openai
import tiktoken
from google import genai
from google.genai import types
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from wptgen.config import DEFAULT_LLM_TIMEOUT, Config
from wptgen.utils import retry

# Default retry configuration for LLM calls
MAX_RETRIES = 3


class LLMTimeoutError(Exception):
  """Raised when an LLM request times out."""

  pass


class InvalidModelError(Exception):
  """Raised when the provided model is invalid or inaccessible."""

  pass


class LLMClient(ABC):
  """Abstract base class for all LLM providers."""

  def __init__(
    self,
    api_key: str,
    model: str,
    max_retries: int = MAX_RETRIES,
    timeout: int = DEFAULT_LLM_TIMEOUT,
  ):
    self.api_key = api_key
    self.model = model
    self.max_retries = max_retries
    self.timeout = timeout

  @abstractmethod
  def verify_model(self) -> None:
    """Verifies that the requested model is valid and accessible."""
    pass  # pragma: no cover

  @abstractmethod
  def count_tokens(self, prompt: str, model: str | None = None) -> int:
    """Returns the total number of tokens for the given prompt."""
    pass  # pragma: no cover

  @abstractmethod
  def generate_content(
    self,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
  ) -> str:
    """Generates a response from the LLM."""
    pass  # pragma: no cover

  @abstractmethod
  def prompt_exceeds_input_token_limit(self, prompt: str, model: str | None = None) -> bool:
    """Checks if the prompt exceeds the model's input token limit."""
    pass  # pragma: no cover


class GeminiClient(LLMClient):
  def __init__(
    self,
    api_key: str,
    model: str,
    max_retries: int = MAX_RETRIES,
    timeout: int = DEFAULT_LLM_TIMEOUT,
  ):
    super().__init__(api_key, model, max_retries, timeout)
    # Initialize the official Google GenAI client
    # Casting timeout to milliseconds to ensure it's interpreted correctly by the SDK
    self.client = genai.Client(
      api_key=self.api_key,
      http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
    )
    self.verify_model()

  def verify_model(self) -> None:
    try:
      self.client.models.get(model=self.model)
    except Exception as e:
      raise InvalidModelError(f"Failed to verify Gemini model '{self.model}': {e}") from e

  @retry(exceptions=Exception, max_attempts_attr='max_retries')
  def count_tokens(self, prompt: str, model: str | None = None) -> int:
    target_model = model or self.model
    try:
      response = self.client.models.count_tokens(model=target_model, contents=prompt)
    except httpx.TimeoutException as e:
      raise LLMTimeoutError(f'Gemini API request timed out after {self.timeout}s: {e}') from e
    if response.total_tokens is None:
      raise ValueError('Gemini API returned no token count.')
    return response.total_tokens

  @retry(exceptions=Exception, max_attempts_attr='max_retries')
  def generate_content(
    self,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
  ) -> str:
    target_model = model or self.model
    config = types.GenerateContentConfig()
    if system_instruction:
      config.system_instruction = system_instruction
    if temperature is not None:
      config.temperature = temperature

    try:
      response = self.client.models.generate_content(
        model=target_model, contents=prompt, config=config
      )
    except httpx.TimeoutException as e:
      raise LLMTimeoutError(f'Gemini API request timed out after {self.timeout}s: {e}') from e

    if response.text is None:
      raise ValueError('Gemini API returned no text.')
    return response.text

  def prompt_exceeds_input_token_limit(self, prompt: str, model: str | None = None) -> bool:
    """Checks the token size of a prompt and checks if it exceeds the input
       limit of the Gemini model.

    Args:
      prompt: The input prompt string.
      model: Optional model override.

    Returns:
      Boolean value of whether the input token limit is exceeded.
    """
    target_model = model or self.model
    token_count = self.count_tokens(prompt, model=target_model)
    try:
      model_info = self.client.models.get(model=target_model)
    except httpx.TimeoutException as e:
      raise LLMTimeoutError(f'Gemini API request timed out after {self.timeout}s: {e}') from e
    limit = model_info.input_token_limit or 1_000_000  # Fallback to 1M if not specified

    logging.info(f'Prompt token count: {token_count}')
    logging.info(f"Model's context limit token count: {limit}")

    return token_count > limit


class OpenAIClient(LLMClient):
  def __init__(
    self,
    api_key: str,
    model: str,
    max_retries: int = MAX_RETRIES,
    timeout: int = DEFAULT_LLM_TIMEOUT,
  ):
    super().__init__(api_key, model, max_retries, timeout)
    self.client = OpenAI(api_key=self.api_key, timeout=float(self.timeout))
    self.verify_model()

  def verify_model(self) -> None:
    try:
      self.client.models.retrieve(self.model)
    except Exception as e:
      raise InvalidModelError(f"Failed to verify OpenAI model '{self.model}': {e}") from e

  def count_tokens(self, prompt: str, model: str | None = None) -> int:
    """Returns the total number of tokens for the given prompt using tiktoken."""
    target_model = model or self.model
    try:
      encoding = tiktoken.encoding_for_model(target_model)
    except KeyError:
      # Fallback for unknown models
      encoding = tiktoken.get_encoding('cl100k_base')
    return len(encoding.encode(prompt))

  @retry(exceptions=Exception, max_attempts_attr='max_retries')
  def generate_content(
    self,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
  ) -> str:
    target_model = model or self.model
    messages: list[ChatCompletionMessageParam] = []
    if system_instruction:
      messages.append({'role': 'system', 'content': system_instruction})
    messages.append({'role': 'user', 'content': prompt})

    try:
      response = self.client.chat.completions.create(
        model=target_model, messages=messages, temperature=temperature
      )
    except openai.APITimeoutError as e:
      raise LLMTimeoutError(f'OpenAI API request timed out after {self.timeout}s: {e}') from e

    content = response.choices[0].message.content
    if content is None:
      raise ValueError('OpenAI API returned no content.')
    return content

  def prompt_exceeds_input_token_limit(self, prompt: str, model: str | None = None) -> bool:
    """Checks the token size of a prompt and checks if it exceeds the input
       limit of the OpenAI model.

    Args:
      prompt: The input prompt string.
      model: Optional model override.

    Returns:
      Boolean value of whether the input token limit is exceeded.
    """
    target_model = model or self.model
    token_count = self.count_tokens(prompt, model=target_model)

    # There is no way to programmatically check model token limits for OpenAI
    # models. GPT-5.2 has a 400,000 token context limit according to:
    # https://developers.openai.com/api/docs/models/gpt-5.2
    limit = 400_000

    logging.info(f'Prompt token count (estimated): {token_count}')
    logging.info(f"Model's assumed context limit token count: {limit}")

    return token_count > limit


class AnthropicClient(LLMClient):
  def __init__(
    self,
    api_key: str,
    model: str,
    max_retries: int = MAX_RETRIES,
    timeout: int = DEFAULT_LLM_TIMEOUT,
  ):
    super().__init__(api_key, model, max_retries, timeout)
    self.client = anthropic.Anthropic(api_key=self.api_key, timeout=float(self.timeout))
    self.verify_model()

  def verify_model(self) -> None:
    try:
      self.client.models.retrieve(self.model)
    except Exception as e:
      raise InvalidModelError(f"Failed to verify Anthropic model '{self.model}': {e}") from e

  @retry(exceptions=Exception, max_attempts_attr='max_retries')
  def count_tokens(self, prompt: str, model: str | None = None) -> int:
    """Returns the total number of tokens for the given prompt using Anthropic SDK."""
    target_model = model or self.model
    try:
      response = self.client.messages.count_tokens(
        model=target_model,
        messages=[{'role': 'user', 'content': prompt}],
      )
      return response.input_tokens
    except anthropic.APITimeoutError as e:
      raise LLMTimeoutError(f'Anthropic API request timed out after {self.timeout}s: {e}') from e

  @retry(exceptions=Exception, max_attempts_attr='max_retries')
  def generate_content(
    self,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
  ) -> str:
    target_model = model or self.model
    kwargs: dict[str, Any] = {
      'model': target_model,
      'messages': [{'role': 'user', 'content': prompt}],
    }

    if system_instruction:
      kwargs['system'] = system_instruction
    if temperature is not None:
      kwargs['temperature'] = temperature

    try:
      response = self.client.messages.create(**kwargs)
    except anthropic.APITimeoutError as e:
      raise LLMTimeoutError(f'Anthropic API request timed out after {self.timeout}s: {e}') from e

    # Anthropic returns a list of content blocks. We assume the first block is text.
    if not response.content:
      raise ValueError('Anthropic API returned no content.')

    content = response.content[0].text
    if not isinstance(content, str):
      raise ValueError('Anthropic API returned no text.')
    return content

  def prompt_exceeds_input_token_limit(self, prompt: str, model: str | None = None) -> bool:
    """Checks the token size of a prompt and checks if it exceeds the input
       limit of the Anthropic model.

    Args:
      prompt: The input prompt string.
      model: Optional model override.

    Returns:
      Boolean value of whether the input token limit is exceeded.
    """
    target_model = model or self.model
    token_count = self.count_tokens(prompt, model=target_model)

    # Claude 4 models have a 200,000 token context limit.
    limit = 200_000

    logging.info(f'Prompt token count: {token_count}')
    logging.info(f"Model's context limit token count: {limit}")

    return token_count > limit


def get_llm_client(config: Config) -> LLMClient:
  """Factory function to instantiate the correct LLM provider."""
  assert config.api_key is not None, 'api_key must be set in configuration'
  if config.provider == 'gemini':
    return GeminiClient(
      api_key=config.api_key,
      model=config.default_model,
      max_retries=config.max_retries,
      timeout=config.timeout,
    )
  elif config.provider == 'openai':
    return OpenAIClient(
      api_key=config.api_key,
      model=config.default_model,
      max_retries=config.max_retries,
      timeout=config.timeout,
    )
  elif config.provider == 'anthropic':
    return AnthropicClient(
      api_key=config.api_key,
      model=config.default_model,
      max_retries=config.max_retries,
      timeout=config.timeout,
    )
  else:
    raise ValueError(f'Unsupported provider: {config.provider}')

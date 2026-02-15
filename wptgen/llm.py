from abc import ABC, abstractmethod

from google import genai
from google.genai import types
from openai import OpenAI

from wptgen.config import Config


class LLMClient(ABC):
  """Abstract base class for all LLM providers."""

  def __init__(self, api_key: str, model: str):
    self.api_key = api_key
    self.model = model

  @abstractmethod
  def count_tokens(self, prompt: str) -> int:
    """Returns the total number of tokens for the given prompt."""
    pass

  @abstractmethod
  def generate_content(self, prompt: str, system_instruction: str | None = None) -> str:
    """Generates a response from the LLM."""
    pass


class GeminiClient(LLMClient):
  def __init__(self, api_key: str, model: str):
    super().__init__(api_key, model)
    # Initialize the official Google GenAI client
    self.client = genai.Client(api_key=self.api_key)

  def count_tokens(self, prompt: str) -> int:
    response = self.client.models.count_tokens(model=self.model, contents=prompt)
    return response.total_tokens

  def generate_content(self, prompt: str, system_instruction: str | None = None) -> str:
    config = types.GenerateContentConfig()
    if system_instruction:
      config.system_instruction = system_instruction

    response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
    return response.text


class OpenAIClient(LLMClient):
  def __init__(self, api_key: str, model: str):
    super().__init__(api_key, model)
    self.client = OpenAI(api_key=self.api_key)

  def count_tokens(self, prompt: str) -> int:
    # MVP Note: OpenAI does not have a lightweight token counting API like Gemini.
    # For MVP, we can return a rough estimate (1 token ~= 4 chars) or integrate tiktoken later.
    return len(prompt) // 4

  def generate_content(self, prompt: str, system_instruction: str | None = None) -> str:
    messages = []
    if system_instruction:
      messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    response = self.client.chat.completions.create(model=self.model, messages=messages)
    return response.choices[0].message.content


def get_llm_client(config: Config) -> LLMClient:
  """Factory function to instantiate the correct LLM provider."""
  if config.provider == "gemini":
    return GeminiClient(api_key=config.api_key, model=config.model)
  elif config.provider == "openai":
    return OpenAIClient(api_key=config.api_key, model=config.model)
  else:
    raise ValueError(f"Unsupported provider: {config.provider}")

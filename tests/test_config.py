import pytest

from wptgen.config import Config, load_config


def test_load_config_default_gemini_happy_path(monkeypatch):
  """Test the happy path: default provider (gemini) with a valid API key."""
  # Arrange: Mock the environment variable
  monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key-123")

  # Act: Pass a non-existent config path so it relies purely on the code's defaults
  config = load_config(config_path="non_existent_dummy.yaml")

  # Assert
  assert isinstance(config, Config)
  assert config.provider == "gemini"
  assert config.model == "gemini-3-pro-preview"
  assert config.api_key == "mock-gemini-key-123"


def test_load_config_provider_override_openai(monkeypatch):
  """Test overriding the provider via the CLI flag to openai."""
  # Mock the OpenAI key instead
  monkeypatch.setenv("OPENAI_API_KEY", "mock-openai-key-456")

  # Force the provider to openai
  config = load_config(config_path="non_existent_dummy.yaml", provider_override="openai")

  assert config.provider == "openai"
  assert config.model == "gpt-5.2-high"
  assert config.api_key == "mock-openai-key-456"


def test_load_config_missing_api_key_raises_error(monkeypatch):
  """Test that missing the required environment variable raises a ValueError."""
  # Ensure the environment variable is explicitly removed for this test
  monkeypatch.delenv("GEMINI_API_KEY", raising=False)

  # Verify the exact error is raised
  with pytest.raises(ValueError, match="GEMINI_API_KEY environment variable is missing"):
    load_config(config_path="non_existent_dummy.yaml")


def test_load_config_unsupported_provider():
  """Test that requesting a random/unsupported provider raises an error."""
  # Act & Assert
  with pytest.raises(ValueError, match="CRITICAL: Unsupported provider"):
    load_config(config_path="non_existent_dummy.yaml", provider_override="sillyLLM")

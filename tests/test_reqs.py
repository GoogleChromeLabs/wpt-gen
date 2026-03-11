from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wptgen.config import Config
from wptgen.models import WebFeatureMetadata, WorkflowContext
from wptgen.phases.requirements_extraction import (
  run_requirements_extraction,
  run_requirements_extraction_categorized,
  run_requirements_extraction_iterative,
)


@pytest.fixture
def base_context() -> WorkflowContext:
  return WorkflowContext(
    feature_id='test',
    metadata=WebFeatureMetadata('Test', 'Desc', ['http://spec']),
    spec_contents={'http://spec': 'Spec'},
  )


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
  return Config(
    provider='test',
    default_model='model',
    api_key='key',
    wpt_path=str(tmp_path),
    categories={},
    phase_model_mapping={},
  )


@pytest.mark.asyncio
async def test_run_requirements_extraction_no_cache(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock Prompt'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    return_value='<requirements_list><requirement></requirement></requirements_list>',
  )

  result = await run_requirements_extraction(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )

  assert '<requirement>' in result
  assert (tmp_path / 'test__requirements.xml').exists()


@pytest.mark.asyncio
async def test_run_requirements_extraction_fails(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  mocker.patch('wptgen.phases.requirements_extraction.generate_safe', return_value=None)

  result = await run_requirements_extraction(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert result is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_cache(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_ui.confirm.return_value = True
  (tmp_path / 'test__requirements.xml').write_text('cached iterative')
  mock_llm = MagicMock()

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, MagicMock(), tmp_path
  )
  assert result == 'cached iterative'


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_fails(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe', return_value=None
  )  # Fails initial

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert result is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_success_and_save(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  # Returns initial requirements list
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<requirements_list><requirement></requirement></requirements_list>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
    ],
  )

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert '<requirement>' in result
  assert (tmp_path / 'test__requirements.xml').exists()


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_fails(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  mocker.patch('wptgen.phases.requirements_extraction.generate_safe', return_value=None)

  result = await run_requirements_extraction_categorized(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert result is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_success_and_save(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  # Mocking standard successful categorizations, one with markdown formatting that we want to trigger
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '```xml\n<requirements_list><requirement id="R1"></requirement></requirements_list>\n```',
      '<requirements_list><requirement id="R2"></requirement></requirements_list>',
      '<requirements_list><requirement id="R3"></requirement></requirements_list>',
      '<requirements_list><requirement id="R4"></requirement></requirements_list>',
      '<requirements_list><requirement id="R5"></requirement></requirements_list>',
    ],
  )

  result = await run_requirements_extraction_categorized(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert '<requirement id="R1">' in result
  assert '<requirement id="R2">' in result
  assert (tmp_path / 'test__requirements.xml').exists()


@pytest.mark.asyncio
async def test_run_requirements_extraction_cache_success(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_ui.confirm.return_value = True
  (tmp_path / 'test__requirements.xml').write_text('cached basic')
  mock_llm = MagicMock()

  result = await run_requirements_extraction(
    base_context, mock_config, mock_llm, mock_ui, MagicMock(), tmp_path
  )
  assert result == 'cached basic'


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_rationale(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  # Returns rationale for the 207-210 block
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<rationale>Because I said so</rationale>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
      '<test_suggestion></test_suggestion>',
    ],
  )

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  # The first one is a rationale so it prints ui.info and continues. The loop will then hit an error if there are no requirements extracted.
  assert result is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_iterative_exhausted(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')
  # Returns exhausted for the 304-305 block
  mocker.patch(
    'wptgen.phases.requirements_extraction.generate_safe',
    side_effect=[
      '<status>EXHAUSTED</status>',
    ],
  )

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert result is None


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_max_iter(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_llm = MagicMock()
  jinja_env = MagicMock()
  jinja_env.get_template.return_value.render.return_value = 'Mock'

  mocker.patch('wptgen.phases.requirements_extraction.confirm_prompts')

  # Needs a lot of valid generations to hit max_iterations (which is 10 by default)
  # But wait, max_iter logic is in iterative! Oh wait, `max_iterations = 10` is in `run_requirements_extraction_iterative`.
  # Let me mock max_iterations!
  # No, we can just pass side_effect.
  side_effects = ['<requirements_list><requirement id="R1"></requirement></requirements_list>'] * 12
  mocker.patch('wptgen.phases.requirements_extraction.generate_safe', side_effect=side_effects)

  result = await run_requirements_extraction_iterative(
    base_context, mock_config, mock_llm, mock_ui, jinja_env, tmp_path
  )
  assert result is not None
  mock_ui.warning.assert_called_with('Reached maximum iterations (10).')


@pytest.mark.asyncio
async def test_run_requirements_extraction_categorized_cache(
  mocker: MagicMock, base_context, mock_config, tmp_path
) -> None:
  mock_ui = MagicMock()
  mock_ui.confirm.return_value = True
  (tmp_path / 'test__requirements.xml').write_text('cached categorized')
  mock_llm = MagicMock()

  result = await run_requirements_extraction_categorized(
    base_context, mock_config, mock_llm, mock_ui, MagicMock(), tmp_path
  )
  assert result == 'cached categorized'

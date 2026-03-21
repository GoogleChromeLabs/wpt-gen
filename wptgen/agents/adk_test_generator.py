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

from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from jinja2 import Environment

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.streaming import stream_adk_event_to_ui
from wptgen.agents.tools import _validate_safe_path, create_agent_tools
from wptgen.config import Config
from wptgen.models import TestType, WorkflowContext
from wptgen.ui import UIProvider


async def generate_test_with_adk(
  suggestion_xml: str,
  root_name: str,
  test_type_enum: TestType,
  context: WorkflowContext,
  config: Config,
  jinja_env: Environment,
  ui: UIProvider,
  wpt_style_guide: str,
  test_type_guide: str,
) -> list[tuple[Path, str, str]]:
  """Runs the ADK Agent to generate tests for a single blueprint.

  Args:
      suggestion_xml: The XML blueprint for the test.
      root_name: The base filename to use (e.g., 'feature-1').
      test_type_enum: The type of test to generate.
      context: The workflow context (contains metadata).
      config: The configuration object.
      jinja_env: The Jinja2 environment for loading templates.
      ui: The UI provider for logging output.
      wpt_style_guide: The general WPT style guide content.
      test_type_guide: The specific style guide for this test type.

  Returns:
      A list of tuples containing (file_path, file_content, suggestion_xml).
  """
  model_string = setup_adk_environment(config)
  wpt_root = Path(config.wpt_path)

  # We need to extract the paths from the agent's final tool call.
  generated_paths: list[str] = []

  def report_generation_complete(file_paths: list[str]) -> dict[str, Any]:
    """Call this tool ONLY when you have successfully written all necessary test files to disk.

    Args:
        file_paths: A list of the absolute or relative file paths you generated.

    Returns:
        A dictionary confirming completion.
    """
    generated_paths.extend(file_paths)
    return {'status': 'success', 'message': 'Generation recorded.'}

  tools = create_agent_tools(wpt_root, browser=config.run_on_browser, channel=config.run_on_channel)
  tools.append(FunctionTool(func=report_generation_complete))

  system_template = jinja_env.get_template('adk_test_generator_system.jinja')
  instruction = system_template.render(
    wpt_style_guide=wpt_style_guide,
    test_type=test_type_enum.value,
    test_type_guide=test_type_guide,
  )

  agent = Agent(
    name='wpt_generator',
    model=model_string,
    instruction=instruction,
    tools=list(tools),
  )

  session_service = InMemorySessionService()  # type: ignore
  session = await session_service.create_session(
    app_name='wpt-gen', user_id='cli_user', session_id=f'gen_{root_name}'
  )
  runner = Runner(agent=agent, app_name='wpt-gen', session_service=session_service)

  feature_name = context.metadata.name if context.metadata else 'Unknown'
  feature_description = context.metadata.description if context.metadata else 'Unknown'

  # Configure output directory context
  if config.output_dir:
    output_dir = Path(config.output_dir).resolve()
  else:
    output_dir = wpt_root

  prompt_template = jinja_env.get_template('adk_test_generator.jinja')
  prompt = prompt_template.render(
    output_dir=output_dir,
    root_name=root_name,
    suggestion_xml=suggestion_xml,
    feature_name=feature_name,
    feature_description=feature_description,
    spec_contents=context.spec_contents,
  )
  content = types.Content(role='user', parts=[types.Part(text=prompt)])

  events = runner.run_async(session_id=session.id, user_id='cli_user', new_message=content)

  # We just consume the stream to let the agent run.
  # (Task 4 will add the UI streaming integration here)
  async for event in events:
    stream_adk_event_to_ui(event, ui)

  results = []
  # If the agent correctly called the completion tool, we read those files back
  for path_str in generated_paths:
    try:
      target_path = Path(path_str)
      # Ensure it is absolutely relative to wpt_root
      target_path = _validate_safe_path(target_path, wpt_root)

      if target_path.is_file():
        file_content = target_path.read_text(encoding='utf-8')
        results.append((target_path, file_content, suggestion_xml))
    except (ValueError, OSError) as e:
      ui.error(f"Failed to read securely generated file '{path_str}': {e}")

  return results

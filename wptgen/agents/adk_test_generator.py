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

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.tools import create_file_tools
from wptgen.config import Config
from wptgen.models import TestType, WorkflowContext

AGENT_INSTRUCTION_TEMPLATE = """You are an expert-level Web Platform Test (WPT) generation agent.
You are equipped with tools to explore the local WPT repository and write tests directly to the file system.
Your ultimate goal is to generate test files that fulfill a given test blueprint (<test_suggestion>) and save them to the correct directory.

# DIRECTIVES
1. Explore: Use the provided `list_directory`, `search_files`, and `read_file` tools to understand the local WPT structure and find related tests if necessary.
2. Generate: Use the `write_file` tool to save the generated test files (and reference files, if applicable) to the designated output directory. Ensure your filenames use the correct WPT suffixes (e.g., .https.html, .any.js, .window.js).
3. Finish: Once you have successfully written ALL the necessary files to disk, you MUST call the `report_generation_complete` tool with the list of the file paths you created, and then stop.

# BLUEPRINT MAPPING PROTOCOL
You will receive a `<test_suggestion>` XML blueprint in the user prompt. You must map its fields to the WPT file as follows:
* `<title>`: Use this exact string for the HTML `<title>` tag AND as the test name string in your `test()` or `promise_test()` function.
* `<description>`: Insert this as a block comment at the top of your `<script>` to explain the test's intent.
* `<pre_conditions>`: Translate this into the necessary HTML elements within the `<body>`, or initialize them in a `setup()` block.
* `<steps>`: Translate these sequential steps directly into the JavaScript execution logic inside the test function.
* `<expected_result>`: Map this strictly to the correct assertion (e.g., `assert_equals`, `assert_throws_js`, `promise_rejects_dom`).

# WPT GENERAL STYLE GUIDE
{wpt_style_guide}

# {test_type} STYLE GUIDE & RULES
{test_type_guide}
"""


async def generate_test_with_adk(
  suggestion_xml: str,
  root_name: str,
  test_type_enum: TestType,
  context: WorkflowContext,
  config: Config,
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

  tools = create_file_tools(wpt_root)
  tools.append(FunctionTool(func=report_generation_complete))

  instruction = AGENT_INSTRUCTION_TEMPLATE.format(
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

  prompt = f"""Generate the WPT tests for the following blueprint.
The output directory for these files MUST be: {output_dir}
The root filename you MUST use for these files is: {root_name}

{suggestion_xml}

Feature Name: {feature_name}
Feature Description: {feature_description}

Related Specifications:
{context.spec_contents}
"""
  content = types.Content(role='user', parts=[types.Part(text=prompt)])

  events = runner.run_async(session_id=session.id, user_id='cli_user', new_message=content)

  # We just consume the stream to let the agent run.
  # (Task 4 will add the UI streaming integration here)
  async for _ in events:
    pass

  results = []
  # If the agent correctly called the completion tool, we read those files back
  for path_str in generated_paths:
    try:
      target_path = Path(path_str)
      if not target_path.is_absolute():
        target_path = wpt_root / target_path

      target_path = target_path.resolve()

      if target_path.is_file():
        file_content = target_path.read_text(encoding='utf-8')
        results.append((target_path, file_content, suggestion_xml))
    except Exception:
      pass

  return results

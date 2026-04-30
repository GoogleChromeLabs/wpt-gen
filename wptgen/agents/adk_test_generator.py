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

"""Agentic test generation using the Google ADK framework."""

import re
from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.skills import load_skill_from_dir
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types
from jinja2 import Environment

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.streaming import ADKStreamManager, StreamConfig
from wptgen.agents.tools import _validate_safe_path, create_agent_tools
from wptgen.config import SKILLS_DIR, Config
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
) -> list[tuple[Path, str, str]]:
    """Runs the ADK Agent to generate tests for a single test suggestion.

    Args:
        suggestion_xml: The XML test suggestion for the test.
        root_name: The base filename to use (e.g., 'feature-1').
        test_type_enum: The type of test to generate.
        context: The workflow context (contains metadata).
        config: The configuration object.
        jinja_env: The Jinja2 environment for loading templates.
        ui: The UI provider for logging output.

    Returns:
        A list of tuples containing (file_path, file_content, suggestion_xml).
    """
    model_string = setup_adk_environment(config)
    if config.provider.lower() == "anthropic" and not model_string.startswith(
        "anthropic/"
    ):
        model_string = f"anthropic/{model_string}"
    elif config.provider.lower() == "openai" and not model_string.startswith(
        "openai/"
    ):
        model_string = f"openai/{model_string}"
    if not config.wpt_path:
        raise ValueError("WPT path is required to generate tests.")
    wpt_root = Path(config.wpt_path)

    # We need to extract the paths from the agent's final tool call.
    generated_paths: list[str] = []

    def report_generation_complete(file_paths: list[str]) -> dict[str, Any]:
        """Tool to call ONLY when all test files are written to disk.

        Args:
            file_paths: A list of the absolute or relative file paths generated.

        Returns:
            A dictionary confirming completion.
        """
        generated_paths.extend(file_paths)
        return {"status": "success", "message": "Generation recorded."}

    tools: list[Any] = list(
        create_agent_tools(
            wpt_root,
            ui,
            config.run_on_browser,
            config.run_on_channel,
            include_run_tool=not config.skip_run,
            omit_search_feature_tests=(context.feature_id is None),
        )
    )
    tools.append(FunctionTool(func=report_generation_complete))

    skill_dir = SKILLS_DIR / "wpt-generator"
    if skill_dir.is_dir():
        try:
            wpt_generator_skill = load_skill_from_dir(skill_dir)

            # Conditionally template the skill instructions to avoid confusing
            # the agent when no web_feature_id is provided.
            has_feature_id = bool(
                re.search(r"<web_feature_id>\s*[^<\s]", suggestion_xml)
            )
            template = jinja_env.from_string(wpt_generator_skill.instructions)
            wpt_generator_skill.instructions = template.render(
                has_web_feature_id=has_feature_id
            )

            skill_toolset = SkillToolset(skills=[wpt_generator_skill])
            tools.append(skill_toolset)
        except Exception as e:
            ui.error(f"Failed to load wpt-generator skill: {e}")
    else:
        ui.warning(
            "wpt-generator skill directory not found. Agent will generate "
            "tests without skill guidance."
        )

    system_template = jinja_env.get_template("adk_test_generator_system.jinja")
    instruction = system_template.render(
        test_type=test_type_enum.value,
    )

    # Prevent ADK's internal template parser from crashing when it encounters
    # WPT syntax like `{{host}}` or `{{variable}}` by mapping them to itself.
    adk_state: dict[str, Any] = {}
    for match in re.finditer(r"\{+([^{}]+)\}+", instruction):
        var_name = match.group(1).strip()
        if var_name.isidentifier():
            adk_state[var_name] = match.group(0)

    # Ensure the agent name is a valid Python identifier.
    safe_root_name = root_name.replace("-", "_").replace(".", "_")
    agent_kwargs: dict[str, Any] = {
        "name": f"wpt_generator_{safe_root_name}",
        "model": model_string,
        "instruction": instruction,
        "tools": list(tools),
    }

    # Enable native thought blocks for compatible Gemini models
    if config.provider.lower() == "gemini":
        model_lower = model_string.lower()
        if "pro" in model_lower or "thinking" in model_lower:
            agent_kwargs["generate_content_config"] = (
                types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(include_thoughts=True)
                )
            )

    agent = Agent(**agent_kwargs)

    session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
    session = await session_service.create_session(
        app_name="wpt-gen",
        user_id="cli_user",
        session_id=f"gen_{root_name}",
        state=adk_state,
    )
    runner = Runner(
        agent=agent, app_name="wpt-gen", session_service=session_service
    )

    feature_name = context.metadata.name if context.metadata else "Unknown"
    feature_description = (
        context.metadata.description if context.metadata else "Unknown"
    )

    # Configure output directory context
    if config.output_dir:
        output_dir = Path(config.output_dir).resolve()
    else:
        output_dir = wpt_root

    prompt_template = jinja_env.get_template("adk_test_generator.jinja")
    prompt = prompt_template.render(
        output_dir=output_dir,
        root_name=root_name,
        suggestion_xml=suggestion_xml,
        feature_name=feature_name,
        feature_description=feature_description,
        spec_contents=context.spec_contents,
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    try:
        events = runner.run_async(
            session_id=session.id, user_id="cli_user", new_message=content
        )

        # We just consume the stream to let the agent run.
        with ADKStreamManager(
            ui, config=StreamConfig(include_thoughts=config.include_thoughts)
        ) as stream_manager:
            async for event in events:
                stream_manager.process_event(event)

        results = []
        if not generated_paths:
            ui.warning("Agent finished but did not report any generated paths.")

        # If the agent correctly called the completion tool, we read the files
        for path_str in generated_paths:
            try:
                target_path = Path(path_str)
                # Ensure it is absolutely relative to wpt_root
                target_path = _validate_safe_path(target_path, wpt_root)

                if target_path.is_file():
                    file_content = target_path.read_text(encoding="utf-8")
                    results.append((target_path, file_content, suggestion_xml))
            except (ValueError, OSError) as e:
                ui.error(
                    f"Failed to read securely generated file '{path_str}': {e}"
                )

        return results

    finally:
        await runner.close()  # type: ignore[no-untyped-call]
        await session_service.delete_session(
            app_name="wpt-gen", user_id="cli_user", session_id=session.id
        )

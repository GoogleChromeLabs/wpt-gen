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

"""ADK Agents and execution runners for Requirements Extraction."""

from typing import Any
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from jinja2 import Environment

from wptgen.agents.provider import setup_adk_environment
from wptgen.agents.streaming import ADKStreamManager, StreamConfig
from wptgen.config import Config
from wptgen.models import WorkflowContext, WorkflowPhase


def create_requirements_generator_agent(
    config: Config, instruction: str
) -> Agent:
    """Creates the Generator agent for requirements extraction."""
    model_string = setup_adk_environment(config)
    reasoning_model = config.get_model_for_phase(
        WorkflowPhase.REQUIREMENTS_EXTRACTION
    )
    agent_model = reasoning_model or model_string

    return Agent(
        name="requirements_generator",
        model=agent_model,
        instruction=instruction,
    )


def create_requirements_critic_agent(config: Config, instruction: str) -> Agent:
    """Creates the Critic agent for requirements extraction."""
    model_string = setup_adk_environment(config)
    reasoning_model = config.get_model_for_phase(
        WorkflowPhase.REQUIREMENTS_EXTRACTION
    )
    agent_model = reasoning_model or model_string

    return Agent(
        name="requirements_critic",
        model=agent_model,
        instruction=instruction,
    )


async def run_generator_turn(
    config: Config,
    jinja_env: Environment,
    context: WorkflowContext,
    ui: Any,
    feedback: str | None = None,
) -> str | None:
    """Runs the Generator agent to extract requirements."""
    assert context.metadata is not None

    system_template = jinja_env.get_template(
        "adk_requirements_generator_system.jinja"
    )
    instruction = system_template.render()

    agent = create_requirements_generator_agent(config, instruction)

    prompt_template = jinja_env.get_template("adk_requirements_generator.jinja")
    prompt = prompt_template.render(
        feature_name=context.metadata.name,
        feature_description=context.metadata.description,
        specs=context.spec_contents,
        feedback=feedback,
    )

    session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
    session = await session_service.create_session(
        app_name="wpt-gen",
        user_id="cli_user",
        session_id=f"req_gen_{context.feature_id}",
    )
    runner = Runner(
        agent=agent, app_name="wpt-gen", session_service=session_service
    )

    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    full_response = ""
    try:
        events = runner.run_async(
            session_id=session.id, user_id="cli_user", new_message=content
        )

        with ADKStreamManager(
            ui, config=StreamConfig(include_thoughts=config.include_thoughts)
        ) as stream_manager:
            async for event in events:
                stream_manager.process_event(event)
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text and not getattr(part, "thought", False):
                            full_response += part.text

        return full_response

    finally:
        await runner.close()  # type: ignore[no-untyped-call]
        await session_service.delete_session(
            app_name="wpt-gen", user_id="cli_user", session_id=session.id
        )


async def run_critic_turn(
    config: Config,
    jinja_env: Environment,
    context: WorkflowContext,
    ui: Any,
    generated_requirements: str,
) -> str | None:
    """Runs the Critic agent to review requirements."""
    assert context.metadata is not None

    system_template = jinja_env.get_template(
        "adk_requirements_critic_system.jinja"
    )
    instruction = system_template.render()

    agent = create_requirements_critic_agent(config, instruction)

    prompt_template = jinja_env.get_template("adk_requirements_critic.jinja")
    prompt = prompt_template.render(
        feature_name=context.metadata.name,
        specs=context.spec_contents,
        generated_requirements=generated_requirements,
    )

    session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
    session = await session_service.create_session(
        app_name="wpt-gen",
        user_id="cli_user",
        session_id=f"req_critic_{context.feature_id}",
    )
    runner = Runner(
        agent=agent, app_name="wpt-gen", session_service=session_service
    )

    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    full_response = ""
    try:
        events = runner.run_async(
            session_id=session.id, user_id="cli_user", new_message=content
        )

        with ADKStreamManager(
            ui, config=StreamConfig(include_thoughts=config.include_thoughts)
        ) as stream_manager:
            async for event in events:
                stream_manager.process_event(event)
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text and not getattr(part, "thought", False):
                            full_response += part.text

        return full_response

    finally:
        await runner.close()  # type: ignore[no-untyped-call]
        await session_service.delete_session(
            app_name="wpt-gen", user_id="cli_user", session_id=session.id
        )

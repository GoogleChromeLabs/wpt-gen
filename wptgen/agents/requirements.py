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

"""ADK Agents for Requirements Extraction."""

from google.adk.agents import Agent
from wptgen.agents.provider import setup_adk_environment
from wptgen.config import Config
from wptgen.models import WorkflowPhase


def create_requirements_generator_agent(config: Config) -> Agent:
    """Creates the Generator agent for requirements extraction."""
    model_string = setup_adk_environment(config)
    # Resolve to reasoning model if available
    reasoning_model = config.get_model_for_phase(
        WorkflowPhase.REQUIREMENTS_EXTRACTION
    )
    agent_model = reasoning_model or model_string

    return Agent(
        name="requirements_generator",
        model=agent_model,
        instruction=(
            "You are an expert at extracting normative requirements from web "
            "specifications. "
            "Your goal is to identify all testable requirements."
        ),
    )


def create_requirements_critic_agent(config: Config) -> Agent:
    """Creates the Critic agent for requirements extraction."""
    model_string = setup_adk_environment(config)
    reasoning_model = config.get_model_for_phase(
        WorkflowPhase.REQUIREMENTS_EXTRACTION
    )
    agent_model = reasoning_model or model_string

    return Agent(
        name="requirements_critic",
        model=agent_model,
        instruction=(
            "You are an expert at reviewing requirements against "
            "specifications. "
            "Your goal is to find missing requirements and suggest "
            "improvements."
        ),
    )

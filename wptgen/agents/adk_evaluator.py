# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Agentic test evaluation using the Google ADK framework."""

import re
from enum import StrEnum
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
from wptgen.agents.streaming import ADKStreamManager, StreamConfig, TokenUsage
from wptgen.agents.tools import create_agent_tools
from wptgen.config import SKILLS_DIR, Config
from wptgen.ui import UIProvider

# Allow-list of tool names from create_agent_tools() that the evaluator
# may use. Anything not in this set is filtered out before the agent
# sees it. The evaluator is read-only: it never runs tests, never
# writes files (the report comes back through the completion tool and
# is written by the phase wrapper), and never explores the broader
# WPT repository.
EVALUATOR_TOOL_ALLOWLIST = frozenset(
    {
        "read_file",
        "list_directory",
        "search_files",
        "search_file_contents",
        "run_wpt_lint",
        "run_lint_ext",
    }
)


class EvaluatorStrategy(StrEnum):
    """Evaluator strategies. Both are served by the single `wpt-evaluator`
    skill, which branches internally on the strategy label passed in the
    prompt: `distilled` (default) judges against the distilled
    `rules.yaml` corpus; `raw` reads the curated upstream docs live.
    """

    DISTILLED = "distilled"
    RAW = "raw"


DEFAULT_EVALUATOR_STRATEGY = EvaluatorStrategy.DISTILLED

# The single skill dir + frontmatter name that serves both strategies.
EVALUATOR_SKILL_NAME = "wpt-evaluator"


async def evaluate_test_with_adk(
    test_path: Path,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
    strategy: EvaluatorStrategy = DEFAULT_EVALUATOR_STRATEGY,
) -> tuple[dict[str, Any], TokenUsage] | None:
    """Runs the ADK Agent to evaluate a single WPT test file.

    Args:
        test_path: Path to the test file under evaluation.
        config: The configuration object.
        jinja_env: The Jinja2 environment for loading templates.
        ui: The UI provider for logging output.

    Returns:
        A `(payload, token_usage)` tuple, or None if the agent did not
        submit a report. The payload dict has two keys, `findings` (a
        list of per-finding dicts) and `input_scope` (a dict describing
        what was read). The phase wrapper is responsible for rendering
        the report Markdown.
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
        raise ValueError("WPT path is required to evaluate tests.")
    wpt_root = Path(config.wpt_path)

    # Capture the structured payload the agent submits.
    reported_payload: list[dict[str, Any]] = []

    def report_evaluation_complete(
        findings: list[dict[str, Any]],
        input_scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Tool to call ONLY when the evaluation is fully composed.

        Submit the structured findings and the input scope. The wpt-gen
        CLI renders the Markdown report and writes it to disk. Do NOT
        attempt to format the report yourself; do NOT write any file.

        Args:
            findings: A list of finding objects, each containing the
                fields `rule_id` (the `rules.yaml` rule that was
                violated, e.g. "GENERAL-005"), `title` (short description),
                `severity` (one of "error", "warn", "info", "nit"),
                `test_line` (a line reference into the test file),
                `evidence` (a short quote or description), `source` (the
                rule's `wpt/...:Lstart-Lend` provenance), and `summary`
                (a one-sentence paraphrase of the rule).
            input_scope: An object describing what was loaded, with the
                fields `files` (a list of `{path, bytes, role}` rows
                where `role` is one of "skill", "rules", "test", or
                "dependency"), `dependencies_not_read` (a list of
                framework/external dependency paths that were detected
                but not read), and `strategy` (a stable label for the
                evaluator variant, currently "distilled").

        Returns:
            A dictionary confirming receipt.
        """
        reported_payload.append(
            {"findings": findings, "input_scope": input_scope}
        )
        return {"status": "success", "message": "Evaluation recorded."}

    # Build the evaluator's tool kit: the full create_agent_tools() set,
    # filtered to the allow-list, plus the completion tool.
    all_tools = list(
        create_agent_tools(
            wpt_root,
            ui,
            config.run_on_browser,
            config.run_on_channel,
            include_run_tool=False,
            omit_search_feature_tests=True,
        )
    )
    tools: list[Any] = [
        t for t in all_tools if t.func.__name__ in EVALUATOR_TOOL_ALLOWLIST
    ]
    tools.append(FunctionTool(func=report_evaluation_complete))

    if not isinstance(strategy, EvaluatorStrategy):
        try:
            strategy = EvaluatorStrategy(strategy)
        except ValueError:
            raise ValueError(
                f"Unknown evaluator strategy {strategy!r}. Valid "
                "strategies: "
                f'{", ".join(sorted(EvaluatorStrategy))}.'
            ) from None

    skill_dir = SKILLS_DIR / EVALUATOR_SKILL_NAME
    if skill_dir.is_dir():
        try:
            wpt_evaluator_skill = load_skill_from_dir(skill_dir)
            skill_toolset = SkillToolset(skills=[wpt_evaluator_skill])
            tools.append(skill_toolset)
        except Exception as e:
            ui.error(f"Failed to load {EVALUATOR_SKILL_NAME} skill: {e}")
    else:
        ui.warning(
            f"{EVALUATOR_SKILL_NAME} skill directory not found. Agent will "
            "evaluate without skill guidance."
        )

    system_template = jinja_env.get_template("adk_evaluator_system.jinja")
    instruction = system_template.render(skill_name=EVALUATOR_SKILL_NAME)

    # Prevent ADK's internal template parser from crashing if any tool
    # description contains WPT placeholder syntax (`{{host}}`, etc.).
    adk_state: dict[str, Any] = {}
    for match in re.finditer(r"\{+([^{}]+)\}+", instruction):
        var_name = match.group(1).strip()
        if var_name.isidentifier():
            adk_state[var_name] = match.group(0)

    # Ensure the agent name is a valid Python identifier.
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", test_path.stem)
    agent_kwargs: dict[str, Any] = {
        "name": f"wpt_evaluator_{safe_name}",
        "model": model_string,
        "instruction": instruction,
        "tools": list(tools),
    }

    # Enable native thought blocks for compatible Gemini models.
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
        session_id=f"eval_{safe_name}",
        state=adk_state,
    )
    runner = Runner(
        agent=agent, app_name="wpt-gen", session_service=session_service
    )

    prompt_template = jinja_env.get_template("adk_evaluator.jinja")
    prompt = prompt_template.render(
        test_path=str(test_path),
        skill_name=EVALUATOR_SKILL_NAME,
        strategy=strategy,
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    try:
        events = runner.run_async(
            session_id=session.id, user_id="cli_user", new_message=content
        )

        with ADKStreamManager(
            ui, config=StreamConfig(include_thoughts=config.include_thoughts)
        ) as stream_manager:
            async for event in events:
                stream_manager.process_event(event)

        if not reported_payload:
            ui.warning("Agent finished but did not submit a findings report.")
            return None

        return reported_payload[-1], stream_manager.token_usage

    finally:
        await runner.close()  # type: ignore[no-untyped-call]
        await session_service.delete_session(
            app_name="wpt-gen", user_id="cli_user", session_id=session.id
        )

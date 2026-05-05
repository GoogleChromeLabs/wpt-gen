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

"""Shared utilities and helpers for the WPT workflow phases."""

import asyncio


from wptgen.config import Config
from wptgen.models import WorkflowAborted
from wptgen.llm import LLMClient
from wptgen.ui import UIProvider

# Global semaphore to limit parallel LLM requests
_llm_semaphore: asyncio.Semaphore | None = None


def get_semaphore(config: Config) -> asyncio.Semaphore:
    """Returns a shared semaphore to limit parallel LLM requests."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(config.max_parallel_requests)
    return _llm_semaphore


async def confirm_prompts(
    prompt_data: list[tuple[str, str]],
    phase_name: str,
    llm: LLMClient,
    ui: UIProvider,
    config: Config,
    model: str | None = None,
) -> None:
    """Calculates token usage and asks for user confirmation.

    Args:
      prompt_data: A list of (prompt_text, task_name) tuples.
      phase_name: The name of the current workflow phase.
      llm: The LLM client.
      ui: The UI provider.
      config: The tool configuration.
      model: The specific model to use for counting.

    Raises:
      typer.Abort: If the user cancels the workflow.
    """
    loop = asyncio.get_running_loop()

    total_tokens = 0
    target_model = model or llm.model

    with ui.status(
        f"Calculating token usage for {phase_name} ({target_model})..."
    ):
        # We do token counting concurrently for speed
        async def get_info(prompt: str, name: str) -> tuple[int, bool, str]:
            async with get_semaphore(config):
                tokens = await loop.run_in_executor(
                    None, llm.count_tokens, prompt, target_model
                )
                limit_exceeded = await loop.run_in_executor(
                    None,
                    llm.prompt_exceeds_input_token_limit,
                    prompt,
                    target_model,
                )
            return tokens, limit_exceeded, name

        results = await asyncio.gather(
            *(get_info(p, n) for p, n in prompt_data)
        )

    for tokens, _, _ in results:
        total_tokens += tokens

    ui.report_token_usage(
        phase_name,
        target_model,
        results,
        total_tokens,
        auto_confirmed=config.yes_tokens,
    )

    if config.yes_tokens:
        return

    if not ui.confirm("\nProceed with these LLM requests?"):
        ui.warning("Aborting workflow due to user cancellation.")
        raise WorkflowAborted()


async def generate_safe(
    prompt: str,
    task_name: str,
    llm: LLMClient,
    ui: UIProvider,
    config: Config,
    system_instruction: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
) -> str:
    """Helper to run LLM generation in a thread and handle errors gracefully.

    Args:
      prompt: The user prompt.
      task_name: A descriptive name for the task.
      llm: The LLM client.
      ui: The UI provider.
      config: The tool configuration.
      system_instruction: Optional system instructions.
      temperature: Optional temperature override.
      model: Optional model override.

    Returns:
      The generated text response, or an empty string on failure.
    """
    target_model = model or llm.model
    effective_temp = (
        config.temperature if config.temperature is not None else temperature
    )
    try:
        loop = asyncio.get_running_loop()
        with ui.status(f"Executing {task_name} ({target_model})..."):
            async with get_semaphore(config):
                response = await loop.run_in_executor(
                    None,
                    llm.generate_content,
                    prompt,
                    system_instruction,
                    effective_temp,
                    model,
                )

        ui.success(f"{task_name} finished (using {target_model}).")
        if config.show_responses:
            ui.report_llm_response(response, task_name)
        return response
    except Exception as e:
        ui.error(f"{task_name} failed ({target_model}): {e}")
        return ""

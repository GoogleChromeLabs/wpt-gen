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
import re
from pathlib import Path


from wptgen.config import Config
from wptgen.models import WorkflowAborted, WorkflowPhase
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


def load_cached_requirements(
    label: str,
    cache_file: Path,
    config: Config,
    ui: UIProvider,
) -> str | None:
    """Loads requirements from cache if present and the user opts in.

    Args:
        label: Human-readable identifier for the cache entry (used in
            UI prompts; e.g. a feature_id or a spec slug).
        cache_file: The path to the potential cache file.
        config: The tool configuration.
        ui: The UI provider.

    Returns:
        The cached XML string if loaded, otherwise None.
    """
    if not cache_file.exists():
        return None

    ui.info(f"Found cached requirements for {label}.")
    if config.yes_cache:
        ui.success("Automatically using cached requirements (--yes-cache).")
        return cache_file.read_text(encoding="utf-8")
    if config.no_cache:
        ui.info("Automatically ignoring cached requirements (--no-cache).")
        return None
    if ui.confirm("Use cached requirements?"):
        ui.success("Using cached requirements.")
        return cache_file.read_text(encoding="utf-8")
    return None


async def invoke_extractor(
    extraction_prompt: str,
    extraction_system_prompt: str,
    label: str,
    cache_file: Path,
    config: Config,
    llm: LLMClient,
    ui: UIProvider,
) -> str | None:
    """Invokes the requirements-extraction LLM call and persists the result.

    Args:
        extraction_prompt: The fully-rendered user prompt.
        extraction_system_prompt: The fully-rendered system prompt.
        label: Short label used in UI ("Requirements Extraction" or
            "Spec Requirements Extraction").
        cache_file: Path where the resulting XML should be written.
        config: The tool configuration.
        llm: The LLM client.
        ui: The UI provider.

    Returns:
        The extracted requirements XML string, or None on failure.
    """
    await confirm_prompts(
        [(extraction_prompt, label)],
        label,
        llm,
        ui,
        config,
        model=config.get_model_for_phase(WorkflowPhase.REQUIREMENTS_EXTRACTION),
    )

    requirements_xml = await generate_safe(
        extraction_prompt,
        label,
        llm,
        ui,
        config,
        system_instruction=extraction_system_prompt,
        temperature=0.01,
        model=config.get_model_for_phase(WorkflowPhase.REQUIREMENTS_EXTRACTION),
    )

    if not requirements_xml:
        return None

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(requirements_xml, encoding="utf-8")
    count = len(re.findall(r"<requirement\b[^>]*>", requirements_xml))
    ui.success(f"Extracted {count} test requirements.")
    return requirements_xml

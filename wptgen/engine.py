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

import asyncio
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from wptgen.config import Config
from wptgen.llm import get_llm_client
from wptgen.models import WorkflowContext
from wptgen.phases.context_assembly import run_context_assembly
from wptgen.phases.coverage_audit import provide_coverage_report, run_coverage_audit
from wptgen.phases.evaluation import run_test_evaluation
from wptgen.phases.execution import run_test_execution
from wptgen.phases.generation import run_test_generation
from wptgen.phases.requirements_extraction import (
  run_requirements_extraction,
  run_requirements_extraction_categorized,
  run_requirements_extraction_iterative,
)
from wptgen.ui import UIProvider

__all__ = [
  'WPTGenEngine',
  'run_context_assembly',
  'run_requirements_extraction',
  'run_requirements_extraction_categorized',
  'run_requirements_extraction_iterative',
  'run_coverage_audit',
  'provide_coverage_report',
  'run_test_generation',
  'run_test_evaluation',
  'run_test_execution',
]


class WorkflowError(Exception):
  """Raised when a phase of the workflow fails to complete."""


class WPTGenEngine:
  def __init__(self, config: Config, ui: UIProvider):
    self.config = config
    self.ui = ui
    self.llm = get_llm_client(config)

    template_dir = Path(__file__).parent.joinpath('templates')
    self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

    assert self.config.cache_path is not None, 'cache_path must be set in configuration'
    self.cache_dir = Path(self.config.cache_path)
    self.cache_dir.mkdir(parents=True, exist_ok=True)

  def run_workflow(self, web_feature_id: str) -> None:
    """Entry point for the synchronous CLI to launch the async workflow."""
    asyncio.run(self._run_async_workflow(web_feature_id))

  def _get_resume_file_path(self, web_feature_id: str) -> Path:
    """Returns the path to the resume file for a given web feature ID."""
    return self.cache_dir / f'resume_{web_feature_id}.json'

  def _save_resume_state(self, context: WorkflowContext) -> None:
    """Serializes and saves the current workflow context to the cache."""
    resume_file = self._get_resume_file_path(context.feature_id)
    with open(resume_file, 'w', encoding='utf-8') as f:
      json.dump(context.to_dict(), f, indent=2)

  def _load_resume_state(self, web_feature_id: str) -> WorkflowContext | None:
    """Attempts to load a serialized workflow context from the cache."""
    resume_file = self._get_resume_file_path(web_feature_id)
    if not resume_file.exists():
      return None

    try:
      with open(resume_file, encoding='utf-8') as f:
        data = json.load(f)
      return WorkflowContext.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
      self.ui.warning(f'Failed to load resume state: {e}. Starting fresh.')
      return None

  async def _run_async_workflow(self, web_feature_id: str) -> None:
    """Orchestrates the end-to-end WPT generation workflow."""
    context = None
    if self.config.resume:
      context = self._load_resume_state(web_feature_id)
      if context:
        self.ui.success(f'Resuming workflow for {web_feature_id}')

    # Phase 1: Context Assembly
    if not context or not context.wpt_context:
      context = await run_context_assembly(web_feature_id, self.config, self.ui)
      if not context:
        raise WorkflowError('Phase 1: Context Assembly failed.')
      self._save_resume_state(context)

    # Phase 2: Requirements Extraction
    if not context.requirements_xml:
      if self.config.categorized_requirements:
        requirements_xml = await run_requirements_extraction_categorized(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      elif self.config.detailed_requirements:
        requirements_xml = await run_requirements_extraction_iterative(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      else:
        requirements_xml = await run_requirements_extraction(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      if not requirements_xml:
        raise WorkflowError('Phase 2: Requirements Extraction failed.')
      context.requirements_xml = requirements_xml
      self._save_resume_state(context)

    # Phase 3: Coverage Audit
    if not context.audit_response:
      audit_response = await run_coverage_audit(
        context, self.config, self.llm, self.ui, self.jinja_env
      )
      if not audit_response:
        raise WorkflowError('Phase 3: Coverage Audit failed.')
      context.audit_response = audit_response
      self._save_resume_state(context)

    # Skip Phase 4 if the user only wants the coverage audit report.
    if self.config.suggestions_only:
      await provide_coverage_report(context, self.config, self.ui)
      # Cleanup resume file if it exists, as this is a terminal state for suggestions-only
      resume_file = self._get_resume_file_path(web_feature_id)
      if resume_file.exists():
        resume_file.unlink()
      return

    # Phase 4: User Selection & Generation
    if not context.generated_tests:
      generated_tests = await run_test_generation(
        context, self.config, self.llm, self.ui, self.jinja_env
      )
      context.generated_tests = generated_tests
      self._save_resume_state(context)
    else:
      self.ui.success('Skipping Phase 4: Tests already generated.')

    # Phase 5: Evaluation
    if context.generated_tests and not self.config.skip_evaluation:
      await run_test_evaluation(
        context, self.config, self.llm, self.ui, self.jinja_env, context.generated_tests
      )
    elif context.generated_tests and self.config.skip_evaluation:
      self.ui.info('Skipping Phase 5: Evaluation.')

    # Phase 6: Test Execution
    if context.generated_tests:
      await run_test_execution(
        context, self.config, self.llm, self.ui, self.jinja_env, context.generated_tests
      )

    # Final cleanup of resume file on success
    resume_file = self._get_resume_file_path(web_feature_id)
    if resume_file.exists():
      resume_file.unlink()

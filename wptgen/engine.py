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
from wptgen.models import WorkflowContext, WorkflowPhase
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

  def _hydrate_context(self, web_feature_id: str) -> WorkflowContext:
    """Hydrates context from explicitly provided state directory or default cache."""
    state_dir = Path(self.config.state_dir) if self.config.state_dir else self.cache_dir
    resume_file = state_dir / f'resume_{web_feature_id}.json'
    if not resume_file.exists():
      resume_file = self._get_resume_file_path(web_feature_id)

    context = WorkflowContext(feature_id=web_feature_id)
    if resume_file.exists():
      try:
        with open(resume_file, encoding='utf-8') as f:
          data = json.load(f)
        context = WorkflowContext.from_dict(data)
      except Exception as e:
        self.ui.warning(f'Failed to load resume state from {resume_file}: {e}')

    req_file = state_dir / 'requirements.json'
    if req_file.exists():
      try:
        with open(req_file, encoding='utf-8') as f:
          context.requirements_xml = json.load(f).get('requirements_xml')
      except Exception:
        pass

    audit_file = state_dir / 'blueprints.json'
    if audit_file.exists():
      try:
        with open(audit_file, encoding='utf-8') as f:
          context.audit_response = json.load(f).get('audit_response')
      except Exception:
        pass

    tests_dir = (
      state_dir / 'generated_tests' if state_dir.joinpath('generated_tests').is_dir() else state_dir
    )
    tests_json = tests_dir / 'generated_tests.json'
    if tests_json.exists():
      try:
        with open(tests_json, encoding='utf-8') as f:
          tests_data = json.load(f)
          context.generated_tests = [
            (Path(item['path']), item['content'], item['suggestion']) for item in tests_data
          ]
      except Exception:
        pass
    else:
      # Glob for HTML files as a fallback execution hydrate source
      html_files = list(tests_dir.glob('*.html'))
      if html_files and not context.generated_tests:
        self.ui.info(f'Hydrating {len(html_files)} tests from {tests_dir}')
        context.generated_tests = [
          (
            hf,
            hf.read_text(encoding='utf-8'),
            '<test_suggestion><title>Imported Test</title></test_suggestion>',
          )
          for hf in html_files
        ]

    return context

  def _save_phase_artifacts(self, context: WorkflowContext, phase: WorkflowPhase) -> None:
    """Explicitly serializes structured output of major phases to disk."""
    state_dir = Path(self.config.state_dir) if self.config.state_dir else self.cache_dir
    state_dir.mkdir(parents=True, exist_ok=True)

    if phase == WorkflowPhase.REQUIREMENTS_EXTRACTION and context.requirements_xml:
      req_file = state_dir / 'requirements.json'
      with open(req_file, 'w', encoding='utf-8') as f:
        json.dump({'requirements_xml': context.requirements_xml}, f, indent=2)

    elif phase == WorkflowPhase.COVERAGE_AUDIT and context.audit_response:
      audit_file = state_dir / 'blueprints.json'
      with open(audit_file, 'w', encoding='utf-8') as f:
        json.dump({'audit_response': context.audit_response}, f, indent=2)

    elif phase == WorkflowPhase.GENERATION and context.generated_tests:
      tests_json = state_dir / 'generated_tests.json'
      tests_data = [
        {'path': str(p), 'content': c, 'suggestion': s} for p, c, s in context.generated_tests
      ]
      with open(tests_json, 'w', encoding='utf-8') as f:
        json.dump(tests_data, f, indent=2)

  async def _run_async_workflow(self, web_feature_id: str) -> None:
    """Orchestrates the end-to-end WPT generation workflow."""
    context = None

    if self.config.resume_from:
      self.ui.success(f'Explicitly resuming workflow from: {self.config.resume_from.value}')
      context = self._hydrate_context(web_feature_id)
    elif self.config.resume:
      context = self._load_resume_state(web_feature_id)
      if context:
        self.ui.success(f'Resuming workflow for {web_feature_id}')

    if not context:
      context = WorkflowContext(feature_id=web_feature_id)

    phases_order = [
      WorkflowPhase.REQUIREMENTS_EXTRACTION,
      WorkflowPhase.COVERAGE_AUDIT,
      WorkflowPhase.GENERATION,
      WorkflowPhase.EVALUATION,
      WorkflowPhase.EXECUTION,
    ]

    def should_run(phase: WorkflowPhase | None, has_data: bool) -> bool:
      if self.config.resume_from:
        target_idx = phases_order.index(phase) if phase else -1
        resume_idx = phases_order.index(self.config.resume_from)
        return target_idx >= resume_idx
      return not has_data

    # Phase 1: Context Assembly
    if should_run(None, bool(context.wpt_context)):
      context = await run_context_assembly(web_feature_id, self.config, self.ui)
      if not context:
        raise WorkflowError('Phase 1: Context Assembly failed.')
      self._save_resume_state(context)

    # Phase 2: Requirements Extraction
    if should_run(WorkflowPhase.REQUIREMENTS_EXTRACTION, bool(context.requirements_xml)):
      if self.config.single_prompt_requirements:
        requirements_xml = await run_requirements_extraction(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      elif self.config.detailed_requirements:
        requirements_xml = await run_requirements_extraction_iterative(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      else:
        requirements_xml = await run_requirements_extraction_categorized(
          context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
        )
      if not requirements_xml:
        raise WorkflowError('Phase 2: Requirements Extraction failed.')
      context.requirements_xml = requirements_xml
      self._save_resume_state(context)
      self._save_phase_artifacts(context, WorkflowPhase.REQUIREMENTS_EXTRACTION)

    # Phase 3: Coverage Audit
    if should_run(WorkflowPhase.COVERAGE_AUDIT, bool(context.audit_response)):
      audit_response = await run_coverage_audit(
        context, self.config, self.llm, self.ui, self.jinja_env
      )
      if not audit_response:
        raise WorkflowError('Phase 3: Coverage Audit failed.')
      context.audit_response = audit_response
      self._save_resume_state(context)
      self._save_phase_artifacts(context, WorkflowPhase.COVERAGE_AUDIT)

    # Skip Phase 4 if the user only wants the coverage audit report.
    if self.config.suggestions_only:
      await provide_coverage_report(context, self.config, self.ui)
      # Cleanup resume file if it exists, as this is a terminal state for suggestions-only
      resume_file = self._get_resume_file_path(web_feature_id)
      if resume_file.exists():
        resume_file.unlink()
      return

    # Phase 4: User Selection & Generation
    if should_run(WorkflowPhase.GENERATION, bool(context.generated_tests)):
      generated_tests = await run_test_generation(
        context, self.config, self.llm, self.ui, self.jinja_env
      )
      context.generated_tests = generated_tests
      self._save_resume_state(context)
      self._save_phase_artifacts(context, WorkflowPhase.GENERATION)
    elif context.generated_tests:
      self.ui.success('Skipping Phase 4: Tests already generated.')

    # Phase 5: Evaluation
    should_run_eval = should_run(WorkflowPhase.EVALUATION, False)
    if should_run_eval and context.generated_tests and not self.config.skip_evaluation:
      await run_test_evaluation(
        context, self.config, self.llm, self.ui, self.jinja_env, context.generated_tests
      )
    elif context.generated_tests and (self.config.skip_evaluation or not should_run_eval):
      self.ui.info('Skipping Phase 5: Evaluation.')

    # Phase 6: Test Execution
    should_run_exec = should_run(WorkflowPhase.EXECUTION, False)
    if should_run_exec and context.generated_tests and not self.config.skip_execution:
      await run_test_execution(
        context, self.config, self.llm, self.ui, self.jinja_env, context.generated_tests
      )
    elif context.generated_tests and (self.config.skip_execution or not should_run_exec):
      self.ui.info('Skipping Phase 6: Test Execution.')

    # Final cleanup of resume file on success
    resume_file = self._get_resume_file_path(web_feature_id)
    if resume_file.exists():
      resume_file.unlink()

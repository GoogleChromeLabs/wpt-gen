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
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from wptgen.config import Config
from wptgen.llm import get_llm_client
from wptgen.phases.context_assembly import run_context_assembly
from wptgen.phases.coverage_audit import provide_coverage_report, run_coverage_audit
from wptgen.phases.evaluation import run_test_evaluation
from wptgen.phases.generation import run_test_generation
from wptgen.phases.requirements_extraction import run_requirements_extraction
from wptgen.ui import UIProvider

__all__ = [
  'WPTGenEngine',
  'run_context_assembly',
  'run_requirements_extraction',
  'run_coverage_audit',
  'provide_coverage_report',
  'run_test_generation',
  'run_test_evaluation',
]


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

  async def _run_async_workflow(self, web_feature_id: str) -> None:
    """Orchestrates the end-to-end WPT generation workflow."""
    # Phase 1: Context Assembly
    context = await run_context_assembly(web_feature_id, self.config, self.ui)
    if not context:
      return

    # Phase 2: Requirements Extraction
    requirements_xml = await run_requirements_extraction(
      context, self.config, self.llm, self.ui, self.jinja_env, self.cache_dir
    )
    if not requirements_xml:
      return

    # Phase 3: Coverage Audit
    audit_response = await run_coverage_audit(
      context, self.config, self.llm, self.ui, self.jinja_env
    )
    if not audit_response:
      return

    # Skip Phase 4 if the user only wants the coverage audit report.
    if self.config.suggestions_only:
      await provide_coverage_report(context, self.config, self.ui)
      return

    # Phase 4: User Selection & Generation
    generated_tests = await run_test_generation(
      context, self.config, self.llm, self.ui, self.jinja_env
    )

    # Phase 5: Evaluation
    if generated_tests:
      await run_test_evaluation(
        context, self.config, self.llm, self.ui, self.jinja_env, generated_tests
      )

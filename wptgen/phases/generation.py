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

from jinja2 import Environment

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import STYLE_GUIDE_MAP, TestType, WorkflowContext
from wptgen.phases.utils import confirm_prompts, generate_safe
from wptgen.ui import UIProvider
from wptgen.utils import (
  MARKDOWN_CODE_BLOCK_RE,
  ensure_trailing_newline,
  extract_xml_tag,
  fix_reftest_link,
  get_next_available_root,
  parse_multi_file_response,
  parse_suggestions,
  strip_trailing_whitespace,
)


async def run_test_generation(
  context: WorkflowContext,
  config: Config,
  llm: LLMClient,
  ui: UIProvider,
  jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
  ui.on_phase_start(4, 'User Selection & Generation')

  assert context.audit_response is not None
  assert context.metadata is not None

  # Check for satisfaction status
  status = extract_xml_tag(context.audit_response, 'status')
  if status and status.strip() == 'SATISFIED':
    ui.success('All identified test requirements have been satisfied.')
    ui.info('No new test suggestions were generated because existing coverage is sufficient.')
    return []

  # Display the audit worksheet in a formatted table
  audit_worksheet = extract_xml_tag(context.audit_response, 'audit_worksheet')
  if audit_worksheet:
    ui.report_audit_worksheet(audit_worksheet)

  suggestions = parse_suggestions(context.audit_response)

  if not suggestions:
    ui.warning('No valid <test_suggestion> blocks found in the LLM response.')
    return []

  ui.success(f'{len(suggestions)} new test suggestions found!\n')

  approved_suggestions_xml = []
  for i, suggestion in enumerate(suggestions):
    title = extract_xml_tag(suggestion, 'title') or f'Suggestion #{i + 1}'
    description = extract_xml_tag(suggestion, 'description') or 'No description provided.'
    test_type = extract_xml_tag(suggestion, 'test_type') or 'Unknown'

    ui.report_test_suggestion(i + 1, title, description, test_type)
    if config.yes_tests or ui.confirm('Generate this test?'):
      approved_suggestions_xml.append(suggestion)

  if not approved_suggestions_xml:
    ui.warning('No tests selected. Exiting.')
    return []

  # Load the general style guide
  resources_path = Path(__file__).parent.parent / 'templates' / 'resources'
  wpt_style_guide = (resources_path / 'wpt_style_guide.md').read_text(encoding='utf-8')

  # Prepare templates
  gen_template = jinja_env.get_template('test_generation.jinja')
  system_template = jinja_env.get_template('test_generation_system.jinja')

  spec_urls = context.metadata.specs if context.metadata and context.metadata.specs else []
  prompts_to_confirm: list[tuple[str, str, str, str]] = []

  # Keep track of filenames used in this run to avoid collisions
  used_names: set[str] = set()
  output_dir = Path(config.output_dir or '.')

  for suggestion_xml in approved_suggestions_xml:
    # Inject specification URLs if available
    if spec_urls:
      spec_url_tags = '\n'.join([f'  <spec_url>{url}</spec_url>' for url in spec_urls])
      suggestion_xml = suggestion_xml.replace(
        '</test_suggestion>', f'{spec_url_tags}\n</test_suggestion>'
      )

    # Extract and normalize test type
    raw_test_type = extract_xml_tag(suggestion_xml, 'test_type') or 'JavaScript Test'
    test_type_enum = TestType.JAVASCRIPT
    for member in TestType:
      if member.value.lower() == raw_test_type.lower():
        test_type_enum = member
        break

    # Generate the root filename: {feature_id}-{num}
    root_name = get_next_available_root(context.feature_id, output_dir, used_names)

    # Load the specific style guide for this test type
    guide_filename = STYLE_GUIDE_MAP.get(test_type_enum, 'javascript_html_style_guide.md')
    test_type_guide = (resources_path / guide_filename).read_text(encoding='utf-8')

    # Render the system instruction with both general and type-specific rules
    system_instruction = system_template.render(
      wpt_style_guide=wpt_style_guide,
      test_type=test_type_enum.value,
      test_type_guide=test_type_guide,
    )

    final_prompt = gen_template.render(
      feature_name=context.metadata.name,
      feature_description=context.metadata.description,
      specs=context.spec_contents,
      test_suggestion_xml_block=suggestion_xml,
    )

    prompts_to_confirm.append((final_prompt, root_name, suggestion_xml, system_instruction))

  # Single confirmation for ALL tests
  await confirm_prompts(
    [(p, f'{r}.*') for p, r, s, si in prompts_to_confirm],
    f'Generate {len(prompts_to_confirm)} Tests',
    llm,
    ui,
    config,
    model=config.get_model_for_phase('generation'),
  )

  ui.report_generation_start(len(prompts_to_confirm))

  tasks = [
    _generate_and_save(
      prompt, root_name, suggestion_xml, llm, ui, config, system_instruction, temperature=0.1
    )
    for prompt, root_name, suggestion_xml, system_instruction in prompts_to_confirm
  ]

  results = []
  total_tasks = len(tasks)
  with ui.progress_indicator(
    f'Generating tests... ({total_tasks} outstanding)', total=total_tasks
  ) as progress:
    for future in asyncio.as_completed(tasks):
      result = await future
      results.append(result)
      remaining = total_tasks - len(results)
      progress.update(
        description='Generating tests...', outstanding=remaining if remaining > 0 else None
      )
      progress.advance()

  # Flatten the list of lists (each task returns a list of files)
  final_results = [r for sublist in results for r in sublist]

  ui.report_generation_summary(final_results)

  return final_results


async def _generate_and_save(
  prompt: str,
  root_name: str,
  suggestion_xml: str,
  llm: LLMClient,
  ui: UIProvider,
  config: Config,
  system_instruction: str | None = None,
  temperature: float | None = None,
) -> list[tuple[Path, str, str]]:
  """Helper to generate specific test file(s) and save to disk."""
  ui.print(f'Starting generation for: {root_name}...')

  content = await generate_safe(
    prompt,
    f'Gen: {root_name}',
    llm,
    ui,
    config,
    system_instruction,
    temperature,
    model=config.get_model_for_phase('generation'),
  )

  if not content:
    ui.report_test_generated(root_name, success=False)
    return []

  results = []
  output_dir = Path(config.output_dir or '.')
  output_dir.mkdir(parents=True, exist_ok=True)

  # Check if we have multiple files (Reftests)
  multi_files = parse_multi_file_response(content, strip_tentative=not config.tentative)
  if multi_files:
    raw_test_type = extract_xml_tag(suggestion_xml, 'test_type') or ''
    is_reftest = raw_test_type.lower() == 'reftest'

    # Pre-calculate filenames to know the reference name
    filenames = []
    for i, (suffix, _) in enumerate(multi_files, 1):
      if i == 2:
        # Assuming FILE_2 is always the ref for reftests
        filenames.append(f'{root_name}-ref{suffix}')
      else:
        # For FILE_1 (test) and any other potential files, just use root + suffix
        filenames.append(f'{root_name}{suffix}')

    for i, (_suffix, fcontent) in enumerate(multi_files, 0):
      fname = filenames[i]
      clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', fcontent).strip()

      # If it's the first file (the test) and it's a reftest, fix the link
      if i == 0 and is_reftest and len(filenames) >= 2:
        clean_content = fix_reftest_link(clean_content, filenames[1])

      output_path = output_dir / fname
      output_path.write_text(
        ensure_trailing_newline(strip_trailing_whitespace(clean_content)), encoding='utf-8'
      )
      ui.report_test_generated(root_name, success=True, path=output_path)
      results.append((output_path, clean_content, suggestion_xml))
  else:
    # Single file fallback - if the LLM failed to use partitioning tags, default to .html
    clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', content).strip()
    output_path = output_dir / f'{root_name}.html'
    output_path.write_text(
      ensure_trailing_newline(strip_trailing_whitespace(clean_content)), encoding='utf-8'
    )
    ui.report_test_generated(root_name, success=True, path=output_path, fallback=True)
    results.append((output_path, clean_content, suggestion_xml))

  return results

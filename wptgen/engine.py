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
import re
from pathlib import Path
from typing import Any

import typer
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

from wptgen.config import Config
from wptgen.context import (
  WebFeatureMetadata,
  extract_feature_metadata,
  fetch_and_extract_text,
  fetch_feature_yaml,
  find_feature_tests,
  gather_local_test_context,
)
from wptgen.llm import get_llm_client

# Regular expressions for parsing and sanitization
SUGGESTION_BLOCK_RE = re.compile(r'<test_suggestion>.*?</test_suggestion>', re.DOTALL)
FILENAME_SANITIZATION_RE = re.compile(r'[^a-z0-9_\-]')
MARKDOWN_CODE_BLOCK_RE = re.compile(r'^```html\s*|^```\s*|\s*```$', re.MULTILINE)


class WPTGenEngine:
  def __init__(self, config: Config):
    self.config = config
    self.console = Console()
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
    context = await self._phase_context_assembly(web_feature_id)
    if not context:
      return

    # Phase 2: Requirements Extraction
    requirements_xml = await self._phase_requirements_extraction(context)
    if not requirements_xml:
      return

    # Phase 3: Coverage Audit
    audit_response = await self._phase_coverage_audit(context, requirements_xml)
    if not audit_response:
      return

    # Skip Phase 4 if the user only wants the coverage audit report.
    if self.config.suggestions_only:
      await self._provide_coverage_report(context, audit_response)
      return

    # Phase 4: User Selection & Generation
    await self._phase_test_generation(context, audit_response)

  async def _provide_coverage_report(self, context: dict[str, Any], audit_response: str) -> None:
    """Prints the coverage audit report and optionally saves it to a file."""
    self.console.print()
    self.console.rule('[bold cyan]Coverage Audit Report')
    self.console.print()
    self.console.print(Markdown(audit_response))
    self.console.print()

    if Confirm.ask('\nSave report to a file?'):
      # Create a sanitized filename from the feature ID
      safe_id = FILENAME_SANITIZATION_RE.sub('_', context['feature_id'].lower())
      filename = f'{safe_id}_coverage_audit.md'

      output_path = Path(self.config.output_dir or '.') / filename
      try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(audit_response, encoding='utf-8')
        self.console.print(f'[green]Saved:[/green] {output_path.absolute()}')
      except Exception as e:
        self.console.print(f'[bold red]Error saving file:[/bold red] {e}')

  async def _phase_requirements_extraction(self, context: dict[str, Any]) -> str | None:
    self.console.print()
    self.console.rule('[bold cyan]Phase 2: Requirements Extraction')
    self.console.print()

    web_feature_id = context['feature_id']
    cache_file = self.cache_dir / f'{web_feature_id}__requirements.xml'
    requirements_xml = None

    if cache_file.exists():
      self.console.print(f'[yellow]Found cached requirements for {web_feature_id}.[/yellow]')
      if Confirm.ask('Use cached requirements?'):
        requirements_xml = cache_file.read_text(encoding='utf-8')
        self.console.print('✔ Using cached requirements.')

    if not requirements_xml:
      extraction_prompt = self.jinja_env.get_template('requirements_extraction.jinja').render(
        feature_name=context['metadata'].name,
        feature_description=context['metadata'].description,
        spec_url=context['metadata'].specs[0],
        spec_contents=context['spec_contents'],
      )
      extraction_system_prompt = self.jinja_env.get_template(
        'requirements_extraction_system.jinja'
      ).render()

      await self._confirm_prompts(
        [(extraction_prompt, 'Requirements Extraction')], 'Requirements Extraction'
      )

      requirements_xml = await self._generate_safe(
        extraction_prompt,
        'Requirements Extraction',
        system_instruction=extraction_system_prompt,
        temperature=0.0,
      )

      if not requirements_xml:
        return None

      # Save to cache
      cache_file.write_text(requirements_xml, encoding='utf-8')

    return requirements_xml

  async def _phase_coverage_audit(
    self, context: dict[str, Any], requirements_xml: str
  ) -> str | None:
    self.console.print()
    self.console.rule('[bold cyan]Phase 3: Coverage Audit')
    self.console.print()

    audit_prompt = self.jinja_env.get_template('coverage_audit.jinja').render(
      requirements_list_xml=requirements_xml,
      wpt_context=context['wpt_context'],
    )
    audit_system_prompt = self.jinja_env.get_template('coverage_audit_system.jinja').render()

    await self._confirm_prompts([(audit_prompt, 'Coverage Audit')], 'Coverage Audit')

    audit_response = await self._generate_safe(
      audit_prompt,
      'Coverage Audit',
      system_instruction=audit_system_prompt,
      temperature=0.0,
    )

    return audit_response

  async def _phase_context_assembly(self, web_feature_id: str) -> dict[str, Any] | None:
    self.console.print()
    self.console.rule('[bold cyan]Phase 1: Context Assembly')
    self.console.print()

    feature_data = fetch_feature_yaml(web_feature_id)
    if not feature_data:
      if self.config.spec_urls and self.config.feature_description:
        self.console.print(
          f'[yellow]Warning:[/yellow] Feature [bold]{web_feature_id}[/bold] not found in the web-features repository.'
        )
        metadata = WebFeatureMetadata(
          name=web_feature_id,
          description=self.config.feature_description,
          specs=self.config.spec_urls,
        )
      else:
        self.console.print(f'[bold red]Error:[/bold red] Feature {web_feature_id} not found.')
        self.console.print(
          'To generate tests for an unregistered feature, please provide both a spec URL using [bold]--spec-urls[/bold] '
          'and a description using [bold]--description[/bold].'
        )
        return None
    else:
      metadata = extract_feature_metadata(feature_data)
      if self.config.spec_urls:
        metadata.specs = self.config.spec_urls
      if self.config.feature_description:
        metadata.description = self.config.feature_description

    if not metadata.specs:
      self.console.print('[bold red]Error:[/bold red] No specification URL found.')
      return None

    metadata_table = Table(show_header=False, box=None, padding=(0, 2))
    metadata_table.add_row('[bold]Web Feature Name:[/bold]', f'[cyan]{metadata.name}[/cyan]')
    metadata_table.add_row('[bold]Description:[/bold]', metadata.description)
    metadata_table.add_row('[bold]Spec URL:[/bold]', f'[blue]{metadata.specs[0]}[/blue]')

    self.console.print(
      Panel(
        metadata_table, title='[bold]Feature Metadata[/bold]', border_style='blue', expand=False
      )
    )

    self.console.print('\nFetching spec content...')
    with self.console.status('[blue]Fetching and extracting text...[/blue]'):
      spec_contents = fetch_and_extract_text(metadata.specs[0])

    if not spec_contents:
      self.console.print('[bold red]Error:[/bold red] Failed to extract spec content.')
      return None

    self.console.print('Scanning local WPT repository for existing tests and dependencies...')
    test_paths = find_feature_tests(self.config.wpt_path, web_feature_id)
    wpt_context = gather_local_test_context(test_paths, self.config.wpt_path)

    self.console.print(
      f'✔ Context gathered: {len(spec_contents)} chars of spec, '
      f'{len(wpt_context.test_contents)} tests, '
      f'{len(wpt_context.dependency_contents)} dependency files.'
    )

    return {
      'feature_id': web_feature_id,
      'metadata': metadata,
      'spec_contents': spec_contents,
      'wpt_context': wpt_context,
    }

  async def _phase_test_generation(
    self, context: dict[str, Any], suggestions_response: str
  ) -> None:
    self.console.print()
    self.console.rule('[bold cyan]Phase 4: User Selection & Generation')
    self.console.print()

    # Check for satisfaction status
    status = self._extract_xml_tag(suggestions_response, 'status')
    if status and status.strip() == 'SATISFIED':
      self.console.print(
        Panel(
          '[bold green]All identified test requirements have been satisfied.[/bold green]\n'
          '[italic]No new test suggestions were generated because existing coverage is sufficient.[/italic]',
          title='[bold]Status[/bold]',
          border_style='green',
          expand=False,
        )
      )
      return

    suggestions = self._parse_suggestions(suggestions_response)

    if not suggestions:
      self.console.print(
        '[yellow]No valid <test_suggestion> blocks found in the LLM response.[/yellow]'
      )
      return

    self.console.print(f'[bold green]{len(suggestions)}[/bold green] new test suggestions found!\n')
    approved_suggestions_xml: list[str] = []

    for idx, xml_block in enumerate(suggestions):
      title = self._extract_xml_tag(xml_block, 'title') or f'Suggestion #{idx + 1}'
      desc = self._extract_xml_tag(xml_block, 'description') or 'No description available'

      self.console.print(
        Panel(
          f'[italic]{desc}[/italic]',
          title=f'[bold blue]Suggestion {idx + 1}:[/bold blue] [white]{title}[/white]',
          title_align='left',
          border_style='blue',
        )
      )
      if Confirm.ask('Generate this test?', default=True):
        approved_suggestions_xml.append(xml_block)
      self.console.print()

    if not approved_suggestions_xml:
      self.console.print('[yellow]No tests selected. Exiting.[/yellow]')
      return

    # Prepare all generation prompts for batch confirmation
    gen_template = self.jinja_env.get_template('test_generation.jinja')
    system_instruction = self.jinja_env.get_template('test_generation_system.jinja').render()
    prompts_to_confirm: list[tuple[str, str]] = []

    for idx, suggestion_xml in enumerate(approved_suggestions_xml):
      final_prompt = gen_template.render(
        feature_name=context['metadata'].name,
        feature_description=context['metadata'].description,
        test_suggestion_xml_block=suggestion_xml,
      )

      raw_title = self._extract_xml_tag(suggestion_xml, 'title') or 'file'
      # Include index to prevent filename collisions
      slug = FILENAME_SANITIZATION_RE.sub('_', raw_title.lower())
      safe_filename = f'{slug}__GENERATED_{idx + 1:02d}_.html'

      prompts_to_confirm.append((final_prompt, safe_filename))

    # Single confirmation for ALL tests
    await self._confirm_prompts(prompts_to_confirm, f'Generate {len(prompts_to_confirm)} Tests')

    self.console.print(f'\nGenerating [bold]{len(prompts_to_confirm)}[/bold] tests in parallel...')

    tasks = [
      self._generate_and_save(prompt, filename, system_instruction, temperature=0.1)
      for prompt, filename in prompts_to_confirm
    ]
    generated_paths = await asyncio.gather(*tasks)

    # Filter out None values and show a final summary for this phase
    final_paths = [p for p in generated_paths if p is not None]

    if final_paths:
      summary_table = Table(
        title='Generated Tests Summary', show_header=True, header_style='bold green'
      )
      summary_table.add_column('File Name', style='cyan')
      summary_table.add_column('Full Path', style='dim')

      for p in final_paths:
        summary_table.add_row(p.name, str(p.absolute()))

      self.console.print()
      self.console.print(summary_table)
      self.console.print(
        f'\n[bold green]✔ {len(final_paths)} tests generated successfully.[/bold green]'
      )
    else:
      self.console.print('\n[bold red]✘ No tests were successfully generated.[/bold red]')

  def _parse_suggestions(self, raw_text: str) -> list[str]:
    return SUGGESTION_BLOCK_RE.findall(raw_text)

  def _extract_xml_tag(self, text: str, tag: str) -> str | None:
    # Use dynamic regex with re.search for per-tag extraction
    match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
    return match.group(1).strip() if match else None

  async def _confirm_prompts(
    self,
    prompt_data: list[tuple[str, str]],
    phase_name: str,
  ) -> None:
    """Calculates tokens for a list of prompts and asks for a single user confirmation."""
    loop = asyncio.get_running_loop()

    total_tokens = 0
    any_limit_exceeded = False

    with self.console.status(f'[yellow]Calculating token usage for {phase_name}...[/yellow]'):
      # We do token counting concurrently for speed
      async def get_info(prompt: str, name: str) -> tuple[int, bool, str]:
        tokens = await loop.run_in_executor(None, self.llm.count_tokens, prompt)
        limit_exceeded = await loop.run_in_executor(
          None, self.llm.prompt_exceeds_input_token_limit, prompt
        )
        return tokens, limit_exceeded, name

      results = await asyncio.gather(*(get_info(p, n) for p, n in prompt_data))

    table = Table(
      title=f'Token Usage Summary ({phase_name})', show_header=True, header_style='bold magenta'
    )
    table.add_column('Task', style='dim')
    table.add_column('Tokens', justify='right', style='cyan')
    table.add_column('Status', justify='center')

    for tokens, limit_exceeded, name in results:
      total_tokens += tokens
      status = '[bold red]EXCEEDED[/bold red]' if limit_exceeded else '[bold green]OK[/bold green]'
      table.add_row(name, str(tokens), status)
      if limit_exceeded:
        any_limit_exceeded = True

    self.console.print(table)
    if len(prompt_data) > 1:
      self.console.print(f'[bold]Total Estimated Tokens:[/bold] [cyan]{total_tokens}[/cyan]')

    if any_limit_exceeded:
      self.console.print(
        '\n[bold red]Warning:[/bold red] One or more prompts exceed the model context limit!'
      )

    if self.config.yes_tokens:
      self.console.print('\n[yellow]Auto-confirming token usage (--yes-tokens).[/yellow]')
      return

    if not Confirm.ask('\nProceed with these LLM requests?'):
      self.console.print('[yellow]Aborting workflow due to user cancellation.[/yellow]')
      raise typer.Abort()

  async def _generate_safe(
    self,
    prompt: str,
    task_name: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
  ) -> str:
    """Helper to run LLM generation in a thread and handle errors gracefully."""
    try:
      loop = asyncio.get_running_loop()
      with self.console.status(f'[blue]Executing {task_name}...[/blue]'):
        response = await loop.run_in_executor(
          None, self.llm.generate_content, prompt, system_instruction, temperature
        )

      self.console.print(f'✔ {task_name} finished.')
      if self.config.show_responses:
        # Determine syntax highlighting based on content (defaulting to xml).
        syntax_lexer = 'xml'
        if 'gen:' in task_name.lower():
          syntax_lexer = 'html'

        syntax = Syntax(response, syntax_lexer, theme='monokai', line_numbers=True, word_wrap=True)
        self.console.print(Panel(syntax, title=f'LLM Response: {task_name}', border_style='cyan'))
      return response
    except Exception as e:
      self.console.print(f'[bold red]✘ {task_name} failed:[/bold red] {e}')
      return ''

  async def _generate_and_save(
    self,
    prompt: str,
    filename: str,
    system_instruction: str | None = None,
    temperature: float | None = None,
  ) -> Path | None:
    """Helper to generate a specific test and save it to disk."""
    self.console.print(f'Starting generation for: [bold]{filename}[/bold]...')
    content = await self._generate_safe(prompt, f'Gen: {filename}', system_instruction, temperature)

    if content:
      # Strip Markdown code blocks if the LLM added them (common behavior)
      clean_content = MARKDOWN_CODE_BLOCK_RE.sub('', content).strip()
      output_path = Path(self.config.output_dir or '.') / filename
      output_path.parent.mkdir(parents=True, exist_ok=True)
      output_path.write_text(clean_content, encoding='utf-8')
      self.console.print(f'[green]✔ Saved:[/green] {output_path.absolute()}')
      return output_path
    return None

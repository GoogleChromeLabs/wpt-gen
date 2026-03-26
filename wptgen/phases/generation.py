"""Module docstring."""
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

from pathlib import Path

from jinja2 import Environment
from rich.rule import Rule

from wptgen.config import Config
from wptgen.llm import LLMClient
from wptgen.models import TestType, WorkflowContext
from wptgen.ui import UIProvider
from wptgen.utils import (
    extract_xml_tag,
    get_next_available_root,
    parse_suggestions,
)


async def run_test_generation(
    context: WorkflowContext,
    config: Config,
    llm: LLMClient,  # pylint: disable=unused-argument
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
        ui.info(
            'No new test suggestions were generated because existing coverage is sufficient.'  # pylint: disable=line-too-long
        )
        return []

    # Display the audit worksheet in a formatted table
    audit_worksheet = extract_xml_tag(context.audit_response, 'audit_worksheet')
    if audit_worksheet:
        ui.report_audit_worksheet(audit_worksheet)

    suggestions = parse_suggestions(context.audit_response)

    if not suggestions:
        ui.warning(
            'No valid <test_suggestion> blocks found in the LLM response.')
        return []

    ui.success(f'{len(suggestions)} new test suggestions found!\n')

    approved_suggestions_xml = []
    for i, suggestion in enumerate(suggestions):
        title = extract_xml_tag(suggestion, 'title') or f'Suggestion #{i + 1}'
        description = (extract_xml_tag(suggestion, 'description') or
                       'No description provided.')
        test_type = extract_xml_tag(suggestion, 'test_type')

        ui.report_test_suggestion(i + 1, title, description, test_type)
        if config.yes_tests or ui.confirm('Generate this test?'):
            approved_suggestions_xml.append(suggestion)

    if not approved_suggestions_xml:
        ui.warning('No tests selected. Exiting.')
        return []

    return await _generate_adk_loop(approved_suggestions_xml, context, config,
                                    ui, jinja_env)


def _format_test_suggestion(
    suggestion_xml: str,
    feature_id: str,
    spec_urls: list[str],
    sanitize: bool = False,
) -> str:
    if sanitize:
        description = (extract_xml_tag(suggestion_xml, 'description') or
                       'No description provided.')
        lines = ['<test_suggestion>']
        lines.append(f'  <description>{description}</description>')
        for url in spec_urls:
            lines.append(f'  <spec_url>{url}</spec_url>')
        lines.append(f'  <web_feature_id>{feature_id}</web_feature_id>')
        lines.append('</test_suggestion>')
        return '\n'.join(lines)
    else:
        # Just inject spec_urls and web_feature_id into the existing XML
        lines = []
        for url in spec_urls:
            lines.append(f'  <spec_url>{url}</spec_url>')
        lines.append(f'  <web_feature_id>{feature_id}</web_feature_id>')
        additions = '\n'.join(lines)
        return suggestion_xml.replace('</test_suggestion>',
                                      f'{additions}\n</test_suggestion>')


async def _generate_adk_loop(
    approved_suggestions_xml: list[str],
    context: WorkflowContext,
    config: Config,
    ui: UIProvider,
    jinja_env: Environment,
) -> list[tuple[Path, str, str]]:
    from wptgen.agents.adk_test_generator import generate_test_with_adk  # pylint: disable=import-outside-toplevel

    ui.report_generation_start(len(approved_suggestions_xml))

    spec_urls = (context.metadata.specs
                 if context.metadata and context.metadata.specs else [])
    output_dir = Path(config.output_dir or '.')
    used_names: set[str] = set()

    tasks = []

    for suggestion_xml in approved_suggestions_xml:
        modified_xml = _format_test_suggestion(
            suggestion_xml,
            context.feature_id,
            spec_urls,
            sanitize=config.brief_suggestions,
        )

        raw_test_type = (extract_xml_tag(modified_xml, 'test_type') or
                         'JavaScript Test')
        test_type_enum = TestType.JAVASCRIPT
        for member in TestType:
            if member.value.lower() == raw_test_type.lower():
                test_type_enum = member
                break

        root_name = get_next_available_root(context.feature_id, output_dir,
                                            used_names)
        used_names.add(root_name)

        tasks.append(
            generate_test_with_adk(
                modified_xml,
                root_name,
                test_type_enum,
                context,
                config,
                jinja_env,
                ui,
            ))

    results = []

    # Unlike standard generation, ADK streams its events to the UI directly.
    # So we await them sequentially here so the streaming output doesn't
    # garble together.
    ui.print('\n[bold cyan]Starting ADK Test Generation...[/bold cyan]')

    for i, task in enumerate(tasks):
        ui.print(  # pylint: disable=line-too-long
            f'\n[bold yellow]--- Generating Test {i + 1} of {len(tasks)} ---[/bold yellow]'  # pylint: disable=line-too-long
        )
        ui.print(
            Rule(
                '[bold cyan]🤖 WPT-Gen Agent[/bold cyan]',
                style='cyan',
                align='left',
            ))
        result = await task
        ui.print()
        ui.print(Rule(style='cyan'))
        results.append(result)

    final_results = [r for sublist in results for r in sublist]

    ui.report_generation_summary(final_results)

    return final_results

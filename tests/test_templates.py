from jinja2 import Environment, FileSystemLoader


def test_coverage_audit_system_template_brief() -> None:
  env = Environment(loader=FileSystemLoader('wptgen/templates'))
  template = env.get_template('coverage_audit_system.jinja')

  # Test with brief_suggestions=True
  rendered_brief = template.render(brief_suggestions=True, spec_urls=['https://example.com/spec'])
  assert '<title>' not in rendered_brief
  assert '<description>' in rendered_brief
  assert '<test_type>' not in rendered_brief
  assert '<pre_conditions>' not in rendered_brief
  assert '<steps>' not in rendered_brief
  assert '<expected_result>' not in rendered_brief
  assert '<spec_url>https://example.com/spec</spec_url>' not in rendered_brief

  # Test with brief_suggestions=False
  rendered_full = template.render(brief_suggestions=False)
  assert '<title>' in rendered_full
  assert '<description>' in rendered_full
  assert '<test_type>' in rendered_full
  assert '<pre_conditions>' in rendered_full
  assert '<steps>' in rendered_full
  assert '<expected_result>' in rendered_full


def test_chromestatus_coverage_audit_system_template_brief() -> None:
  env = Environment(loader=FileSystemLoader('wptgen/templates/chromestatus_templates'))
  template = env.get_template('coverage_audit_system.jinja')

  # Test with brief_suggestions=True
  rendered_brief = template.render(brief_suggestions=True, spec_urls=['https://example.com/spec'])
  assert '<title>' not in rendered_brief
  assert '<description>' in rendered_brief
  assert '<test_type>' not in rendered_brief
  assert '<pre_conditions>' not in rendered_brief
  assert '<steps>' not in rendered_brief
  assert '<expected_result>' not in rendered_brief
  assert '<spec_url>https://example.com/spec</spec_url>' not in rendered_brief

  # Test with brief_suggestions=False
  rendered_full = template.render(brief_suggestions=False)
  assert '<title>' in rendered_full
  assert '<description>' in rendered_full
  assert '<test_type>' in rendered_full
  assert '<pre_conditions>' in rendered_full
  assert '<steps>' in rendered_full
  assert '<expected_result>' in rendered_full


def test_agentic_test_generation_template_interactive() -> None:
  env = Environment(loader=FileSystemLoader('wptgen/templates'))
  template = env.get_template('agentic_test_generation.jinja')

  # Test with is_interactive=True
  rendered_interactive = template.render(
    is_interactive=True, test_suggestion_xml_block='<test></test>'
  )
  assert 'safely close the Gemini CLI now' in rendered_interactive

  # Test with is_interactive=False
  rendered_non_interactive = template.render(
    is_interactive=False, test_suggestion_xml_block='<test></test>'
  )
  assert 'safely close the Gemini CLI now' not in rendered_non_interactive

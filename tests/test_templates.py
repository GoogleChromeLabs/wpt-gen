from jinja2 import Environment, FileSystemLoader


def test_coverage_audit_system_template_brief() -> None:
  env = Environment(loader=FileSystemLoader('wptgen/templates'))
  template = env.get_template('coverage_audit_system.jinja')

  # Test with brief_suggestions=True
  rendered_brief = template.render(brief_suggestions=True)
  assert '<title>' in rendered_brief
  assert '<description>' in rendered_brief
  assert '<test_type>' not in rendered_brief
  assert '<pre_conditions>' not in rendered_brief
  assert '<steps>' not in rendered_brief
  assert '<expected_result>' not in rendered_brief

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
  rendered_brief = template.render(brief_suggestions=True)
  assert '<title>' in rendered_brief
  assert '<description>' in rendered_brief
  assert '<test_type>' not in rendered_brief
  assert '<pre_conditions>' not in rendered_brief
  assert '<steps>' not in rendered_brief
  assert '<expected_result>' not in rendered_brief

  # Test with brief_suggestions=False
  rendered_full = template.render(brief_suggestions=False)
  assert '<title>' in rendered_full
  assert '<description>' in rendered_full
  assert '<test_type>' in rendered_full
  assert '<pre_conditions>' in rendered_full
  assert '<steps>' in rendered_full
  assert '<expected_result>' in rendered_full

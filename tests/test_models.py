from wptgen.models import WorkflowContext


def test_workflow_context_from_dict_legacy_spec_contents() -> None:
  data = {
    'feature_id': 'mock_feature',
    'metadata': {'name': 'Mock Feature', 'description': 'Mock', 'specs': ['https://mock.spec']},
    'spec_contents': 'Legacy spec content string',
    'wpt_context': None,
    'requirements_xml': None,
    'audit_response': None,
    'suggestions': [],
    'approved_suggestions_xml': [],
    'mdn_contents': None,
    'generated_tests': None,
  }
  context = WorkflowContext.from_dict(data)
  assert context.spec_contents == {'https://mock.spec': 'Legacy spec content string'}


def test_workflow_context_from_dict_legacy_spec_contents_no_metadata() -> None:
  data = {
    'feature_id': 'mock_feature',
    'metadata': None,
    'spec_contents': 'Legacy spec content string',
    'wpt_context': None,
    'requirements_xml': None,
    'audit_response': None,
    'suggestions': [],
    'approved_suggestions_xml': [],
    'mdn_contents': None,
    'generated_tests': None,
  }
  context = WorkflowContext.from_dict(data)
  assert context.spec_contents == {'unknown': 'Legacy spec content string'}

from pathlib import Path
from typing import Any

import yaml


def is_path_covered(rel_path: Path, patterns: list[str]) -> bool:
  """
  Checks if a relative file path is covered by a list of glob patterns.
  """
  is_covered = False
  for pattern in patterns:
    is_negative = pattern.startswith('!')
    clean_pattern = pattern[1:] if is_negative else pattern

    is_match = rel_path.match(clean_pattern)
    if not is_match and clean_pattern.startswith('**/'):
      is_match = rel_path.match(clean_pattern[3:])

    if is_match:
      is_covered = not is_negative

  return is_covered


def update_web_features_yml(
  output_dir: Path, web_feature_id: str, generated_paths: list[Path]
) -> None:
  """
  Updates or creates a WEB_FEATURES.yml file at the root of output_dir, linking
  generated tests to the given web_feature_id.
  """
  yml_path = output_dir / 'WEB_FEATURES.yml'
  yaml_data: dict[str, Any] = {}

  if yml_path.exists():
    with open(yml_path, encoding='utf-8') as f:
      yaml_data = yaml.safe_load(f) or {}

  if 'features' not in yaml_data:
    yaml_data['features'] = {}

  if not isinstance(yaml_data['features'], dict):
    # Handle unexpected type, maybe it's a list. But standard is dict.
    pass

  features_dict = yaml_data['features']

  if web_feature_id not in features_dict:
    features_dict[web_feature_id] = {}

  feature_block = features_dict[web_feature_id]
  if 'files' not in feature_block:
    feature_block['files'] = []

  existing_patterns = feature_block['files']

  new_patterns = []
  for test_path in generated_paths:
    rel_path = test_path.relative_to(output_dir)

    if not is_path_covered(rel_path, existing_patterns):
      new_patterns.append(rel_path.as_posix())

  if new_patterns:
    for p in new_patterns:
      if p not in existing_patterns:
        existing_patterns.append(p)

    with open(yml_path, 'w', encoding='utf-8') as f:
      yaml.dump(yaml_data, f, sort_keys=False, default_flow_style=False)

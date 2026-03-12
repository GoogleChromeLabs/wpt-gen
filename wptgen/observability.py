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

import json
import time
from pathlib import Path
from typing import Any


class Tracer:
  """Captures LLM interactions for observability and evaluation."""

  def __init__(self, save_traces: bool = False, trace_dir: str = '.wptgen/traces'):
    self.save_traces = save_traces
    self.trace_dir = Path(trace_dir)
    self.traces: list[dict[str, Any]] = []
    self.trace_file: Path | None = None

    if self.save_traces:
      self.trace_dir.mkdir(parents=True, exist_ok=True)
      self.trace_file = self.trace_dir / f'trace_{int(time.time())}.jsonl'

  def record(
    self,
    prompt: str,
    system_instruction: str | None,
    model: str,
    temperature: float | None,
    raw_response: str,
    token_usage: int | None,
    latency: float,
  ) -> None:
    """Records a single LLM interaction trace."""
    trace_entry = {
      'prompt': prompt,
      'system_instruction': system_instruction,
      'model': model,
      'temperature': temperature,
      'raw_response': raw_response,
      'token_usage': token_usage,
      'latency': latency,
      'timestamp': time.time(),
    }
    self.traces.append(trace_entry)

    if self.save_traces and self.trace_file:
      with open(self.trace_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(trace_entry) + '\n')

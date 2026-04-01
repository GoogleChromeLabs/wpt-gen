# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from pathlib import Path

from wptgen.observability import Tracer


def test_tracer_no_save() -> None:
    tracer = Tracer(save_traces=False)
    assert tracer.save_traces is False
    assert tracer.trace_file is None

    tracer.record(
        prompt="hello",
        system_instruction="sys",
        model="model",
        temperature=0.0,
        raw_response="resp",
        token_usage=10,
        latency=0.5,
    )
    assert len(tracer.traces) == 1
    assert tracer.traces[0]["prompt"] == "hello"


def test_tracer_save(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    tracer = Tracer(save_traces=True, trace_dir=str(trace_dir))
    assert tracer.save_traces is True
    assert tracer.trace_file is not None
    assert tracer.trace_file.parent == trace_dir

    tracer.record(
        prompt="hello",
        system_instruction="sys",
        model="model",
        temperature=0.0,
        raw_response="resp",
        token_usage=10,
        latency=0.5,
    )

    assert len(tracer.traces) == 1

    with open(tracer.trace_file) as f:
        data = json.loads(f.read())
        assert data["prompt"] == "hello"
        assert data["latency"] == 0.5

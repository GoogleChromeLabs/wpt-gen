import json
from pathlib import Path

from wptgen.observability import Tracer


def test_tracer_no_save() -> None:
  tracer = Tracer(save_traces=False)
  assert tracer.save_traces is False
  assert tracer.trace_file is None

  tracer.record(
    prompt='hello',
    system_instruction='sys',
    model='model',
    temperature=0.0,
    raw_response='resp',
    token_usage=10,
    latency=0.5,
  )
  assert len(tracer.traces) == 1
  assert tracer.traces[0]['prompt'] == 'hello'


def test_tracer_save(tmp_path: Path) -> None:
  trace_dir = tmp_path / 'traces'
  tracer = Tracer(save_traces=True, trace_dir=str(trace_dir))
  assert tracer.save_traces is True
  assert tracer.trace_file is not None
  assert tracer.trace_file.parent == trace_dir

  tracer.record(
    prompt='hello',
    system_instruction='sys',
    model='model',
    temperature=0.0,
    raw_response='resp',
    token_usage=10,
    latency=0.5,
  )

  assert len(tracer.traces) == 1

  with open(tracer.trace_file) as f:
    data = json.loads(f.read())
    assert data['prompt'] == 'hello'
    assert data['latency'] == 0.5

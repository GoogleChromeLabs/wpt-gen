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
"""Print the line-vs-rule_id flakiness decomposition for a bench run.

    python scripts/benchmark/analyze_consistency.py bench-runs/<run-dir>

Read-only diagnostic: it explains *which* lines/rules are flaky by reading an
existing report.json. It never fails a build — the CI gate is
``run_benchmark.py --min-stability`` (see benchmarks/README.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _keys(line: dict[str, Any]) -> str:
    return ", ".join(line.get("keys", []))


def _format_stability(val: Any) -> str:
    return f"{float(val):.2f}" if val is not None else "n/a"


def _run(out: Path) -> int:
    report_file = out / "report.json"
    if not report_file.is_file():
        sys.stderr.write(f"error: report file not found at {report_file}\n")
        return 1
    report = json.loads(report_file.read_text(encoding="utf-8"))

    found_any = False
    for entry in report.get("entries", []):
        detection = entry.get("detection_flaky_lines", [])
        churn = entry.get("label_churn_lines", [])
        if not detection and not churn:
            continue
        found_any = True
        d = entry.get("consistency_decomposition", {})
        stab = _format_stability(entry.get("stability"))
        print(f"\n{entry['entry_id']} ({entry.get('role', 'unknown')})")
        print(
            f"  stability {stab} | detection-flaky "
            f"{d.get('line_flaky', 0)} | label-churn {d.get('label_churn', 0)}"
        )
        for line in detection:
            print(
                f"    {'detection':<10} {line.get('line', 'file')}: "
                f"{line.get('firings', 0)}/{line.get('repeats', 0)} "
                f"({_keys(line)})"
            )
        for line in churn:
            print(
                f"    {'churn':<10} {line.get('line', 'file')}: {_keys(line)}"
            )

    if not found_any:
        print("No flaky findings (all detected lines stable across repeats).")

    agg = report.get("aggregate", {})
    d = agg.get("consistency_decomposition", {})
    total_stab = _format_stability(agg.get("corpus_stability"))
    print(
        f"\nTOTALS  corpus-stability {total_stab} | detection-flaky "
        f"{d.get('line_flaky', 0)} | label-churn {d.get('label_churn', 0)}"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write("usage: analyze_consistency.py <run-dir>\n")
        raise SystemExit(2)
    raise SystemExit(_run(Path(sys.argv[1])))

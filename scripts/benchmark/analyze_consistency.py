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
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _keys(line: dict[str, Any]) -> str:
    return ", ".join(line.get("keys", []))


def _run(out: Path) -> int:
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    for entry in report["entries"]:
        detection = entry.get("detection_flaky_lines", [])
        churn = entry.get("label_churn_lines", [])
        if not detection and not churn:
            continue
        d = entry.get("consistency_decomposition", {})
        print(f"\n{entry['entry_id']} ({entry['role']})")
        print(
            f"  stability {entry.get('stability')}  |  detection-flaky "
            f"{d.get('line_flaky', 0)}  |  label-churn {d.get('label_churn', 0)}"
        )
        for line in detection:
            print(
                f"    detection  {line['line']}: {line['firings']}/"
                f"{line['repeats']} ({_keys(line)})"
            )
        for line in churn:
            print(f"    churn      {line['line']}: {_keys(line)}")

    agg = report["aggregate"]
    d = agg.get("consistency_decomposition", {})
    print(
        f"\nTOTALS  corpus-stability {agg.get('corpus_stability')}  |  "
        f"detection-flaky {d.get('line_flaky', 0)}  |  label-churn "
        f"{d.get('label_churn', 0)}"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write("usage: analyze_consistency.py <run-dir>\n")
        raise SystemExit(2)
    raise SystemExit(_run(Path(sys.argv[1])))

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
"""Tests for adk_conformance_evaluator.py."""

import pytest

pytest.importorskip("google.adk")

from wptgen.agents.adk_conformance_evaluator import (  # noqa: E402
    EVALUATOR_TOOL_ALLOWLIST as CONFORMANCE_ALLOWLIST,
)
from wptgen.agents.adk_evaluator import (  # noqa: E402
    EVALUATOR_TOOL_ALLOWLIST as DOC_INPUTS_ALLOWLIST,
)


def test_conformance_evaluator_shares_doc_inputs_allowlist() -> None:
    """The two evaluator variants intentionally share one read-only allowlist.

    Both evaluators must remain read-only; sharing the allowlist means a
    change in one place is caught by both pin tests. If the conformance
    agent ever needs a different (still read-only) toolset, fork the
    allowlist deliberately and add a separate pin.
    """
    assert CONFORMANCE_ALLOWLIST is DOC_INPUTS_ALLOWLIST

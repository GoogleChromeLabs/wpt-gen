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
"""Tests for the deterministic linter extension (wptgen.lint_ext).

Each check is named with its rules.yaml id; these tests assert the gap-set
checks fire on violations and stay quiet on clean input.
"""

from wptgen.lint_ext import check_file


def _rule_ids(path: str, content: bytes) -> list[str]:
    return [err[0] for err in check_file(path, content)]


def test_clean_reftest_has_no_gap_findings() -> None:
    """A well-formed reftest triggers none of the gap checks."""
    content = (
        b"<!DOCTYPE html>\n<html>\n<head>\n"
        b'<link rel="match" href="ref.html">\n'
        b'<link rel="help" href="http://example.org/#x">\n'
        b"</head>\n<body>\n<p>Test passes if green.</p>\n</body>\n</html>\n"
    )
    assert _rule_ids("css/foo/align_center.html", content) == []


def test_name_004_flags_manual_suffix_not_last() -> None:
    assert "FILENAMES-001" in _rule_ids(
        "bar-manual-other.html", b"<!doctype html>"
    )


def test_name_004_quiet_when_manual_is_last() -> None:
    assert "FILENAMES-001" not in _rule_ids(
        "bar-manual.html", b"<!doctype html>"
    )


def test_rev_003_flags_commented_out_code() -> None:
    ids = _rule_ids("t.any.js", b"// doThing();\nassert_true(1);")
    assert "CHECKLIST-008" in ids


def test_rev_003_quiet_on_prose_comment() -> None:
    ids = _rule_ids("t.any.js", b"// this is a prose comment\nassert_true(1);")
    assert "CHECKLIST-008" not in ids


def test_api_005_flags_manual_setup_without_explicit_timeout() -> None:
    assert "MANUAL-004" in _rule_ids("m-manual.html", b"setup();\n")


def test_api_005_quiet_with_explicit_timeout() -> None:
    ids = _rule_ids("m-manual.html", b"setup({explicit_timeout: true});\n")
    assert "MANUAL-004" not in ids


def test_api_005_quiet_on_non_manual_test() -> None:
    """The gate: an ordinary (non-manual) test's setup() is not flagged."""
    assert "MANUAL-004" not in _rule_ids("m.html", b"setup();\n")
    assert "MANUAL-004" not in _rule_ids("m.any.js", b"setup();\n")


def test_name_011_flags_crash_suffix_not_last() -> None:
    assert "CRASHTEST-001" in _rule_ids(
        "bar-crash-001.html", b"<!doctype html>"
    )


def test_name_011_quiet_when_crash_is_last() -> None:
    assert "CRASHTEST-001" not in _rule_ids(
        "bar-crash.html", b"<!doctype html>"
    )


def test_name_011_quiet_under_crashtests_dir() -> None:
    ids = _rule_ids("css/crashtests/bar-crash-001.html", b"<!doctype html>")
    assert "CRASHTEST-001" not in ids


def test_name_012_flags_print_suffix_not_last() -> None:
    assert "PRINT-REFTESTS-001" in _rule_ids(
        "bar-print-001.html", b"<!doctype html>"
    )


def test_name_012_quiet_under_print_dir() -> None:
    assert "PRINT-REFTESTS-001" not in _rule_ids(
        "css/print/bar-print-1.html", b"x"
    )


def test_name_006_flags_token_not_before_js() -> None:
    assert "FILENAMES-005" in _rule_ids("foo.any.bar.js", b"x")


def test_name_006_quiet_when_token_before_js() -> None:
    assert "FILENAMES-005" not in _rule_ids("foo.any.js", b"x")


def test_meta_008_flags_deprecated_css_flag() -> None:
    content = b'<meta name=flags content="animated">'
    assert "CSS-METADATA-003" in _rule_ids("t.html", content)


def test_meta_008_quiet_on_non_deprecated_flags() -> None:
    content = b'<meta name=flags content="dom">'
    assert "CSS-METADATA-003" not in _rule_ids("t.html", content)


def test_fmt_004_flags_worker_missing_importscripts() -> None:
    ids = _rule_ids("t.worker.js", b"done();")
    assert "TESTHARNESS-003" in ids


def test_fmt_004_flags_worker_missing_done() -> None:
    content = b'importScripts("/resources/testharness.js");'
    assert "TESTHARNESS-003" in _rule_ids("t.worker.js", content)


def test_fmt_004_quiet_on_complete_worker() -> None:
    content = (
        b'importScripts("/resources/testharness.js");\n'
        b"test(() => {});\ndone();\n"
    )
    assert "TESTHARNESS-003" not in _rule_ids("t.worker.js", content)


def test_fmt_004_only_applies_to_worker_js() -> None:
    """A non-worker file is never flagged for TESTHARNESS-003 even if it lacks both."""
    assert "TESTHARNESS-003" not in _rule_ids("t.any.js", b"assert_true(1);")


def test_check_file_reports_line_numbers_for_line_checks() -> None:
    """Line-pattern checks report a 1-indexed line number."""
    content = b"<!doctype html>\n// foo();\n"
    errors = check_file("t.any.js", content)
    rev = [e for e in errors if e[0] == "CHECKLIST-008"]
    assert len(rev) == 1
    assert rev[0][3] == 2

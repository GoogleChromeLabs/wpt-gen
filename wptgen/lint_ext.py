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
"""Deterministic linter extension for wpt-gen.

This module implements the subset of `layer: deterministic` rules from
`wptgen/skills/wpt-evaluator/references/rules.yaml` that upstream
`wpt lint` does NOT already cover. Each check is named with its
`rules.yaml` id (e.g. `GENERAL-004`) so the linter and the LLM evaluator
share one identifier space.

"""

from __future__ import annotations

import abc
import os
import re
from collections.abc import Callable

# An `Error` is `(rule_id, description, path, line_no)`; `line_no` is None
# for whole-file / filename findings.
Error = tuple[str, str, str, int | None]


# ---------------------------------------------------------------------------
# Filename predicates
#
# Several checks apply only to a subset of tests identifiable by filename
# (e.g. manual tests, `.worker.js` tests). These predicates let both
# line-pattern and path checks gate on the filename without duplicating the
# parsing logic.
# ---------------------------------------------------------------------------


def is_manual_test(path: str) -> bool:
    """A test whose filename marks it manual (`-manual` before the ext)."""
    stem, _ = os.path.splitext(os.path.basename(path))
    return stem.endswith("-manual")


def is_worker_js(path: str) -> bool:
    """A `.worker.js` test file."""
    return os.path.basename(path).endswith(".worker.js")


# File-extension groups, mirrored from upstream lint so `file_extensions`
# on a check reads the same way it does there.
EXTENSIONS: dict[str, list[str]] = {
    "html": [".html", ".htm"],
    "xhtml": [".xht", ".xhtml"],
    "svg": [".svg"],
    "js": [".js", ".mjs"],
    "python": [".py"],
}
EXTENSIONS["markup"] = (
    EXTENSIONS["html"] + EXTENSIONS["xhtml"] + EXTENSIONS["svg"]
)
EXTENSIONS["js_all"] = EXTENSIONS["markup"] + EXTENSIONS["js"]


class Regexp(abc.ABC):
    """A line-pattern check. Subclasses set `pattern`, `name`, and
    `description`; `file_extensions` optionally restricts which files it
    applies to (None = all files), and `path_predicate` optionally gates
    it on a filename property (e.g. only manual tests)."""

    pattern: bytes
    name: str
    description: str
    file_extensions: list[str] | None = None
    path_predicate: Callable[[str], bool] | None = None

    def __init__(self) -> None:
        self._re: re.Pattern[bytes] = re.compile(self.pattern)

    def applies(self, path: str) -> bool:
        if (
            self.file_extensions is not None
            and os.path.splitext(path)[1] not in self.file_extensions
        ):
            return False
        if self.path_predicate is not None and not self.path_predicate(path):
            return False
        return True

    def search(self, line: bytes) -> re.Match[bytes] | None:
        return self._re.search(line)


# ---------------------------------------------------------------------------
# Line-pattern gap rules (self-contained Regexp subclasses)
# ---------------------------------------------------------------------------


class CommentedOutCode(Regexp):
    """CHECKLIST-008: the test must not contain commented-out code."""

    # A `//`-comment whose body looks like code: ends in `;`, `{`, or `}`,
    # or contains a call `foo(`. Deliberately conservative to limit false
    # positives on prose comments.
    pattern = rb"//\s*[A-Za-z_$][\w$.]*\s*\([^)]*\)\s*;?\s*$"
    name = "CHECKLIST-008"
    file_extensions = EXTENSIONS["js_all"]
    description = "Test-file line appears to contain commented-out code"


class ManualExplicitTimeout(Regexp):
    """MANUAL-004: manual testharness tests must pass {explicit_timeout: true}.

    Flags a `setup()` call that lacks `explicit_timeout`, but only in
    manual tests — `path_predicate` gates the check on the `-manual`
    filename so ordinary tests' `setup()` calls are not flagged.
    """

    pattern = rb"setup\((?![^)]*explicit_timeout)[^)]*\)"
    name = "MANUAL-004"
    file_extensions = EXTENSIONS["markup"]
    path_predicate = staticmethod(is_manual_test)
    description = (
        "Manual testharness test calls setup() without "
        "{explicit_timeout: true}"
    )


class DeprecatedCssFlag(Regexp):
    """CSS-METADATA-003: deprecated `<meta name=flags>` tokens for CSS tests.

    The tokens `animated`, `font`, `history`, `interact`, `speech`, and
    `userstyle` are deprecated for new CSS tests; such tests should use the
    `-manual` filename flag instead. Matches a `<meta name=flags ...>`
    element whose `content` includes one of those tokens.
    """

    pattern = (
        rb'<meta\s+name=["\']?flags["\']?\s+content=["\'][^"\']*'
        rb"\b(animated|font|history|interact|speech|userstyle)\b"
    )
    name = "CSS-METADATA-003"
    file_extensions = EXTENSIONS["markup"]
    description = (
        "`<meta name=flags>` uses a token deprecated for new CSS tests "
        "(animated/font/history/interact/speech/userstyle)"
    )


# ---------------------------------------------------------------------------
# Filename gap rules (path logic, no file contents needed)
# ---------------------------------------------------------------------------

# NOTE: GENERAL-004 ("tests requiring HTTPS must carry `.https.`") is NOT
# implemented here. Whether a test *requires* a secure context is a
# semantic property — no fixed regex over API names can decide it
# completely, and scanning full file content for that proxy is both
# noisy and the slowest possible check. GENERAL-004 is `layer: semantic` in
# rules.yaml and left to the LLM judge.


def check_manual_suffix_position(path: str) -> Error | None:
    """FILENAMES-001 / MANUAL-002: `-manual` must be the last `-` element.

    `foo-manual.html` is a manual test; `foo-manual-other.html` is not,
    and if a file carries `-manual` anywhere but immediately before the
    extension it is a likely mistake.
    """
    base = os.path.basename(path)
    stem, _ = os.path.splitext(base)
    if "-manual" in stem and not stem.endswith("-manual"):
        return (
            "FILENAMES-001",
            "`-manual` appears in the filename but is not the last `-` "
            "element before the extension",
            path,
            None,
        )
    return None


def check_crash_suffix_position(path: str) -> Error | None:
    """CRASHTEST-001: `-crash` must be immediately before the extension.

    A file with `-crash` mid-stem (e.g. `bar-crash-001.html`) is NOT a
    crashtest and the misplaced flag is a likely mistake — unless the file
    lives under a `crashtests/` directory, where the flag is not required.
    """
    parts = path.replace("\\", "/").split("/")
    if "crashtests" in parts[:-1]:
        return None
    stem, _ = os.path.splitext(parts[-1])
    if "-crash" in stem and not stem.endswith("-crash"):
        return (
            "CRASHTEST-001",
            "`-crash` appears in the filename but is not immediately before "
            "the extension; such a file is not treated as a crashtest",
            path,
            None,
        )
    return None


def check_print_suffix_position(path: str) -> Error | None:
    """PRINT-REFTESTS-001: `-print` must be immediately before the extension.

    A file with `-print` mid-stem (e.g. `bar-print-001.html`) is NOT a
    print reftest — unless it lives under a `print/` directory, where the
    flag is not required.
    """
    parts = path.replace("\\", "/").split("/")
    if "print" in parts[:-1]:
        return None
    stem, _ = os.path.splitext(parts[-1])
    if "-print" in stem and not stem.endswith("-print"):
        return (
            "PRINT-REFTESTS-001",
            "`-print` appears in the filename but is not immediately before "
            "the extension; such a file is not treated as a print reftest",
            path,
            None,
        )
    return None


def check_multiglobal_extension(path: str) -> Error | None:
    """FILENAMES-005: `.window`, `.worker`, `.any` must be immediately followed
    by the final `.js` extension.

    `foo.any.js` is correct; `foo.any.bar.js` (the token not immediately
    before `.js`) is the mistake this catches.
    """
    base = os.path.basename(path)
    if not base.endswith(".js"):
        return None
    for token in (".window", ".worker", ".any"):
        if token in base and not base.endswith(f"{token}.js"):
            return (
                "FILENAMES-005",
                f"`{token}` should be immediately followed by the final "
                f"`.js` extension",
                path,
                None,
            )
    return None


# ---------------------------------------------------------------------------
# Content gap rules (need full file bytes; gated on filename to stay cheap)
# ---------------------------------------------------------------------------

_IMPORT_TESTHARNESS_RE = re.compile(
    rb"importScripts\(\s*[\"'][^\"']*/resources/testharness\.js[\"']"
)
_DONE_CALL_RE = re.compile(rb"\bdone\s*\(\s*\)")


def check_worker_boilerplate(path: str, content: bytes) -> Error | None:
    """TESTHARNESS-003: a `.worker.js` file must importScripts testharness.js and
    call done().

    Only runs for `.worker.js` files (gated by the driver), so the content
    read is not incurred for other files.
    """
    if not _IMPORT_TESTHARNESS_RE.search(content):
        return (
            "TESTHARNESS-003",
            "`.worker.js` file does not importScripts "
            "`/resources/testharness.js`",
            path,
            None,
        )
    if not _DONE_CALL_RE.search(content):
        return (
            "TESTHARNESS-003",
            "`.worker.js` file does not call `done()`",
            path,
            None,
        )
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

# Line-pattern checks (Regexp instances) run against every applicable line.
_LINE_CHECKS: list[Regexp] = [
    CommentedOutCode(),
    ManualExplicitTimeout(),
    DeprecatedCssFlag(),
]

# Path checks run once per file against the path only (no content needed).
_PATH_CHECKS: list[Callable[[str], Error | None]] = [
    check_manual_suffix_position,
    check_crash_suffix_position,
    check_print_suffix_position,
    check_multiglobal_extension,
]

# Content checks need full file bytes. Each is paired with a filename
# predicate so content is only read when at least one applies.
_CONTENT_CHECKS: list[
    tuple[Callable[[str], bool], Callable[[str, bytes], Error | None]]
] = [
    (is_worker_js, check_worker_boilerplate),
]


def check_file(path: str, content: bytes | None = None) -> list[Error]:
    """Run the gap-set deterministic checks against a single file.

    Args:
        path: Path to the file (used for filename checks and reporting).
        content: File bytes. If omitted, the file is read from disk.

    Returns:
        A list of `Error` tuples `(rule_id, description, path, line_no)`.
    """
    errors: list[Error] = []

    for path_check in _PATH_CHECKS:
        err = path_check(path)
        if err is not None:
            errors.append(err)

    line_checks = [chk for chk in _LINE_CHECKS if chk.applies(path)]
    content_checks = [check for gate, check in _CONTENT_CHECKS if gate(path)]

    # Only read the file if some content-consuming check applies.
    if not line_checks and not content_checks:
        return errors

    if content is None:
        with open(path, "rb") as handle:
            content = handle.read()

    for content_check in content_checks:
        err = content_check(path, content)
        if err is not None:
            errors.append(err)

    for line_no, line in enumerate(content.splitlines(), start=1):
        for chk in line_checks:
            if chk.search(line):
                errors.append((chk.name, chk.description, path, line_no))

    return errors

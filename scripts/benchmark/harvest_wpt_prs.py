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
"""Golden-PR candidate harvester for the WPT evaluator benchmark.

Snapshots recently merged wpt PRs that received substantive human review into
``benchmarks/golden/candidates/<pr>.json``. A maintainer then annotates
the candidates (see ``benchmarks/golden/ANNOTATION.md``); only the annotated
result becomes the answer key. Finding candidates is automated here; judging
them is not.

Each record groups a PR's CHANGES_REQUESTED comments on test files into one
block per ``commit_id`` — the revision each comment's ``line`` is relative to.
A block carries the commented files at that commit, so it is a self-contained
scoring unit: fetch these bytes, run the evaluator, check the flagged lines.

    python scripts/benchmark/harvest_wpt_prs.py \\
      [--out benchmarks/golden/candidates] \\
      [--watermark benchmarks/golden/watermark.json] \\
      [--max-prs 200] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--dry-run]

Talks to GitHub through the ``gh`` CLI.

Vendor-export / sync PRs (which dominate the merge feed and carry no in-repo
review) are excluded server-side via the Search API ``-label:`` qualifier, so
that bulk is never fetched. The client-side label/author filters remain as a
safety net for any that slip through.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = "web-platform-tests/wpt"

_BOT_LOGIN_MARKERS = (
    "[bot]",
    "wpt-pr-bot",
    "-export-bot",
    "wptsync",
    "wpt-sync",
)

_EXPORT_LABEL_MARKERS = (
    "-export",
    "gecko-sync",
)

_EXPORT_LABELS = (
    "chromium-export",
    "webkit-export",
    "servo-export",
    "mozilla:gecko-sync",
)

# Non-test paths. `.py` stays: wpt has Python tests (e.g. core-aam).
_NON_TEST_TOPLEVEL = (
    "tools/",
    "docs/",
    "resources/",
    "infrastructure/",
    ".github/",
)
_NON_TEST_SUFFIXES = (
    ".ignore", ".headers", ".ini", ".md", ".txt", ".json",
)
_NON_TEST_NAMES = ("MANIFEST", "META.yml", "WEB_FEATURES.yml", "OWNERS")
# Matched at any depth, unlike _NON_TEST_TOPLEVEL.
_SUPPORT_SEGMENTS = frozenset(
    {"support", "resources", "reference", "references"}
)


# --- Pure filter logic (unit-tested without network) ------------------------


def is_bot_author(login: str) -> bool:
    login = login.lower()
    return any(marker in login for marker in _BOT_LOGIN_MARKERS)


def is_export_pr(labels: list[str]) -> bool:
    return any(
        marker in label.lower()
        for label in labels
        for marker in _EXPORT_LABEL_MARKERS
    )


def is_test_path(path: str) -> bool:
    """True if a single changed path is plausibly a reviewable test file."""
    segments = path.split("/")
    name = segments[-1]
    return (
        not path.startswith(_NON_TEST_TOPLEVEL)
        and not path.endswith(_NON_TEST_SUFFIXES)
        and name not in _NON_TEST_NAMES
        and "-ref." not in name
        and not any(seg in _SUPPORT_SEGMENTS for seg in segments[:-1])
    )


def touches_test_file(paths: list[str]) -> bool:
    """True if at least one changed path is a reviewable test file."""
    return any(is_test_path(p) for p in paths)


def qualifies(pr: PullRequest) -> bool:
    """A candidate: merged, human-authored, non-export, and with at least one
    CHANGES_REQUESTED comment on a test file."""
    return (
        pr.merged_at is not None
        and not is_bot_author(pr.author)
        and not is_export_pr(pr.labels)
        and touches_test_file(pr.changed_paths)
        and len(changes_requested_comments(pr)) > 0
    )


# --- Data model -------------------------------------------------------------


@dataclass
class PullRequest:
    """The subset of a wpt PR the harvester reasons about."""

    number: int
    merged_at: str | None
    author: str
    head_sha: str
    html_url: str = ""
    labels: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)


_CHANGES_REQUESTED = "CHANGES_REQUESTED"


def changes_requested_comments(pr: PullRequest) -> list[dict[str, Any]]:
    """Test-file comments under a CHANGES_REQUESTED review, excluding author
    self-replies. ``line`` is relative to the comment's ``commit_id``."""
    state_by_review = {r["id"]: r["state"] for r in pr.reviews}
    kept: list[dict[str, Any]] = []
    for c in pr.review_comments:
        path = c.get("path")
        if state_by_review.get(c.get("review_id")) != _CHANGES_REQUESTED:
            continue
        if c["author"] == pr.author or not path or not is_test_path(path):
            continue
        kept.append(
            {
                "author": c["author"],
                "path": path,
                "line": c.get("original_line") or c.get("line"),
                "commit_id": c.get("commit_id"),
                "review_state": _CHANGES_REQUESTED,
                "html_url": c.get("html_url"),
                "body": c.get("body", ""),
            }
        )
    return kept


def snapshot(
    pr: PullRequest,
    comments: list[dict[str, Any]],
    content_at: dict[tuple[str, str], str],
    fixed: dict[str, bool],
) -> dict[str, Any]:
    """Shapes a PR into the candidate record, one block per ``commit_id``.

    Pure. ``content_at`` maps ``(commit_id, path) -> content_b64``; ``fixed``
    maps ``path -> fixed_before_merge``.
    """
    by_commit: dict[str, list[dict[str, Any]]] = {}
    for c in comments:
        by_commit.setdefault(c["commit_id"], []).append(c)

    blocks: list[dict[str, Any]] = []
    for commit_id, block_comments in by_commit.items():
        paths = sorted({c["path"] for c in block_comments})
        test_files = [
            {"path": p, "content_b64": content_at[(commit_id, p)]}
            for p in paths
            if (commit_id, p) in content_at
        ]
        blocks.append(
            {
                "commit_id": commit_id,
                "test_files": test_files,
                "comments": [
                    {**c, "fixed_before_merge": fixed.get(c["path"], False)}
                    for c in block_comments
                ],
            }
        )

    return {
        "pr": pr.number,
        "pr_url": pr.html_url,
        "merged_at": pr.merged_at,
        "reviewed_commits": blocks,
        "final_diff_paths": pr.changed_paths,
    }


# --- gh I/O layer (thin; injected so tests can stub it) ---------------------


# Transient HTTP statuses worth retrying (server hiccups / rate limits).
_TRANSIENT_STATUS = re.compile(r"HTTP (429|50[0234])")
_MAX_RETRIES = 4


def _gh_json(path: str) -> Any:
    """One gh api call, one page. Retries transient (5xx/429) failures with
    exponential backoff; a fatal error (or exhausted retries) re-raises the
    CalledProcessError. Paging is explicit (see _all_pages)."""
    for attempt in range(_MAX_RETRIES + 1):
        result = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        transient = _TRANSIENT_STATUS.search(result.stderr)
        if not transient or attempt == _MAX_RETRIES:
            raise subprocess.CalledProcessError(
                result.returncode, ["gh", "api", path],
                output=result.stdout, stderr=result.stderr,
            )
        delay = 2**attempt
        print(
            f"[warn] {transient.group(0)} from gh; retry "
            f"{attempt + 1}/{_MAX_RETRIES} in {delay}s...",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


_PER_PAGE = 100


def _merged_qualifier(since: str | None, until: str | None) -> str:
    """The search `merged:` date qualifier (leading `+`), or "" if unbounded."""
    if since and until:
        return f"+merged:{since}..{until}"
    if since:
        return f"+merged:>={since}"
    if until:
        return f"+merged:<={until}"
    return ""


class GitHub:
    """gh-CLI-backed accessors, one method per endpoint the harvester needs."""

    def __init__(self, fetch: Any = _gh_json) -> None:
        self._fetch = fetch

    def _all_pages(self, path: str, max_items: int) -> list[dict[str, Any]]:
        """Pages a collection up to max_items, stopping on a short page."""
        items: list[dict[str, Any]] = []
        page = 1
        sep = "&" if "?" in path else "?"
        while len(items) < max_items:
            batch = self._fetch(
                f"{path}{sep}per_page={_PER_PAGE}&page={page}"
            )
            if not batch:
                break
            items.extend(batch)
            if len(batch) < _PER_PAGE:
                break
            page += 1
        return items[:max_items]

    def merged_pulls(
        self,
        max_items: int,
        since_date: str | None = None,
        until_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Merged PRs, newest first, vendor-export labels excluded server-side.
        ``since_date`` / ``until_date`` (YYYY-MM-DD) bound the merge date."""
        excluded = "".join(f"+-label:{label}" for label in _EXPORT_LABELS)
        merged = _merged_qualifier(since_date, until_date)
        query = (
            f"repo:{REPO}+is:pr+is:merged{excluded}{merged}"
            "&sort=updated&order=desc"
        )
        items: list[dict[str, Any]] = []
        page = 1
        while len(items) < max_items:
            result = self._fetch(
                f"/search/issues?q={query}&per_page={_PER_PAGE}&page={page}"
            )
            batch = result.get("items", []) if isinstance(result, dict) else []
            if not batch:
                break
            items.extend(batch)
            if len(batch) < _PER_PAGE:
                break
            page += 1
        return [_normalize_search_item(it) for it in items[:max_items]]

    # Caps guard a pathological PR.
    def review_comments(self, number: int) -> list[dict[str, Any]]:
        return self._all_pages(f"/repos/{REPO}/pulls/{number}/comments", 500)

    def reviews(self, number: int) -> list[dict[str, Any]]:
        return self._all_pages(f"/repos/{REPO}/pulls/{number}/reviews", 500)

    def files(self, number: int) -> list[dict[str, Any]]:
        return self._all_pages(f"/repos/{REPO}/pulls/{number}/files", 3000)

    def file_at_ref(self, path: str, ref: str) -> str | None:
        try:
            data = self._fetch(f"/repos/{REPO}/contents/{path}?ref={ref}")
        except subprocess.CalledProcessError:
            return None
        return data.get("content") if isinstance(data, dict) else None

    def head_sha(self, number: int) -> str:
        """The PR's head SHA (search items omit it)."""
        data = self._fetch(f"/repos/{REPO}/pulls/{number}")
        return (data.get("head") or {}).get("sha", "")


def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    """Maps a /search/issues item onto the pulls-endpoint shape. `merged_at`
    lives under `pull_request`; `head` is absent (fetched later)."""
    return {
        "number": item["number"],
        "merged_at": (item.get("pull_request") or {}).get("merged_at"),
        "user": item.get("user") or {},
        "labels": item.get("labels", []),
    }


def _to_pull_request(
    raw: dict[str, Any], gh: GitHub
) -> PullRequest:
    number = raw["number"]
    pr = PullRequest(
        number=number,
        merged_at=raw.get("merged_at"),
        author=(raw.get("user") or {}).get("login", ""),
        head_sha=(raw.get("head") or {}).get("sha", ""),
        html_url=raw.get("html_url", f"https://github.com/{REPO}/pull/{number}"),
        labels=[label["name"] for label in raw.get("labels", [])],
    )
    if pr.merged_at is None or is_bot_author(pr.author) or is_export_pr(
        pr.labels
    ):
        # Cheap gates first; skip the per-PR API calls for obvious rejects.
        return pr
    if not pr.head_sha:
        pr.head_sha = gh.head_sha(number)
    pr.changed_paths = [f["filename"] for f in gh.files(number)]
    pr.review_comments = [
        {
            "author": (c.get("user") or {}).get("login", ""),
            "path": c.get("path"),
            "line": c.get("line"),
            "original_line": c.get("original_line"),
            "commit_id": c.get("commit_id"),
            "review_id": c.get("pull_request_review_id"),
            "html_url": c.get("html_url"),
            "body": c.get("body", ""),
        }
        for c in gh.review_comments(number)
    ]
    pr.reviews = [
        {
            "id": r.get("id"),
            "author": (r.get("user") or {}).get("login", ""),
            "state": r.get("state", ""),
            "body": r.get("body", ""),
        }
        for r in gh.reviews(number)
    ]
    return pr


def build_record(pr: PullRequest, gh: GitHub) -> dict[str, Any]:
    """Fetches each commented file at its commit_id and at head (to derive
    fixed_before_merge), then shapes the record."""
    comments = changes_requested_comments(pr)

    content_at: dict[tuple[str, str], str] = {}
    fixed: dict[str, bool] = {}
    for path in {c["path"] for c in comments}:
        head_content = gh.file_at_ref(path, pr.head_sha)
        for commit_id in {c["commit_id"] for c in comments if c["path"] == path}:
            reviewed = gh.file_at_ref(path, commit_id)
            if reviewed is not None:
                content_at[(commit_id, path)] = reviewed
            # Changed after review = the flaw was addressed before merge.
            fixed[path] = head_content is not None and reviewed != head_content

    return snapshot(pr, comments, content_at, fixed)


# --- Watermark --------------------------------------------------------------


def load_watermark(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("merged_at")
    except (OSError, json.JSONDecodeError):
        return None


def write_watermark(path: Path, merged_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"merged_at": merged_at}, indent=2) + "\n",
        encoding="utf-8",
    )


def _candidate_file(out_dir: Path, pr_number: int) -> Path:
    return out_dir / f"{pr_number}.json"


# --- Orchestration ----------------------------------------------------------


def harvest(
    gh: GitHub,
    out_dir: Path,
    watermark_path: Path,
    max_prs: int,
    dry_run: bool,
    since_date: str | None = None,
    until_date: str | None = None,
) -> tuple[int, str | None]:
    """Returns (candidate_count, newest_merged_at)."""
    watermark = load_watermark(watermark_path)
    print(f"watermark: {watermark or '(none)'}", file=sys.stderr, flush=True)
    print("harvesting merged PRs...", file=sys.stderr, flush=True)

    raw_pulls = gh.merged_pulls(
        max_items=max_prs, since_date=since_date, until_date=until_date
    )
    if len(raw_pulls) == max_prs and (since_date or until_date):
        # A bounded window that fills --max-prs was probably truncated: the
        # oldest PRs in the window may be missing (search is newest-first).
        print(
            f"[warn] hit --max-prs={max_prs} with a --since/--until window; "
            "the window may be incomplete. Raise --max-prs to be sure.",
            file=sys.stderr,
        )
    newest_seen = watermark
    count = 0

    for raw in raw_pulls:
        merged_at = raw.get("merged_at")
        if merged_at is None:
            continue
        if watermark is not None and merged_at <= watermark:
            continue  # already processed in an earlier run

        try:
            pr = _to_pull_request(raw, gh)
            if newest_seen is None or (pr.merged_at or "") > newest_seen:
                newest_seen = pr.merged_at
            if not qualifies(pr):
                continue
            record = build_record(pr, gh)
        except subprocess.CalledProcessError:
            # gh failed even after retries. Candidates already written are
            # complete (per-PR atomic writes); report where we stopped so the
            # run can be resumed with --since <last merged_at written>.
            print(
                f"\n[error] gh API failed on PR #{raw.get('number')} "
                f"(merged {merged_at}); stopping.\n"
                f"        {count} candidate(s) written to {out_dir} so far.\n"
                "        Re-run to continue; already-written candidates are "
                "complete.",
                file=sys.stderr,
            )
            raise

        count += 1
        if dry_run:
            blocks = record["reviewed_commits"]
            n_comments = sum(len(b["comments"]) for b in blocks)
            print(
                f"  candidate PR #{pr.number} "
                f"({n_comments} CHANGES_REQUESTED comment(s) across "
                f"{len(blocks)} commit(s))",
                file=sys.stderr,
            )
            continue

        out_file = _candidate_file(out_dir, pr.number)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )

    if not dry_run and newest_seen and newest_seen != watermark:
        write_watermark(watermark_path, newest_seen)

    return count, newest_seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Harvest golden-PR candidates from web-platform-tests.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("benchmarks/golden/candidates"),
        help="Directory for <pr>.json candidate snapshots.",
    )
    parser.add_argument(
        "--watermark",
        type=Path,
        default=Path("benchmarks/golden/watermark.json"),
        help="File tracking the last merged_at processed.",
    )
    parser.add_argument(
        "--max-prs",
        type=int,
        default=200,
        help="Cap on PRs inspected this run (default: 200).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only PRs merged on/after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Only PRs merged on/before this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report candidates without writing snapshots or the watermark.",
    )
    args = parser.parse_args(argv)

    try:
        count, newest = harvest(
            GitHub(),
            args.out,
            args.watermark,
            args.max_prs,
            args.dry_run,
            since_date=args.since,
            until_date=args.until,
        )
    except FileNotFoundError:
        print(
            "error: `gh` CLI not found. Install it or run in an environment "
            "where it is available.",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as exc:
        # A per-PR failure is already reported by harvest() (with where it
        # stopped); this catches a failure in the initial PR-list fetch.
        print(
            f"error: gh api call failed: {exc.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    verb = "would harvest" if args.dry_run else "harvested"
    print(
        f"{verb} {count} candidate(s); newest merged_at {newest}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

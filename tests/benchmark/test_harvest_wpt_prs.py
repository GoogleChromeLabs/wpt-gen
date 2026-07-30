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

"""Tests for the golden-PR harvester. No network: the gh I/O layer is
stubbed with a fake serving fixture payloads."""

import json
from pathlib import Path

import pytest

# scripts/ is on sys.path via tests/conftest.py.
from benchmark import harvest_wpt_prs as h


# --- Pure filters -----------------------------------------------------------


@pytest.mark.parametrize(
    ("login", "expected"),
    [
        ("jcsteh", False),
        ("chromium-wpt-export-bot", True),
        ("moz-wptsync-bot", True),
        ("servo-wpt-sync", True),
        ("dependabot[bot]", True),
        ("wpt-pr-bot", True),
    ],
)
def test_is_bot_author(login: str, expected: bool) -> None:
    assert h.is_bot_author(login) is expected


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["editing", "mozilla:gecko-sync"], True),
        (["html", "chromium-export"], True),
        (["css-tables", "servo-export"], True),
        (["dom", "webkit-export"], True),
        (["infra", "very-large"], False),
        ([], False),
    ],
)
def test_is_export_pr(labels: list[str], expected: bool) -> None:
    assert h.is_export_pr(labels) is expected


def test_is_test_path() -> None:
    assert h.is_test_path("css/foo/bar-001.html") is True
    assert h.is_test_path("core-aam/aamtests/role/button.py") is True  # .py
    assert h.is_test_path("tools/wptrunner/x.py") is False
    assert h.is_test_path("docs/index.md") is False
    assert h.is_test_path("dom/nodes/META.yml") is False
    assert h.is_test_path("uievents/mouse/WEB_FEATURES.yml") is False
    assert h.is_test_path("fetch/foo.html.headers") is False
    assert h.is_test_path("css/foo/bar-ref.html") is False
    assert h.is_test_path("lint.ignore") is False
    assert h.is_test_path("url/resources/setters_tests.json") is False
    # support/resources at any depth marks a fixture tree
    assert h.is_test_path("fetch/x/resources/util.sub.js") is False
    assert h.is_test_path("dom/support/helper.html") is False


def test_touches_test_file() -> None:
    assert h.touches_test_file(["css/foo/bar-001.html"]) is True
    assert h.touches_test_file(["tools/x.py", "docs/index.md"]) is False
    assert h.touches_test_file(["tools/x.py", "dom/nodes/t.html"]) is True
    assert h.touches_test_file(["dom/nodes/META.yml"]) is False


# --- qualifies() ------------------------------------------------------------


def _pr(**over: object) -> h.PullRequest:
    # Default: a PR that qualifies.
    base: dict[str, object] = {
        "number": 1,
        "merged_at": "2026-07-20T00:00:00Z",
        "author": "author",
        "head_sha": "abc",
        "html_url": "https://github.com/web-platform-tests/wpt/pull/1",
        "labels": ["dom"],
        "changed_paths": ["dom/nodes/t.html"],
        "review_comments": [
            {
                "author": "reviewer",
                "path": "dom/nodes/t.html",
                "line": 5,
                "commit_id": "sha1",
                "review_id": 1,
                "body": "fix this",
            }
        ],
        "reviews": [{"id": 1, "state": "CHANGES_REQUESTED", "author": "rev"}],
    }
    base.update(over)
    return h.PullRequest(**base)  # type: ignore[arg-type]


def test_qualifies_happy_path() -> None:
    assert h.qualifies(_pr()) is True


def test_qualifies_rejects_unmerged() -> None:
    assert h.qualifies(_pr(merged_at=None)) is False


def test_qualifies_rejects_bot_author() -> None:
    assert h.qualifies(_pr(author="chromium-wpt-export-bot")) is False


def test_qualifies_rejects_export_even_with_human_author() -> None:
    # Human author, but a *-export label -> reviewed downstream, not here.
    assert h.qualifies(_pr(author="lukewarlow", labels=["webkit-export"])) is (
        False
    )


def test_qualifies_rejects_tooling_only() -> None:
    assert h.qualifies(_pr(changed_paths=["tools/x.py"])) is False


def test_qualifies_rejects_no_changes_requested() -> None:
    # Only a COMMENTED review -> no answer-key finding -> does not qualify.
    assert h.qualifies(
        _pr(reviews=[{"id": 1, "state": "COMMENTED", "author": "rev"}])
    ) is False


# --- changes_requested_comments() -------------------------------------------


def test_changes_requested_filters_to_answer_key() -> None:
    pr = _pr(
        author="twilco",
        review_comments=[
            # kept: reviewer, CHANGES_REQUESTED, test file
            {"author": "jcsteh", "path": "dom/t.py", "line": 30,
             "commit_id": "A", "review_id": 1, "html_url": "u1", "body": "fix"},
            # dropped: author's own reply
            {"author": "twilco", "path": "dom/t.py", "line": 30,
             "commit_id": "A", "review_id": 2, "body": "Fixed!"},
            # dropped: COMMENTED (not CHANGES_REQUESTED)
            {"author": "cookiecrook", "path": "dom/t.py", "line": 5,
             "commit_id": "A", "review_id": 3, "body": "nit"},
            # dropped: CHANGES_REQUESTED but on a tooling file
            {"author": "jcsteh", "path": "tools/x.py", "line": 1,
             "commit_id": "A", "review_id": 1, "body": "tooling"},
        ],
        reviews=[
            {"id": 1, "state": "CHANGES_REQUESTED", "author": "jcsteh"},
            {"id": 2, "state": "COMMENTED", "author": "twilco"},
            {"id": 3, "state": "COMMENTED", "author": "cookiecrook"},
        ],
    )
    kept = h.changes_requested_comments(pr)
    assert len(kept) == 1
    assert kept[0]["author"] == "jcsteh"
    assert kept[0]["path"] == "dom/t.py"
    assert kept[0]["line"] == 30
    assert kept[0]["commit_id"] == "A"
    assert kept[0]["review_state"] == "CHANGES_REQUESTED"
    assert kept[0]["html_url"] == "u1"


def test_changes_requested_prefers_original_line() -> None:
    pr = _pr(
        review_comments=[
            {"author": "rev", "path": "dom/t.py", "line": 9,
             "original_line": 30, "commit_id": "A", "review_id": 1,
             "body": "x"}
        ],
        reviews=[{"id": 1, "state": "CHANGES_REQUESTED", "author": "rev"}],
    )
    assert h.changes_requested_comments(pr)[0]["line"] == 30


# --- snapshot() -------------------------------------------------------------


def test_snapshot_groups_by_commit() -> None:
    pr = _pr(number=59768, author="twilco",
             changed_paths=["dom/a.py", "dom/b.py", "tools/x.py"])
    comments = [
        {"author": "j", "path": "dom/a.py", "line": 30, "commit_id": "A",
         "review_state": "CHANGES_REQUESTED", "html_url": "u1", "body": "x"},
        {"author": "j", "path": "dom/b.py", "line": 33, "commit_id": "B",
         "review_state": "CHANGES_REQUESTED", "html_url": "u2", "body": "y"},
    ]
    content_at = {("A", "dom/a.py"): "Zm9v", ("B", "dom/b.py"): "YmFy"}
    fixed = {"dom/a.py": True, "dom/b.py": False}

    rec = h.snapshot(pr, comments, content_at, fixed)

    assert rec["pr"] == 59768
    assert rec["pr_url"] == pr.html_url
    assert "reviews" not in rec
    # One block per distinct commit_id, each with its commented file.
    blocks = {b["commit_id"]: b for b in rec["reviewed_commits"]}
    assert set(blocks) == {"A", "B"}
    assert blocks["A"]["test_files"] == [
        {"path": "dom/a.py", "content_b64": "Zm9v"}
    ]
    assert blocks["A"]["comments"][0]["fixed_before_merge"] is True
    assert blocks["B"]["comments"][0]["fixed_before_merge"] is False
    # Full changed set, tooling included.
    assert rec["final_diff_paths"] == ["dom/a.py", "dom/b.py", "tools/x.py"]


def test_build_record_derives_fixed_before_merge() -> None:
    # file_at_ref returns different bytes at commit vs head -> fixed=True.
    class _Gh:
        def file_at_ref(self, path: str, ref: str) -> str:
            return "reviewed" if ref == "A" else "head"

    pr = _pr(
        author="twilco",
        head_sha="HEAD",
        review_comments=[
            {"author": "rev", "path": "dom/t.py", "line": 30, "commit_id": "A",
             "review_id": 1, "html_url": "u", "body": "x"}
        ],
        reviews=[{"id": 1, "state": "CHANGES_REQUESTED", "author": "rev"}],
    )
    rec = h.build_record(pr, _Gh())
    block = rec["reviewed_commits"][0]
    assert block["comments"][0]["fixed_before_merge"] is True
    assert block["test_files"][0]["content_b64"] == "reviewed"  # @ commit A


# --- date-window qualifier --------------------------------------------------


def test_merged_qualifier() -> None:
    assert h._merged_qualifier(None, None) == ""
    assert h._merged_qualifier("2026-07-01", None) == "+merged:>=2026-07-01"
    assert h._merged_qualifier(None, "2026-07-31") == "+merged:<=2026-07-31"
    assert h._merged_qualifier("2026-06-01", "2026-07-01") == (
        "+merged:2026-06-01..2026-07-01"
    )


def test_merged_pulls_injects_date_window() -> None:
    seen: list[str] = []

    def fake_fetch(path: str) -> dict:
        seen.append(path)
        return {"items": []}

    gh = h.GitHub(fetch=fake_fetch)
    gh.merged_pulls(max_items=10, since_date="2026-07-01")
    assert "merged:>=2026-07-01" in seen[0]


# --- search item normalization ----------------------------------------------


def test_normalize_search_item() -> None:
    # /search/issues shape: merged_at nested under pull_request, no head.
    item = {
        "number": 42,
        "user": {"login": "alice"},
        "labels": [{"name": "dom"}],
        "pull_request": {"merged_at": "2026-07-20T00:00:00Z"},
    }
    norm = h._normalize_search_item(item)
    assert norm["number"] == 42
    assert norm["merged_at"] == "2026-07-20T00:00:00Z"
    assert norm["user"]["login"] == "alice"
    assert "head" not in norm  # fetched later


def test_to_pull_request_fetches_head_sha_when_absent() -> None:
    # Search items omit head; _to_pull_request fetches it after the gates pass.
    per_pr = {
        7: {
            "files": [{"filename": "dom/t.html"}],
            "comments": [{"user": {"login": "rev"}, "body": "x"}],
            "reviews": [],
        }
    }
    gh = _FakeGitHub([], per_pr)
    raw = {
        "number": 7,
        "merged_at": "2026-07-20T00:00:00Z",
        "user": {"login": "human"},
        "labels": [{"name": "dom"}],
    }
    pr = h._to_pull_request(raw, gh)
    assert pr.head_sha == "fetched-sha"


# --- watermark --------------------------------------------------------------


def test_watermark_roundtrip(tmp_path: Path) -> None:
    wm = tmp_path / "watermark.json"
    assert h.load_watermark(wm) is None  # missing file
    h.write_watermark(wm, "2026-07-20T00:00:00Z")
    assert h.load_watermark(wm) == "2026-07-20T00:00:00Z"


def test_watermark_load_tolerates_garbage(tmp_path: Path) -> None:
    wm = tmp_path / "watermark.json"
    wm.write_text("not json", encoding="utf-8")
    assert h.load_watermark(wm) is None


# --- harvest() orchestration (stubbed gh) -----------------------------------


class _FakeGitHub:
    """Serves canned endpoint payloads keyed by PR number."""

    def __init__(self, pulls: list[dict], per_pr: dict[int, dict]) -> None:
        self._pulls = pulls
        self._per_pr = per_pr

    def merged_pulls(
        self, max_items: int, since_date: str | None = None,
        until_date: str | None = None,
    ) -> list[dict]:
        return self._pulls[:max_items]

    def review_comments(self, number: int) -> list[dict]:
        return self._per_pr[number].get("comments", [])

    def reviews(self, number: int) -> list[dict]:
        return self._per_pr[number].get("reviews", [])

    def files(self, number: int) -> list[dict]:
        return self._per_pr[number].get("files", [])

    def file_at_ref(self, path: str, ref: str) -> str | None:
        return "Y29udGVudA=="  # base64("content")

    def head_sha(self, number: int) -> str:
        return "fetched-sha"


def _raw_pull(number: int, merged_at: str, author: str, labels: list[str]):
    return {
        "number": number,
        "merged_at": merged_at,
        "user": {"login": author},
        "head_sha": "sha",
        "head": {"sha": "sha"},
        "labels": [{"name": n} for n in labels],
    }


def _cr_pr(number: int) -> dict:
    """per_pr payload for a PR that qualifies (one CHANGES_REQUESTED comment
    from a reviewer on a test file)."""
    return {
        "files": [{"filename": "dom/nodes/t.html"}],
        "comments": [
            {"user": {"login": "rev"}, "path": "dom/nodes/t.html",
             "line": 5, "original_line": 5, "commit_id": "sha1",
             "pull_request_review_id": 1, "html_url": "u", "body": "fix"}
        ],
        "reviews": [
            {"id": 1, "user": {"login": "rev"}, "state": "CHANGES_REQUESTED",
             "body": ""}
        ],
    }


def test_harvest_writes_qualifying_and_skips_rest(tmp_path: Path) -> None:
    pulls = [
        _raw_pull(10, "2026-07-25T00:00:00Z", "human", ["dom"]),  # qualifies
        _raw_pull(11, "2026-07-24T00:00:00Z", "chromium-wpt-export-bot",
                  ["chromium-export"]),  # export bot
        _raw_pull(12, "2026-07-23T00:00:00Z", "human", ["css"]),  # no CR
    ]
    per_pr = {
        10: _cr_pr(10),
        11: {},
        12: {
            "files": [{"filename": "css/t.html"}],
            "comments": [{"user": {"login": "rev"}, "path": "css/t.html",
                          "line": 1, "commit_id": "s", "pull_request_review_id":
                          9, "body": "x"}],
            "reviews": [{"id": 9, "user": {"login": "rev"},
                         "state": "COMMENTED", "body": ""}],
        },
    }
    gh = _FakeGitHub(pulls, per_pr)
    out = tmp_path / "candidates"
    wm = tmp_path / "watermark.json"

    count, newest = h.harvest(gh, out, wm, max_prs=200, dry_run=False)

    assert count == 1
    assert newest == "2026-07-25T00:00:00Z"  # advances across skipped PRs
    # One JSON file per PR; only PR 10 qualifies.
    assert {p.name for p in out.glob("*.json")} == {"10.json"}
    rec = json.loads((out / "10.json").read_text(encoding="utf-8"))
    assert rec["pr"] == 10
    block = rec["reviewed_commits"][0]
    assert block["commit_id"] == "sha1"
    assert block["test_files"][0]["path"] == "dom/nodes/t.html"
    assert h.load_watermark(wm) == "2026-07-25T00:00:00Z"


def test_harvest_respects_watermark(tmp_path: Path) -> None:
    wm = tmp_path / "watermark.json"
    h.write_watermark(wm, "2026-07-25T00:00:00Z")
    pulls = [
        _raw_pull(10, "2026-07-25T00:00:00Z", "human", ["dom"]),  # == wm, skip
        _raw_pull(9, "2026-07-24T00:00:00Z", "human", ["dom"]),  # older, skip
    ]
    gh = _FakeGitHub(pulls, {10: _cr_pr(10), 9: _cr_pr(9)})
    count, _ = h.harvest(
        gh, tmp_path / "c", wm, max_prs=200, dry_run=False
    )
    assert count == 0


def test_harvest_dry_run_writes_nothing(tmp_path: Path) -> None:
    pulls = [_raw_pull(10, "2026-07-25T00:00:00Z", "human", ["dom"])]
    out = tmp_path / "candidates"
    wm = tmp_path / "watermark.json"
    count, _ = h.harvest(
        _FakeGitHub(pulls, {10: _cr_pr(10)}), out, wm, max_prs=200,
        dry_run=True,
    )
    assert count == 1
    assert not out.exists()
    assert not wm.exists()  # watermark untouched in dry-run


# --- GitHub._all_pages (bounded paging) -------------------------------------


def test_all_pages_stops_at_max_items() -> None:
    calls: list[str] = []

    def fake_fetch(path: str) -> list[dict]:
        calls.append(path)
        return [{"i": 1}] * 100  # always a full page

    gh = h.GitHub(fetch=fake_fetch)
    items = gh._all_pages("/x", max_items=250)
    assert len(items) == 250
    assert len(calls) == 3  # 3 pages of 100, no more


def test_all_pages_stops_on_short_page() -> None:
    pages = [[{"i": 1}] * 100, [{"i": 2}] * 20]

    def fake_fetch(path: str) -> list[dict]:
        return pages.pop(0) if pages else []

    gh = h.GitHub(fetch=fake_fetch)
    items = gh._all_pages("/x", max_items=10_000)
    assert len(items) == 120  # stopped at the short second page

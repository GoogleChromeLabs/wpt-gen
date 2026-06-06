"""Tests for the spec-keyed requirements extraction phase."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from wptgen.config import Config
from wptgen.phases.spec_requirements_extraction import (
    _fetch_spec_section,
    _slice_html_by_anchor,
    extract_requirements_from_spec_url,
    run_spec_requirements_extraction,
)


@pytest.fixture
def jinja_env() -> MagicMock:
    """A minimal jinja_env that records what was rendered."""
    env = MagicMock()
    template = MagicMock()
    template.render.return_value = "rendered prompt"
    env.get_template.return_value = template
    return env


@pytest.mark.asyncio
async def test_writes_cache_and_reports_miss_when_fresh(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    jinja_env: MagicMock,
    mocker: MockerFixture,
) -> None:
    """First run: no cache file → invokes the LLM, writes cache,
    reports cache_hit=False."""
    cache_dir = tmp_path / "evaluator-cache"

    invoke_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.invoke_extractor",
        new=AsyncMock(return_value="<requirements_list/>"),
    )

    result = await run_spec_requirements_extraction(
        spec_contents={"https://example.com/spec/": "spec body"},
        label="spec-example-com-spec",
        config=mock_config,
        llm=mock_llm,
        ui=mock_ui,
        jinja_env=jinja_env,
        cache_dir=cache_dir,
    )

    assert result is not None
    requirements_xml, cache_hit = result
    assert requirements_xml == "<requirements_list/>"
    assert cache_hit is False
    invoke_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reads_cache_and_reports_hit(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    jinja_env: MagicMock,
    mocker: MockerFixture,
) -> None:
    """Second run: cache file present + yes_cache → LLM is NOT called,
    reports cache_hit=True."""
    mock_config.yes_cache = True

    cache_dir = tmp_path / "evaluator-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_xml = "<requirements_list><requirement id='R1'/></requirements_list>"
    (cache_dir / "spec-example-com-spec__requirements.xml").write_text(
        cached_xml, encoding="utf-8"
    )

    invoke_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.invoke_extractor",
        new=AsyncMock(),
    )

    result = await run_spec_requirements_extraction(
        spec_contents={"https://example.com/spec/": "spec body"},
        label="spec-example-com-spec",
        config=mock_config,
        llm=mock_llm,
        ui=mock_ui,
        jinja_env=jinja_env,
        cache_dir=cache_dir,
    )

    assert result is not None
    requirements_xml, cache_hit = result
    assert requirements_xml == cached_xml
    assert cache_hit is True
    invoke_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_none_on_extractor_failure(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    jinja_env: MagicMock,
    mocker: MockerFixture,
) -> None:
    """Extractor returning None propagates as None (not a tuple)."""
    cache_dir = tmp_path / "evaluator-cache"

    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.invoke_extractor",
        new=AsyncMock(return_value=None),
    )

    result = await run_spec_requirements_extraction(
        spec_contents={"https://example.com/spec/": "spec body"},
        label="spec-example-com-spec",
        config=mock_config,
        llm=mock_llm,
        ui=mock_ui,
        jinja_env=jinja_env,
        cache_dir=cache_dir,
    )

    assert result is None


@pytest.mark.asyncio
async def test_creates_cache_dir_if_missing(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mock_llm: MagicMock,
    jinja_env: MagicMock,
    mocker: MockerFixture,
) -> None:
    """The cache directory is created on demand (does not require the
    caller to mkdir first)."""
    cache_dir = tmp_path / "nested" / "evaluator-cache" / "deep"
    assert not cache_dir.exists()

    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.invoke_extractor",
        new=AsyncMock(return_value="<requirements_list/>"),
    )

    result = await run_spec_requirements_extraction(
        spec_contents={"https://example.com/spec/": "spec body"},
        label="spec-example-com-spec",
        config=mock_config,
        llm=mock_llm,
        ui=mock_ui,
        jinja_env=jinja_env,
        cache_dir=cache_dir,
    )
    assert result is not None
    assert cache_dir.is_dir()


# ---------------------------------------------------------------------------
# HTML anchor slicing
# ---------------------------------------------------------------------------


def test_slice_html_by_heading_anchor_collects_until_same_level() -> None:
    """Slice from an <h3> anchor collects forward to the next <h3>/<h2>/<h1>."""
    html = """
    <html><body>
    <h2 id="other-section">Other</h2>
    <p>other content</p>
    <h3 id="align-content-property">align-content</h3>
    <p>The align-content property...</p>
    <p>It applies to multi-line flex containers.</p>
    <h4 id="sub">Sub-section</h4>
    <p>sub content</p>
    <h3 id="next-property">next-property</h3>
    <p>should be excluded</p>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "align-content-property")
    assert sliced is not None
    assert "align-content property" in sliced
    assert "multi-line flex containers" in sliced
    assert "Sub-section" in sliced  # h4 is below the boundary, included
    assert "sub content" in sliced
    assert "next-property" not in sliced  # same-level h3 → boundary
    assert "should be excluded" not in sliced


def test_slice_html_by_section_anchor_returns_section() -> None:
    """A <section id="..."> anchor returns the whole section."""
    html = """
    <html><body>
    <section id="video">
      <h2>The video element</h2>
      <p>The video element represents a video.</p>
    </section>
    <section id="audio">
      <h2>The audio element</h2>
    </section>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "video")
    assert sliced is not None
    assert "video element" in sliced
    assert "represents a video" in sliced
    assert "audio element" not in sliced


def test_slice_html_by_inline_anchor_walks_to_enclosing_section() -> None:
    """An inline <dfn> anchor walks up to the nearest enclosing <section>."""
    html = """
    <html><body>
    <section>
      <h2>Other</h2>
      <p>other content</p>
    </section>
    <section>
      <h2>The <dfn id="flex-basis">flex-basis</dfn> property</h2>
      <p>flex-basis description.</p>
    </section>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "flex-basis")
    assert sliced is not None
    assert 'id="flex-basis"' in sliced
    assert "flex-basis description" in sliced
    assert "other content" not in sliced


def test_slice_html_by_anchor_missing_returns_none() -> None:
    """A missing anchor returns None so callers can fall back."""
    html = "<html><body><h2 id='real'>Real</h2></body></html>"
    assert _slice_html_by_anchor(html, "does-not-exist") is None


def test_slice_html_by_heading_anchor_higher_level_boundary() -> None:
    """An <h4> anchor stops at the next <h4>/<h3>/<h2>/<h1>, not at <h5>/<h6>."""
    html = """
    <html><body>
    <h4 id="target">Target</h4>
    <p>p1</p>
    <h5>Sub</h5>
    <p>p2</p>
    <h6>Sub-sub</h6>
    <p>p3</p>
    <h3>Higher</h3>
    <p>p4 should be excluded</p>
    </body></html>
    """
    sliced = _slice_html_by_anchor(html, "target")
    assert sliced is not None
    assert "p1" in sliced
    assert "p2" in sliced
    assert "p3" in sliced
    assert "p4 should be excluded" not in sliced
    assert "Higher" not in sliced


# ---------------------------------------------------------------------------
# _fetch_spec_section (slicer + fetch integration)
# ---------------------------------------------------------------------------


def test_fetch_spec_section_without_fragment_uses_full_extract(
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """A URL with no fragment delegates to fetch_and_extract_text."""
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_and_extract_text",
        return_value="full document markdown",
    )
    raw_html_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_raw_html",
    )

    result = _fetch_spec_section("https://example.com/spec/", ui=mock_ui)
    assert result == "full document markdown"
    raw_html_mock.assert_not_called()


def test_fetch_spec_section_with_fragment_slices(
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """A URL with a fragment fetches raw HTML and slices to the section."""
    raw_html = """
    <html><body>
      <h2 id="other">other</h2>
      <p>excluded</p>
      <h2 id="video">Video element</h2>
      <p>The video element represents a video.</p>
    </body></html>
    """
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_raw_html",
        return_value=raw_html,
    )
    fallback_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_and_extract_text",
    )

    result = _fetch_spec_section(
        "https://example.com/spec/#video", ui=mock_ui
    )
    assert result is not None
    assert "Video element" in result
    assert "represents a video" in result
    assert "excluded" not in result
    fallback_mock.assert_not_called()


def test_fetch_spec_section_missing_anchor_falls_back_to_full(
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """Anchor not found → warn + fall back to the full document."""
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_raw_html",
        return_value="<html><body><p>no anchors</p></body></html>",
    )
    fallback_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_and_extract_text",
        return_value="full document markdown",
    )

    result = _fetch_spec_section(
        "https://example.com/spec/#does-not-exist", ui=mock_ui
    )
    assert result == "full document markdown"
    fallback_mock.assert_called_once_with("https://example.com/spec/")
    mock_ui.warning.assert_called_once()


def test_fetch_spec_section_raw_fetch_failure_returns_none(
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_raw_html",
        return_value=None,
    )
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.fetch_and_extract_text",
    )
    assert (
        _fetch_spec_section(
            "https://example.com/spec/#anything", ui=mock_ui
        )
        is None
    )


# ---------------------------------------------------------------------------
# extract_requirements_from_spec_url (the public URL → requirements pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_from_url_returns_none_on_fetch_failure(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """If the spec fetch returns nothing, the pipeline returns None and
    does not invoke the extractor."""
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction._fetch_spec_section",
        return_value=None,
    )
    extract_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.run_spec_requirements_extraction",
        new=AsyncMock(),
    )

    result = await extract_requirements_from_spec_url(
        spec_url="https://example.com/spec/",
        config=mock_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        cache_dir=tmp_path / "evaluator-cache",
    )
    assert result is None
    extract_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_from_url_forwards_extractor_result(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """The URL pipeline forwards the extractor's tuple verbatim."""
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction._fetch_spec_section",
        return_value="spec body",
    )
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.run_spec_requirements_extraction",
        new=AsyncMock(return_value=("<requirements_list/>", True)),
    )
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.get_llm_client",
        return_value=MagicMock(),
    )

    result = await extract_requirements_from_spec_url(
        spec_url="https://example.com/spec/",
        config=mock_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        cache_dir=tmp_path / "evaluator-cache",
    )
    assert result == ("<requirements_list/>", True)


@pytest.mark.asyncio
async def test_extract_from_url_fragment_caches_independently(
    tmp_path: Path,
    mock_config: Config,
    mock_ui: MagicMock,
    mocker: MockerFixture,
) -> None:
    """`spec/#video` and `spec/#audio` derive distinct cache labels.

    The slug derivation lives in this module; cache-hit detection lives
    in `run_spec_requirements_extraction`. This test confirms the public
    pipeline passes a fragment-distinguishing label down to the
    extractor.
    """
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction._fetch_spec_section",
        return_value="spec body",
    )
    extractor_mock = mocker.patch(
        "wptgen.phases.spec_requirements_extraction.run_spec_requirements_extraction",
        new=AsyncMock(return_value=("<requirements_list/>", False)),
    )
    mocker.patch(
        "wptgen.phases.spec_requirements_extraction.get_llm_client",
        return_value=MagicMock(),
    )

    cache_dir = tmp_path / "evaluator-cache"
    await extract_requirements_from_spec_url(
        spec_url="https://example.com/spec/#video",
        config=mock_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        cache_dir=cache_dir,
    )
    await extract_requirements_from_spec_url(
        spec_url="https://example.com/spec/#audio",
        config=mock_config,
        jinja_env=MagicMock(),
        ui=mock_ui,
        cache_dir=cache_dir,
    )

    assert extractor_mock.await_count == 2
    label_a = extractor_mock.await_args_list[0].kwargs["label"]
    label_b = extractor_mock.await_args_list[1].kwargs["label"]
    assert label_a == "spec-example-com-spec-video"
    assert label_b == "spec-example-com-spec-audio"

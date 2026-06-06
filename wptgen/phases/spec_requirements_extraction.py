"""Spec Requirements Extraction — keyed on spec URLs.
"""

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

import markdownify
from bs4 import BeautifulSoup, Tag
from jinja2 import Environment

from wptgen.config import Config
from wptgen.context import fetch_and_extract_text, fetch_raw_html
from wptgen.llm import LLMClient, get_llm_client
from wptgen.phases.utils import invoke_extractor, load_cached_requirements
from wptgen.ui import UIProvider


_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_SECTIONING_TAGS = ("section", "article")


def _find_section_root(target: Tag) -> Tag:
    """Resolves the target element to the root of its section for slicing."""
    if target.name in _SECTIONING_TAGS or target.name in _HEADING_TAGS:
        return target
    for ancestor in target.parents:
        if not isinstance(ancestor, Tag):
            continue
        if ancestor.name in _SECTIONING_TAGS:
            return ancestor
        first_child = next(
            (c for c in ancestor.children if isinstance(c, Tag)), None
        )
        if first_child is not None and first_child.name in _HEADING_TAGS:
            return ancestor
    return target


def _slice_html_by_anchor(html: str, fragment: str) -> str | None:
    """Returns an HTML fragment containing just the section at `fragment`,
    or None if the anchor can't be found."""
    soup = BeautifulSoup(html, "lxml")
    target = soup.find(id=fragment)
    if not isinstance(target, Tag):
        return None

    root = _find_section_root(target)

    if root.name in _SECTIONING_TAGS:
        return str(root)

    if root.name in _HEADING_TAGS:
        boundary_level = int(root.name[1])
        collected = [str(root)]
        for sibling in root.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in _HEADING_TAGS:
                if int(sibling.name[1]) <= boundary_level:
                    break
            collected.append(str(sibling))
        return "".join(collected)

    return str(root)


def _section_to_markdown(section_html: str) -> str:
    """Converts a sliced HTML section to Markdown."""
    soup = BeautifulSoup(section_html, "lxml")
    for element in soup(
        ["nav", "script", "style", "footer", "head", "link", "meta", "noscript"]
    ):
        element.extract()
    for a_tag in soup.find_all("a"):
        href = a_tag.get("href")
        if not isinstance(href, str) or not href.startswith("#"):
            a_tag.unwrap()
    content = markdownify.markdownify(
        str(soup),
        heading_style="ATX",
        strip=["img", "picture", "video", "audio", "iframe"],
    )
    return str(content).strip()


def _fetch_spec_section(spec_url: str, ui: UIProvider) -> str | None:
    """Fetches a spec URL, slicing to the fragment section if one is given."""
    parsed = urlparse(spec_url)
    fragment = parsed.fragment
    if not fragment:
        return fetch_and_extract_text(spec_url)

    base_url = spec_url.split("#", 1)[0]
    raw_html = fetch_raw_html(base_url)
    if not raw_html:
        return None

    section_html = _slice_html_by_anchor(raw_html, fragment)
    if section_html is None:
        ui.warning(
            f"Anchor #{fragment} not found in {base_url}; falling back "
            "to the full document."
        )
        return fetch_and_extract_text(base_url)

    return _section_to_markdown(section_html)


def _slug_for_spec_url(spec_url: str) -> str:
    """Stable, human-readable cache key for a spec URL."""
    parsed = urlparse(spec_url)
    slug_source = parsed.netloc + parsed.path
    if parsed.fragment:
        slug_source += "-" + parsed.fragment
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")
    return f"spec-{slug}"


async def run_spec_requirements_extraction(
    spec_contents: dict[str, str],
    label: str,
    config: Config,
    llm: LLMClient,
    ui: UIProvider,
    jinja_env: Environment,
    cache_dir: Path,
) -> tuple[str, bool] | None:
    """Extracts normative requirements from user-supplied spec content.

    Args:
        spec_contents: Mapping from spec URL → extracted spec text. One
            or more entries.
        label: Cache key / UI identifier. The cache file will be
            written as `<cache_dir>/<label>__requirements.xml`.
        config: The tool configuration.
        llm: The LLM client.
        ui: The UI provider.
        jinja_env: The Jinja2 environment.
        cache_dir: Directory where the requirements XML cache lives.

    Returns:
        `(requirements_xml, cache_hit)` on success, or None on failure.
    """
    ui.on_phase_start(2, "Spec Requirements Extraction")

    cache_file = cache_dir / f"{label}__requirements.xml"

    cached = load_cached_requirements(label, cache_file, config, ui)
    if cached:
        count = len(re.findall(r"<requirement\b[^>]*>", cached))
        ui.success(f"Extracted {count} test requirements.")
        return cached, True

    extraction_prompt = jinja_env.get_template(
        "requirements_extraction.jinja"
    ).render(
        feature_name=label,
        feature_description="Specification under evaluation",
        specs=spec_contents,
        mdn_contents=None,
        explainer_contents=None,
    )
    extraction_system_prompt = jinja_env.get_template(
        "requirements_extraction_system.jinja"
    ).render(
        has_mdn=False,
        has_explainer=False,
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    requirements_xml = await invoke_extractor(
        extraction_prompt=extraction_prompt,
        extraction_system_prompt=extraction_system_prompt,
        label="Spec Requirements Extraction",
        cache_file=cache_file,
        config=config,
        llm=llm,
        ui=ui,
    )
    if not requirements_xml:
        return None
    return requirements_xml, False


async def extract_requirements_from_spec_url(
    spec_url: str,
    config: Config,
    jinja_env: Environment,
    ui: UIProvider,
    cache_dir: Path,
) -> tuple[str, bool] | None:
    """Public entrypoint: fetches a spec URL and extracts requirements.

    Returns:
        `(requirements_xml, cache_hit)` on success, or None if the
        spec could not be fetched or the extractor failed.
    """
    spec_text = await asyncio.to_thread(_fetch_spec_section, spec_url, ui)
    if not spec_text:
        ui.error(f"Failed to fetch spec content from {spec_url}.")
        return None

    label = _slug_for_spec_url(spec_url)
    llm = get_llm_client(config)
    return await run_spec_requirements_extraction(
        spec_contents={spec_url: spec_text},
        label=label,
        config=config,
        llm=llm,
        ui=ui,
        jinja_env=jinja_env,
        cache_dir=cache_dir,
    )

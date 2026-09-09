"""Thin ARTICLE_URL / TOPIC ingest on the existing P0–P12 chain (MUST-023).

Not a new pipeline: fetch primary → fill ``sources[]`` or stop. Never invent VO
blocks from a topic/URL when the primary page has no title.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable
from urllib.parse import urlparse

from ..errors import NoSource
from .providers.press import _TITLE_KEYS, _unescape, meta_map

FetchFn = Callable[[str], str]

_TITLE_TAG = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
_CANONICAL = re.compile(
    r"<link\b[^>]*rel=['\"]canonical['\"][^>]*>", re.I)
_HREF = re.compile(r"""href\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_ITEM = re.compile(r"<item\b[^>]*>(.*?)</item>", re.I | re.S)
_TAG = lambda name: re.compile(rf"<{name}\b[^>]*>(.*?)</{name}>", re.I | re.S)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.I | re.S)


def _strip_markup(raw: str) -> str:
    text = _CDATA.sub(r"\1", raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _unescape(text)).strip()


def extract_primary(html: str, url: str) -> dict[str, Any] | None:
    """Title + canonical/domain from HTML. None when there is no title."""
    meta = meta_map(html or "")
    title = next((_unescape(meta[k]) for k in _TITLE_KEYS if meta.get(k)), "")
    if not title:
        found = _TITLE_TAG.search(html or "")
        title = _strip_markup(found.group(1)) if found else ""
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None
    canonical = ""
    link = _CANONICAL.search(html or "")
    if link:
        href = _HREF.search(link.group(0))
        if href:
            canonical = href.group(2) or href.group(3) or href.group(4) or ""
    canonical = canonical or meta.get("og:url") or url
    domain = urlparse(canonical or url).netloc.lower().removeprefix("www.")
    snippet = _unescape(meta.get("og:description") or meta.get("description") or "").strip()
    return {
        "title": title[:200],
        "domain": domain or "unknown",
        "url": str(canonical or url),
        "show_on_screen": True,
        "snippet": (snippet or title)[:280],
    }


def _default_fetch(url: str) -> str:
    import requests

    resp = requests.get(
        url, timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; REDSHIFT/1.0)"},
    )
    if resp.status_code >= 400:
        raise NoSource(
            f"primary source недоступен: HTTP {resp.status_code}",
            url=url[:160], status=resp.status_code,
        )
    return resp.text[:400_000]


def apply_article_url(script: dict[str, Any], url: str, *,
                      fetch_html: FetchFn | None = None) -> dict[str, Any]:
    """Merge extracted primary into sources[]. Does not invent VO blocks."""
    href = str(url or "").strip()
    if not href.lower().startswith(("http://", "https://")):
        raise NoSource("ARTICLE_URL: нужен http(s) primary source", url=href[:160])
    html = (fetch_html or _default_fetch)(href)
    primary = extract_primary(html, href)
    if primary is None:
        raise NoSource(
            "ARTICLE_URL: primary source не извлечён (нет title) — стоп, не пишем VO из темы",
            url=href[:160],
        )
    out = copy.deepcopy(script)
    sources = list(out.get("sources") or [])
    urls = {str(s.get("url") or "") for s in sources}
    if primary["url"] not in urls:
        sources.append(primary)
    out["sources"] = sources
    return out


def topic_donors(news_yaml: dict[str, Any], topic: str) -> list[dict[str, Any]]:
    """RSS donors already listed in sources.yaml whose topics/name match TOPIC."""
    needle = str(topic or "").strip().lower()
    if not needle:
        return []
    hits: list[dict[str, Any]] = []
    for item in news_yaml.get("rss") or []:
        if not isinstance(item, dict):
            continue
        topics = [str(t).lower() for t in (item.get("topics") or [])]
        name = str(item.get("name") or "").lower()
        blob = " ".join([name, *topics])
        if needle in blob or any(needle in t or t in needle for t in topics if t):
            hits.append(item)
    return hits


def parse_rss_items(xml: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for body in _ITEM.findall(xml or ""):
        title_m = _TAG("title").search(body)
        link_m = _TAG("link").search(body)
        title = _strip_markup(title_m.group(1) if title_m else "")
        link = _strip_markup(link_m.group(1) if link_m else "")
        if not title or not link:
            continue
        items.append({"title": title, "url": link})
    return items


def _load_news_yaml(news_yaml: dict[str, Any] | None, cfg) -> dict[str, Any]:
    if news_yaml is not None:
        return news_yaml
    import yaml
    from pathlib import Path

    root = getattr(cfg, "repo_root", None)
    if root is None:
        raise NoSource("TOPIC: нет config/sources.yaml")
    path = Path(root) / "config" / "sources.yaml"
    if not path.is_file():
        raise NoSource("TOPIC: нет config/sources.yaml", path=str(path))
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def apply_topic(script: dict[str, Any], topic: str, *,
                news_yaml: dict[str, Any] | None = None,
                fetch_rss: FetchFn | None = None,
                cfg=None) -> dict[str, Any]:
    """Search only listed donors. 0 donors or 0 hits → stop. No VO from topic."""
    data = _load_news_yaml(news_yaml, cfg)
    donors = topic_donors(data or {}, topic)
    if not donors:
        raise NoSource(
            f"TOPIC {topic!r}: 0 доноров в sources.yaml — стоп, не генерируем из темы",
            topic=topic,
        )
    hits: list[dict[str, str]] = []
    fetcher = fetch_rss or _default_fetch
    for donor in donors:
        url = str(donor.get("url") or "").strip()
        if not url:
            continue
        try:
            xml = fetcher(url)
        except Exception:  # noqa: BLE001 — один фид не должен маскировать 0 hits
            continue
        hits.extend(parse_rss_items(xml))
        if hits:
            break
    if not hits:
        raise NoSource(
            f"TOPIC {topic!r}: 0 hits у доноров sources.yaml — стоп",
            topic=topic,
        )
    hit = hits[0]
    domain = urlparse(hit["url"]).netloc.lower().removeprefix("www.") or "unknown"
    primary = {
        "title": hit["title"][:200],
        "domain": domain,
        "url": hit["url"],
        "show_on_screen": True,
        "snippet": hit["title"][:280],
    }
    out = copy.deepcopy(script)
    sources = list(out.get("sources") or [])
    urls = {str(s.get("url") or "") for s in sources}
    if primary["url"] not in urls:
        sources.append(primary)
    out["sources"] = sources
    return out

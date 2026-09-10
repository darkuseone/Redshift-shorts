"""Кадр со страницы самой статьи (§7.2, «реальный материал»).

Заказчик просил брать больше настоящего материала: «если материал по какой-то
статье, то можешь брать прям оттуда кадры или видео». Провайдер это и делает —
читает страницу источника, которую ролик и так цитирует, и берёт её главный
кадр (``og:image``). Тот же домен в этот момент стоит на экране карточкой
источника, а ссылка уходит в манифест материалов.

Лицензию такого кадра подтвердить нельзя, и делать вид, что можно, — нельзя
тем более: у издания он чаще всего сам лицензирован у агентства. Поэтому
источник помечен в ``stock_sources.yaml`` режимом ``owner_decision``: правило
§7.2.7 не ослаблено для всех, а один источник назван поимённо, и решение о нём
принимает владелец канала. Выключается одной строкой ``enabled: false``.

Разбор страницы — регуляркой по тегам ``<meta>``, без HTML-парсера: он тянул бы
зависимость ради пяти атрибутов, а зависимости здесь стоят воспроизводимости
прогона на голом раннере.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from ...errors import ProviderError
from ..logging import get_logger
from ..retry import call_with_retry
from .base import ProviderMode
from .stock import StockCandidate, StockProvider

_log = get_logger("press")

_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""(\w[\w:.-]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")
# Порядок предпочтения: то, что издание само выбрало для превью, — первым.
_IMAGE_KEYS = ("og:image:secure_url", "og:image:url", "og:image", "twitter:image",
               "twitter:image:src")
_TITLE_KEYS = ("og:title", "twitter:title")
_SITE_KEYS = ("og:site_name",)
# Дату каждое издание кладёт по-своему: у блогов это og-время статьи, у научных
# журналов — Dublin Core и PRISM. Проверено на живых страницах: blog.google
# отдаёт article:published_time, nature.com — только dc.date и
# prism.publicationdate, и без них карточка осталась бы без даты.
_TIME_KEYS = ("article:published_time", "article:modified_time",
              "dc.date", "prism.publicationdate", "citation_online_date", "date")
_JSONLD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _jsonld_images(html: str) -> list[str]:
    """Картинки из JSON-LD: у научных пресс-релизов og:image бывает пуст, схема — нет."""
    out: list[str] = []
    for match in _JSONLD.finditer(html or ""):
        raw = (match.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        blobs = data if isinstance(data, list) else [data]
        for blob in blobs:
            if not isinstance(blob, dict):
                continue
            image = blob.get("image")
            urls: list[Any] = []
            if isinstance(image, str):
                urls = [image]
            elif isinstance(image, dict):
                urls = [image.get("url") or image.get("@id")]
            elif isinstance(image, list):
                urls = image
            for item in urls:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict):
                    url = item.get("url") or item.get("@id")
                    if url:
                        out.append(str(url).strip())
    return out


def _unique_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = url.split("?")[0].rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(url)
    return out


def meta_map(html: str) -> dict[str, str]:
    """Карта ``property``/``name`` → ``content`` со страницы.

    Атрибуты у изданий идут в обоих порядках и в любых кавычках, поэтому
    разбираем каждый тег целиком, а не ищем пару «property, потом content».
    """
    out: dict[str, str] = {}
    for tag in _META_TAG.findall(html or ""):
        attrs: dict[str, str] = {}
        for match in _ATTR.finditer(tag):
            value = match.group(3) or match.group(4) or match.group(5) or ""
            attrs[match.group(1).lower()] = value
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        content = attrs.get("content")
        if key and content and key.lower() not in out:
            out[key.lower()] = content.strip()
    return out


def _unescape(value: str) -> str:
    import html as html_mod

    return html_mod.unescape(value)


class PressProvider(StockProvider):
    """Страница статьи как источник материала. ``query`` — её адрес."""

    license_name = "editorial-quote"
    license_per_item = True
    kind_support = ("photo",)

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="press")

    def _fetch(self, url: str) -> str:
        import requests

        def _call() -> str:
            resp = requests.get(
                url, timeout=self._timeout(),
                # Без явного User-Agent часть изданий отдаёт заглушку без
                # og-тегов: страница приходит, а кадра на ней нет.
                headers={"User-Agent": "Mozilla/5.0 (compatible; REDSHIFT/1.0)"},
            )
            if resp.status_code >= 400:
                raise ProviderError(f"страница источника вернула {resp.status_code}",
                                    status=resp.status_code, url=url[:120])
            # Читаем только начало документа: og-теги стоят в <head>, а тело
            # статьи может весить мегабайты.
            return resp.text[:400_000]

        return call_with_retry(_call, **self._retry_kwargs("press page"))

    def search(self, query: str, *, kind: str = "photo",
               limit: int = 1) -> list[StockCandidate]:
        url = str(query or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return []
        page = self._fetch(url)
        meta = meta_map(page)
        images = [
            _unescape(meta[k]) for k in _IMAGE_KEYS if meta.get(k)
        ]
        images.extend(_jsonld_images(page))
        images = _unique_urls([urljoin(url, img) for img in images if img])
        if not images:
            _log.info("на странице нет og:image / json-ld image", extra={"url": url[:120]})
            return []
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        title = next((_unescape(meta[k]) for k in _TITLE_KEYS if meta.get(k)), "")
        site = next((_unescape(meta[k]) for k in _SITE_KEYS if meta.get(k)), domain)
        published = next((meta[k] for k in _TIME_KEYS if meta.get(k)), "")

        self.charge("search", 1, "request", 0.0)
        found: list[StockCandidate] = []
        for image in images[: max(1, int(limit))]:
            digest = hashlib.sha256(image.encode("utf-8")).hexdigest()[:10]
            found.append(StockCandidate(
                id=f"press_{digest}", source="press", kind="photo", query=url,
                download_url=image, page_url=url, preview_url=image,
                license=self.license_name,
                license_confirmed=False,
                attribution=site or domain,
                author=site or domain,
                tags=[t for t in re.split(r"\W+", title.lower()) if len(t) > 3][:10],
                meta={"title": title, "site_name": site, "published": published,
                      "domain": domain},
            ))
        return found

    def wikipedia_candidates(self, title: str, *, limit: int = 2) -> list[StockCandidate]:
        """Официальный кадр статьи в Википедии (REST summary thumbnail)."""
        slug = str(title or "").strip()
        if len(slug) < 3:
            return []
        import requests

        found: list[StockCandidate] = []
        for host in ("en.wikipedia.org", "ru.wikipedia.org"):
            if len(found) >= limit:
                break
            api = f"https://{host}/api/rest_v1/page/summary/{quote(slug, safe='')}"

            def _call(url: str = api) -> dict[str, Any]:
                resp = requests.get(
                    url, timeout=self._timeout(),
                    headers={"User-Agent": "Mozilla/5.0 (compatible; REDSHIFT/1.0)"},
                )
                if resp.status_code >= 400:
                    return {}
                try:
                    data = resp.json()
                except ValueError:
                    return {}
                return data if isinstance(data, dict) else {}

            try:
                data = call_with_retry(_call, **self._retry_kwargs("wikipedia summary"))
            except Exception:  # noqa: BLE001 — вики не роняет отбор стока
                continue
            image = str((data.get("originalimage") or {}).get("source")
                        or (data.get("thumbnail") or {}).get("source") or "")
            page = str(data.get("content_urls", {}).get("desktop", {}).get("page")
                       or f"https://{host}/wiki/{quote(slug)}")
            if not image:
                continue
            digest = hashlib.sha256(image.encode("utf-8")).hexdigest()[:10]
            found.append(StockCandidate(
                id=f"press_{digest}", source="press", kind="photo", query=page,
                download_url=image, page_url=page, preview_url=image,
                license=self.license_name, license_confirmed=False,
                attribution="Wikipedia", author="Wikipedia",
                tags=[t for t in re.split(r"\W+", slug.lower()) if len(t) > 3][:10],
                meta={"title": data.get("title") or slug, "site_name": "Wikipedia",
                      "published": "", "domain": host.removeprefix("www.")},
            ))
        if found:
            self.charge("search", 1, "request", 0.0)
        return found[:limit]

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        return self._http_download(candidate.download_url, dst)


def build_press_provider(cfg, costs, *, sources: dict[str, Any]) -> StockProvider | None:
    """Провайдер статьи — или ``None``, если источник выключен или режим mock.

    Отдельной сборкой, а не внутри ``build_stock_providers``: этот источник
    ищет не по запросу, а по адресу, и в общую очередь стоков не встаёт.
    """
    spec = (sources.get("sources") or {}).get("press") or {}
    if not spec.get("enabled"):
        return None
    if str(cfg.get("providers.mode", "auto")).lower() == "mock":
        # Mock не ходит в сеть, но путь обязан работать целиком: без него ветка
        # «кадр из статьи» проверялась бы только живым прогоном за деньги.
        from .stock import MockStock

        return MockStock(cfg, costs, name="press")
    return PressProvider(cfg, costs)

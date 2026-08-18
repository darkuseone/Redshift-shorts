"""Стоковые источники B-roll (§7.2, §10.4).

Live-провайдеры: Pexels, Pixabay, NASA Images, Internet Archive, Mixkit.
Каждый возвращает кандидатов с **лицензией**: §7.2.7 требует проверять лицензию
до скачивания, а для Internet Archive — попозиционно (§10.4, R-10), потому что
там у каждого объекта своя.

Mock-провайдер синтезирует настоящие видеофайлы через lavfi-источники ffmpeg —
разной ориентации и длительности. Это не «заглушка ради заглушки»: дальше по
пайплайну работают настоящие probe, кроп 9:16, pHash и Ken Burns, и они должны
работать на реальных файлах, а не на пустышках.
"""

from __future__ import annotations

import colorsys
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ...errors import ProviderError
from ..ffmpeg import probe, run
from ..logging import get_logger
from ..retry import call_with_retry
from .base import Provider, ProviderMode, resolve_mode

_log = get_logger("stock")

MAX_HEIGHT_DEFAULT = 1080          # §3.6.1: строго до 1080p, выше не брать


@dataclass
class StockCandidate:
    """Кандидат до скачивания: решение о лицензии принимается уже здесь."""

    id: str
    source: str
    kind: str                       # video | photo
    query: str
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    download_url: str = ""
    page_url: str = ""
    preview_url: str = ""
    license: str = ""
    license_confirmed: bool = False
    attribution: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        if self.height > self.width * 1.2:
            return "portrait"
        if self.width > self.height * 1.2:
            return "landscape"
        return "square"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "source": self.source, "kind": self.kind, "query": self.query,
            "width": self.width, "height": self.height,
            "duration_sec": round(self.duration_sec, 2),
            "download_url": self.download_url, "page_url": self.page_url,
            "license": self.license, "license_confirmed": self.license_confirmed,
            "attribution": self.attribution, "tags": self.tags, "author": self.author,
            "orientation": self.orientation, "meta": self.meta,
        }


class StockProvider(Provider):
    kind_support: tuple[str, ...] = ("video", "photo")
    license_name: str = ""
    license_per_item: bool = False

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        raise NotImplementedError

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        raise NotImplementedError

    # --- общее ---
    def _max_height(self) -> int:
        return int(self.cfg.get("stock.max_download_height", MAX_HEIGHT_DEFAULT))

    def _http_download(self, url: str, dst: Path) -> Path:
        import requests

        dst.parent.mkdir(parents=True, exist_ok=True)

        def _call() -> Path:
            with requests.get(url, stream=True, timeout=self._timeout()) as resp:
                if resp.status_code >= 400:
                    raise ProviderError(f"{self.name}: скачивание вернуло {resp.status_code}",
                                        status=resp.status_code, url=url[:120])
                with open(dst, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
            return dst

        return call_with_retry(_call, **self._retry_kwargs(f"{self.name} download"))


# --- mock ---------------------------------------------------------------------

# Дешёвые для CPU источники: раннер не должен тратить минуты на генерацию
# тестового материала. Разнообразие даёт цвет и геометрия, а не сложность.
_LAVFI_PATTERNS = (
    "gradients=s={w}x{h}:c0={c0}:c1={c1}:x0={x0}:y0={y0}:speed={speed}:d={d}:type=linear",
    "gradients=s={w}x{h}:c0={c0}:c1={c1}:x0={x0}:y0={y0}:speed={speed}:d={d}:type=radial",
    "cellauto=s={w}x{h}:rate=30:scroll=1:full=0",
    "testsrc2=s={w}x{h}:rate=30",
    "gradients=s={w}x{h}:c0={c1}:c1={c0}:x0={y0}:y0={x0}:speed={speed}:d={d}:type=spiral",
)

_MOCK_SIZES = ((1080, 1920), (1920, 1080), (1080, 1080), (1280, 720), (720, 1280))


class MockStock(StockProvider):
    """Синтетические, но настоящие видеофайлы: детерминированы по запросу."""

    license_name = "mock-synthetic"

    def __init__(self, cfg, costs, name: str = "mock_stock") -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name=name)

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        digest = hashlib.sha256(f"{self.name}|{query}|{kind}".encode()).hexdigest()
        out: list[StockCandidate] = []
        for i in range(limit):
            seed = int(digest[i * 4:i * 4 + 8] or "0", 16)
            width, height = _MOCK_SIZES[seed % len(_MOCK_SIZES)]
            # Слоты не длиннее 5 сек (§3.6.2) — генерировать длинные клипы незачем.
            duration = 2.5 + (seed % 36) / 10.0 if kind == "video" else 0.0
            out.append(StockCandidate(
                id=f"{self.name}_{digest[:8]}_{i:02d}",
                source=self.name, kind=kind, query=query,
                width=width, height=height, duration_sec=duration,
                download_url=f"mock://{self.name}/{digest[:8]}/{i}",
                page_url=f"mock://{self.name}/{digest[:8]}/{i}",
                license=self.license_name, license_confirmed=True,
                attribution="synthetic (mock provider)",
                tags=_tags_from_query(query),
                author="REDSHIFT mock",
                meta={"seed": seed, "mock": True},
            ))
        return out

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        seed = int(candidate.meta.get("seed", 0))
        width = min(candidate.width, 1920)
        height = min(candidate.height, 1920)
        if max(width, height) > self._max_height() and candidate.kind == "video":
            scale = self._max_height() / max(width, height)
            width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2

        hue = (seed % 360) / 360.0
        c0 = _hex_color(hue, 0.55, 0.85)
        c1 = _hex_color((hue + 0.12) % 1.0, 0.7, 0.35)
        pattern = _LAVFI_PATTERNS[seed % len(_LAVFI_PATTERNS)]
        duration = max(2.0, candidate.duration_sec or 4.0)
        source = pattern.format(w=width, h=height, c0=f"0x{c0}", c1=f"0x{c1}",
                                x0=seed % width, y0=seed % height,
                                speed=0.02 + (seed % 7) / 100.0, d=duration)

        dst.parent.mkdir(parents=True, exist_ok=True)
        if candidate.kind == "photo":
            run(["-y", "-f", "lavfi", "-i", source, "-frames:v", "1", str(dst)],
                what="mock photo")
        else:
            run(["-y", "-f", "lavfi", "-i", source, "-t", f"{duration:.2f}",
                 "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
                 "-g", "30", "-pix_fmt", "yuv420p", str(dst)], what="mock video")
        self.charge("download", 1, "item", 0.0)
        return dst


def _hex_color(hue: float, saturation: float, value: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _tags_from_query(query: str) -> list[str]:
    return [w.lower() for w in query.replace(",", " ").split() if len(w) > 2][:8]


# --- Pexels -------------------------------------------------------------------

class PexelsStock(StockProvider):
    license_name = "Pexels License"

    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="pexels")
        self.api_key = api_key

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        import requests

        base = "https://api.pexels.com"
        url = f"{base}/videos/search" if kind == "video" else f"{base}/v1/search"
        params = {"query": query, "per_page": limit, "orientation": "portrait"}
        headers = {"Authorization": self.api_key}

        def _call() -> dict[str, Any]:
            resp = requests.get(url, params=params, headers=headers, timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Pexels вернул {resp.status_code}", status=resp.status_code)
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Pexels search"))
        out: list[StockCandidate] = []
        max_h = self._max_height()

        if kind == "video":
            for item in data.get("videos", []):
                files = [f for f in item.get("video_files", [])
                         if f.get("height") and int(f["height"]) <= max_h]
                if not files:
                    continue
                best = max(files, key=lambda f: int(f.get("height") or 0))
                out.append(StockCandidate(
                    id=f"pexels_v{item['id']}", source="pexels", kind="video", query=query,
                    width=int(best.get("width") or 0), height=int(best.get("height") or 0),
                    duration_sec=float(item.get("duration") or 0),
                    download_url=best.get("link", ""), page_url=item.get("url", ""),
                    preview_url=item.get("image", ""),
                    license=self.license_name, license_confirmed=True,
                    attribution=f"Pexels / {item.get('user', {}).get('name', '')}",
                    author=item.get("user", {}).get("name", ""),
                    tags=_tags_from_query(query),
                    meta={"pexels_id": item.get("id")},
                ))
        else:
            for item in data.get("photos", []):
                src = item.get("src", {})
                out.append(StockCandidate(
                    id=f"pexels_p{item['id']}", source="pexels", kind="photo", query=query,
                    width=int(item.get("width") or 0), height=int(item.get("height") or 0),
                    download_url=src.get("large2x") or src.get("large") or src.get("original", ""),
                    page_url=item.get("url", ""), preview_url=src.get("medium", ""),
                    license=self.license_name, license_confirmed=True,
                    attribution=f"Pexels / {item.get('photographer', '')}",
                    author=item.get("photographer", ""),
                    tags=_tags_from_query(f"{query} {item.get('alt', '')}"),
                ))
        self.charge("search", 1, "request", 0.0)
        return out

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        return self._http_download(candidate.download_url, dst)


# --- Pixabay ------------------------------------------------------------------

class PixabayStock(StockProvider):
    license_name = "Pixabay Content License"

    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="pixabay")
        self.api_key = api_key

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        import requests

        url = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
        params = {"key": self.api_key, "q": query, "per_page": max(3, limit), "safesearch": "true"}

        def _call() -> dict[str, Any]:
            resp = requests.get(url, params=params, timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Pixabay вернул {resp.status_code}", status=resp.status_code)
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Pixabay search"))
        max_h = self._max_height()
        out: list[StockCandidate] = []
        for item in data.get("hits", []):
            if kind == "video":
                variants = [v for v in (item.get("videos") or {}).values()
                            if v.get("height") and int(v["height"]) <= max_h]
                if not variants:
                    continue
                best = max(variants, key=lambda v: int(v.get("height") or 0))
                out.append(StockCandidate(
                    id=f"pixabay_v{item['id']}", source="pixabay", kind="video", query=query,
                    width=int(best.get("width") or 0), height=int(best.get("height") or 0),
                    duration_sec=float(item.get("duration") or 0),
                    download_url=best.get("url", ""), page_url=item.get("pageURL", ""),
                    license=self.license_name, license_confirmed=True,
                    attribution=f"Pixabay / {item.get('user', '')}",
                    author=item.get("user", ""),
                    tags=[t.strip() for t in str(item.get("tags", "")).split(",") if t.strip()],
                ))
            else:
                out.append(StockCandidate(
                    id=f"pixabay_p{item['id']}", source="pixabay", kind="photo", query=query,
                    width=int(item.get("imageWidth") or 0), height=int(item.get("imageHeight") or 0),
                    download_url=item.get("largeImageURL", ""), page_url=item.get("pageURL", ""),
                    license=self.license_name, license_confirmed=True,
                    attribution=f"Pixabay / {item.get('user', '')}",
                    author=item.get("user", ""),
                    tags=[t.strip() for t in str(item.get("tags", "")).split(",") if t.strip()],
                ))
        self.charge("search", 1, "request", 0.0)
        return out

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        return self._http_download(candidate.download_url, dst)


# --- NASA ---------------------------------------------------------------------

class NasaStock(StockProvider):
    license_name = "NASA public domain (проверять попозиционно)"
    license_per_item = True

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="nasa")

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        import requests

        params = {"q": query, "media_type": "video" if kind == "video" else "image"}

        def _call() -> dict[str, Any]:
            resp = requests.get("https://images-api.nasa.gov/search", params=params,
                                timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"NASA вернул {resp.status_code}", status=resp.status_code)
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("NASA search"))
        out: list[StockCandidate] = []
        for item in (data.get("collection", {}).get("items", []) or [])[:limit]:
            meta = (item.get("data") or [{}])[0]
            nasa_id = meta.get("nasa_id", "")
            if not nasa_id:
                continue
            # §10.4: часть материалов NASA — чужие; берём только с явным PD/CC.
            rights = str(meta.get("rights", "")).lower()
            confirmed = "public domain" in rights or not rights
            out.append(StockCandidate(
                id=f"nasa_{nasa_id}", source="nasa", kind=kind, query=query,
                download_url=item.get("href", ""),
                page_url=f"https://images.nasa.gov/details-{nasa_id}",
                preview_url=(item.get("links") or [{}])[0].get("href", ""),
                license="public-domain" if confirmed else f"rights: {meta.get('rights', '')}",
                license_confirmed=confirmed,
                attribution=f"NASA / {meta.get('center', '')}",
                tags=[str(k) for k in (meta.get("keywords") or [])][:10],
                meta={"nasa_id": nasa_id, "collection_href": item.get("href", "")},
            ))
        self.charge("search", 1, "request", 0.0)
        return out

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        import requests

        # href кандидата — это collection.json со списком файлов.
        collection = candidate.meta.get("collection_href") or candidate.download_url
        resp = requests.get(collection, timeout=self._timeout())
        if resp.status_code >= 400:
            raise ProviderError(f"NASA collection вернул {resp.status_code}",
                                status=resp.status_code)
        urls = [u for u in resp.json() if isinstance(u, str)]
        prefer = [u for u in urls if u.endswith(("~orig.mp4", "~large.mp4", ".mp4"))] or urls
        # §3.6.1: выше 1080p не берём даже при наличии.
        ranked = sorted(prefer, key=lambda u: ("4k" in u.lower(), "orig" in u.lower()))
        if not ranked:
            raise ProviderError("NASA: в коллекции нет пригодных файлов", id=candidate.id)
        return self._http_download(ranked[0], dst)


# --- Internet Archive ---------------------------------------------------------

class InternetArchiveStock(StockProvider):
    license_name = "varies (per item)"
    license_per_item = True

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="internet_archive")

    def search(self, query: str, *, kind: str = "video", limit: int = 8) -> list[StockCandidate]:
        import requests

        params = {
            "q": f'{query} AND mediatype:(movies)',
            "fl[]": ["identifier", "title", "licenseurl", "rights", "year"],
            "rows": limit, "page": 1, "output": "json",
        }

        def _call() -> dict[str, Any]:
            resp = requests.get("https://archive.org/advancedsearch.php", params=params,
                                timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Internet Archive вернул {resp.status_code}",
                                    status=resp.status_code)
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Internet Archive search"))
        out: list[StockCandidate] = []
        for doc in (data.get("response", {}).get("docs", []) or []):
            license_url = doc.get("licenseurl") or ""
            # R-10: лицензия проверяется попозиционно; без явной лицензии — мимо.
            confirmed = bool(license_url) and any(
                marker in license_url for marker in
                ("publicdomain", "creativecommons.org/licenses/by", "cc0", "mark/1.0"))
            out.append(StockCandidate(
                id=f"ia_{doc['identifier']}", source="internet_archive", kind=kind, query=query,
                page_url=f"https://archive.org/details/{doc['identifier']}",
                license=license_url or f"rights: {doc.get('rights', 'не указана')}",
                license_confirmed=confirmed,
                attribution=f"Internet Archive / {doc.get('title', '')}",
                tags=_tags_from_query(query),
                meta={"identifier": doc["identifier"], "year": doc.get("year")},
            ))
        self.charge("search", 1, "request", 0.0)
        return out

    def download(self, candidate: StockCandidate, dst: Path) -> Path:
        import requests

        identifier = candidate.meta.get("identifier")
        resp = requests.get(f"https://archive.org/metadata/{identifier}", timeout=self._timeout())
        if resp.status_code >= 400:
            raise ProviderError("Internet Archive: метаданные недоступны", id=candidate.id)
        files = resp.json().get("files", [])
        videos = [f for f in files if str(f.get("name", "")).endswith((".mp4", ".m4v"))]
        if not videos:
            raise ProviderError("Internet Archive: нет mp4 в объекте", id=candidate.id)
        smallest = min(videos, key=lambda f: int(f.get("size") or 1 << 40))
        url = f"https://archive.org/download/{identifier}/{smallest['name']}"
        return self._http_download(url, dst)


# --- фабрика ------------------------------------------------------------------

def build_stock_providers(cfg, costs) -> dict[str, StockProvider]:
    """Собрать словарь source → провайдер согласно режиму и наличию ключей."""
    providers: dict[str, StockProvider] = {}

    pexels_key = cfg.secret_for("stock.pexels_api_key_env", purpose="Pexels")
    if resolve_mode(cfg, api_key=pexels_key, service="pexels") is ProviderMode.LIVE:
        providers["pexels"] = PexelsStock(cfg, costs, pexels_key or "")
    else:
        providers["pexels"] = MockStock(cfg, costs, name="pexels")

    pixabay_key = cfg.secret_for("stock.pixabay_api_key_env", purpose="Pixabay")
    if resolve_mode(cfg, api_key=pixabay_key, service="pixabay") is ProviderMode.LIVE:
        providers["pixabay"] = PixabayStock(cfg, costs, pixabay_key or "")
    else:
        providers["pixabay"] = MockStock(cfg, costs, name="pixabay")

    # NASA и Internet Archive работают без ключа, но в mock-режиме их всё равно
    # подменяем: providers.mode=mock означает «ни одного внешнего вызова».
    mode = str(cfg.get("providers.mode", "auto")).lower()
    if mode == "mock":
        providers["nasa"] = MockStock(cfg, costs, name="nasa")
        providers["internet_archive"] = MockStock(cfg, costs, name="internet_archive")
        providers["mixkit"] = MockStock(cfg, costs, name="mixkit")
    else:
        providers["nasa"] = NasaStock(cfg, costs)
        providers["internet_archive"] = InternetArchiveStock(cfg, costs)
        providers["mixkit"] = MockStock(cfg, costs, name="mixkit")
    return providers

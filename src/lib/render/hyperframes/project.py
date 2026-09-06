"""Сборка каталога проекта HyperFrames под один вариант монтажа.

HyperFrames резолвит медиа относительно каталога проекта, а исходники лежат в
``work/<video_id>/``. Файлы не копируются, а линкуются: футажи и аватар весят
десятки мегабайт, и дублировать их на каждый вариант монтажа незачем. Если
файловая система откажет в жёсткой ссылке (иное устройство), падаем на копию.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from ...jsonio import read_json
from ...logging import get_logger
from .brand_css import build_css, copy_fonts
from .composition import CompositionBuilder

_log = get_logger("hyperframes.project")

HYPERFRAMES_JSON = {
    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
    "paths": {"blocks": "compositions", "components": "compositions/components",
              "assets": "assets"},
    # Прокси-транскодирование нужно только живому предпросмотру; в рендере
    # кадры извлекает ffmpeg, и лишний проход по большим футажам ни к чему.
    "media": {"autoProxy": False},
}


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


class HyperFramesProject:
    """Каталог проекта: index.html, стили, шрифты, медиа."""

    def __init__(self, root: Path, cfg) -> None:
        self.root = root
        self.cfg = cfg
        self.assets_dir = root / "assets"

    def prepare(self, plan: dict[str, Any], mix_path: Path,
                blocks: list[dict[str, Any]] | None = None) -> Path:
        """Разложить проект на диске и вернуть путь к index.html."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        assets = self._stage_media(plan)
        mix_name = f"assets/{mix_path.name}"
        _link_or_copy(mix_path, self.assets_dir / mix_path.name)

        fonts_dir = self.cfg.path("paths.assets_dir", "assets") / "fonts"
        fonts = copy_fonts(fonts_dir, self.root / "fonts",
                           read_json(fonts_dir / "fonts_manifest.json"))

        # Статические ассеты шаблонов (маски, логотипы)
        repo_assets = self.cfg.path("paths.assets_dir", "assets")
        if repo_assets.exists():
            for asset_file in repo_assets.glob("*.svg"):
                _link_or_copy(asset_file, self.assets_dir / asset_file.name)
            for asset_file in repo_assets.glob("*.png"):
                _link_or_copy(asset_file, self.assets_dir / asset_file.name)

        brandbook = self.cfg.brandbook
        (self.root / "brand.css").write_text(build_css(brandbook, fonts),
                                             encoding="utf-8")
        self._stage_vendor()

        # Планировщик не кладёт исходные блоки в edit-план, а слово за головой
        # берётся из emphasis_word. Передаём их отдельным полем, чтобы не
        # менять формат плана — он общий для обоих движков.
        enriched = dict(plan)
        enriched["_blocks"] = blocks or []

        builder = CompositionBuilder(enriched, brandbook, assets)
        html_text = builder.build(mix_name)
        index = self.root / "index.html"
        index.write_text(html_text, encoding="utf-8")
        self.stats = builder.stats

        (self.root / "hyperframes.json").write_text(
            json.dumps(HYPERFRAMES_JSON, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

        _log.info("проект HyperFrames собран", extra={
            "dir": str(self.root), "media": len(assets), **builder.stats})
        return index

    def _stage_media(self, plan: dict[str, Any]) -> dict[str, str]:
        """Слинковать все медиа плана внутрь проекта.

        Имя файла внутри проекта делается уникальным по индексу источника:
        разные шоты могут ссылаться на один файл, а дублирующиеся id у
        ``<video>`` дают пустой кадр — продюсер инжектит кадры по id.
        """
        assets: dict[str, str] = {}
        sources: list[str] = []
        for shot in plan.get("shots", []):
            if shot.get("file"):
                sources.append(str(shot["file"]))
            bg_file = shot.get("bg_file")
            if bg_file:
                sources.append(str(bg_file))
            # Материал приёма — отдельный файл шота, и он тоже обязан переехать
            # внутрь. В конвейере это скрывалось: приём берёт кадр у соседнего
            # шота, а тот уже перенесён своей строкой выше. Проба отдаёт приёму
            # файл, которого нет ни у одного шота, — и lint честно ловил
            # `missing_local_asset`.
            hero_file = (shot.get("hero") or {}).get("file")
            if hero_file:
                sources.append(str(hero_file))
        for seg in plan.get("avatar", []):
            if seg.get("file"):
                sources.append(str(seg["file"]))
        # Плита фона — такой же файл проекта, как футаж: она обязана переехать
        # внутрь, иначе разметка сошлётся на путь, которого в проекте нет.
        plate = (plan.get("backdrop") or {}).get("plate")
        if plate:
            sources.append(str(plate))
        # Fullscreen/overlay thumbs (`params.media`) land in <img src="...">.
        # Without staging, HyperFrames lint reports missing_local_asset on the
        # raw work/.../shots/... path (seen on 0042 slam after e3970be).
        for shot in plan.get("shots", []):
            params = shot.get("params") or {}
            for key in ("media", "media_src"):
                if params.get(key):
                    sources.append(str(params[key]))
        for ovl in plan.get("overlays", []):
            params = ovl.get("params") or {}
            for key in ("media", "media_src"):
                if params.get(key):
                    sources.append(str(params[key]))

        for path_text in sources:
            if path_text in assets:
                continue
            src = Path(path_text)
            if not src.exists():
                _log.warning("медиа плана нет на диске", extra={"file": path_text})
                continue
            name = f"m{len(assets):03d}_{src.name}"
            _link_or_copy(src, self.assets_dir / name)
            assets[path_text] = f"assets/{name}"
        return assets

    def _stage_vendor(self) -> None:
        """Локальный GSAP: рендер не должен ходить в CDN."""
        vendor_src = Path(__file__).resolve().parents[4] / "render/hyperframes/vendor"
        vendor_dst = self.root / "vendor"
        vendor_dst.mkdir(parents=True, exist_ok=True)
        gsap = vendor_src / "gsap.min.js"
        if not gsap.exists():
            raise FileNotFoundError(
                f"нет локальной сборки GSAP: {gsap}. "
                "Скачайте gsap.min.js в render/hyperframes/vendor/")
        _link_or_copy(gsap, vendor_dst / "gsap.min.js")

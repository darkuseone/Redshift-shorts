"""Вечнозелёная база: полка материала, с которой берут, а не ищут заново.

Первый засев показал, чем кончается доверие к подписи каталога: в базу легли
три концепта художника вместо чёрной дыры, график с осями вместо вулкана,
самолёт вместо океана (слово «ocean» стояло в описании миссии), полоса 640×113
и четыре плёнки Internet Archive на 200 МБ. Здесь проверяются заслоны, которые
из этого выросли.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from src.lib.config import load_config
from src.lib.footage_seed import (
    ASPECT_RANGE, EVERGREEN, MAX_BYTES, MIN_SHORT_SIDE, NOT_A_PHOTOGRAPH,
    seed_footage,
)
from src.lib.providers.stock import StockCandidate
from src.lib.storage import build_storage, sniff_suffix


class TestTopics:
    def test_every_topic_carries_a_query_a_meaning_and_tags(self):
        """Смысл нужен судье, теги — поиску: без них тема бесполезна.

        Теги совпадают с тем, что P7 достаёт из своих запросов
        (``_tags_for``): латиница, слова от трёх букв, нижний регистр.
        """
        for topic in EVERGREEN:
            assert topic["query"] and topic["intent"], topic["id"]
            assert topic["tags"], topic["id"]
            for tag in topic["tags"]:
                assert tag == tag.lower() and len(tag) >= 3 and tag.isalpha(), \
                    f"{topic['id']}: тег {tag!r} поиск не найдёт"

    def test_topic_ids_are_unique(self):
        ids = [t["id"] for t in EVERGREEN]
        assert len(ids) == len(set(ids))


class TestSeeding:
    """Засев с подставным источником: сеть в тестах не трогается."""

    @pytest.fixture
    def cfg(self, tmp_path):
        cfg = load_config()
        cfg.set("paths.storage_dir", str(tmp_path / "storage"))
        cfg.set("paths.cache_dir", str(tmp_path / "cache"))
        cfg.set("paths.work_dir", str(tmp_path / "work"))
        cfg.set("providers.mode", "mock")
        return cfg

    def _provider(self, monkeypatch, images):
        """Источник, отдающий заданные картинки. images: id → (w, h, подпись)."""
        class _Stub:
            name = "nasa"

            def search(self, query, *, kind="video", limit=8):
                return [StockCandidate(
                    id=asset_id, source="nasa", kind="photo", query=query,
                    download_url=f"https://example/{asset_id}",
                    license="public-domain", license_confirmed=True,
                    attribution="NASA", meta={"title": caption, "description": ""})
                    for asset_id, (_w, _h, caption) in images.items()]

            def download(self, candidate, dst):
                width, height, _caption = images[candidate.id]
                dst.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (width, height), (30, 30, 34)).save(dst, format="PNG")
                return dst

        import src.lib.providers.stock as S
        monkeypatch.setattr(S, "build_stock_providers",
                            lambda cfg, costs: {"nasa": _Stub()})
        return _Stub()

    def test_a_strip_and_a_thumbnail_do_not_enter_the_base(self, cfg, monkeypatch):
        """640×113 в вертикальном кадре можно только растянуть."""
        self._provider(monkeypatch, {
            "strip": (640, 113, "Dunes"),          # полоса
            "thumb": (640, 360, "Dunes"),          # мелко
            "good": (1600, 1200, "Dunes"),         # годится
        })
        report = seed_footage(cfg, storage=build_storage(cfg), per_topic=3,
                              topics=("desert",))
        assert [a["id"] for a in report["added"]] == ["good"]
        assert MIN_SHORT_SIDE >= 900 and ASPECT_RANGE[1] <= 3.0

    def test_an_artists_impression_is_not_real_material(self, cfg, monkeypatch):
        """«Преимущество всегда за реальным материалом» — слова заказчика.

        Концепт художника в кадре читается ровно как AI-генерация, от которой
        мы уходим.
        """
        self._provider(monkeypatch, {
            "art": (1600, 1200, "Artist concept of a black hole"),
            "real": (1600, 1200, "Chandra image of the galactic centre"),
        })
        report = seed_footage(cfg, storage=build_storage(cfg), per_topic=2,
                              topics=("black-hole",))
        assert [a["id"] for a in report["added"]] == ["real"]
        assert "artist" in NOT_A_PHOTOGRAPH

    def test_seeding_twice_downloads_nothing_the_second_time(self, cfg, monkeypatch):
        """База пополняется, а не переписывается: второй запуск обязан молчать."""
        self._provider(monkeypatch, {"one": (1600, 1200, "Dunes")})
        storage = build_storage(cfg)
        first = seed_footage(cfg, storage=storage, per_topic=1, topics=("desert",))
        second = seed_footage(cfg, storage=storage, per_topic=1, topics=("desert",))
        assert len(first["added"]) == 1
        assert second["added"] == []
        assert any("уже в базе" in s["reason"] for s in second["skipped"])

    def test_the_record_points_at_a_file_that_exists(self, cfg, monkeypatch):
        """Запись без файла — промах: индекс говорит «есть», слот уходит пустым.

        Ровно так база и умерла в прошлый раз: 195 записей из 213 без файлов.
        """
        self._provider(monkeypatch, {"one": (1600, 1200, "Dunes")})
        storage = build_storage(cfg)
        seed_footage(cfg, storage=storage, per_topic=1, topics=("desert",))
        index = json.loads((cfg.path("paths.cache_dir", "cache")
                            / "footage_index.json").read_text("utf-8"))
        assert index["items"], "запись не сохранилась"
        for item in index["items"]:
            assert storage.exists(item["file"]), item["file"]
            assert not item.get("mock"), "мок-запись в общей базе"
            assert item["tags"], "без тегов запись не найдётся"

    def test_the_name_comes_from_the_bytes_not_from_the_link(self, cfg, monkeypatch):
        """У NASA ссылка ведёт на collection.json, а приходит по ней JPEG.

        Первый засев сложил три десятка снимков под именем ``.json``.
        """
        self._provider(monkeypatch, {"one": (1600, 1200, "Dunes")})
        storage = build_storage(cfg)
        report = seed_footage(cfg, storage=storage, per_topic=1, topics=("desert",))
        key = report["added"][0]["key"]
        assert key.endswith(".png"), key
        got = cfg.path("paths.work_dir", "work") / "check.bin"
        storage.get(key, got)
        assert sniff_suffix(got) == ".png"

    def test_the_weight_cap_keeps_the_repository_usable(self):
        """База едет в git: плёнка на 50 МБ там не нужна ни одному ролику."""
        assert MAX_BYTES <= 16 * 1024 * 1024

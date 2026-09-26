"""Подложка из открытой библиотеки: выбирается по id и подписывается в описании.

25.09 (0052): заказчик попросил тихий эмбиент без скрипок. Пять записей
Kevin MacLeod (CC BY 4.0) — лицензия требует автора рядом с роликом.
"""

from __future__ import annotations

from src.lib.config import load_config
from src.p10_audio.audio_build import choose_bed
from src.p12_render_qc.render import _metadata


def test_music_mood_can_name_a_bed_by_id():
    cfg = load_config()
    record = choose_bed(cfg, {"video_id": "redshift_t003", "music_mood": "space_harvest_drone"})
    assert record is not None and record.id == "music_space_harvest_drone"


def test_open_library_beds_carry_license_and_attribution():
    from src.lib.manifest import open_library

    lib = open_library(load_config(), "music")
    for bed_id in ("space_new_direction", "space_harvest_drone", "dark_ossuary",
                   "mirage_bells", "galaxy_pulse"):
        item = lib.by_id(f"music_{bed_id}")
        assert item is not None, bed_id
        assert item.license == "cc-by-4.0"
        assert "Kevin MacLeod" in item.extra.get("attribution", "")
        assert item.url_origin.startswith("https://incompetech.com/")
        assert "strings" not in item.tags


def _meta(avatar_segments, music=None):
    plan = {"video_id": "redshift_t003"}
    script = {"meta": {"title": "Т", "topic": "t", "category": "space"}, "sources": []}
    return _metadata(plan, script, {"passed": True}, {"segments": avatar_segments},
                     load_config(), music=music)


def test_cc_by_music_is_credited_in_the_description():
    meta = _meta([], music={"attribution": "«Mirage» — Kevin MacLeod (incompetech.com), CC BY 4.0"})
    assert "Музыка: «Mirage» — Kevin MacLeod" in meta["description"]


def test_no_digital_twin_claim_without_an_avatar():
    meta = _meta([])
    assert "двойник" not in meta["description"]
    assert not any("HeyGen" in r for r in meta["synthetic_content_disclosure"]["reasons"])
    with_avatar = _meta([{"index": 0}])
    assert "двойник" in with_avatar["description"]

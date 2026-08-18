"""Фаза 2 — футажи: P5 монтажный план, запросы, лимиты библиотек, оценка."""

from __future__ import annotations

import json

import pytest

from src.errors import LibraryFrozen
from src.lib.manifest import AssetLibrary, AssetRecord, FootageIndex
from src.lib.query import build_queries, classify_intent
from src.lib.templates import TemplateCatalog
from src.lib.providers.vision import MockVision, _verdict_from_json
from src.p5_replan.replanner import (
    Slot, _avatar_runs, _needs_interstitial, _split_span, close_gaps, compute_stats,
)
from src.p7_broll_search.search import _stage1_reject
from src.p8_broll_judge.judge import _needs_arbitration
from src.lib.providers.stock import StockCandidate


def _slot(index, start, end, kind="footage", block="b1", mode="C", role="develop"):
    return Slot(index=index, start=start, end=end, kind=kind, block_id=block,
                role=role, mode=mode)


# --- P5: жёсткие правила монтажа ---------------------------------------------

def test_split_span_respects_max_length():
    parts = _split_span(0.0, 12.0, target=2.6, min_len=1.5, max_len=5.0, words=[])
    assert all(end - start <= 5.0 + 1e-6 for start, end in parts)
    assert parts[0][0] == 0.0 and parts[-1][1] == 12.0


def test_split_span_respects_min_length():
    parts = _split_span(0.0, 6.4, target=2.6, min_len=1.5, max_len=5.0, words=[])
    assert all(end - start >= 1.5 - 1e-6 for start, end in parts)


def test_split_span_short_span_untouched():
    assert _split_span(1.0, 4.0, target=2.6, min_len=1.5, max_len=5.0, words=[]) == [(1.0, 4.0)]


def test_interstitial_required_between_blocks():
    """§7.4.3 — стык двух генераций аватара даёт «прыжок» головы."""
    a = _slot(0, 0, 3, kind="avatar", block="b1")
    b = _slot(1, 3, 6, kind="avatar", block="b2")
    assert _needs_interstitial(a, b)


def test_interstitial_not_required_between_splits_of_one_block():
    """Внутри блока аватар — одно непрерывное видео, стыка нет."""
    a = _slot(0, 0, 3, kind="split", block="b3")
    b = _slot(1, 3, 6, kind="split", block="b3")
    assert not _needs_interstitial(a, b)


def test_interstitial_required_between_full_frame_of_one_block():
    a = _slot(0, 0, 3, kind="avatar", block="b5")
    b = _slot(1, 3, 6, kind="avatar", block="b5")
    assert _needs_interstitial(a, b)


def test_close_gaps_makes_strict_partition():
    slots = [_slot(0, 0.5, 2.0), _slot(1, 2.4, 5.0), _slot(2, 5.0, 7.5)]
    slots = close_gaps(slots, 8.0)
    assert slots[0].start == 0.0
    assert slots[-1].end == 8.0
    for prev, nxt in zip(slots, slots[1:]):
        assert prev.end == nxt.start


def test_avatar_runs_merge_contiguous():
    slots = [_slot(0, 0, 2, kind="footage"), _slot(1, 2, 5, kind="split", block="b3"),
             _slot(2, 5, 8, kind="split", block="b3"), _slot(3, 8, 10, kind="footage")]
    runs = _avatar_runs(slots)
    assert runs == [[1, 2]]


def test_compute_stats_counts_appearance_not_slots():
    slots = [_slot(0, 0, 2, kind="footage"), _slot(1, 2, 5, kind="split", block="b3"),
             _slot(2, 5, 8, kind="split", block="b3"), _slot(3, 8, 10, kind="footage")]
    for slot in slots:
        slot.events = [{"t": slot.start, "kind": "shot_change"}]
    stats = compute_stats(slots, 10.0)
    assert stats["avatar_appearances"] == 1
    assert stats["avatar_appearance_durations"] == [6.0]


def test_cut_plan_of_sample_run_satisfies_hard_rules(repo_root):
    """Интеграционная проверка §11.1 по реальному прогону, если он есть."""
    path = repo_root / "work" / "redshift_0042" / "cut_plan.json"
    if not path.exists():
        pytest.skip("нет прогона: запустите python -m src.cli run --script scripts/redshift_0042.json")
    stats = json.loads(path.read_text(encoding="utf-8"))["stats"]
    assert 0.35 <= stats["avatar_share"] <= 0.60
    assert 2 <= stats["avatar_appearances"] <= 5
    assert all(3.0 <= d <= 12.0 for d in stats["avatar_appearance_durations"])
    assert stats["max_shot_sec"] <= 5.0 + 1e-6
    assert stats["max_event_gap_sec"] <= 2.5 + 1e-3
    assert stats["first_event_sec"] <= 0.8
    assert stats["split_share"] <= 0.25 + 1e-3
    assert stats["longest_footage_block_share"] <= 0.40 + 1e-3
    assert stats["cut_share"] >= 0.70


# --- запросы (§7.2) -----------------------------------------------------------

def test_queries_are_english_and_varied():
    slot = {"queries": ["quantum processor macro"], "visual_intent": "квантовый чип в криостате",
            "role": "hook", "block_id": "b1"}
    plan = {"blocks": [{"id": "b1", "text": "Это квантовый чип с кубитами."}]}
    queries = build_queries(slot, plan, count=4)
    assert len(queries) >= 3
    assert all(q.isascii() for q in queries), queries
    assert len(set(queries)) == len(queries)


def test_russian_queries_are_not_translated_literally():
    slot = {"queries": ["квантовый процессор крупным планом"], "visual_intent": "",
            "role": "setup", "block_id": "b1"}
    plan = {"blocks": [{"id": "b1", "text": "Квантовый чип."}]}
    queries = build_queries(slot, plan, count=4)
    assert all(q.isascii() for q in queries)
    assert any("quantum" in q for q in queries)


@pytest.mark.parametrize("intent,expected", [
    ("deep space stars nebula", "space"),
    ("research laboratory microscope", "lab"),
    ("server room racks", "servers"),
    ("city street crowd", "city"),
])
def test_classify_intent(intent, expected):
    assert classify_intent(intent, [], "") == expected


# --- шаг 1: дешёвая отбраковка (§7.3) ----------------------------------------

def _cand(**kwargs):
    base = dict(id="x", source="pexels", kind="video", query="q", width=1080, height=1920,
                duration_sec=5.0, license="Pexels License", license_confirmed=True)
    base.update(kwargs)
    return StockCandidate(**base)


def test_stage1_rejects_unconfirmed_license(cfg):
    assert _stage1_reject(_cand(license_confirmed=False), cfg, 3.0)


def test_stage1_rejects_above_1080p(cfg):
    assert "1080" in (_stage1_reject(_cand(width=3840, height=2160), cfg, 3.0) or "")


def test_stage1_rejects_too_short(cfg):
    assert _stage1_reject(_cand(duration_sec=0.4), cfg, 3.0)


def test_stage1_rejects_ultrawide(cfg):
    assert _stage1_reject(_cand(width=3000, height=1000), cfg, 3.0)


def test_stage1_rejects_watermark_markers(cfg):
    assert _stage1_reject(_cand(tags=["watermark", "preview"]), cfg, 3.0)


def test_stage1_accepts_good_candidate(cfg):
    assert _stage1_reject(_cand(), cfg, 3.0) is None


# --- шаг 3: триггеры арбитража (§7.3) ----------------------------------------

def _verdict(score, disagreement=0.0):
    from src.lib.providers.vision import VisionVerdict

    scores = [score, score + disagreement]
    return VisionVerdict(score=score, reason="", per_frame_scores=scores)


def test_arbitration_triggered_in_borderline_zone(cfg):
    assert _needs_arbitration(_verdict(0.55), "develop", cfg)


def test_arbitration_triggered_on_frame_disagreement(cfg):
    assert _needs_arbitration(_verdict(0.85, disagreement=0.4), "develop", cfg)


def test_arbitration_triggered_for_evidence_role(cfg):
    assert _needs_arbitration(_verdict(0.9), "evidence", cfg)


def test_arbitration_not_triggered_for_clear_accept(cfg):
    assert _needs_arbitration(_verdict(0.92), "develop", cfg) is None


def test_arbiter_budget_respected_in_run(repo_root):
    path = repo_root / "work" / "redshift_0042" / "accepted_assets.json"
    if not path.exists():
        pytest.skip("нет прогона")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["arbiter_calls"] <= doc["arbiter_budget"]


# --- vision --------------------------------------------------------------------

def test_mock_vision_is_deterministic(cfg, tmp_path):
    from PIL import Image

    frame = tmp_path / "f.jpg"
    Image.new("RGB", (320, 568), (40, 80, 160)).save(frame)
    judge = MockVision(cfg=cfg, costs=None)
    a = judge.judge([frame], intent="lab", role="develop", query="laboratory")
    b = judge.judge([frame], intent="lab", role="develop", query="laboratory")
    assert a.score == b.score
    assert 0.0 <= a.score <= 1.0


def test_vision_json_parsing_clamps_values():
    verdict = _verdict_from_json(
        '{"score": 1.7, "reason": "ok", "summary": "s", "quality": -3}',
        judge="gemini", frames=3)
    assert verdict.score == 1.0
    assert verdict.quality == 0.0


def test_vision_json_parsing_rejects_garbage():
    from src.errors import ProviderError

    with pytest.raises(ProviderError):
        _verdict_from_json("совсем не json", judge="gemini", frames=1)


# --- библиотеки и индекс (§14) ------------------------------------------------

def test_library_freezes_at_limit(tmp_path):
    lib = AssetLibrary("sfx", tmp_path / "sfx", max_items=2, frozen_when_full=True)
    lib.add(AssetRecord(id="a", type="sfx", source="elevenlabs", role="pop"))
    lib.add(AssetRecord(id="b", type="sfx", source="elevenlabs", role="hit_impact"))
    assert lib.is_full and lib.frozen
    with pytest.raises(LibraryFrozen):
        lib.add(AssetRecord(id="c", type="sfx", source="elevenlabs", role="tick"))


def test_library_roundtrip_and_usage(tmp_path):
    lib = AssetLibrary("memes", tmp_path / "memes", max_items=10)
    lib.add(AssetRecord(id="m1", type="meme", source="local", emotion="ирония",
                        tags=["ирония", "абсурд"]))
    lib.mark_used("m1", "redshift_0001")
    lib.save()

    again = AssetLibrary("memes", tmp_path / "memes", max_items=10)
    assert again.count == 1
    assert again.by_id("m1").used_in == ["redshift_0001"]
    assert again.find_by_tags(["ирония"])


def test_library_cooldown_excludes_recent(tmp_path):
    lib = AssetLibrary("memes", tmp_path / "memes", max_items=10)
    lib.add(AssetRecord(id="m1", type="meme", source="local", tags=["ирония"],
                        used_in=["v9", "v10"]))
    assert lib.find_by_tags(["ирония"]) != []
    assert lib.find_by_tags(["ирония"], exclude_recent=["v10"], cooldown=2) == []


def test_footage_index_dedup_and_search(tmp_path):
    index = FootageIndex(tmp_path / "footage_index.json")
    index.add(AssetRecord(id="f1", type="video", source="pexels", tags=["lab", "blue"],
                          phashes=["0" * 16, "0" * 16, "0" * 16], score=0.8))
    index.save()

    assert index.find_duplicate(["0" * 16, "0" * 16, "0" * 16]) is not None
    assert index.find_duplicate(["f" * 16, "f" * 16, "f" * 16]) is None
    assert [r.id for r in index.search(["lab"])] == ["f1"]
    assert index.search(["totally-unrelated"]) == []


def test_footage_index_penalizes_recent_videos(tmp_path):
    index = FootageIndex(tmp_path / "footage_index.json")
    index.add(AssetRecord(id="old", type="video", source="pexels", tags=["lab"],
                          score=0.9, used_in=["v1"]))
    index.add(AssetRecord(id="fresh", type="video", source="pexels", tags=["lab"],
                          score=0.7))
    ordered = [r.id for r in index.search(["lab"], exclude_videos=["v1"])]
    assert ordered[0] == "fresh"


# --- регрессии, найденные прогоном трёх роликов подряд ------------------------

def test_index_excludes_material_from_recent_videos(tmp_path):
    """§14.4: материал из последних 5 роликов не переиспользуется при наличии
    альтернативы. Мягкий штраф вместо исключения приводил к тому, что второй
    ролик набирался из первого и валил QC-6 (пересечение ≤20 %)."""
    index = FootageIndex(tmp_path / "footage_index.json")
    index.add(AssetRecord(id="used", type="video", source="pexels", tags=["lab"],
                          score=0.95, used_in=["v1"], file="pexels/used.mp4"))
    index.add(AssetRecord(id="fresh", type="video", source="pexels", tags=["lab"],
                          score=0.6, file="pexels/fresh.mp4"))

    found = [r.id for r in index.search(["lab"], exclude_videos=["v1"])]
    assert found == ["fresh"], "материал из недавнего ролика обязан быть исключён"


def test_index_allows_recent_when_cache_frozen(tmp_path):
    """При замороженном кэше внешних источников нет — альтернативы тоже нет."""
    index = FootageIndex(tmp_path / "footage_index.json")
    index.add(AssetRecord(id="used", type="video", source="pexels", tags=["lab"],
                          score=0.95, used_in=["v1"], file="pexels/used.mp4"))
    found = [r.id for r in index.search(["lab"], exclude_videos=["v1"], allow_recent=True)]
    assert found == ["used"]


def test_ab_difference_is_forced_when_variants_converge(cfg):
    """§15.12.2 — различие версий обеспечивается конструктивно, а не удачей сида."""
    from src.p11_assemble.assemble import _force_ab_difference

    catalog = TemplateCatalog.load(cfg)
    shared = ["kenburns/pan-left", "kenburns/pan-right", "transitions/glitch-short"]
    plans = {
        "A": {"templates_used": list(shared), "shots": []},
        "B": {
            "templates_used": list(shared),
            "shots": [
                {"index": 0, "duration": 3.0,
                 "kenburns": {"template": "kenburns/pan-left"}, "transition": None},
                {"index": 1, "duration": 3.0,
                 "kenburns": {"template": "kenburns/pan-right"}, "transition": None},
                {"index": 2, "duration": 3.0, "kenburns": None,
                 "transition": {"template": "transitions/glitch-short", "duration": 0.24}},
            ],
        },
    }

    class _Ctx:
        def warn(self, *a, **k):
            pass

    diff = _force_ab_difference(plans, ["A", "B"], catalog, 3, _Ctx())
    assert diff >= 3
    assert plans["B"]["templates_used"] != shared
    # Замены остались внутри своих категорий: Ken Burns не превратился в переход.
    for shot in plans["B"]["shots"]:
        if shot.get("kenburns"):
            assert shot["kenburns"]["template"].startswith("kenburns/")
        if shot.get("transition"):
            assert shot["transition"]["template"].startswith("transitions/")


def test_generated_clips_are_visually_distinct(cfg, tmp_path):
    """QC-5 запрещает дубли в ролике, а абстрактный сгенерированный B-roll
    легко получается похожим сам на себя: разные промпты обязаны давать
    визуально разный кадр."""
    from src.lib.ffmpeg import extract_frames
    from src.lib.phash import hamming, phash_image
    from src.lib.providers.generation import build_generation_provider

    provider = build_generation_provider(cfg, None)
    prompts = ["quantum processor macro. Role: hook",
               "abstract data particles. Role: develop",
               "white dwarf star. Role: twist"]
    hashes = []
    for i, prompt in enumerate(prompts):
        asset = provider.generate(prompt, tmp_path / f"g{i}.mp4", kind="video",
                                  duration_sec=2.0)
        frame = extract_frames(asset.path, tmp_path / f"f{i}", [0.5])
        hashes.append(phash_image(frame[0]))

    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            distance = hamming(hashes[i], hashes[j])
            assert distance > 8, f"промпты {i} и {j} дали дубль (hamming={distance})"


def test_p9_dedup_helper_finds_duplicate():
    from src.p9_generate.generate import _find_duplicate

    pool = [("existing", ["0" * 16, "0" * 16, "0" * 16])]
    assert _find_duplicate(["0" * 16, "0" * 16, "0" * 16], pool, 8) == "existing"
    assert _find_duplicate(["f" * 16, "f" * 16, "f" * 16], pool, 8) is None

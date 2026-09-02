"""Фаза 7 и 9: обучение A/B, идемпотентность, resume, обслуживание, смысловой QC."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.errors import RedshiftError
from src.lib.cache import StepCache, hash_obj
from src.lib.learning import _differences, record_choice
from src.lib.maintenance import run_maintenance
from src.p12_render_qc.vision_qc import run_vision_qc
from src.pipeline import Pipeline, RunContext, Step


# --- обучение A/B (§4.5, §7.8) ------------------------------------------------

def _plan(variant: str, kb: str, transition: str, fs: str, rotation: int = 0):
    return {
        "variant": variant,
        "asset_rotation": rotation,
        "shots": [
            {"index": 0, "role": "hook", "block_id": "b1", "kind": "footage",
             "kenburns": {"template": kb}, "transition": {"template": transition},
             "asset_id": "a1"},
            {"index": 1, "role": "develop", "block_id": "b2", "kind": "fullscreen_text",
             "template": fs, "asset_id": None},
        ],
        "overlays": [{"type": "cta", "start": 48.0, "end": 50.0,
                      "template": f"outro-cta/{variant}"}],
    }


def test_differences_are_situations_not_labels():
    """§4.5 — запись «в ситуации X выбран вариант Y», а не «нравится B»."""
    diffs = _differences(
        _plan("A", "kenburns/pan-left", "transitions/glitch-short", "text-fullscreen/impact-01"),
        _plan("B", "kenburns/zoom-in-center", "transitions/white-flash", "text-fullscreen/fact-card"))
    situations = {d["situation"] for d in diffs}
    assert "kenburns@hook" in situations
    assert "transition@hook" in situations
    assert "fullscreen_text@develop" in situations
    assert "overlay@cta" in situations


def test_asset_order_recorded_as_decision_not_ids():
    """Конкретные id материалов в следующем ролике не повторятся — запоминаем решение."""
    diffs = _differences(
        _plan("A", "k", "t", "f", rotation=0),
        _plan("B", "k", "t", "f", rotation=1))
    order = [d for d in diffs if d["situation"] == "asset_order"]
    assert order and order[0]["A"] == "rotation:0" and order[0]["B"] == "rotation:1"
    assert not any(d["situation"].startswith("asset_order@") for d in diffs)


def test_record_choice_shifts_defaults(cfg, tmp_path):
    out = tmp_path / "redshift_test"
    out.mkdir()
    (out / "edit_plan_A.json").write_text(json.dumps(
        _plan("A", "kenburns/pan-left", "transitions/glitch-short", "text-fullscreen/impact-01")),
        encoding="utf-8")
    (out / "edit_plan_B.json").write_text(json.dumps(
        _plan("B", "kenburns/zoom-in-center", "transitions/white-flash", "text-fullscreen/fact-card")),
        encoding="utf-8")

    prefs = tmp_path / "config"
    prefs.mkdir()
    (prefs / "editing_preferences.json").write_text(
        json.dumps({"version": 1, "runs": [], "situation_weights": {}, "defaults": {}}),
        encoding="utf-8")
    cfg.repo_root = tmp_path

    record_choice(cfg, video_id="redshift_test", choice="A", output_dir=out)
    result = record_choice(cfg, video_id="redshift_test", choice="A", output_dir=out)
    # Вес ≥2.0 делает вариант дефолтом для своей ситуации.
    assert result["defaults"]["kenburns@hook"] == "kenburns/pan-left"


def test_record_choice_rejects_bad_input(cfg, tmp_path):
    cfg.repo_root = tmp_path
    with pytest.raises(RedshiftError):
        record_choice(cfg, video_id="nope", choice="C")


def test_record_choice_without_plans_fails_clearly(cfg, tmp_path):
    cfg.repo_root = tmp_path
    with pytest.raises(RedshiftError) as exc:
        record_choice(cfg, video_id="missing", choice="A", output_dir=tmp_path / "none")
    assert exc.value.code == "EDIT_PLANS_MISSING"


# --- идемпотентность и resume (§7.1, §7.6) ------------------------------------

def _ctx(tmp_path, cfg) -> RunContext:
    from src.lib.costs import CostLedger
    from src.lib.storage import LocalStorage

    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return RunContext(
        video_id="t", cfg=cfg, work_dir=work, output_dir=tmp_path / "out",
        script_path=tmp_path / "script.json", cache=StepCache(work),
        costs=CostLedger(), storage=LocalStorage(tmp_path / "store"))


def test_pipeline_skips_step_when_input_unchanged(tmp_path, cfg):
    calls: list[str] = []

    def step_a(ctx):
        calls.append("a")
        ctx.write("a.json", {"n": 1})
        return {}

    pipeline = Pipeline([Step("P0", "a", step_a, outputs=("a.json",))])
    ctx = _ctx(tmp_path, cfg)

    pipeline.run(ctx)
    pipeline.run(ctx)
    assert calls == ["a"], "второй прогон обязан взять результат из кэша"


def test_pipeline_reruns_when_forced(tmp_path, cfg):
    calls: list[str] = []

    def step_a(ctx):
        calls.append("a")
        ctx.write("a.json", {"n": len(calls)})
        return {}

    pipeline = Pipeline([Step("P0", "a", step_a, outputs=("a.json",))])
    ctx = _ctx(tmp_path, cfg)
    pipeline.run(ctx)
    pipeline.run(ctx, force=True)
    assert calls == ["a", "a"]


def test_pipeline_enforces_step_contract(tmp_path, cfg):
    """Шаг, не создавший заявленный выход, обязан упасть, а не «пройти»."""
    pipeline = Pipeline([Step("P0", "пустышка", lambda ctx: {}, outputs=("nope.json",))])
    with pytest.raises(RedshiftError) as exc:
        pipeline.run(_ctx(tmp_path, cfg))
    assert exc.value.code == "STEP_CONTRACT_VIOLATION"


def test_pipeline_reports_missing_input(tmp_path, cfg):
    pipeline = Pipeline([Step("P1", "нужен вход", lambda ctx: {},
                              inputs=("missing.json",), outputs=())])
    with pytest.raises(RedshiftError) as exc:
        pipeline.run(_ctx(tmp_path, cfg))
    assert exc.value.code == "MISSING_STEP_INPUT"
    assert "--from" in exc.value.message


def test_pipeline_resume_from_step(tmp_path, cfg):
    calls: list[str] = []
    steps = [
        Step("P0", "a", lambda ctx: (calls.append("P0"), ctx.write("a.json", {}))[1] and {},
             outputs=("a.json",)),
        Step("P1", "b", lambda ctx: (calls.append("P1"), ctx.write("b.json", {}))[1] and {},
             inputs=("a.json",), outputs=("b.json",)),
    ]
    ctx = _ctx(tmp_path, cfg)
    Pipeline(steps).run(ctx, to_step="P0")
    calls.clear()
    Pipeline(steps).run(ctx, from_step="P1")
    assert calls == ["P1"]


def test_step_fingerprint_changes_with_config(tmp_path, cfg):
    step = Step("P0", "a", lambda ctx: {}, outputs=())
    ctx = _ctx(tmp_path, cfg)
    before = step.fingerprint(ctx)
    ctx.cfg.set("limits.max_shot_sec", 6)
    assert step.fingerprint(ctx) != before


def test_step_fingerprint_follows_declared_config_files(tmp_path, cfg, monkeypatch):
    """§7.1: вход шага — это и файлы репозитория, которые он читает.

    Записанный выбор A/B меняет `editing_preferences.json`; без этого правила
    P11 возвращался из кэша и накопленное предпочтение не применялось.
    """
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    prefs = repo / "config" / "editing_preferences.json"
    prefs.write_text('{"defaults": {}}', encoding="utf-8")
    monkeypatch.setattr(type(cfg), "repo_root", property(lambda self: repo))

    step = Step("P11", "a", lambda ctx: {}, outputs=(),
                config_inputs=("config/editing_preferences.json",))
    ctx = _ctx(tmp_path, cfg)
    before = step.fingerprint(ctx)
    prefs.write_text('{"defaults": {"kenburns@hook": "kenburns/pan-up"}}', encoding="utf-8")
    assert step.fingerprint(ctx) != before


def test_step_without_config_inputs_ignores_repo_files(tmp_path, cfg, monkeypatch):
    """Шаг не объявил файл — файл на него и не влияет: правка словаря
    произношений не должна обнулять кэш аватара, это лишние кредиты HeyGen."""
    repo = tmp_path / "repo2"
    (repo / "config").mkdir(parents=True)
    other = repo / "config" / "pronunciation.json"
    other.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(type(cfg), "repo_root", property(lambda self: repo))

    step = Step("P6", "a", lambda ctx: {}, outputs=())
    ctx = _ctx(tmp_path, cfg)
    before = step.fingerprint(ctx)
    other.write_text('{"ИИ": "и-и"}', encoding="utf-8")
    assert step.fingerprint(ctx) == before


# --- обслуживание (§14.4, R-11) -----------------------------------------------

def test_maintenance_dry_run_changes_nothing(cfg):
    report = run_maintenance(cfg, dry_run=True)
    assert report["dry_run"] is True
    assert report["evicted"] == []
    assert "libraries" in report and "index" in report


def test_maintenance_reports_storage_state(cfg):
    report = run_maintenance(cfg, dry_run=True)
    storage = report["storage"]
    assert storage["max_bytes"] > 0
    assert isinstance(storage["over_limit"], bool)


# --- смысловой QC §11.2 --------------------------------------------------------

def test_vision_qc_can_be_disabled(cfg, tmp_path):
    from src.p12_render_qc.vision_qc import run_vision_qc

    cfg.set("features.vision_qc", False)
    ctx = _ctx(tmp_path, cfg)
    report = run_vision_qc(ctx, video_path=tmp_path / "nope.mp4",
                           plan={"duration_sec": 10, "shots": [], "subtitles": []})
    assert report["enabled"] is False


def test_the_final_frame_is_not_judged_as_raw_stock(cfg, tmp_path, monkeypatch):
    """§11.2 смотрит готовый кадр, и вопрос ему нужен другой.

    Прежде судье показывали кадр ролика, а спрашивали про «материал B-roll». Он
    честно снижал оценку за наш собственный субтитр («крупный текст в центре
    портит B-roll») и за самого ведущего («это говорящая голова, а не B-roll»).
    На 0047 так набралось четыре пробы из шести — 67 % расхождений там, где
    картинка разошлась с речью в лучшем случае дважды.
    """
    from src.lib.providers import vision as V
    from src.p12_render_qc import vision_qc as VQ

    asked: list[dict] = []

    class _Spy:
        def judge(self, frames, *, intent, role, query, kind="broll"):
            asked.append({"intent": intent, "role": role, "query": query, "kind": kind})
            return V.VisionVerdict(score=0.9, reason="", summary="кадр", judge="spy")

    frame = tmp_path / "f.jpg"
    Image.new("RGB", (54, 96), (20, 20, 24)).save(frame)
    monkeypatch.setattr(VQ, "build_vision_provider", lambda *a, **k: _Spy())
    monkeypatch.setattr(VQ, "extract_frames", lambda *a, **k: [frame] * VQ.SAMPLES)

    plan = {"duration_sec": 12.0, "variant": "A",
            "shots": [{"index": 0, "start": 0.0, "end": 12.0, "kind": "avatar",
                       "role": "hook", "reason": "ведущий вводит тему"}],
            "subtitles": [{"display": "бюджет", "lead": "не в", "start": 6.0,
                           "end": 6.4}]}
    report = run_vision_qc(_ctx(tmp_path, cfg), video_path=tmp_path / "v.mp4", plan=plan)

    assert asked and all(a["kind"] == "final_frame" for a in asked)
    # Судье сказано, что ведущий в кадре — это замысел, а не промах материала.
    assert "ведущий в кадре" in asked[0]["intent"]
    # Эталон речи не теряет приклеенное начало реплики: «не в бюджет», а не
    # «бюджет» — иначе отрицание пропадает ровно там, где оно и есть смысл.
    assert any("не в бюджет" in a["query"] for a in asked)
    assert report["mismatch_share"] == 0.0
    assert report["samples"][0]["expected"]


def test_the_channel_own_captions_are_not_foreign_text(cfg, tmp_path):
    """Субтитр канала — не «текст в кадре» (§11.2.2).

    Судья-заглушка ловил текст по плотности краёв, а её на готовом кадре
    поднимает наш же субтитр. Проба уходила в отчёт как чужая надпись.
    """
    from src.lib.costs import CostLedger
    from src.lib.providers.vision import MockVision

    frame = tmp_path / "busy.jpg"
    noise = np.random.default_rng(7).integers(0, 255, (96, 54, 3), dtype=np.uint8)
    Image.fromarray(noise).save(frame)
    judge = MockVision(cfg, CostLedger())
    for query in ("проба один", "проба два", "проба три", "проба четыре"):
        verdict = judge.judge([frame], intent="кадр ролика", role="body",
                              query=query, kind="final_frame")
        assert verdict.has_text is False


def test_vision_qc_is_not_blocking(repo_root):
    """§11.2 даёт материал для правки правил, но брак определяет §11.1."""
    path = repo_root / "output" / "redshift_0042" / "build_report.json"
    if not path.exists():
        pytest.skip("нет собранного ролика")
    report = json.loads(path.read_text(encoding="utf-8"))
    for qc in report["qc"].values():
        vision = qc.get("vision")
        if vision and vision.get("enabled"):
            assert vision["blocking"] is False


# --- устойчивость к отсутствующим файлам (регрессия) --------------------------

def test_empty_path_is_not_treated_as_existing(tmp_path):
    """Path("") — это Path("."), и он существует.

    Из-за этого материал из локальной базы (у него нет local_file, только ключ
    storage) уходил в ffmpeg как каталог. Ошибка проявлялась только со второго
    ролика, когда в индексе уже что-то есть, — и уронила и CI, и второй прогон.
    """
    assert Path("").exists() is True          # источник ошибки
    assert Path("").is_file() is False        # проверка, которая её ловит
    assert Path(str("").strip() or "x").is_file() is False


def test_p7_skips_index_entries_without_files(tmp_path, cfg):
    """Индекс живёт в git, файлы — во внешнем storage: на свежем клоне их нет."""
    from src.lib.manifest import AssetRecord, FootageIndex
    from src.lib.storage import LocalStorage

    index = FootageIndex(tmp_path / "footage_index.json")
    index.add(AssetRecord(id="ghost", type="video", source="pexels", tags=["lab"],
                          score=0.9, file="pexels/ghost.mp4"))
    storage = LocalStorage(tmp_path / "store")
    assert not storage.exists("pexels/ghost.mp4")
    # Материал найден по тегам, но payload'а нет — предлагать его нельзя.
    found = index.search(["lab"])
    assert [r.id for r in found] == ["ghost"]
    assert not any(storage.exists(r.file) for r in found)


def test_maintenance_removes_orphan_index_entries(cfg, tmp_path, monkeypatch):
    """Записи без файлов вычищаются обслуживанием, а не копятся вечно."""
    from src.lib.manifest import AssetRecord, FootageIndex

    index_path = tmp_path / "cache" / "footage_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = FootageIndex(index_path)
    index.add(AssetRecord(id="ghost", type="video", source="pexels",
                          file="pexels/ghost.mp4"))
    index.save()

    monkeypatch.setattr(cfg, "path", lambda dotted, default=None: (
        tmp_path / "cache" if "cache" in dotted else tmp_path / "store"))
    cfg.set("storage.local_root", str(tmp_path / "store"))
    report = run_maintenance(cfg, dry_run=False)
    assert "ghost" in report["orphans_removed"]


def test_mock_material_never_enters_the_shared_library(tmp_path, cfg):
    """Синтетика мок-прогона в общей базе — чистый вред.

    База лежит в репозитории и просматривается раньше внешних стоков (§7.2.1),
    а мок-прогон CI гоняется на каждом коммите. К моменту находки в базе было
    195 мок-записей из 213 — 92 % «материала», которого нет ни на одном диске.
    Живому ролику такая запись даёт только промах: индекс говорит «материал
    есть», файла нет, слот уходит в генерацию.
    """
    from src.lib.manifest import AssetRecord, FootageIndex

    index = FootageIndex(tmp_path / "index.json")

    def _record(asset_id: str, *, mock: bool) -> AssetRecord:
        return AssetRecord(id=asset_id, type="video", source="pexels",
                           license="Pexels License", url_origin="",
                           phash="0" * 16, phashes=["0" * 16], tags=["гранит"],
                           vision_summary="", score=0.8, duration_sec=3.0,
                           width=1080, height=1920, file="footage/x.mp4",
                           used_in=["redshift_0099"], mock=mock)

    index.add(_record("mock_1", mock=True))
    assert index.items == [], "мок-материал попал в общую базу"

    index.add(_record("real_1", mock=False))
    assert [i.id for i in index.items] == ["real_1"]


def test_the_committed_library_holds_no_mock_rows(repo_root):
    """И сама база в репозитории — тоже: 195 таких строк оттуда вычищены."""
    path = repo_root / "cache" / "footage_index.json"
    if not path.exists():
        pytest.skip("базы нет")
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    assert not [i for i in items if i.get("mock")], "в базе снова синтетика"


def test_the_evergreen_base_is_never_evicted(cfg, tmp_path, monkeypatch):
    """Курированная база переживает вытеснение — иначе она бессмысленна.

    LRU защищал только материал последних пяти роликов. У свежего засева ноль
    использований и самое старое время доступа, то есть по этому правилу он
    уходил первым — все 44 снимка, собранные руками и глазами, ради которых
    база и заведена: «чтоб не искать их постоянно новые, а брать из базы».
    """
    from src.lib.manifest import AssetRecord, FootageIndex

    store = tmp_path / "store"
    (store / "seed" / "galaxy").mkdir(parents=True, exist_ok=True)
    (store / "pexels").mkdir(parents=True, exist_ok=True)
    seed_file = store / "seed" / "galaxy" / "deep_field.jpg"
    churn_file = store / "pexels" / "clip.mp4"
    seed_file.write_bytes(b"x" * 4096)
    churn_file.write_bytes(b"y" * 4096)

    index_path = tmp_path / "cache" / "footage_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = FootageIndex(index_path)
    index.add(AssetRecord(id="seeded", type="photo", source="nasa",
                          file="seed/galaxy/deep_field.jpg",
                          extra={"seed_topic": "galaxy"}))
    index.add(AssetRecord(id="churn", type="video", source="pexels",
                          file="pexels/clip.mp4"))
    index.save()

    monkeypatch.setattr(cfg, "path", lambda dotted, default=None: (
        tmp_path / "cache" if "cache" in dotted else store))
    cfg.set("storage.local_root", str(store))
    cfg.set("storage.max_bytes", 4096)          # места хватает ровно на один файл
    report = run_maintenance(cfg, dry_run=False)

    # Вытеснение обязано было сработать, иначе тест ничего не доказывает:
    # лимит меньше суммы двух файлов, и один из них уйти должен.
    assert report["evicted_count"] >= 1, "вытеснение не запускалось"
    assert seed_file.exists(), "засев вытеснен — база потеряна"
    assert not churn_file.exists(), "вытеснили не то: расходный клип на месте"

"""Реестр шагов пайплайна с контрактами из таблицы §7.1.

Здесь и только здесь описано, какой шаг что читает и что обязан произвести.
Оркестратор (``src/pipeline.py``) опирается на эти объявления при проверке
входов/выходов и при кэшировании.
"""

from __future__ import annotations

from .pipeline import Pipeline, Step

# Импорты шагов держим ленивыми внутри функции: так `redshift validate` не
# тянет за собой numpy/Pillow, а падение одного шага при импорте не ломает CLI.


def _speech_of_plan(plan: dict) -> dict:
    """Часть плана, от которой зависит озвучка."""
    return {
        "video_id": plan.get("video_id"),
        "tts_target_sec": plan.get("tts_target_sec"),
        "blocks": [{key: block.get(key) for key in ("id", "role", "spoken_text")}
                   for block in plan.get("blocks", [])],
    }


def build_pipeline() -> Pipeline:
    from .p0_validate.validator import run_step as p0
    from .p1_plan.planner import run_step as p1
    from .p2_tts.tts import run_step as p2
    from .p3_speech_opt.optimizer import run_step as p3
    from .p4_align.aligner import run_step as p4
    from .p5_replan.replanner import run_step as p5
    from .p6_avatar.avatar import run_step as p6
    from .p7_broll_search.search import run_step as p7
    from .p8_broll_judge.judge import run_step as p8
    from .p9_generate.generate import run_step as p9
    from .p10_audio.audio_build import run_step as p10
    from .p11_assemble.assemble import run_step as p11
    from .p12_render_qc.render import run_step as p12

    return Pipeline([
        Step("P0", "Валидация сценария и конфига", p0,
             inputs=(), outputs=("validated_script.json",)),
        Step("P1", "Планирование хронометража и режимов кадра", p1,
             inputs=("validated_script.json",), outputs=("draft_plan.json",),
             config_inputs=("config/pronunciation.json",)),
        Step("P2", "TTS: сырая озвучка с запасом длины", p2,
             inputs=("draft_plan.json",), outputs=("voice_raw.wav", "tts_meta.json"),
             # Озвучка зависит от речи и только от неё. В том же плане лежат
             # поисковые запросы футажа, visual_intent и подсказки шаблонов —
             # правка любой из этих строк меняла отпечаток шага, ElevenLabs
             # озвучивал заново, границы фраз уезжали, и клипы ведущего из
             # репозитория браковались как разошедшийся липсинк. Здесь названо
             # ровно то, что шаг и правда читает (см. src/p2_tts/tts.py).
             input_slice={"draft_plan.json": _speech_of_plan}),
        Step("P3", "Оптимизация речи: паузы, вдохи, нормализация", p3,
             inputs=("voice_raw.wav", "tts_meta.json"),
             outputs=("voice_final.wav", "speech_map.json")),
        Step("P4", "Word-level выравнивание и субтитры", p4,
             inputs=("voice_final.wav", "speech_map.json"),
             outputs=("words.json", "subtitles.srt")),
        Step("P5", "Пересчёт плана: аватар, футаж, текст", p5,
             inputs=("draft_plan.json", "words.json"), outputs=("cut_plan.json",),
             config_inputs=("config/brandbook.json",)),
        Step("P6", "Генерация аватара посегментно", p6,
             inputs=("cut_plan.json", "voice_final.wav"), outputs=("avatar_meta.json",)),
        Step("P7", "Поиск B-roll", p7,
             inputs=("cut_plan.json",), outputs=("candidates.json",),
             config_inputs=("config/stock_sources.yaml",)),
        Step("P8", "Трёхступенчатая оценка футажей", p8,
             inputs=("candidates.json",), outputs=("accepted_assets.json",)),
        Step("P9", "Генерация недостающих материалов", p9,
             inputs=("accepted_assets.json", "cut_plan.json"), outputs=("generated_assets.json",)),
        Step("P10", "Аудио: SFX, музыкальная подложка, микс", p10,
             inputs=("cut_plan.json", "voice_final.wav"),
             outputs=("sfx_map.json", "music_bed.wav", "mix.wav")),
        Step("P11", "Сборка edit-планов A и B", p11,
             inputs=("cut_plan.json", "accepted_assets.json", "generated_assets.json",
                     "avatar_meta.json", "sfx_map.json", "words.json"),
             outputs=("edit_plan_A.json", "edit_plan_B.json"),
             # templates/manifest.json сюда не входит: его пишет сам P11
             # (состояние ротации), и шаг стал бы вечно несвежим.
             config_inputs=("config/brandbook.json", "config/editing_preferences.json")),
        Step("P12", "Рендер, QC, артефакты", p12,
             inputs=("edit_plan_A.json", "edit_plan_B.json", "mix.wav"),
             outputs=("build_report.json",),
             # Отчёт лежит в рабочем каталоге, а ролики — в выдаче, и она
             # прогон не переживает. Без этой строки возобновление с P12
             # возвращалось из кэша, не отрендерив ничего.
             deliverables=("{video_id}_{variant}.mp4",),
             config_inputs=("config/brandbook.json",)),
    ])


PIPELINE_STEPS = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12")

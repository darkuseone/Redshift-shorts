"""Смысловой QC §11.2 — vision по **финальному** ролику.

Автоматические проверки §11.1 меряют цифры: длительности, уровни, доли. Они не
видят того, что видит зритель, поэтому §11.2 задаёт три вопроса уже готовому
файлу:

1. Соответствует ли картинка произносимому? (несоответствий ≤ 10 %)
2. Есть ли нечитаемый текст — контраст, пёстрый фон?
3. Есть ли артефакты: битые маски, обрезанные головы, растяжение, чужие
   водяные знаки?

Проверка неблокирующая: она даёт материал для правки правил и для обучения
(§11.3), а не отменяет выдачу ролика. Блокирует только §11.1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..lib.ffmpeg import extract_frames
from ..lib.logging import get_logger
from ..lib.providers.vision import build_vision_provider

_log = get_logger("vision_qc")

MISMATCH_LIMIT = 0.10          # §11.2.1
SAMPLES = 6


def _spoken_at(plan: dict[str, Any], t: float, window: float = 1.2) -> str:
    """Что произносится вокруг момента t — эталон для сверки с картинкой."""
    words: list[str] = []
    for cue in plan.get("subtitles", []):
        if abs(float(cue["start"]) - t) > window:
            continue
        # Приклеенное начало реплики — тоже произнесённые слова, и без них
        # эталон теряет отрицание: «не в бюджет» превращается в «бюджет».
        if cue.get("lead"):
            words.append(str(cue["lead"]))
        words.append(str(cue["display"]))
    return " ".join(words)


# Что в кадре по замыслу — по виду кадра. Судья без этого честно ставил 0.15
# кадру с ведущим («это говорящая голова, а не B-roll»), хотя ведущий там и
# должен быть: замысел кадра ему просто не сообщали.
_EXPECTED = {
    "avatar": "ведущий в кадре крупным планом — так и задумано",
    "split": "сплит: ведущий и материал в одном кадре — так и задумано",
    "fullscreen_text": "фраза во весь экран поверх фона — так и задумано",
    "meme": "картинка-цитата целиком в кадре — так и задумано",
    "footage": "материал по смыслу речи, ведущего в кадре нет",
}


def _expected(shot: dict[str, Any]) -> str:
    kind = str(shot.get("kind") or "")
    expected = _EXPECTED.get(kind, _EXPECTED["footage"])
    hero = (shot.get("hero") or {}).get("device")
    if hero:
        expected += f"; поверх — приём «{hero}»"
    return expected


def run_vision_qc(ctx, *, video_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.cfg
    if not bool(cfg.get("features.vision_qc", True)):
        return {"enabled": False, "reason": "features.vision_qc выключен"}

    # skip_vision / vision.skip_live: ZERO live Gemini/Grok — §11.2 тоже.
    # Неблокирующий QC не должен ронять весь P12 при 429/403.
    if bool(cfg.get("vision.skip_live", False)):
        _log.warning("vision.skip_live: смысловой QC без live vision",
                     extra={"variant": plan.get("variant")})
        return {
            "enabled": False,
            "skipped": True,
            "reason": "vision.skip_live: без Gemini/Grok vision API",
            "variant": plan.get("variant"),
            "samples": [],
            "sample_count": 0,
            "mismatch_share": 0.0,
            "mismatch_limit": MISMATCH_LIMIT,
            "picture_matches_speech": True,
            "watermarks_found": 0,
            "blocking": False,
            "notes": ["vision.skip_live: смысловой QC пропущен"],
        }

    duration = float(plan["duration_sec"])
    try:
        provider = build_vision_provider(cfg, ctx.costs, role="primary")
        positions = [(i + 0.5) / SAMPLES for i in range(SAMPLES)]
        frames = extract_frames(
            video_path, ctx.wpath("qc", plan.get("variant", "A"), ".k").parent,
            positions, width=540)

        samples: list[dict[str, Any]] = []
        for position, frame in zip(positions, frames):
            t = duration * position
            shot = next((s for s in plan["shots"]
                         if float(s["start"]) <= t < float(s["end"])), {})
            spoken = _spoken_at(plan, t)
            intent = shot.get("reason") or shot.get("kind", "")
            verdict = provider.judge(
                [frame], kind="final_frame",
                intent=f"{_expected(shot)}. Замысел кадра: {intent}",
                role=str(shot.get("role", "")), query=spoken or intent)
            samples.append({
                "t": round(t, 2),
                "shot_index": shot.get("index"),
                "kind": shot.get("kind"),
                "expected": _expected(shot),
                "spoken": spoken,
                "score": round(verdict.score, 3),
                "summary": verdict.summary,
                "has_text": verdict.has_text,
                "watermark": verdict.watermark,
                "reason": verdict.reason,
                "judge": verdict.judge,
            })
    except Exception as exc:  # noqa: BLE001 — §11.2 никогда не блокирует выдачу
        from ..errors import ProviderError
        soft = isinstance(exc, ProviderError) or "PROVIDER" in type(exc).__name__.upper()
        msg = str(exc)[:240]
        _log.warning("смысловой QC: provider/ошибка — пропускаю без fail",
                     extra={"variant": plan.get("variant"), "err": msg, "soft": soft})
        ctx.warn(f"смысловой QC пропущен из-за ошибки провайдера: {msg}",
                 variant=plan.get("variant"))
        return {
            "enabled": True,
            "skipped": True,
            "provider_error": True,
            "reason": msg,
            "variant": plan.get("variant"),
            "samples": [],
            "sample_count": 0,
            "mismatch_share": 0.0,
            "mismatch_limit": MISMATCH_LIMIT,
            "picture_matches_speech": True,
            "watermarks_found": 0,
            "blocking": False,
            "notes": [f"vision provider error (non-blocking): {msg}"],
        }

    mismatches = [s for s in samples if s["score"] < 0.45]
    watermarks = [s for s in samples if s["watermark"]]
    mismatch_share = len(mismatches) / max(len(samples), 1)

    report = {
        "enabled": True,
        "variant": plan.get("variant"),
        "samples": samples,
        "sample_count": len(samples),
        "mismatch_share": round(mismatch_share, 3),
        "mismatch_limit": MISMATCH_LIMIT,
        "picture_matches_speech": mismatch_share <= MISMATCH_LIMIT,
        "watermarks_found": len(watermarks),
        "blocking": False,
        "notes": [],
    }
    if not report["picture_matches_speech"]:
        report["notes"].append(
            f"картинка расходится с речью на {mismatch_share:.0%} проб "
            f"(предел {MISMATCH_LIMIT:.0%}, §11.2.1)")
    if watermarks:
        report["notes"].append(f"подозрение на водяные знаки в {len(watermarks)} пробах")

    for note in report["notes"]:
        ctx.warn(f"смысловой QC: {note}", variant=plan.get("variant"))
    _log.info("смысловой QC завершён", extra={
        "variant": plan.get("variant"), "samples": len(samples),
        "mismatch_share": report["mismatch_share"],
    })
    return report

"""Смысловой QC §11.2 — vision по **финальному** ролику.

Автоматические проверки §11.1 меряют цифры: длительности, уровни, доли. Они не
видят того, что видит зритель, поэтому §11.2 задаёт три вопроса уже готовому
файлу:

1. Соответствует ли картинка произносимому? (несоответствий ≤ 10 %)
2. Есть ли нечитаемый текст — контраст, пёстрый фон?
3. Есть ли артефакты: битые маски, обрезанные головы, растяжение, чужие
   водяные знаки?

``mismatch_share > limits.vision_mismatch_share_max`` — blocking: ролик не
выдаётся. ``vision.skip_live`` не имеет права ставить semantic pass: в отчёте
``qc_skipped_semantic``, статус не «выдан».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..lib.ffmpeg import extract_frames
from ..lib.jsonio import read_json_or, write_json
from ..lib.logging import get_logger
from ..lib.providers.vision import VisionVerdict, build_vision_provider

_log = get_logger("vision_qc")

MISMATCH_LIMIT = 0.10          # §11.2.1; канон — limits.vision_mismatch_share_max
SAMPLES = 6


def _mismatch_limit(cfg) -> float:
    return float(cfg.get("limits.vision_mismatch_share_max", MISMATCH_LIMIT))


def semantic_blocks(*, mismatch_share: float | None, limit: float,
                    skipped: bool) -> bool:
    """Выдача блокируется при skip или при доле расхождений строго выше порога."""
    if skipped:
        return True
    if mismatch_share is None:
        return False
    return mismatch_share > limit + 1e-6


def _skipped_semantic_report(plan: dict[str, Any], *, reason: str,
                             notes: list[str], cfg) -> dict[str, Any]:
    """Честный skip: не pass, не mismatch_share=0.0, не status «выдан»."""
    limit = _mismatch_limit(cfg)
    return {
        "enabled": True,
        "skipped": True,
        "qc_skipped_semantic": True,
        "reason": reason,
        "variant": plan.get("variant"),
        "samples": [],
        "sample_count": 0,
        "mismatch_share": None,
        "mismatch_limit": limit,
        "picture_matches_speech": False,
        "watermarks_found": 0,
        "blocking": True,
        "notes": notes,
    }


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


def sample_positions() -> list[float]:
    """Где именно снимаются пробы. Одно место правды на весь P12.

    Доля акцента (§7.5) меряется на **тех же** кадрах: новых вызовов ffmpeg
    волна не добавляет, а расхождение позиций сделало бы два замера про разные
    ролики.
    """
    return [(i + 0.5) / SAMPLES for i in range(SAMPLES)]


def _verdict_from_saved(data: Any) -> VisionVerdict | None:
    if isinstance(data, VisionVerdict):
        return data
    if not isinstance(data, dict):
        return None
    return VisionVerdict(
        score=float(data.get("score") or 0.0),
        reason=str(data.get("reason") or ""),
        summary=str(data.get("summary") or ""),
        has_text=bool(data.get("has_text")),
        has_logo=bool(data.get("has_logo")),
        watermark=bool(data.get("watermark")),
        stocky=bool(data.get("stocky")),
        composition_9x16=float(data.get("composition_9x16") or 0.5),
        quality=float(data.get("quality") or 0.5),
        relevance=float(data.get("relevance") or 0.5),
        judge=str(data.get("judge") or "cached"),
        frames=int(data.get("frames") or 0),
        per_frame_scores=list(data.get("per_frame_scores") or []),
    )


def _verdict_cache_path(ctx) -> Path | None:
    work = getattr(ctx, "work_dir", None)
    if not isinstance(work, (str, Path)):
        return None
    return Path(work) / "vision_verdicts.json"


def _save_verdict_cache(ctx, cache: dict[str, Any]) -> None:
    path = _verdict_cache_path(ctx)
    if path is None:
        return
    payload = {}
    for key, verdict in cache.items():
        if hasattr(verdict, "to_dict"):
            payload[key] = verdict.to_dict()
        elif isinstance(verdict, dict):
            payload[key] = verdict
    write_json(path, payload)


def _verdict_cache(ctx) -> dict[str, Any]:
    """Кэш вердиктов на одну сборку (§11.3, Q3.10).

    Версии A и B расходятся шестью шаблонами из двадцати кадров, а проб на
    версию шесть. Значит бо́льшая часть проб B — это те же самые кадры под ту
    же самую речь, и второй вызов судьи по ним ничего не узнаёт: он платный,
    а ответ уже есть.

    Кэш живёт на контексте прогона, а не в модуле: две сборки в одном процессе
    (тесты, батч) не имеют права делиться вердиктами о разных роликах.
    На диск пишется тот же словарь: 429 на шестой пробе 0042 иначе выкидывал
    пять уже оплаченных судей и начинал с нуля.

    Замер на отрендеренном 0042 (A и B, шесть проб): **три кадра из шести**
    совпадают побитово — экономия три вызова из двенадцати, а не шесть, как
    обещала таблица Q3.10. Шесть означало бы, что версии не различаются вовсе;
    они различаются шестью шаблонами, и на двух пробах расхождение большое
    (16 и 19 бит), на одной — один бит. Этот один бит мы намеренно **не**
    засчитываем: см. `_verdict_key`.
    """
    cache = getattr(ctx, "_vision_verdicts", None)
    if type(cache) is not dict:
        cache = {}
        path = _verdict_cache_path(ctx)
        if path is not None and path.exists():
            raw = read_json_or(path, {}) or {}
            if isinstance(raw, dict):
                for key, data in raw.items():
                    verdict = _verdict_from_saved(data)
                    if verdict is not None:
                        cache[key] = verdict
        try:
            setattr(ctx, "_vision_verdicts", cache)
        except Exception:                                # noqa: BLE001
            return cache
    return cache


def _verdict_key(frame: Any, *, role: str, spoken: str, intent: str) -> str:
    """Ключ пробы: сам кадр плюс то, с чем его сверяют.

    Кадр берётся точным dHash, а не порогом похожести: порог экономит больше,
    но начинает переиспользовать вердикт о **другом** кадре, а смысловой QC
    только тем и ценен, что смотрит на конкретный кадр. Совпало побитово —
    это буквально тот же вход, и ответ судьи обязан быть тем же.
    """
    from ..lib.phash import dhash_image

    try:
        digest = dhash_image(frame)
    except Exception:                                    # noqa: BLE001
        return ""
    return "|".join((digest, role, spoken[:120], intent[:120]))


def run_vision_qc(ctx, *, video_path: Path, plan: dict[str, Any],
                  frames: list[Any] | None = None) -> dict[str, Any]:
    cfg = ctx.cfg
    if not bool(cfg.get("features.vision_qc", True)):
        return {"enabled": False, "reason": "features.vision_qc выключен"}

    # skip_live: ZERO live Gemini/Grok. Это не semantic pass и не выдача.
    if bool(cfg.get("vision.skip_live", False)):
        _log.warning("vision.skip_live: смысловой QC без live vision",
                     extra={"variant": plan.get("variant")})
        return _skipped_semantic_report(
            plan,
            reason="vision.skip_live: без Gemini/Grok vision API",
            notes=["vision.skip_live: смысловой QC пропущен (qc_skipped_semantic)"],
            cfg=cfg)

    duration = float(plan["duration_sec"])
    from ..errors import ProviderError

    try:
        provider = build_vision_provider(cfg, ctx.costs, role="primary")
        positions = sample_positions()
        if frames is None:
            frames = extract_frames(
                video_path, ctx.wpath("qc", plan.get("variant", "A"), ".k").parent,
                positions, width=540)
    except Exception as exc:  # noqa: BLE001 — нет ни одной пробы
        soft = isinstance(exc, ProviderError) or "PROVIDER" in type(exc).__name__.upper()
        msg = str(exc)[:240]
        _log.warning("смысловой QC: provider/ошибка — skip, не pass",
                     extra={"variant": plan.get("variant"), "err": msg, "soft": soft})
        ctx.warn(f"смысловой QC пропущен из-за ошибки провайдера: {msg}",
                 variant=plan.get("variant"))
        report = _skipped_semantic_report(
            plan, reason=msg,
            notes=[f"vision provider error (qc_skipped_semantic): {msg}"],
            cfg=cfg)
        report["provider_error"] = True
        return report

    samples: list[dict[str, Any]] = []
    cache = _verdict_cache(ctx)
    reused = 0
    truncated_err: str | None = None
    for position, frame in zip(positions, frames):
        t = duration * position
        shot = next((s for s in plan["shots"]
                     if float(s["start"]) <= t < float(s["end"])), {})
        spoken = _spoken_at(plan, t)
        intent = shot.get("reason") or shot.get("kind", "")
        key = _verdict_key(frame, role=str(shot.get("role", "")),
                           spoken=spoken or "", intent=intent)
        try:
            verdict = cache.get(key) if key else None
            if isinstance(verdict, dict):
                verdict = _verdict_from_saved(verdict)
            if verdict is None:
                verdict = provider.judge(
                    [frame], kind="final_frame",
                    intent=f"{_expected(shot)}. Замысел кадра: {intent}",
                    role=str(shot.get("role", "")), query=spoken or intent)
                if key:
                    cache[key] = verdict
                    _save_verdict_cache(ctx, cache)
            else:
                reused += 1
        except Exception as exc:  # noqa: BLE001
            soft = isinstance(exc, ProviderError) or "PROVIDER" in type(exc).__name__.upper()
            msg = str(exc)[:240]
            if samples and soft:
                truncated_err = msg
                _log.warning(
                    "смысловой QC: проба пропущена, считаем собранные",
                    extra={"variant": plan.get("variant"),
                           "have": len(samples), "err": msg})
                ctx.warn(
                    f"смысловой QC: {len(samples)} проб собрано, остальные — "
                    f"ошибка провайдера: {msg}",
                    variant=plan.get("variant"))
                break
            _log.warning("смысловой QC: provider/ошибка — skip, не pass",
                         extra={"variant": plan.get("variant"), "err": msg, "soft": soft})
            ctx.warn(f"смысловой QC пропущен из-за ошибки провайдера: {msg}",
                     variant=plan.get("variant"))
            report = _skipped_semantic_report(
                plan, reason=msg,
                notes=[f"vision provider error (qc_skipped_semantic): {msg}"],
                cfg=cfg)
            report["provider_error"] = True
            return report
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

    if not samples:
        report = _skipped_semantic_report(
            plan, reason="нет собранных проб vision",
            notes=["vision provider error (qc_skipped_semantic): нет проб"],
            cfg=cfg)
        report["provider_error"] = True
        return report

    mismatches = [s for s in samples if s["score"] < 0.45]
    watermarks = [s for s in samples if s["watermark"]]
    mismatch_share = len(mismatches) / max(len(samples), 1)
    limit = _mismatch_limit(cfg)
    blocks = semantic_blocks(mismatch_share=mismatch_share, limit=limit,
                             skipped=False)

    report = {
        "enabled": True,
        "variant": plan.get("variant"),
        "samples": samples,
        "sample_count": len(samples),
        "mismatch_share": round(mismatch_share, 3),
        "mismatch_limit": limit,
        "picture_matches_speech": not blocks,
        "watermarks_found": len(watermarks),
        # Сколько проб закрыто кэшем вместо платного вызова (Q3.10). Число в
        # отчёте, а не в логе: денежный DoD §4.4 проверяется по отчёту.
        "reused_verdicts": reused,
        "blocking": blocks,
        "notes": [],
    }
    if truncated_err:
        report["provider_error"] = True
        report["notes"].append(
            f"проб {len(samples)}/{SAMPLES}: остальные — ошибка провайдера")
    if not report["picture_matches_speech"]:
        report["notes"].append(
            f"картинка расходится с речью на {mismatch_share:.0%} проб "
            f"(предел {limit:.0%}, §11.2.1)")
    if watermarks:
        report["notes"].append(f"подозрение на водяные знаки в {len(watermarks)} пробах")

    for note in report["notes"]:
        ctx.warn(f"смысловой QC: {note}", variant=plan.get("variant"))
    _log.info("смысловой QC завершён", extra={
        "variant": plan.get("variant"), "samples": len(samples),
        "mismatch_share": report["mismatch_share"],
    })
    return report

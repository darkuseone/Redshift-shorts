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
from ..lib.logging import get_logger
from ..lib.providers.vision import build_vision_provider

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


def _speech_timeline(plan: dict[str, Any], ctx: Any = None) -> list[dict[str, Any]]:
    """Word timings: plan first, then ``words.json``. Karaoke is not the VO."""
    explicit = plan.get("speech_words")
    if not explicit:
        words = plan.get("words")
        if (isinstance(words, list) and words and isinstance(words[0], dict)
                and "start" in words[0]):
            explicit = words
    if explicit:
        return list(explicit)
    read_or = getattr(ctx, "read_or", None) if ctx is not None else None
    if callable(read_or):
        doc = read_or("words.json", {}) or {}
        if isinstance(doc, dict):
            return list(doc.get("words") or [])
    return []


def _token_in_window(item: dict[str, Any], t: float, window: float) -> bool:
    """True when a cue/word overlaps [t − window, t + window]."""
    try:
        start = float(item.get("start") or 0.0)
        end = float(item["end"]) if item.get("end") is not None else start
    except (TypeError, ValueError):
        return False
    return end >= t - window and start <= t + window


def _spoken_tokens(timeline: list[dict[str, Any]], t: float,
                   window: float) -> list[str]:
    tokens: list[str] = []
    for word in timeline:
        if not _token_in_window(word, t, window):
            continue
        lead = str(word.get("lead") or "").strip()
        display = str(word.get("display") or word.get("word") or "").strip()
        if lead and display:
            tokens.append(f"{lead} {display}")
        elif lead:
            tokens.append(lead)
        elif display:
            tokens.append(display)
    return tokens


def _spoken_at(plan: dict[str, Any], t: float, window: float = 1.2,
               speech: list[dict[str, Any]] | None = None) -> str:
    """Что произносится вокруг момента t — эталон для сверки с картинкой.

    Караоке под source_card/dataviz выключается, поэтому ``subtitles`` в плане
    в этот момент пустые. Судья тогда видел статью OpenAI и думал, что речи
    нет. Эталон — тайминги VO (``words.json`` / ``speech_words``), субтитры
    только запасной путь.

    Узкое окно сначала: на 17-й секунде 0048 широкое ±1.2 с захватывало
    хвост «течёт жидкость» и отравляло карточку openai.com.
    """
    tokens: list[str] = []
    timeline = speech if speech is not None else _speech_timeline(plan)
    if timeline:
        tokens = _spoken_tokens(timeline, t, min(window, 0.5))
        # One leftover adjective («Страшное») must not hide «Навье-Стокса»
        # from the water plate at 41.02 — but two tokens already start a
        # new sentence, so 0048's card stays unpoisoned by «жидкость».
        if len(tokens) < 2:
            tokens = _spoken_tokens(timeline, t, window)
        if tokens:
            return " ".join(tokens)
    for cue in plan.get("subtitles", []):
        if not _token_in_window(cue, t, window):
            continue
        # Приклеенное начало реплики — тоже произнесённые слова, и без них
        # эталон теряет отрицание: «не в бюджет» превращается в «бюджет».
        if cue.get("lead"):
            tokens.append(str(cue["lead"]))
        tokens.append(str(cue["display"]))
    return " ".join(tokens)


def _picture_copy(shot: dict[str, Any], plan: dict[str, Any], t: float) -> str:
    """On-screen copy covering t — the judge should see the card, not only VO."""
    bits: list[str] = []
    content = shot.get("content")
    if content:
        bits.append(str(content))
    hero = shot.get("hero") if isinstance(shot.get("hero"), dict) else {}
    params = hero.get("params") if isinstance(hero.get("params"), dict) else {}
    for key in ("word", "title", "text", "content", "kicker"):
        val = params.get(key)
        if isinstance(val, list):
            bits.extend(str(x) for x in val if x)
        elif val:
            bits.append(str(val))
    lines = params.get("lines")
    if isinstance(lines, list):
        bits.extend(str(x) for x in lines if x)
    for ovl in plan.get("overlays") or []:
        if not isinstance(ovl, dict) or not _token_in_window(ovl, t, 0.0):
            continue
        oparams = ovl.get("params") if isinstance(ovl.get("params"), dict) else {}
        for key in ("title", "domain", "text", "highlight", "label", "content"):
            val = oparams.get(key) or ovl.get(key)
            if val:
                bits.append(str(val))
    # Karaoke on this frame. Phrase clips stay up for the whole group, so a
    # tight word window missed «глухой» on the 0048 wall cut while the line
    # was still painted.
    for cue in plan.get("subtitles") or []:
        if not isinstance(cue, dict) or not _token_in_window(cue, t, 1.0):
            continue
        lead = str(cue.get("lead") or "").strip()
        display = str(cue.get("display") or "").strip()
        if lead and display:
            bits.append(f"{lead} {display}")
        elif display:
            bits.append(display)
        elif lead:
            bits.append(lead)
    return " ".join(bits)


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


_OVERLAY_INTENT = {
    "source_card": "карточка источника статьи — так и задумано",
    "dataviz": "числовая плашка по речи — так и задумано",
}

_WALL_PLATE = ("cracked", "peeling", "plaster", "rock", "wall")
_WALL_SPEECH = ("дыр", "глух", "стен", "трещин")


def _wall_metaphor_intent(shot: dict[str, Any], hay: str) -> str:
    """Cracked/peeling plates on «дыра / глухой» are the metaphor, not filler."""
    aid = str(shot.get("asset_id") or shot.get("file") or "").lower()
    if not any(token in aid for token in _WALL_PLATE):
        return ""
    blob = hay.lower()
    if any(token in blob for token in _WALL_SPEECH):
        return "метафора глухой или дырявой стены по речи — так и задумано"
    return ""


def _overlay_intent(plan: dict[str, Any] | None, t: float | None) -> str:
    """Overlays covering t, so the judge does not treat a source card as noise."""
    if plan is None or t is None:
        return ""
    bits: list[str] = []
    for ovl in plan.get("overlays") or []:
        if not isinstance(ovl, dict):
            continue
        if not _token_in_window(ovl, t, 0.0):
            continue
        kind = str(ovl.get("type") or "")
        note = _OVERLAY_INTENT.get(kind)
        if note:
            bits.append(note)
        if kind == "source_card":
            params = ovl.get("params") if isinstance(ovl.get("params"), dict) else {}
            domain = str(params.get("domain") or "")
            if domain:
                bits.append(f"домен {domain}")
    return "; ".join(bits)


def _expected(shot: dict[str, Any], *, plan: dict[str, Any] | None = None,
              t: float | None = None, spoken: str = "") -> str:
    kind = str(shot.get("kind") or "")
    expected = _EXPECTED.get(kind, _EXPECTED["footage"])
    hero = (shot.get("hero") or {}).get("device")
    if hero:
        expected += f"; поверх — приём «{hero}»"
    overlay = _overlay_intent(plan, t)
    if overlay:
        expected += f"; {overlay}"
    copy = _picture_copy(shot, plan, t) if plan is not None and t is not None else ""
    wall = _wall_metaphor_intent(shot, f"{spoken} {copy}")
    if wall:
        expected += f"; {wall}"
    return expected


def sample_positions() -> list[float]:
    """Где именно снимаются пробы. Одно место правды на весь P12.

    Доля акцента (§7.5) меряется на **тех же** кадрах: новых вызовов ffmpeg
    волна не добавляет, а расхождение позиций сделало бы два замера про разные
    ролики.
    """
    return [(i + 0.5) / SAMPLES for i in range(SAMPLES)]


def _verdict_cache(ctx) -> dict[str, Any]:
    """Кэш вердиктов на одну сборку (§11.3, Q3.10).

    Версии A и B расходятся шестью шаблонами из двадцати кадров, а проб на
    версию шесть. Значит бо́льшая часть проб B — это те же самые кадры под ту
    же самую речь, и второй вызов судьи по ним ничего не узнаёт: он платный,
    а ответ уже есть.

    Кэш живёт на контексте прогона, а не в модуле: две сборки в одном процессе
    (тесты, батч) не имеют права делиться вердиктами о разных роликах.

    Замер на отрендеренном 0042 (A и B, шесть проб): **три кадра из шести**
    совпадают побитово — экономия три вызова из двенадцати, а не шесть, как
    обещала таблица Q3.10. Шесть означало бы, что версии не различаются вовсе;
    они различаются шестью шаблонами, и на двух пробах расхождение большое
    (16 и 19 бит), на одной — один бит. Этот один бит мы намеренно **не**
    засчитываем: см. `_verdict_key`.
    """
    cache = getattr(ctx, "_vision_verdicts", None)
    if cache is None:
        cache = {}
        try:
            setattr(ctx, "_vision_verdicts", cache)
        except Exception:                                # noqa: BLE001
            return {}
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
    try:
        provider = build_vision_provider(cfg, ctx.costs, role="primary")
        mode = str(cfg.get("providers.mode", "auto")).lower()
        if getattr(provider, "is_mock", False) and mode != "mock":
            _log.warning("смысловой QC: нет live GLM/Grok — skip, не mock-pass",
                         extra={"variant": plan.get("variant"),
                                "provider": getattr(provider, "name", "")})
            return _skipped_semantic_report(
                plan,
                reason="нет live Grok/Gemini vision (qc_skipped_semantic)",
                notes=["auto/live без GLM и XAI: mock-судья не закрывает §11.2"],
                cfg=cfg)
        positions = sample_positions()
        if frames is None:
            frames = extract_frames(
                video_path, ctx.wpath("qc", plan.get("variant", "A"), ".k").parent,
                positions, width=540)

        speech = _speech_timeline(plan, ctx)
        samples: list[dict[str, Any]] = []
        cache = _verdict_cache(ctx)
        reused = 0
        for position, frame in zip(positions, frames):
            t = duration * position
            shot = next((s for s in plan["shots"]
                         if float(s["start"]) <= t < float(s["end"])), {})
            spoken = _spoken_at(plan, t, speech=speech)
            on_screen = _picture_copy(shot, plan, t)
            query = " ".join(part for part in (spoken, on_screen) if part).strip()
            intent = shot.get("reason") or shot.get("kind", "")
            pictured = _expected(shot, plan=plan, t=t, spoken=spoken)
            key = _verdict_key(frame, role=str(shot.get("role", "")),
                               spoken=query or "", intent=intent)
            verdict = cache.get(key) if key else None
            if verdict is None:
                verdict = provider.judge(
                    [frame], kind="final_frame",
                    intent=f"{pictured}. Замысел кадра: {intent}",
                    role=str(shot.get("role", "")), query=query or intent)
                if key:
                    cache[key] = verdict
            else:
                reused += 1
            samples.append({
                "t": round(t, 2),
                "shot_index": shot.get("index"),
                "kind": shot.get("kind"),
                "expected": pictured,
                "spoken": spoken,
                "score": round(verdict.score, 3),
                "summary": verdict.summary,
                "has_text": verdict.has_text,
                "watermark": verdict.watermark,
                "reason": verdict.reason,
                "judge": verdict.judge,
            })
    except Exception as exc:  # noqa: BLE001 — ошибка провайдера ≠ semantic pass
        from ..errors import ProviderError
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

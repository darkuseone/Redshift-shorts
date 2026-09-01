"""P4: ``voice_final.wav`` + тексты блоков → ``words.json`` + ``subtitles.srt``.

Пословные субтитры (§5.1) требуют точной привязки каждого слова ко времени.
Источник таймингов — по убыванию надёжности:

1. Выравнивание от провайдера TTS, перенесённое в финальный таймкод картой из P3.
2. Энергетическое выравнивание: голосовые участки дорожки распределяются между
   словами пропорционально числу слогов. Работает без внешних сервисов и
   используется, когда провайдер таймингов не отдал.

Отдельная работа шага — вернуть **экранную** форму слова: TTS произносит «сто
пять», а субтитр обязан показать «105». Связь хранится в токенах из P1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..lib.audio import load_wav, rms_envelope
from ..lib.jsonio import write_text
from ..lib.logging import get_logger
from ..lib.render.text_rules import glue_short_cues
from ..lib.schema import count_syllables

_log = get_logger("p4")

_WORD_CHAR = re.compile(r"[^\W_]", re.UNICODE)


def is_spoken_word(text: str) -> bool:
    """Пунктуация словом не считается — её не озвучивают и не показывают."""
    return bool(_WORD_CHAR.search(text))


@dataclass
class AlignedWord:
    index: int
    display: str
    start: float
    end: float
    block_id: str
    role: str
    emphasis: bool
    spoken: list[str]
    source: str            # provider | energy | interpolated

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "display": self.display,
            "start": round(self.start, 4), "end": round(self.end, 4),
            "block_id": self.block_id, "role": self.role,
            "emphasis": self.emphasis, "spoken": self.spoken, "source": self.source,
        }


# Служебные части речи в акцент не годятся: подсвеченный предлог читается как
# сбой рендера, а не как смысловое ударение.
_FUNCTION_WORDS = frozenset("""
и а но да или либо то же ли бы не ни как что чтобы если когда пока хотя
в во на за под над при про для из от до по с со к ку у о об обо без через
это этот эта эти тот та те там тут здесь так вот уже ещё еще только даже
был была было были быть есть будет будут может можно нужно надо
он она оно они его её ее их им ими себя свой своя свои мы вы ты я
""".split())

# Длина отсекает служебную мелочь, которую не покрыл список: акцент на слове из
# трёх букв не читается как ударение даже когда слово знаменательное.
_ACCENT_MIN_LETTERS = 5


def top_up_emphasis(words: list[AlignedWord], ratio: Sequence[float]) -> int:
    """Довести плотность акцентов до §5.1 и вернуть, сколько добрано.

    Сценарий ставит ``emphasis_word`` по одному на блок, и на пятидесяти
    секундах это даёт четыре цветных слова на сотню — один на тридцать. Правило
    брендбука другое: одно на 6–8 слов. Цвет в потоке субтитров и есть
    единственный смысловой акцент, и такой редкий он просто не прочитывается.

    ``accent_word_ratio`` читается буквально: следующий акцент ищется в полосе
    от ``lo`` до ``hi`` слов после предыдущего, а внутри полосы берётся самое
    длинное знаменательное слово — оно почти всегда и есть смысловое. Отсчёт
    ведётся от последнего акцента, поэтому авторский сдвигает сетку, а не
    ломает её. Случайности нет: рендер сэмплирует кадры не по порядку, и один и
    тот же ролик обязан собраться одинаково.
    """
    if not words:
        return 0
    lo = max(2, int(round(float(ratio[0]))))
    hi = max(lo, int(round(float(ratio[1]))))

    def weight(word: AlignedWord) -> int:
        """Вес слова как кандидата в акценты; 0 — не годится."""
        letters = [ch for ch in word.display if ch.isalpha()]
        if len(letters) < _ACCENT_MIN_LETTERS:
            return 0
        if "".join(letters).lower() in _FUNCTION_WORDS:
            return 0
        return len(letters)

    added = 0
    last = -lo
    while True:
        # Авторский акцент внутри полосы отменяет добор: он и есть акцент этой
        # полосы, а два подряд читаются как заливка, а не как ударение.
        author = next((i for i in range(max(0, last + 1), min(last + hi + 1, len(words)))
                       if words[i].emphasis), None)
        if author is not None:
            last = author
            continue

        band = range(last + lo, min(last + hi + 1, len(words)))
        # При равном весе побеждает более раннее слово — ключ по -j.
        best = max(band, key=lambda j: (weight(words[j]), -j), default=None)
        if best is None:
            break
        if not weight(words[best]):
            # В полосе одни служебные слова: берём ближайшее годное за ней.
            beyond = next((j for j in range(min(last + hi + 1, len(words)), len(words))
                           if weight(words[j])), None)
            if beyond is None:
                break
            best = beyond
        # Авторский акцент чуть дальше по тексту делает добор лишним: два
        # цветных слова в трёх словах друг от друга читаются как заливка.
        crowding = next((j for j in range(best + 1, min(best + lo, len(words)))
                         if words[j].emphasis), None)
        if crowding is not None:
            last = crowding
            continue
        words[best].emphasis = True
        added += 1
        last = best
    return added


def voiced_regions(audio: np.ndarray, sr: int, *, floor_db: float = -42.0,
                   min_ms: float = 60.0) -> list[tuple[float, float]]:
    """Участки со звуком — основа энергетического выравнивания."""
    env = rms_envelope(audio, sr, window_ms=20.0)
    with np.errstate(divide="ignore"):
        env_db = 20.0 * np.log10(env + 1e-12)
    loud = env_db > floor_db
    regions: list[tuple[float, float]] = []
    start: int | None = None
    min_len = int(sr * min_ms / 1000.0)
    for i, is_loud in enumerate(loud):
        if is_loud and start is None:
            start = i
        elif not is_loud and start is not None:
            if i - start >= min_len:
                regions.append((start / sr, i / sr))
            start = None
    if start is not None and len(loud) - start >= min_len:
        regions.append((start / sr, len(loud) / sr))
    return regions


def align_by_energy(words: list[str], span: tuple[float, float], audio: np.ndarray,
                    sr: int) -> list[tuple[float, float]]:
    """Разложить слова по интервалу пропорционально слогам, опираясь на энергию."""
    start, end = span
    if not words:
        return []
    i0, i1 = int(start * sr), int(end * sr)
    regions = voiced_regions(audio[i0:i1], sr)
    regions = [(a + start, b + start) for a, b in regions]

    weights = np.array([max(1, count_syllables(w)) for w in words], dtype=np.float64)
    weights /= weights.sum()

    if len(regions) == len(words):
        return regions

    # Голосовое время (без пауз) делим по слогам, паузы отдаём границам слов.
    voiced_total = sum(b - a for a, b in regions) or (end - start)
    out: list[tuple[float, float]] = []
    cursor = regions[0][0] if regions else start
    region_idx = 0
    for weight in weights:
        need = voiced_total * weight
        w_start = cursor
        while need > 1e-6 and region_idx < len(regions):
            r_start, r_end = regions[region_idx]
            cursor = max(cursor, r_start)
            available = r_end - cursor
            if available <= need:
                need -= available
                cursor = r_end
                region_idx += 1
            else:
                cursor += need
                need = 0.0
        out.append((w_start, max(cursor, w_start + 0.06)))
    if out:
        out[-1] = (out[-1][0], min(max(out[-1][1], out[-1][0] + 0.06), end))
    return out


def map_tokens_to_words(tokens: list[dict[str, Any]],
                        aligned: list[dict[str, Any]]) -> tuple[list[tuple[dict, float, float]], bool]:
    """Сопоставить экранные токены произнесённым словам.

    Возвращает ``(пары, точно_ли)``. При расхождении количества (например, TTS
    склеил числительное) переходим на пропорциональное распределение по блоку —
    лучше приблизительный тайминг, чем сдвиг всех последующих слов.
    """
    needed = [sum(1 for s in t["spoken"] if is_spoken_word(s)) for t in tokens]
    total_needed = sum(needed)
    exact = total_needed == len(aligned)

    pairs: list[tuple[dict, float, float]] = []
    if exact:
        cursor = 0
        for token, count in zip(tokens, needed):
            if count == 0:
                continue
            chunk = aligned[cursor:cursor + count]
            cursor += count
            pairs.append((token, float(chunk[0]["start"]), float(chunk[-1]["end"])))
        return pairs, True

    if not aligned:
        return [], False

    span_start = float(aligned[0]["start"])
    span_end = float(aligned[-1]["end"])
    weights = [max(1, count_syllables(t["display"])) for t in tokens]
    total_weight = sum(weights) or 1
    cursor = span_start
    for token, weight in zip(tokens, weights):
        dur = (span_end - span_start) * weight / total_weight
        pairs.append((token, cursor, cursor + dur))
        cursor += dur
    return pairs, False


def _srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[AlignedWord]) -> str:
    """Файл субтитров для площадки — теми же репликами, что и кадр.

    Склейка коротких слов общая с рендером: разойдись они, зритель с включёнными
    субтитрами читал бы одно, а видел другое.
    """
    cues = glue_short_cues([{"display": w.display, "start": w.start, "end": w.end,
                             "block_id": w.block_id} for w in words])
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        text = f'{cue["lead"]} {cue["display"]}' if cue.get("lead") else cue["display"]
        lines.append(str(i))
        lines.append(f'{_srt_time(cue["start"])} --> {_srt_time(cue["end"])}')
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def run_step(ctx) -> dict[str, Any]:
    draft = ctx.read("draft_plan.json")
    speech = ctx.read("speech_map.json")
    audio, sr = load_wav(ctx.work_dir / "voice_final.wav")
    audio = audio[:, 0] if audio.ndim == 2 else audio

    min_ms = float(ctx.cfg.get("speech.min_word_ms", 250)) / 1000.0
    max_ms = float(ctx.cfg.get("speech.max_word_ms", 450)) / 1000.0

    blocks_by_id = {b["id"]: b for b in speech["blocks"]}
    result: list[AlignedWord] = []
    inexact_blocks: list[str] = []
    index = 0

    for block in draft["blocks"]:
        tokens = [t for t in block["tokens"] if t["is_word"]]
        speech_block = blocks_by_id.get(block["id"], {})
        aligned = speech_block.get("words", [])
        source = "provider"

        if not aligned:
            # Фолбэк: провайдер не отдал тайминги — выравниваем по энергии.
            source = "energy"
            span = (float(speech_block.get("start", 0.0)), float(speech_block.get("end", 0.0)))
            spoken_flat = [s for t in tokens for s in t["spoken"] if is_spoken_word(s)]
            spans = align_by_energy(spoken_flat, span, audio, sr)
            aligned = [{"word": w, "start": a, "end": b} for w, (a, b) in zip(spoken_flat, spans)]

        pairs, exact = map_tokens_to_words(tokens, aligned)
        if not exact:
            inexact_blocks.append(block["id"])
            source = "interpolated"
        for token, start, end in pairs:
            result.append(AlignedWord(
                index=index, display=token["display"], start=start, end=end,
                block_id=block["id"], role=block["role"], emphasis=bool(token.get("emphasis")),
                spoken=token["spoken"], source=source,
            ))
            index += 1

    result.sort(key=lambda w: w.start)

    # §5.1: слово держится на экране 250–450 мс; окна не перекрываются.
    short_words = 0
    for i, word in enumerate(result):
        next_start = result[i + 1].start if i + 1 < len(result) else word.end + max_ms
        natural = max(word.end, word.start + min_ms)
        word.end = min(natural, word.start + max_ms, next_start)
        if word.end - word.start < min_ms - 1e-3:
            short_words += 1
        if word.end <= word.start:
            word.end = word.start + 0.08

    accents_added = top_up_emphasis(
        result, ctx.cfg.brand("subtitles.accent_word_ratio", [6, 8]))

    durations = [w.end - w.start for w in result]
    stats = {
        "count": len(result),
        "avg_ms": round(float(np.mean(durations)) * 1000, 1) if durations else 0.0,
        "min_ms": round(float(np.min(durations)) * 1000, 1) if durations else 0.0,
        "max_ms": round(float(np.max(durations)) * 1000, 1) if durations else 0.0,
        "below_min_count": short_words,
        "emphasis_count": sum(1 for w in result if w.emphasis),
        "emphasis_from_script": sum(1 for w in result if w.emphasis) - accents_added,
        "emphasis_added": accents_added,
        "inexact_blocks": inexact_blocks,
        "sources": sorted({w.source for w in result}),
    }

    ctx.write("words.json", {
        "video_id": speech["video_id"],
        "duration_sec": speech["duration_sec"],
        "stats": stats,
        "words": [w.to_dict() for w in result],
    })
    write_text(ctx.wpath("subtitles.srt"), build_srt(result))

    if inexact_blocks:
        ctx.warn(f"выравнивание приближённое в блоках {inexact_blocks}: "
                 f"число произнесённых слов не совпало с числом токенов",
                 blocks=inexact_blocks)
    if short_words:
        ctx.warn(f"{short_words} слов держатся на экране меньше 250 мс — темп речи очень плотный",
                 count=short_words)

    _log.info("выравнивание готово", extra=stats)
    return {"words": len(result), "avg_ms": stats["avg_ms"], "exact": not inexact_blocks}

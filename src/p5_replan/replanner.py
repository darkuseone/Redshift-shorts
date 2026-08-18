"""P5: ``draft_plan.json`` + ``words.json`` → ``cut_plan.json``.

Здесь черновые намерения превращаются в монтажный таймлайн с точностью до кадра.
Слоты строго разбивают [0, длительность] без дыр и наложений: в каждый момент
времени на экране ровно один источник картинки (аватар, футаж, сплит,
полноэкранный текст или мем), а плашки и подсветки живут отдельным слоем.

Жёсткие правила, которые обеспечивает именно этот шаг:

* визуальное событие не реже 1 раза в 2.5 сек (§4.1), первое — до 0.8 сек;
* один футаж 1.5–5 сек, до 7 сек только при внутренних событиях (§3.6.2);
* доля аватара 35–60 % (§3.5) и 2–5 появлений по 3–12 сек;
* два аватар-сегмента подряд без перебивки запрещены (§7.4.3, R-3);
* сплит-скрин ≤25 %, один блок футажа ≤40 % хронометража (§3.5);
* полноэкранный текст 2–4 раза по 0.8–2 сек (§5.2), подсветка 1–3 раза (§5.5);
* последние 2 сек — окно кнопки подписки (§6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..errors import RedshiftError
from ..lib.logging import get_logger

_log = get_logger("p5")

AVATAR_KINDS = ("avatar", "split")
ASSET_KINDS = ("footage", "split")     # слоты, которым нужен внешний материал

# Маркеры иронии для мем-вставки (§5.8: только при явном ироническом маркере)
IRONY_MARKERS = (
    "конечно", "разумеется", "ну да", "как всегда", "внезапно", "сюрприз",
    "что могло пойти не так", "спойлер", "ирония", "казалось бы", "ага",
    "всего лишь", "просто", "естественно", "неожиданно",
)


@dataclass
class Slot:
    index: int
    start: float
    end: float
    kind: str                       # avatar | split | footage | fullscreen_text | meme
    block_id: str
    role: str
    mode: str
    visual_intent: str = ""
    queries: list[str] = field(default_factory=list)
    content: str = ""               # текст для fullscreen_text
    transition_in: str = "cut"
    events: list[dict[str, Any]] = field(default_factory=list)
    needs_asset: bool = False
    asset_role: str = ""            # broll | evidence | meme | generated
    template_hint: str = ""
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "start": round(self.start, 3), "end": round(self.end, 3),
            "duration": round(self.duration, 3), "kind": self.kind,
            "block_id": self.block_id, "role": self.role, "mode": self.mode,
            "visual_intent": self.visual_intent, "queries": self.queries,
            "content": self.content, "transition_in": self.transition_in,
            "events": self.events, "needs_asset": self.needs_asset,
            "asset_role": self.asset_role, "template_hint": self.template_hint,
            "reason": self.reason,
        }


def _snap_to_word(t: float, words: list[dict[str, Any]], *, prefer: str = "start") -> float:
    """Прижать момент реза к ближайшей границе слова — рез посреди слова слышен."""
    if not words:
        return t
    best = t
    best_dist = 1e9
    for word in words:
        for candidate in (float(word["start"]), float(word["end"])):
            dist = abs(candidate - t)
            if dist < best_dist:
                best_dist, best = dist, candidate
    return best if best_dist <= 0.28 else t


def _split_span(start: float, end: float, *, target: float, min_len: float,
                max_len: float, words: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Нарезать интервал на планы длиной около ``target``, но в [min_len, max_len]."""
    total = end - start
    if total <= max_len:
        return [(start, end)]
    count = max(1, round(total / target))
    while total / count > max_len:
        count += 1
    while count > 1 and total / count < min_len:
        count -= 1
    step = total / count
    cuts = [start]
    for i in range(1, count):
        cuts.append(_snap_to_word(start + step * i, words))
    cuts.append(end)
    # Снап мог нарушить монотонность — восстанавливаем.
    for i in range(1, len(cuts)):
        if cuts[i] <= cuts[i - 1] + 0.25:
            cuts[i] = min(cuts[i - 1] + max(min_len, 0.5), end)
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1) if cuts[i + 1] > cuts[i] + 0.05]


def close_gaps(slots: list[Slot], duration: float) -> list[Slot]:
    """Слоты обязаны строго разбивать [0, duration] — без дыр и наложений.

    Вызывается после каждого структурного прохода: иначе проверки длительности
    (появление аватара, длина плана) считаются по «дырявому» таймлайну и
    расходятся с тем, что реально попадёт в рендер.
    """
    slots = [s for s in slots if s.end > s.start + 1e-6]
    if not slots:
        return slots
    slots.sort(key=lambda s: s.start)
    slots[0].start = 0.0
    for prev, nxt in zip(slots, slots[1:]):
        if abs(prev.end - nxt.start) > 1e-9:
            prev.end = nxt.start
    slots[-1].end = duration
    return slots


def _find_word(words: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for word in words:
        if predicate(word):
            return word
    return None


def _has_irony(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in IRONY_MARKERS)


def build_slots(draft: dict[str, Any], words_doc: dict[str, Any], cfg) -> dict[str, Any]:
    limits = cfg.get("limits")
    brand = cfg.brandbook
    duration = float(words_doc["duration_sec"])
    all_words: list[dict[str, Any]] = words_doc["words"]

    min_shot = float(limits.get("min_shot_sec", 1.5))
    max_shot = float(limits.get("max_shot_sec", 5.0))
    max_shot_ev = float(limits.get("max_shot_sec_with_events", 7.0))
    max_gap = float(limits.get("max_event_gap_sec", 2.5))
    fs_range = brand["fullscreen_text"]["duration_sec"]
    fs_limits = limits.get("fullscreen_text_per_video", [2, 4])
    meme_range = brand["memes"]["duration_sec"]
    avatar_a_range = brand["avatar"]["modes"]["A"]["duration_sec"]
    avatar_b_range = brand["avatar"]["modes"]["B"]["duration_sec"]

    words_by_block: dict[str, list[dict[str, Any]]] = {}
    for word in all_words:
        words_by_block.setdefault(word["block_id"], []).append(word)

    slots: list[Slot] = []
    notes: list[str] = []
    fullscreen_used = 0

    for block in draft["blocks"]:
        bwords = words_by_block.get(block["id"], [])
        if not bwords:
            continue
        b_start = float(bwords[0]["start"])
        b_end = float(bwords[-1]["end"])
        overlay = block.get("overlay") or {}
        mode = block["mode"]
        queries = list(block.get("broll_queries") or [])

        # --- окна, вырезающие блок: полноэкранный текст и мем -----------------
        reserved: list[tuple[float, float, str, str, str]] = []

        if overlay.get("type") == "fullscreen_text" and fullscreen_used < int(fs_limits[1]):
            anchor = _find_word(bwords, lambda w: w.get("emphasis")) or bwords[0]
            fs_dur = min(max(float(fs_range[0]), 1.2), float(fs_range[1]))
            fs_start = max(b_start, float(anchor["start"]) - 0.15)
            fs_end = min(b_end, fs_start + fs_dur)
            if fs_end - fs_start >= float(fs_range[0]) - 1e-6:
                reserved.append((fs_start, fs_end, "fullscreen_text",
                                 overlay.get("content", ""), overlay.get("template_hint", "")))
                fullscreen_used += 1

        if (block.get("meme_allowed") and _has_irony(block.get("text", ""))
                and draft["planned_counts"].get("memes", 0) > 0):
            meme_dur = float(meme_range[0]) + 0.4
            meme_start = max(b_start, b_end - meme_dur - 0.2)
            if meme_start > b_start + min_shot:
                reserved.append((meme_start, meme_start + meme_dur, "meme", "", ""))
                notes.append(f"мем в блоке {block['id']}: найден иронический маркер (§5.8)")

        reserved.sort(key=lambda r: r[0])

        # --- разложить блок на интервалы: свободные + зарезервированные -------
        pieces: list[tuple[float, float, str, str, str]] = []
        cursor = b_start
        for r_start, r_end, kind, content, hint in reserved:
            r_start = max(r_start, cursor)
            r_end = min(r_end, b_end)
            if r_end <= r_start:
                continue
            if r_start > cursor + 0.05:
                pieces.append((cursor, r_start, "free", "", ""))
            pieces.append((r_start, r_end, kind, content, hint))
            cursor = r_end
        if cursor < b_end - 0.05:
            pieces.append((cursor, b_end, "free", "", ""))

        # --- заполнить свободные интервалы по режиму кадра --------------------
        for p_start, p_end, kind, content, hint in pieces:
            if kind != "free":
                slots.append(Slot(
                    index=0, start=p_start, end=p_end, kind=kind,
                    block_id=block["id"], role=block["role"], mode=mode,
                    content=content, template_hint=hint,
                    visual_intent=block.get("visual_intent", ""),
                    needs_asset=(kind == "meme"),
                    asset_role="meme" if kind == "meme" else "",
                    reason="полноэкранный текст (§5.2)" if kind == "fullscreen_text"
                    else "мем-панчлайн (§5.8)",
                ))
                continue

            if mode == "A":
                spans = _split_span(p_start, p_end, target=(avatar_a_range[0] + avatar_a_range[1]) / 2,
                                    min_len=min_shot, max_len=float(avatar_a_range[1]),
                                    words=bwords)
                for i, (s, e) in enumerate(spans):
                    if i and slots and slots[-1].kind in AVATAR_KINDS:
                        pass  # перебивку вставит отдельный проход ниже
                    slots.append(Slot(
                        index=0, start=s, end=e, kind="avatar", block_id=block["id"],
                        role=block["role"], mode=mode,
                        visual_intent=block.get("visual_intent", ""),
                        reason="режим A: аватар во весь кадр (§3.5)",
                    ))
            elif mode == "B":
                spans = _split_span(p_start, p_end, target=(avatar_b_range[0] + avatar_b_range[1]) / 2,
                                    min_len=min_shot, max_len=float(avatar_b_range[1]),
                                    words=bwords)
                for s, e in spans:
                    slots.append(Slot(
                        index=0, start=s, end=e, kind="split", block_id=block["id"],
                        role=block["role"], mode=mode,
                        visual_intent=block.get("visual_intent", ""),
                        queries=list(queries), needs_asset=True,
                        asset_role="evidence" if block.get("source_ref") else "broll",
                        reason="режим B: сплит 50/50, сверху доказательство (§3.5)",
                    ))
            else:
                spans = _split_span(p_start, p_end, target=2.6, min_len=min_shot,
                                    max_len=max_shot, words=bwords)
                for s, e in spans:
                    slots.append(Slot(
                        index=0, start=s, end=e, kind="footage", block_id=block["id"],
                        role=block["role"], mode=mode,
                        visual_intent=block.get("visual_intent", ""),
                        queries=list(queries), needs_asset=True,
                        asset_role="evidence" if block.get("source_ref") else "broll",
                        reason="режим C: футаж во весь кадр (§3.5)",
                    ))

    slots = close_gaps(slots, duration)
    slots = close_gaps(_insert_avatar_interstitials(slots, min_shot, notes), duration)
    slots = close_gaps(_limit_appearance_length(
        slots, float(brand["avatar"]["appearance_sec"][1]), min_shot, notes), duration)
    slots = close_gaps(
        _enforce_shot_limits(slots, max_shot, max_shot_ev, min_shot, notes), duration)
    _assign_queries(slots, draft)
    _add_internal_events(slots, max_gap, float(limits.get("first_event_sec", 0.8)), notes)
    _assign_transitions(slots, cfg, notes)

    for i, slot in enumerate(slots):
        slot.index = i

    return {"slots": slots, "notes": notes, "duration": duration}


def _needs_interstitial(prev: Slot, nxt: Slot) -> bool:
    """Нужна ли перебивка между двумя соседними аватар-слотами.

    Правило §7.4.3 защищает от «прыжка» головы на стыке **двух разных
    генераций** HeyGen. Внутри одного блока аватар — это одно непрерывное видео,
    и стыка там нет:

    * разные блоки → разные генерации → перебивка обязательна;
    * внутри блока два сплита подряд → перебивка не нужна: меняется верхняя
      половина кадра, и это само по себе визуальное событие;
    * внутри блока два полнокадровых сегмента подряд → перебивка нужна, иначе
      «склейка» не меняет картинку вообще и ломает ритм §4.1.
    """
    if prev.kind not in AVATAR_KINDS or nxt.kind not in AVATAR_KINDS:
        return False
    if prev.block_id != nxt.block_id:
        return True
    return not (prev.kind == "split" and nxt.kind == "split")


def _insert_avatar_interstitials(slots: list[Slot], min_shot: float,
                                 notes: list[str]) -> list[Slot]:
    """§7.4.3: два аватар-сегмента подряд без перебивки запрещены (R-3).

    Перебивка вырезается из **хвоста первого** сегмента: так стык закрывается
    футажом и «прыжок» головы на склейке не виден.
    """
    out: list[Slot] = []
    for slot in slots:
        if out and _needs_interstitial(out[-1], slot):
            prev = out[-1]
            cut = min(1.4, max(0.9, prev.duration * 0.35))
            if prev.duration - cut >= min_shot * 0.8:
                inter_start = prev.end - cut
                prev.end = inter_start
                out.append(Slot(
                    index=0, start=inter_start, end=slot.start, kind="footage",
                    block_id=prev.block_id, role=prev.role, mode="C",
                    visual_intent=prev.visual_intent, queries=list(prev.queries),
                    needs_asset=True, asset_role="broll",
                    reason="перебивка между аватар-сегментами (§7.4.3, R-3)",
                ))
                notes.append(
                    f"вставлена перебивка {inter_start:.2f}–{slot.start:.2f} сек "
                    f"между аватар-сегментами блоков {prev.block_id}/{slot.block_id}")
            else:
                # Короткий сегмент дробить нечем — сливаем его со следующим.
                slot.start = prev.start
                slot.block_id = prev.block_id if prev.duration > slot.duration else slot.block_id
                out.pop()
                notes.append("смежные аватар-сегменты слиты: перебивка не помещалась")
        out.append(slot)
    return out


def _avatar_runs(slots: list[Slot]) -> list[list[int]]:
    """Индексы слотов, образующих непрерывные появления аватара."""
    runs: list[list[int]] = []
    for i, slot in enumerate(slots):
        if slot.kind not in AVATAR_KINDS:
            continue
        if runs and runs[-1][-1] == i - 1 and abs(slots[i - 1].end - slot.start) < 1e-6:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _limit_appearance_length(slots: list[Slot], max_appearance: float, min_shot: float,
                             notes: list[str]) -> list[Slot]:
    """§3.5: одно появление аватара — 3–12 сек.

    Слишком длинный непрерывный участок разбивается перебивкой у ближайшей к
    середине границы слотов: длинное непрерывное присутствие «приклеивает»
    аватара к кадру и убивает разнообразие.
    """
    guard = 0
    while guard < 8:
        guard += 1
        runs = _avatar_runs(slots)
        target = next(
            (r for r in runs if slots[r[-1]].end - slots[r[0]].start > max_appearance), None)
        if target is None or len(target) < 2:
            if target is not None:
                notes.append(
                    f"появление {slots[target[0]].start:.2f}–{slots[target[-1]].end:.2f} сек длиннее "
                    f"{max_appearance} сек, но состоит из одного слота — перебивку вставить негде")
            break
        run_start = slots[target[0]].start
        run_end = slots[target[-1]].end
        middle = (run_start + run_end) / 2
        boundary_idx = min(target[1:], key=lambda i: abs(slots[i].start - middle))
        prev = slots[boundary_idx - 1]
        cut = min(1.4, max(0.9, prev.duration * 0.4))
        if prev.duration - cut < min_shot * 0.8:
            break
        inter_start = prev.end - cut
        inter_end = prev.end
        prev.end = inter_start
        slots.insert(boundary_idx, Slot(
            index=0, start=inter_start, end=inter_end, kind="footage",
            block_id=prev.block_id, role=prev.role, mode="C",
            visual_intent=prev.visual_intent, queries=list(prev.queries),
            needs_asset=True, asset_role="broll",
            reason="дробление слишком длинного появления аватара (§3.5: 3–12 сек)",
        ))
        notes.append(f"появление {run_start:.2f}–{run_end:.2f} сек разбито перебивкой "
                     f"{inter_start:.2f}–{inter_end:.2f} сек")
    return slots


def _enforce_shot_limits(slots: list[Slot], max_shot: float, max_shot_ev: float,
                         min_shot: float, notes: list[str]) -> list[Slot]:
    """Ни один футажный слот не висит дольше допустимого (§3.6.2, QC-4)."""
    out: list[Slot] = []
    for slot in slots:
        if slot.kind not in ("footage", "split") or slot.duration <= max_shot:
            out.append(slot)
            continue
        parts = _split_span(slot.start, slot.end, target=max_shot * 0.75,
                            min_len=min_shot, max_len=max_shot, words=[])
        for i, (s, e) in enumerate(parts):
            clone = Slot(**{**slot.__dict__, "start": s, "end": e, "events": [],
                            "reason": slot.reason + " | разрез по лимиту длины плана"})
            if i:
                clone.transition_in = "cut"
            out.append(clone)
        notes.append(f"футаж {slot.start:.2f}–{slot.end:.2f} разрезан на {len(parts)} плана "
                     f"(лимит {max_shot} сек)")
    return out


def _assign_queries(slots: list[Slot], draft: dict[str, Any]) -> None:
    """Раздать поисковые запросы блока по его футажным слотам (по кругу)."""
    by_block: dict[str, list[Slot]] = {}
    for slot in slots:
        if slot.needs_asset and slot.asset_role in ("broll", "evidence"):
            by_block.setdefault(slot.block_id, []).append(slot)
    for block in draft["blocks"]:
        block_slots = by_block.get(block["id"], [])
        queries = list(block.get("broll_queries") or [])
        if not block_slots:
            continue
        if not queries:
            queries = [block.get("visual_intent") or block.get("text", "")[:80]]
        for i, slot in enumerate(block_slots):
            primary = queries[i % len(queries)]
            slot.queries = [primary] + [q for q in queries if q != primary]


def _add_internal_events(slots: list[Slot], max_gap: float, first_event_sec: float,
                         notes: list[str]) -> None:
    """Догнать ритм §4.1: событие не реже 2.5 сек, первое — до 0.8 сек."""
    for slot in slots:
        slot.events = [{"t": round(slot.start, 3), "kind": "shot_change"}]
        # Длинный план получает внутренние события: старт Ken Burns / push-in.
        t = slot.start + max_gap * 0.8
        while t < slot.end - 0.4:
            slot.events.append({
                "t": round(t, 3),
                "kind": "kenburns_restart" if slot.kind == "footage" else "push_in",
            })
            t += max_gap * 0.8

    if slots and slots[0].duration > first_event_sec:
        slots[0].events.insert(1, {"t": round(min(0.6, slots[0].duration * 0.5), 3),
                                   "kind": "punch_in"})
        notes.append("в первый план добавлено событие до 0.8 сек (§4.1)")


def _assign_transitions(slots: list[Slot], cfg, notes: list[str]) -> None:
    """Cut — база ≥70 %; динамика только на входах аватара и смене блока (§4.3)."""
    min_gap = float(cfg.get("limits.dynamic_transition_min_gap_sec", 6.0))
    last_dynamic = -1e9
    for i, slot in enumerate(slots):
        if i == 0:
            slot.transition_in = "cut"
            continue
        prev = slots[i - 1]
        entering_avatar = slot.kind in AVATAR_KINDS and prev.kind not in AVATAR_KINDS
        leaving_avatar = prev.kind in AVATAR_KINDS and slot.kind not in AVATAR_KINDS
        block_change = slot.block_id != prev.block_id
        wants_dynamic = entering_avatar or leaving_avatar or (block_change and slot.role == "twist")
        if wants_dynamic and slot.start - last_dynamic >= min_gap:
            slot.transition_in = "dynamic"
            last_dynamic = slot.start
        else:
            slot.transition_in = "cut"

    dynamic = sum(1 for s in slots if s.transition_in == "dynamic")
    if slots and dynamic / len(slots) > (1 - float(cfg.get("limits.cut_share_min", 0.7))):
        notes.append(f"доля динамических переходов {dynamic}/{len(slots)} — на границе §4.3")


def compute_stats(slots: list[Slot], duration: float) -> dict[str, Any]:
    avatar_sec = sum(s.duration for s in slots if s.kind in AVATAR_KINDS)
    split_sec = sum(s.duration for s in slots if s.kind == "split")

    events: list[float] = []
    for slot in slots:
        events.extend(float(e["t"]) for e in slot.events)
    events = sorted(set(events))
    gaps = [b - a for a, b in zip(events, events[1:])] if len(events) > 1 else [duration]
    tail_gap = duration - events[-1] if events else duration

    # Самый длинный непрерывный блок футажа (§3.5: ≤40 % хронометража)
    longest_footage = 0.0
    run_start: float | None = None
    for slot in slots:
        if slot.kind in ("footage", "fullscreen_text", "meme"):
            if run_start is None:
                run_start = slot.start
            longest_footage = max(longest_footage, slot.end - run_start)
        else:
            run_start = None

    # Появление — непрерывный участок с аватаром в кадре, а не каждый слот:
    # соседние сплиты одного блока — это одно появление (§3.5: 2–5 появлений).
    appearances: list[tuple[float, float]] = []
    for slot in slots:
        if slot.kind not in AVATAR_KINDS:
            continue
        if appearances and abs(appearances[-1][1] - slot.start) < 1e-6:
            appearances[-1] = (appearances[-1][0], slot.end)
        else:
            appearances.append((slot.start, slot.end))

    first_avatar = next((s.start for s in slots if s.kind in AVATAR_KINDS), None)
    return {
        "duration_sec": round(duration, 3),
        "slot_count": len(slots),
        "avatar_sec": round(avatar_sec, 3),
        "avatar_share": round(avatar_sec / max(duration, 1e-6), 4),
        "avatar_appearances": len(appearances),
        "avatar_appearance_durations": [round(e - s, 2) for s, e in appearances],
        "first_avatar_sec": round(first_avatar, 3) if first_avatar is not None else None,
        "split_share": round(split_sec / max(duration, 1e-6), 4),
        "longest_footage_block_sec": round(longest_footage, 3),
        "longest_footage_block_share": round(longest_footage / max(duration, 1e-6), 4),
        "max_shot_sec": round(max((s.duration for s in slots), default=0.0), 3),
        "max_event_gap_sec": round(max(max(gaps, default=0.0), tail_gap), 3),
        "first_event_sec": round(events[0], 3) if events else None,
        "event_count": len(events),
        "cut_share": round(
            sum(1 for s in slots if s.transition_in == "cut") / max(len(slots), 1), 4),
        "fullscreen_text_count": sum(1 for s in slots if s.kind == "fullscreen_text"),
        "meme_count": sum(1 for s in slots if s.kind == "meme"),
        "asset_slots": sum(1 for s in slots if s.needs_asset),
    }


def run_step(ctx) -> dict[str, Any]:
    draft = ctx.read("draft_plan.json")
    words_doc = ctx.read("words.json")

    built = build_slots(draft, words_doc, ctx.cfg)
    slots: list[Slot] = built["slots"]
    duration = built["duration"]
    if not slots:
        raise RedshiftError("монтажный план пуст: нет ни одного слота",
                            code="EMPTY_CUT_PLAN")

    stats = compute_stats(slots, duration)
    limits = ctx.cfg.get("limits")
    lo_share, hi_share = limits.get("avatar_share", [0.35, 0.60])

    warnings: list[str] = list(built["notes"])
    if not (lo_share <= stats["avatar_share"] <= hi_share):
        warnings.append(f"доля аватара {stats['avatar_share']:.1%} вне {lo_share:.0%}–{hi_share:.0%}")
    if stats["max_event_gap_sec"] > float(limits.get("max_event_gap_sec", 2.5)) + 1e-3:
        warnings.append(f"интервал без события {stats['max_event_gap_sec']:.2f} сек > лимита")
    if stats["longest_footage_block_share"] > float(limits.get("footage_block_share_max", 0.4)) + 1e-3:
        warnings.append(
            f"непрерывный блок футажа {stats['longest_footage_block_share']:.0%} > 40 % (§3.5)")
    if stats["split_share"] > float(limits.get("split_share_max", 0.25)) + 1e-3:
        warnings.append(f"сплит-скрин {stats['split_share']:.0%} > 25 % (§3.5)")

    lo_app, hi_app = ctx.cfg.brand("avatar.appearances", [2, 5])
    if not (lo_app <= stats["avatar_appearances"] <= hi_app):
        warnings.append(
            f"появлений аватара {stats['avatar_appearances']}, требуется {lo_app}–{hi_app} (§3.5)")
    app_lo, app_hi = ctx.cfg.brand("avatar.appearance_sec", [3.0, 12.0])
    off_spec = [d for d in stats["avatar_appearance_durations"] if not (app_lo <= d <= app_hi)]
    if off_spec:
        warnings.append(
            f"появления аватара длиной {off_spec} сек вне коридора {app_lo}–{app_hi} сек (§3.5)")

    cta_tail = float(limits.get("cta_tail_sec", 2.0))
    plan_doc = {
        "video_id": draft["video_id"],
        "fps": ctx.cfg.fps,
        "duration_sec": round(duration, 3),
        "target_duration_sec": draft["target_duration_sec"],
        "music_mood": draft["music_mood"],
        "category": draft.get("category"),
        "sources": draft.get("sources", []),
        "cta": draft.get("cta", {}),
        "cta_window": [round(max(0.0, duration - cta_tail), 3), round(duration, 3)],
        "hook_window": [0.0, float(limits.get("hook_sec", 3.0))],
        "avatar_id": ctx.cfg.get("heygen.avatar_id"),
        "stats": stats,
        "notes": warnings,
        "slots": [s.to_dict() for s in slots],
        "avatar_segments": [
            {"index": i, "slot_index": s.index, "start": round(s.start, 3),
             "end": round(s.end, 3), "duration": round(s.duration, 3),
             "block_id": s.block_id, "mode": s.mode, "kind": s.kind}
            for i, s in enumerate(s for s in slots if s.kind in AVATAR_KINDS)
        ],
        "blocks": [
            {"id": b["id"], "role": b["role"], "mode": b["mode"], "text": b["text"],
             "spoken_text": b["spoken_text"], "sfx": b.get("sfx", "none"),
             "overlay": b.get("overlay", {}), "source_ref": b.get("source_ref"),
             "visual_intent": b.get("visual_intent", ""),
             "emphasis_word": b.get("emphasis_word")}
            for b in draft["blocks"]
        ],
    }
    ctx.write("cut_plan.json", plan_doc)

    for warning in warnings:
        ctx.warn(f"P5: {warning}")
    _log.info("монтажный план готов", extra={
        "slots": stats["slot_count"], "avatar_share": stats["avatar_share"],
        "appearances": stats["avatar_appearances"],
        "max_shot": stats["max_shot_sec"], "max_gap": stats["max_event_gap_sec"],
        "asset_slots": stats["asset_slots"], "cut_share": stats["cut_share"],
    })
    return {"slots": stats["slot_count"], "avatar_share": stats["avatar_share"],
            "asset_slots": stats["asset_slots"]}

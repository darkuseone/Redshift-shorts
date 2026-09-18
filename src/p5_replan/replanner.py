"""P5: ``draft_plan.json`` + ``words.json`` → ``cut_plan.json``.

Здесь черновые намерения превращаются в монтажный таймлайн с точностью до кадра.
Слоты строго разбивают [0, длительность] без дыр и наложений: в каждый момент
времени на экране ровно один источник картинки (аватар, футаж, сплит,
полноэкранный текст или мем), а плашки и подсветки живут отдельным слоем.

Жёсткие правила, которые обеспечивает именно этот шаг:

* визуальное событие не реже 1 раза в 2.5 сек (§4.1), первое — до 0.8 сек;
* один футаж 1.5–5 сек, до 7 сек только при внутренних событиях (§3.6.2);
* доля аватара 35–50 % (§3.5) и 2–5 появлений по 3–12 сек;
* два аватар-сегмента подряд без перебивки запрещены (§7.4.3, R-3);
* сплит-скрин ≤25 %, один блок футажа ≤40 % хронометража (§3.5);
* полноэкранный текст 2–4 раза по 0.8–2 сек (§5.2), подсветка 1–3 раза (§5.5);
* последние 2 сек — окно кнопки подписки (§6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from ..errors import RedshiftError
from ..lib.beats import annotate_slots
from ..lib.logging import get_logger
from ..lib.text import (
    accent_card_start, enrich_overlay_punch, find_spoken_anchor,
    sync_overlays_from_script,
)

_log = get_logger("p5")

AVATAR_KINDS = ("avatar", "split")
ASSET_KINDS = ("footage", "split")     # слоты, которым нужен внешний материал
# Интервал [0.00, 1.00) — не talking-head. Лицо с 1.0 с; хук после 1.0 с можно.
AVATAR_EARLIEST_SEC = 1.0

# Маркеры иронии для мем-вставки (§5.8: только при явном ироническом маркере)
# Иронический маркер не только включает мем (§5.8), но и говорит, какой именно:
# карточки в базе разложены по эмоциям (§14.3), и «внезапно» просит удивления,
# а «всего лишь» — разочарования.
IRONY_MARKERS: dict[str, str] = {
    "конечно": "сарказм", "разумеется": "сарказм", "естественно": "сарказм",
    "ну да": "сарказм", "как всегда": "сарказм", "ага": "сарказм",
    "внезапно": "удивление", "неожиданно": "удивление", "сюрприз": "удивление",
    "что могло пойти не так": "ирония", "спойлер": "ирония",
    "казалось бы": "ирония", "ирония": "ирония",
    "всего лишь": "разочарование", "просто": "разочарование",
}


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
    asset_role: str = ""            # broll | evidence | meme | interstitial | generated
    template_hint: str = ""
    meme_emotion: str = ""          # эмоция мема (§14.3): по ней он и берётся из базы
    # Бит петли удержания (§6.1). Роль говорит о содержании блока, бит — о его
    # месте в петле: «evidence» бывает и затяжкой, и ответом.
    beat: str = "stretch"
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
            "meme_emotion": self.meme_emotion, "beat": self.beat,
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


def _hold_face_until(slots: list[Slot],
                     earliest: float = AVATAR_EARLIEST_SEC) -> list[Slot]:
    """[0, earliest) не talking-head: лицо только с 1.0 с.

    Допустимы card / b-roll / title. Аватар после 1.0 с в том же хуке — можно.
    """
    out: list[Slot] = []
    for slot in slots:
        if slot.kind not in AVATAR_KINDS or slot.start >= earliest - 1e-9:
            out.append(slot)
            continue
        if slot.end <= earliest + 1e-9:
            out.append(replace(
                slot,
                kind="footage",
                mode="C",
                needs_asset=True,
                asset_role=slot.asset_role or "broll",
                reason="первая секунда не talking-head",
            ))
            continue
        out.append(replace(
            slot,
            end=earliest,
            kind="footage",
            mode="C",
            needs_asset=True,
            asset_role=slot.asset_role or "broll",
            reason="первая секунда не talking-head",
            events=[],
        ))
        out.append(replace(slot, start=earliest))
    return out


def _find_word(words: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for word in words:
        if predicate(word):
            return word
    return None


def _irony_emotion(text: str) -> str:
    """Эмоция мема по найденному маркеру, либо пустая строка, если маркера нет."""
    lowered = text.lower()
    for marker, emotion in IRONY_MARKERS.items():
        if marker in lowered:
            return emotion
    return ""


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
            # Sync to spoken punch onset (content word), never early (−0.15).
            raw_content = str(overlay.get("content") or "").strip()
            content = enrich_overlay_punch(raw_content, str(block.get("text") or ""))
            anchor = (find_spoken_anchor(
                bwords, content or raw_content, block.get("emphasis_word"))
                or bwords[0])
            # Prefer catalog min, but never invent an early card: if the punch
            # lands near block end, keep a short on-beat card (≥0.55s) instead
            # of dropping it (r5) or sliding it to block start (legacy).
            fs_dur = min(max(float(fs_range[0]), 1.2), float(fs_range[1]))
            fs_start = accent_card_start(anchor, block_start=b_start, delay_sec=0.05)
            fs_end = min(b_end, fs_start + fs_dur)
            min_keep = min(float(fs_range[0]), 0.55)
            if fs_end - fs_start < float(fs_range[0]) - 1e-6:
                # stretch to catalog min when room remains in the block
                if b_end - fs_start >= float(fs_range[0]) - 1e-6:
                    fs_end = min(b_end, fs_start + float(fs_range[0]))
                elif b_end - fs_start >= min_keep - 1e-6:
                    fs_end = b_end
            if fs_end - fs_start >= min_keep - 1e-6:
                reserved.append((fs_start, fs_end, "fullscreen_text",
                                 content or raw_content, overlay.get("template_hint", "")))
                fullscreen_used += 1

        meme_emotion = _irony_emotion(block.get("text", ""))
        if (block.get("meme_allowed") and meme_emotion
                and draft["planned_counts"].get("memes", 0) > 0):
            meme_dur = float(meme_range[0]) + 0.4
            meme_start = max(b_start, b_end - meme_dur - 0.2)
            if meme_start > b_start + min_shot:
                # Эмоция едет в hint: по ней P7 и достанет карточку из базы (§14.3).
                reserved.append((meme_start, meme_start + meme_dur, "meme", "", meme_emotion))
                notes.append(f"мем в блоке {block['id']}: найден иронический маркер, "
                             f"эмоция «{meme_emotion}» (§5.8)")

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
                    content=content,
                    template_hint="" if kind == "meme" else hint,
                    meme_emotion=hint if kind == "meme" else "",
                    visual_intent=block.get("visual_intent", ""),
                    # Полноэкранный текст тоже просит материал. Раньше он его
                    # не просил, и кадр выходил белыми буквами на пустом
                    # чёрном: слово-акцент есть, а смысла за ним нет. Материал
                    # ищется по тем же запросам блока, что и остальной футаж,
                    # — то есть по смыслу той самой фразы, которую он и
                    # выносит крупно.
                    needs_asset=kind in ("meme", "fullscreen_text"),
                    asset_role=("meme" if kind == "meme"
                                else "broll" if kind == "fullscreen_text" else ""),
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

    slots = close_gaps(_hold_face_until(slots), duration)

    share_range = limits.get("avatar_share", [0.35, 0.50])
    share_lo, share_hi = float(share_range[0]), float(share_range[1])
    footage_share_max = float(limits.get("footage_block_share_max", 0.40))
    appearances_max = int(brand["avatar"].get("appearances", [2, 5])[1])
    appearance_min = float(brand["avatar"]["appearance_sec"][0])
    appearance_max = float(brand["avatar"]["appearance_sec"][1])

    # Структурные проходы и добор доли аватара сходятся итеративно, а не в один
    # проход: перебивки (§7.4.3) и дробление длинных появлений (§3.5) вырезают
    # секунды **из** аватара, поэтому добор до 35 %, сделанный раньше них,
    # снова уезжает вниз, а добор после них ломает те же правила. Считаем по
    # тому же таймлайну, что уйдёт в рендер, и повторяем до сходимости.
    for _ in range(4):
        slots = close_gaps(
            _insert_avatar_interstitials(slots, min_shot, appearance_min, notes), duration)
        slots = close_gaps(
            _limit_appearance_length(slots, appearance_min, appearance_max, min_shot, notes),
            duration)
        slots = close_gaps(
            _enforce_shot_limits(slots, max_shot, max_shot_ev, min_shot, notes,
                                 appearance_min=appearance_min, words=all_words), duration)
        slots = close_gaps(
            _heal_stub_appearances(slots, appearance_min, appearance_max, notes),
            duration)
        # Оба правила §3.5 чинятся одним действием — «отдать аватару футажный
        # слот», и оба должны попасть в ту же сходимость: разрыв футажа может
        # поднять долю, а добор доли — разорвать футаж.
        fixed = _raise_avatar_share(slots, draft["blocks"], duration, share_lo, share_hi,
                                    appearance_min, appearance_max, notes)
        fixed = _break_long_footage_run(slots, draft["blocks"], duration, footage_share_max,
                                        share_hi, appearance_min, appearance_max,
                                        appearances_max, notes) or fixed
        if not fixed:
            break
        slots = close_gaps(_hold_face_until(slots), duration)

    # Последним — контроль того, что осталось после всех резов, включая сдвиг
    # первого появления: появление короче §3.5 в кадр не выходит ни при каких
    # обстоятельствах.
    slots = close_gaps(_hold_face_until(slots), duration)
    slots = close_gaps(
        _heal_stub_appearances(slots, appearance_min, appearance_max, notes), duration)

    final_share = _avatar_share(slots, duration)
    if final_share < share_lo:
        notes.append(f"доля аватара {final_share:.1%} осталась ниже {share_lo:.0%}: "
                     f"добирать нечем — свободных футажных слотов в блоках без "
                     f"директивы avatar: off не осталось")
    _assign_queries(slots, draft)
    _add_internal_events(slots, max_gap, float(limits.get("first_event_sec", 0.8)), notes)
    _assign_transitions(slots, cfg, notes)

    for i, slot in enumerate(slots):
        slot.index = i

    return {"slots": slots, "notes": notes, "duration": duration}



def _avatar_share(slots: list[Slot], duration: float) -> float:
    """Доля хронометража, где аватар в кадре (полный кадр или сплит)."""
    return sum(s.duration for s in slots if s.kind in AVATAR_KINDS) / max(duration, 1e-6)


class _AvatarConversion:
    """Механика перевода футажного слота в аватар (§3.5).

    Общая для двух правил: добора доли аватара до 35 % и разрыва слишком
    длинного непрерывного футажа. Оба сводятся к одному действию — «отдать
    аватару подходящий футажный слот», и оба обязаны при этом не сломать
    остальные правила §3.5.
    """

    def __init__(self, slots: list[Slot], blocks: list[dict[str, Any]], duration: float,
                 share_hi: float, appearance_min: float, appearance_max: float) -> None:
        self.slots = slots
        self.blocks = blocks
        self.duration = duration
        self.share_hi = share_hi
        self.appearance_min = appearance_min
        self.appearance_max = appearance_max
        # Блоки с ``avatar: off`` — указание сценария, их не трогаем.
        self.allowed = {b["id"] for b in blocks if b.get("avatar_directive") != "off"}

    def _block(self, block_id: str) -> dict[str, Any]:
        return next((b for b in self.blocks if b["id"] == block_id), {})

    def _target_kind(self, block_id: str) -> str:
        return "split" if self._block(block_id).get("role") == "evidence" else "avatar"

    def is_candidate(self, i: int) -> bool:
        """Перебивки не забираем: они и существуют затем, чтобы разорвать аватара."""
        s = self.slots[i]
        return (s.kind == "footage" and s.block_id in self.allowed
                and "перебивка" not in s.reason
                and s.start >= AVATAR_EARLIEST_SEC - 1e-9)

    def candidates(self) -> list[int]:
        return [i for i in range(len(self.slots)) if self.is_candidate(i)]

    def span(self, group: list[int]) -> float:
        """Длина появления, если слоты group сольются в один аватарный слот.

        Слипание засчитывается только там, где §7.4.3 не потребует перебивку:
        внутри одного блока и только между двумя сплитами. Иначе аватар соседа
        отделён перебивкой и в это появление не входит.
        """
        slots = self.slots
        block_id = slots[group[0]].block_id
        kind = self._target_kind(block_id)
        start, end = slots[group[0]].start, slots[group[-1]].end
        left, right = group[0] - 1, group[-1] + 1
        if (left >= 0 and slots[left].kind == "split" and kind == "split"
                and slots[left].block_id == block_id
                and abs(slots[left].end - start) < 1e-6):
            start = slots[left].start
        if (right < len(slots) and slots[right].kind == "split" and kind == "split"
                and slots[right].block_id == block_id
                and abs(slots[right].start - end) < 1e-6):
            end = slots[right].end
        return end - start

    def _grow(self, group: list[int]) -> bool:
        """Дотянуть группу соседним футажом того же блока до минимума появления."""
        block_id = self.slots[group[0]].block_id
        options = [j for j in (group[0] - 1, group[-1] + 1)
                   if 0 <= j < len(self.slots) and self.is_candidate(j)
                   and self.slots[j].block_id == block_id]
        if not options:
            return False
        group.append(min(options, key=lambda j: self.slots[j].duration))
        group.sort()
        return True

    def plan(self, i: int) -> list[int] | None:
        """Группа слотов вокруг i, дающая допустимое появление, либо None."""
        headroom = (self.share_hi - _avatar_share(self.slots, self.duration)) * self.duration
        group = [i]
        while self.span(group) < self.appearance_min and self._grow(group):
            pass
        if not self.appearance_min <= self.span(group) <= self.appearance_max:
            return None
        if sum(self.slots[j].duration for j in group) > headroom:
            return None
        return group

    def extends_existing(self, group: list[int]) -> bool:
        """Прирастает ли группа к уже существующему появлению, не создавая нового."""
        return self.span(group) > sum(self.slots[j].duration for j in group) + 1e-6

    def apply(self, group: list[int], reason: str, notes: list[str]) -> None:
        """Слить группу в один аватарный слот.

        Именно слить, а не пометить каждый: два полнокадровых аватар-слота
        подряд §7.4.3 разорвёт перебивкой, и появление снова развалится.
        """
        head = self.slots[group[0]]
        head.end = self.slots[group[-1]].end
        head.kind = self._target_kind(head.block_id)
        head.mode = "B" if head.kind == "split" else "A"
        head.needs_asset = head.kind == "split"
        head.asset_role = "evidence" if head.kind == "split" else ""
        head.reason = reason
        for j in reversed(group[1:]):
            del self.slots[j]
        notes.append(f"слот {head.start:.2f}–{head.end:.2f} сек отдан аватару: {reason}")


def _longest_footage_run(slots: list[Slot]) -> tuple[float, int, int]:
    """Самый длинный непрерывный кусок без аватара: (длина, первый, последний).

    Совпадает с метрикой ``longest_footage_block_share`` из ``compute_stats``:
    полноэкранный текст и мем тоже «не аватар» и рвут не картинку, а только
    источник кадра.
    """
    best = (0.0, -1, -1)
    start_idx: int | None = None
    for i, slot in enumerate(slots):
        if slot.kind in ("footage", "fullscreen_text", "meme"):
            if start_idx is None:
                start_idx = i
            length = slot.end - slots[start_idx].start
            if length > best[0]:
                best = (length, start_idx, i)
        else:
            start_idx = None
    return best


def _break_long_footage_run(slots: list[Slot], blocks: list[dict[str, Any]], duration: float,
                            max_share: float, share_hi: float,
                            appearance_min: float, appearance_max: float,
                            appearances_max: int, notes: list[str]) -> bool:
    """§3.5: непрерывный футаж не длиннее 40 % хронометража. Вернуть, менялось ли.

    Правило про разнообразие: если картинка полминуты идёт без ведущего, ролик
    перестаёт быть авторским. Лечится тем же действием, что и недобор доли, —
    один футажный слот внутри куска отдаётся аватару. Берём слот ближе к
    середине: он делит кусок на две примерно равные половины, а не отрезает
    хвост, оставляя почти тот же кусок.

    Но чинить одно правило §3.5, ломая соседнее, нельзя: новое появление
    аватара может вывести их число за 2–5. В отличие от доли аватара (QC-2)
    непрерывный футаж — не блокирующая проверка, поэтому при конфликте
    уступает именно он, а в план уходит запись, почему кусок остался длинным.
    """
    conv = _AvatarConversion(slots, blocks, duration, share_hi, appearance_min, appearance_max)
    changed = False
    guard = 0
    while guard < 8:
        guard += 1
        length, first, last = _longest_footage_run(slots)
        if first < 0 or length <= max_share * duration + 1e-3:
            break
        middle = (slots[first].start + slots[last].end) / 2
        inside = [i for i in range(first, last + 1) if conv.is_candidate(i)]
        applied = False
        blocked_by_count = False
        for i in sorted(inside, key=lambda i: abs((slots[i].start + slots[i].end) / 2 - middle)):
            group = conv.plan(i)
            if group is None:
                continue
            if len(_avatar_runs(slots)) >= appearances_max and not conv.extends_existing(group):
                blocked_by_count = True
                continue
            conv.apply(group, f"разрыв непрерывного футажа длиннее {max_share:.0%} (§3.5)", notes)
            applied = changed = True
            break
        if not applied:
            notes.append(
                f"непрерывный футаж {length:.2f} сек длиннее {max_share:.0%} хронометража, "
                + (f"но разрыв дал бы {appearances_max + 1}-е появление аватара при лимите "
                   f"{appearances_max} (§3.5): правило про число появлений строже"
                   if blocked_by_count else
                   "но разорвать нечем: подходящих футажных слотов в блоках без "
                   "директивы avatar: off не нашлось"))
            break
    return changed


def _raise_avatar_share(slots: list[Slot], blocks: list[dict[str, Any]], duration: float,
                        share_lo: float, share_hi: float,
                        appearance_min: float, appearance_max: float,
                        notes: list[str]) -> bool:
    """Добрать долю аватара до нижней границы 35 % (§3.5). Вернуть, менялось ли.

    P1 распределяет режимы кадра по **оценке** длительности блоков, а реальная
    речь ложится иначе: после нарезки слотов, окон полноэкранного текста и
    перебивок доля уезжает ниже порога. Это жёсткое правило (§10.2.2), поэтому
    здесь оно исправляется, а не отмечается предупреждением — предупреждение
    всё равно превратится в провал QC-2 через четыре минуты рендера.
    """
    conv = _AvatarConversion(slots, blocks, duration, share_hi, appearance_min, appearance_max)
    if not conv.allowed:
        return False

    changed = False
    guard = 0
    while _avatar_share(slots, duration) < share_lo and guard < 12:
        guard += 1
        deficit = (share_lo - _avatar_share(slots, duration)) * duration

        def footage_run_after(i: int) -> float:
            """Самый длинный непрерывный футаж, если слот i станет аватарным."""
            longest = run = 0.0
            for j, s in enumerate(slots):
                if j == i or s.kind in AVATAR_KINDS:
                    run = 0.0
                    continue
                run += s.duration
                longest = max(longest, run)
            return longest

        # Сначала кандидаты, которые сразу дают появление нужной длины; затем те,
        # что заодно разрывают самый длинный кусок футажа (§3.5); внутри группы —
        # ближайшие по длительности к недобору, чтобы не проскочить коридор.
        ranked = sorted(conv.candidates(),
                        key=lambda i: (
                            not appearance_min <= conv.span([i]) <= appearance_max,
                            round(footage_run_after(i), 1),
                            abs(slots[i].duration - deficit)))
        applied = False
        for i in ranked:
            group = conv.plan(i)
            if group is None:
                continue
            conv.apply(group, f"добор доли аватара до {share_lo:.0%} по факту таймингов (§3.5)",
                       notes)
            applied = changed = True
            break
        if not applied:
            break

    return changed


def _needs_interstitial(prev: Slot, nxt: Slot) -> bool:
    """Нужна ли перебивка между двумя соседними аватар-слотами.

    Правило §7.4.3 защищает от «прыжка» головы на стыке **двух разных
    генераций** HeyGen, а §4.1 — от кадра, который не меняется:

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


def _trailing_appearance(out: list[Slot]) -> float:
    """Длина появления аватара, которое заканчивается последним слотом ``out``."""
    if not out or out[-1].kind not in AVATAR_KINDS:
        return 0.0
    end = out[-1].end
    start = out[-1].start
    for prev in reversed(out[:-1]):
        if prev.kind not in AVATAR_KINDS or abs(prev.end - start) > 1e-6:
            break
        start = prev.start
    return end - start


def _insert_avatar_interstitials(slots: list[Slot], min_shot: float, appearance_min: float,
                                 notes: list[str]) -> list[Slot]:
    """§7.4.3: два аватар-сегмента подряд без перебивки запрещены (R-3).

    Перебивку стараемся вырезать из **хвоста первого** сегмента: так стык
    закрывается футажом и «прыжок» головы на склейке не виден. Но вырезать
    вслепую нельзя — если появление и без того короткое, вырез оставит от него
    огрызок короче трёх секунд (§3.5). Тогда перебивка забирается из **головы
    второго** сегмента: стык закрыт так же, а укорачивается уже то появление,
    которое только начинается.
    """
    out: list[Slot] = []
    for slot in slots:
        if out and _needs_interstitial(out[-1], slot):
            prev = out[-1]
            cut = min(1.4, max(0.9, prev.duration * 0.35))
            fits_tail = (prev.duration - cut >= min_shot * 0.8
                         and _trailing_appearance(out) - cut >= appearance_min)
            fits_head = slot.duration - cut >= max(min_shot * 0.8, appearance_min)
            if fits_tail:
                inter_start = prev.end - cut
                prev.end = inter_start
                out.append(Slot(
                    index=0, start=inter_start, end=slot.start, kind="footage",
                    block_id=prev.block_id, role=prev.role, mode="C",
                    visual_intent=prev.visual_intent, queries=list(prev.queries),
                    needs_asset=True, asset_role="interstitial",
                    reason="перебивка между аватар-сегментами (§7.4.3, R-3)",
                ))
                notes.append(
                    f"вставлена перебивка {inter_start:.2f}–{slot.start:.2f} сек "
                    f"между аватар-сегментами блоков {prev.block_id}/{slot.block_id}")
            elif fits_head:
                inter_end = slot.start + cut
                out.append(Slot(
                    index=0, start=slot.start, end=inter_end, kind="footage",
                    block_id=slot.block_id, role=slot.role, mode="C",
                    visual_intent=slot.visual_intent, queries=list(slot.queries),
                    needs_asset=True, asset_role="interstitial",
                    reason="перебивка между аватар-сегментами (§7.4.3, R-3)",
                ))
                slot.start = inter_end
                notes.append(
                    f"вставлена перебивка {out[-1].start:.2f}–{inter_end:.2f} сек "
                    f"перед аватар-сегментом блока {slot.block_id}: у предыдущего "
                    f"появления не было запаса до {appearance_min:.0f} сек")
            else:
                # Дробить нечем с обеих сторон — сливаем сегменты.
                slot.start = prev.start
                slot.block_id = prev.block_id if prev.duration > slot.duration else slot.block_id
                out.pop()
                notes.append("смежные аватар-сегменты слиты: перебивка не помещалась")
        out.append(slot)
    return out


def _heal_stub_appearances(slots: list[Slot], appearance_min: float,
                           appearance_max: float, notes: list[str]) -> list[Slot]:
    """Появление короче §3.5 не доживает до кадра — ни в каком виде.

    Проходы выше режут секунды из аватара каждый по своему правилу: перебивка
    §7.4.3 берёт их с хвоста, лимит длины плана §3.6.2 — из середины, дробление
    §3.5 — у границы слотов. Каждый бережёт свой минимум, но ни один не смотрит,
    что осталось после соседа. На 0050 так вышел сегмент в 0.26 сек: ведущий
    выпрыгивал в кадр на четверть секунды и исчезал. Заказчик: «аватар
    выпрыгивает и исчезает быстро, так быть не должно».

    Лечим двумя способами. Если огрызок отделён от соседнего появления одной
    перебивкой и вместе они влезают в 12 сек — перебивка снимается, и это одно
    появление, а не два подряд (QC-18 запрещает именно два подряд, а не длинное
    одно). Не влезают — огрызок становится футажом: лучше лишний кадр материала,
    чем вспышка лица.
    """
    for _ in range(8):
        runs = _avatar_runs(slots)
        stub = next((r for r in runs
                     if slots[r[-1]].end - slots[r[0]].start < appearance_min - 1e-6),
                    None)
        if stub is None:
            return slots
        merged = False
        for other in runs:
            if other[0] <= stub[-1]:
                continue
            # Ровно одна перебивка между огрызком и соседом.
            if other[0] - stub[-1] != 2:
                break
            span = slots[other[-1]].end - slots[stub[0]].start
            if span > appearance_max + 1e-6:
                break
            head, tail = slots[stub[0]], slots[other[-1]]
            notes.append(
                f"появление {slots[stub[0]].start:.2f}–{slots[stub[-1]].end:.2f} сек "
                f"короче {appearance_min:.0f} сек: слито с соседним через снятую "
                f"перебивку в одно появление {head.start:.2f}–{tail.end:.2f} сек")
            head.end = tail.end
            slots = slots[:stub[0] + 1] + slots[other[-1] + 1:]
            merged = True
            break
        if merged:
            continue
        first = slots[stub[0]]
        notes.append(
            f"появление {first.start:.2f}–{slots[stub[-1]].end:.2f} сек короче "
            f"{appearance_min:.0f} сек и слить не с чем: отдано под футаж")
        for i in stub:
            slot = slots[i]
            slot.kind = "footage"
            slot.mode = "C"
            slot.needs_asset = True
            slot.asset_role = slot.asset_role or "broll"
            slot.reason = (f"огрызок появления короче {appearance_min:.0f} сек "
                           f"отдан под футаж (§3.5)")
    return slots


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


def _limit_appearance_length(slots: list[Slot], min_appearance: float, max_appearance: float,
                             min_shot: float, notes: list[str]) -> list[Slot]:
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

        def halves(i: int) -> tuple[float, float, float]:
            """Куски появления слева и справа от перебивки на границе i."""
            prev = slots[i - 1]
            cut = min(1.4, max(0.9, prev.duration * 0.4))
            return cut, prev.end - cut - run_start, run_end - slots[i].start

        # Обе половины обязаны остаться внутри коридора 3–12 сек (§3.5): развалить
        # длинное появление на «12 + огрызок» — то же нарушение, вид сбоку.
        usable = [i for i in target[1:]
                  if min(halves(i)[1:]) >= min_appearance
                  and slots[i - 1].duration - halves(i)[0] >= min_shot * 0.8]
        if not usable:
            notes.append(
                f"появление {run_start:.2f}–{run_end:.2f} сек длиннее {max_appearance} сек, "
                f"но перебивку некуда поставить: любая половина выходит короче "
                f"{min_appearance:.0f} сек")
            break
        boundary_idx = max(usable, key=lambda i: min(halves(i)[1:]))
        prev = slots[boundary_idx - 1]
        cut = halves(boundary_idx)[0]
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


def _cut_away_from_avatar(slot: Slot, max_shot_ev: float, appearance_min: float,
                          words: list[dict[str, Any]], notes: list[str]) -> list[Slot]:
    """Разорвать перебивкой аватар-слот, который висит дольше §3.6.2.

    Появление 3–12 сек законно (§3.5), но одним планом столько висеть нельзя:
    режем не «на два аватара подряд» — это запрещено (QC-18) — а вырезаем из
    середины окно под футаж. Голос под ним продолжает звучать: аватар уходит с
    экрана, речь не прерывается.
    """
    pieces = 2
    while slot.duration / pieces > max_shot_ev:
        pieces += 1
    # Перебивка короче 0.9 сек читается как брак склейки, а не как приём.
    room = (slot.duration - pieces * appearance_min) / (pieces - 1)
    cut = min(min(1.4, max(0.9, slot.duration * 0.15)), room)
    if cut < 0.9 - 1e-9:
        notes.append(
            f"аватар-слот {slot.start:.2f}–{slot.end:.2f} сек висит дольше {max_shot_ev} сек, "
            f"но перебивка не помещается: куски выходят короче {appearance_min:.0f} сек")
        return [slot]
    piece = (slot.duration - cut * (pieces - 1)) / pieces

    bounds = [slot.start]
    for i in range(pieces - 1):
        gap_start = bounds[-1] + piece
        bounds += [gap_start, gap_start + cut]
    bounds.append(slot.end)
    snapped = _snap_avatar_bounds(bounds, words, max_shot_ev, appearance_min)

    out: list[Slot] = []
    for i in range(0, len(snapped) - 1, 2):
        out.append(Slot(**{**slot.__dict__,
                           "start": snapped[i], "end": snapped[i + 1], "events": [],
                           "transition_in": "cut" if i else slot.transition_in}))
        if i + 2 < len(snapped):
            out.append(Slot(
                index=0, start=snapped[i + 1], end=snapped[i + 2], kind="footage",
                block_id=slot.block_id, role=slot.role, mode="C",
                visual_intent=slot.visual_intent, queries=list(slot.queries),
                needs_asset=True, asset_role="broll", transition_in="cut",
                reason="перебивка внутри длинного аватар-плана (§3.6.2, QC-4)",
            ))
    notes.append(f"аватар-план {slot.start:.2f}–{slot.end:.2f} сек разорван "
                 f"{pieces - 1} перебивкой (лимит {max_shot_ev} сек)")
    return out


def _snap_avatar_bounds(bounds: list[float], words: list[dict[str, Any]],
                        max_shot_ev: float, appearance_min: float) -> list[float]:
    """Прижать края перебивки к границам слов — иначе клип аватара режется по слогу.

    P6 берёт в сегмент каждое слово, задевающее его окно (``snap_to_phrase``):
    рез посреди слова отдал бы это слово обоим клипам сразу. Если прижатие
    ломает сами лимиты — оставляем расчётные моменты.
    """
    if not words:
        return bounds
    out = [bounds[0]] + [_snap_to_word(t, words) for t in bounds[1:-1]] + [bounds[-1]]
    for a, b in zip(out, out[1:]):
        if b - a < 0.4:
            return bounds
    for i in range(0, len(out) - 1, 2):
        if not (appearance_min - 1e-6 <= out[i + 1] - out[i] <= max_shot_ev + 1e-6):
            return bounds
    return out


def _enforce_shot_limits(slots: list[Slot], max_shot: float, max_shot_ev: float,
                         min_shot: float, notes: list[str], *,
                         appearance_min: float = 3.0,
                         words: list[dict[str, Any]] | None = None) -> list[Slot]:
    """Ни один слот не висит дольше допустимого (§3.6.2, QC-4).

    Футаж режется на планы: материал тот же, склейка новая. С аватаром так
    нельзя — два аватар-плана подряд это тот же непрерывный кадр (QC-18),
    поэтому длинный аватар разрывается перебивкой.
    """
    out: list[Slot] = []
    for slot in slots:
        if slot.kind == "avatar" and slot.duration > max_shot_ev + 1e-3:
            out.extend(_cut_away_from_avatar(slot, max_shot_ev, appearance_min,
                                             words or [], notes))
            continue
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
        if slot.needs_asset and slot.asset_role in ("broll", "evidence", "interstitial"):
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



def _prepared_avatar_request_path(cfg, video_id: str):
    """Path to assets/avatar_clips/<video_id>/avatar_request.json if usable."""
    from pathlib import Path as _Path
    base = cfg.path("heygen.prepared_dir", "assets/avatar_clips")
    return _Path(base) / str(video_id) / "avatar_request.json"


def load_prepared_avatar_windows(cfg, video_id: str) -> list[dict[str, Any]] | None:
    """Prepared clip windows for ``heygen.source=prepared``.

    Prefers explicit ``start``/``end`` on ``avatar_request.json`` segments
    (round15-green timings). Falls back to ``duration_sec`` only when both
    bounds are present via start+duration.
    """
    from ..lib.jsonio import read_json_or

    if str(cfg.get("heygen.source", "prepared")).lower() != "prepared":
        return None
    path = _prepared_avatar_request_path(cfg, video_id)
    if not path.is_file():
        return None
    req = read_json_or(path, {})
    segments = req.get("segments") or []
    if not segments:
        return None
    windows: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg["start"]) if seg.get("start") is not None else None
            end = float(seg["end"]) if seg.get("end") is not None else None
            dur = float(seg.get("duration_sec") or 0.0)
        except (TypeError, ValueError):
            continue
        if start is None or end is None:
            continue
        if end <= start + 1e-6:
            continue
        # duration_sec is what P6 matches against the webm — keep it.
        if dur > 0 and abs((end - start) - dur) > 0.05:
            end = start + dur
        windows.append({
            "index": int(seg.get("index", len(windows))),
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "block_id": str(seg.get("block_id") or ""),
            "kind": str(seg.get("kind") or "avatar"),
            "mode": str(seg.get("mode") or "A"),
            "text": str(seg.get("text") or ""),
        })
    windows.sort(key=lambda w: (w["start"], w["index"]))
    return windows or None


def _subtract_interval(pieces: list[tuple[float, float]],
                       cut0: float, cut1: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in pieces:
        if cut1 <= a + 1e-9 or cut0 >= b - 1e-9:
            out.append((a, b))
            continue
        if cut0 > a + 1e-9:
            out.append((a, min(b, cut0)))
        if cut1 < b - 1e-9:
            out.append((max(a, cut1), b))
    return [(a, b) for a, b in out if b > a + 1e-6]


def apply_prepared_avatar_windows(
        slots: list[Slot],
        windows: list[dict[str, Any]],
        *,
        duration: float,
        notes: list[str] | None = None) -> list[Slot]:
    """Replace rebuilt avatar/split slots with frozen prepared windows.

    P5 ``build_slots`` re-carves mode-A blocks; prepared seg_*.webm were
    generated for earlier windows. Keep footage/life-beat slots, punch holes
    for the frozen avatar appearances, and restore exact start/end so P6
    duration matches the webm (±0.20s).
    """
    if not windows:
        return slots
    notes = notes if notes is not None else []
    non_av = [s for s in slots if s.kind not in AVATAR_KINDS]
    punched: list[Slot] = []
    for slot in non_av:
        pieces = [(slot.start, slot.end)]
        for win in windows:
            pieces = _subtract_interval(pieces, win["start"], win["end"])
        for a, b in pieces:
            if b - a < 0.05:
                continue
            punched.append(replace(slot, start=a, end=b, events=[]))

    # Fill holes that are not covered by punched non-avatar or windows.
    covered = sorted(
        [(w["start"], w["end"]) for w in windows]
        + [(s.start, s.end) for s in punched],
        key=lambda p: p[0],
    )
    def _gap_ref(gap_start: float, gap_end: float) -> Slot | None:
        """Prefer the enclosing/nearest avatar window block (stamp on b6 gaps).

        Falling back to punched[0] labeled interstitial gaps as b1 and left
        by_block stamp unused (round18 QC-SEMANTIC).
        """
        # Nearest avatar by time (before, else after).
        before = [w for w in windows if float(w["end"]) <= gap_start + 1e-6]
        after = [w for w in windows if float(w["start"]) >= gap_end - 1e-6]
        pick = before[-1] if before else (after[0] if after else None)
        if pick is not None:
            ref = next((s for s in slots if s.block_id == pick.get("block_id")), None)
            return Slot(
                index=0, start=gap_start, end=gap_end, kind="footage",
                block_id=str(pick.get("block_id") or (ref.block_id if ref else "")),
                role=ref.role if ref else "twist",
                mode="C", needs_asset=True, asset_role="broll",
                reason="gap fill around prepared avatar window",
            )
        ref = next((s for s in punched if s.end <= gap_start + 1e-6), None) or (
            punched[0] if punched else (slots[0] if slots else None))
        if ref is None:
            return None
        return Slot(
            index=0, start=gap_start, end=gap_end, kind="footage",
            block_id=ref.block_id, role=ref.role, mode="C",
            needs_asset=True, asset_role="broll",
            reason="gap fill around prepared avatar window",
        )

    fillers: list[Slot] = []
    cursor = 0.0
    for a, b in covered:
        if a > cursor + 0.05:
            gap = _gap_ref(cursor, a)
            if gap is not None:
                fillers.append(gap)
        cursor = max(cursor, b)
    if duration > cursor + 0.05:
        gap = _gap_ref(cursor, duration)
        if gap is not None:
            fillers.append(gap)

    avatars: list[Slot] = []
    for win in windows:
        ref = next((s for s in slots if s.block_id == win["block_id"]), None)
        avatars.append(Slot(
            index=0,
            start=float(win["start"]),
            end=float(win["end"]),
            kind=str(win.get("kind") or "avatar"),
            block_id=str(win.get("block_id") or (ref.block_id if ref else "")),
            role=ref.role if ref else "setup",
            mode=str(win.get("mode") or (ref.mode if ref else "A")),
            visual_intent=ref.visual_intent if ref else "",
            reason="prepared avatar window (frozen for heygen_source=prepared)",
        ))

    out = sorted(punched + fillers + avatars, key=lambda s: (s.start, s.end))
    # Neighbor clamp without stretching avatar durations (close_gaps would).
    out = [s for s in out if s.end > s.start + 1e-6]
    if out:
        if out[0].kind not in AVATAR_KINDS:
            out[0].start = 0.0
        elif out[0].start > 1e-6:
            out.insert(0, Slot(
                index=0, start=0.0, end=out[0].start, kind="footage",
                block_id=out[0].block_id, role=out[0].role, mode="C",
                needs_asset=True, asset_role="broll",
                reason="lead-in before first prepared avatar",
            ))
        for prev, nxt in zip(out, out[1:]):
            if abs(prev.end - nxt.start) <= 1e-9:
                continue
            if prev.kind in AVATAR_KINDS and nxt.kind not in AVATAR_KINDS:
                nxt.start = prev.end
            elif nxt.kind in AVATAR_KINDS and prev.kind not in AVATAR_KINDS:
                prev.end = nxt.start
            elif prev.kind not in AVATAR_KINDS and nxt.kind not in AVATAR_KINDS:
                prev.end = nxt.start
            # avatar|avatar gap: insert interstitial rather than stretch
            elif prev.kind in AVATAR_KINDS and nxt.kind in AVATAR_KINDS and nxt.start > prev.end + 0.05:
                pass  # fillers already cover; leave
        if out[-1].kind not in AVATAR_KINDS:
            out[-1].end = duration
        elif out[-1].end < duration - 1e-6:
            out.append(Slot(
                index=0, start=out[-1].end, end=duration, kind="footage",
                block_id=out[-1].block_id, role=out[-1].role, mode="C",
                needs_asset=True, asset_role="broll",
                reason="tail after last prepared avatar",
            ))

    # Drop zero/negative after clamps; reindex.
    cleaned: list[Slot] = []
    for slot in out:
        if slot.end - slot.start < 0.05 and slot.kind not in AVATAR_KINDS:
            continue
        if slot.end <= slot.start + 1e-6:
            continue
        cleaned.append(slot)
    for i, slot in enumerate(cleaned):
        slot.index = i

    # Restore exact prepared bounds (clamps must not drift lipsync windows).
    av_i = 0
    for slot in cleaned:
        if slot.kind not in AVATAR_KINDS:
            continue
        if av_i >= len(windows):
            break
        slot.start = float(windows[av_i]["start"])
        slot.end = float(windows[av_i]["end"])
        slot.block_id = str(windows[av_i].get("block_id") or slot.block_id)
        av_i += 1
        if av_i >= 2:
            # ensure previous non-avatar ends at this start
            pass
    for i, slot in enumerate(cleaned):
        if slot.kind not in AVATAR_KINDS:
            continue
        if i > 0 and cleaned[i - 1].kind not in AVATAR_KINDS:
            cleaned[i - 1].end = slot.start
        if i + 1 < len(cleaned) and cleaned[i + 1].kind not in AVATAR_KINDS:
            cleaned[i + 1].start = slot.end

    notes.append(
        f"prepared avatar windows frozen: {len(windows)} clips "
        f"(heygen_source=prepared)")
    return cleaned



def reinsert_gaps_between_prepared_avatars(
        slots: list[Slot],
        *,
        notes: list[str] | None = None,
        min_gap: float = 0.05) -> list[Slot]:
    """Fill timeline holes between frozen avatar windows (and other coverage).

    densify neighbor-clamp + b6 keyword snap can drop the 1.2s interstitial
    between 0050 seg_02/seg_03; vision then samples a navy void (QC-SEMANTIC).
    """
    notes = notes if notes is not None else []
    if not slots:
        return slots
    covered = sorted(((s.start, s.end) for s in slots), key=lambda p: p[0])
    fillers: list[Slot] = []
    cursor = 0.0
    for a, b in covered:
        if a > cursor + min_gap:
            bid = ""
            role = "twist"
            for s in slots:
                if s.kind in AVATAR_KINDS and s.end <= a + 1e-6:
                    bid, role = s.block_id, s.role
            if not bid:
                for s in slots:
                    if s.kind in AVATAR_KINDS and s.start >= a - 1e-6:
                        bid, role = s.block_id, s.role
                        break
            fillers.append(Slot(
                index=0, start=cursor, end=a, kind="footage",
                block_id=bid or "b6", role=role or "twist", mode="C",
                needs_asset=True, asset_role="broll",
                reason="gap fill around prepared avatar window | densify reinsert",
            ))
            notes.append(
                f"prepared-avatar densify: reinserted gap fill "
                f"{cursor:.3f}–{a:.3f} (block {bid or 'b6'})")
        cursor = max(cursor, b)
    if not fillers:
        return slots
    out = list(slots) + fillers
    out.sort(key=lambda s: (s.start, s.end))
    for i, slot in enumerate(out):
        slot.index = i
    return out


def densify_after_prepared_freeze(
        slots: list[Slot],
        cfg,
        *,
        draft: dict[str, Any] | None = None,
        words: list[dict[str, Any]] | None = None,
        notes: list[str] | None = None) -> list[Slot]:
    """Restore QC-3/4 density after prepared-avatar freeze.

    Freeze punches avatar holes and clears events, which can leave a long
    continuous footage gap (and ``max_event_gap_sec`` ≈ full duration). Keep
    every prepared avatar start/end/duration untouched.

    Prefer **internal events / transitions inside one shot** (QC-3/4) over
    splitting into many asset slots that would need the same by_block pin
    (QC-5 phash clones). Only split when longer than
    ``max_shot_sec_with_events``; shorter long-shots stay one plate and get
    kenburns/push events below.
    """
    notes = notes if notes is not None else []
    limits = cfg.get("limits")
    min_shot = float(limits.get("min_shot_sec", 1.5))
    max_shot = float(limits.get("max_shot_sec", 5.0))
    max_shot_ev = float(limits.get("max_shot_sec_with_events", 7.0))
    max_gap = float(limits.get("max_event_gap_sec", 2.5))
    first_event = float(limits.get("first_event_sec", 0.8))

    # Snapshot prepared avatar bounds so densify cannot drift lipsync windows.
    frozen = [(s.start, s.end) for s in slots if s.kind in AVATAR_KINDS]

    out: list[Slot] = []
    split_notes = 0
    event_kept = 0
    for slot in slots:
        if slot.kind in AVATAR_KINDS:
            out.append(slot)
            continue
        if slot.kind not in ("footage", "split"):
            out.append(slot)
            continue
        # One plate + internal events covers QC-3/4 up to max_shot_ev.
        if slot.duration <= max_shot_ev + 1e-3:
            if slot.duration > max_shot + 1e-3:
                event_kept += 1
            out.append(slot)
            continue
        # Must split: keep each sibling ≤ max_shot_ev so events still qualify.
        parts = _split_span(
            slot.start, slot.end, target=max_shot_ev * 0.75,
            min_len=min_shot, max_len=max_shot_ev, words=words or [])
        for i, (s, e) in enumerate(parts):
            clone = Slot(**{**slot.__dict__, "start": s, "end": e, "events": [],
                            "reason": (slot.reason + " | densify after prepared freeze").strip(" |")})
            if i:
                clone.transition_in = "cut"
            out.append(clone)
        split_notes += 1
        notes.append(
            f"футаж {slot.start:.2f}–{slot.end:.2f} разрезан на {len(parts)} плана "
            f"после freeze prepared-avatar (лимит с событиями {max_shot_ev} сек)")
    if event_kept:
        notes.append(
            f"prepared-avatar densify: kept {event_kept} long shot(s) as one "
            f"plate with internal events (≤{max_shot_ev}s, avoid QC-5 clones)")
    if split_notes:
        notes.append(
            f"prepared-avatar densify: split {split_notes} long non-avatar shot(s)")

    out.sort(key=lambda s: (s.start, s.end))
    for i, slot in enumerate(out):
        slot.index = i

    # Re-assert exact frozen avatar bounds (split neighbors only).
    av_i = 0
    for i, slot in enumerate(out):
        if slot.kind not in AVATAR_KINDS:
            continue
        if av_i >= len(frozen):
            break
        slot.start, slot.end = frozen[av_i]
        av_i += 1
        if i > 0 and out[i - 1].kind not in AVATAR_KINDS:
            out[i - 1].end = slot.start
        if i + 1 < len(out) and out[i + 1].kind not in AVATAR_KINDS:
            out[i + 1].start = slot.end

    # Drop collapsed non-avatar crumbs from neighbor clamps.
    cleaned: list[Slot] = []
    for slot in out:
        if slot.end - slot.start < 0.05 and slot.kind not in AVATAR_KINDS:
            continue
        if slot.end <= slot.start + 1e-6:
            continue
        cleaned.append(slot)
    for i, slot in enumerate(cleaned):
        slot.index = i

    cleaned = reinsert_gaps_between_prepared_avatars(cleaned, notes=notes)

    if draft is not None:
        _assign_queries(cleaned, draft)
    _add_internal_events(cleaned, max_gap, first_event, notes)
    _assign_transitions(cleaned, cfg, notes)
    notes.append(
        "prepared-avatar densify: internal events restored for QC-3/QC-4 "
        "(avatar windows unchanged)")
    return cleaned


def _slots_from_plan_dicts(raw_slots: list[Any]) -> list[Slot]:
    """Rebuild Slot objects from cut_plan slot dicts (post-snap refresh)."""
    out: list[Slot] = []
    for i, s in enumerate(raw_slots or []):
        if not isinstance(s, dict):
            continue
        out.append(Slot(
            index=int(s.get("index") or i),
            start=float(s["start"]), end=float(s["end"]),
            kind=str(s.get("kind") or "footage"),
            block_id=str(s.get("block_id") or ""),
            role=str(s.get("role") or ""),
            mode=str(s.get("mode") or "C"),
            visual_intent=str(s.get("visual_intent") or ""),
            queries=list(s.get("queries") or []),
            content=str(s.get("content") or ""),
            transition_in=str(s.get("transition_in") or "cut"),
            events=list(s.get("events") or []),
            needs_asset=bool(s.get("needs_asset")),
            asset_role=str(s.get("asset_role") or ""),
            template_hint=str(s.get("template_hint") or ""),
            meme_emotion=str(s.get("meme_emotion") or ""),
            beat=str(s.get("beat") or "stretch"),
            reason=str(s.get("reason") or ""),
        ))
    return out


def enforce_prepared_avatar_on_plan(
        plan: dict[str, Any],
        windows: list[dict[str, Any]]) -> int:
    """Re-assert prepared avatar start/end on cut_plan slots after footage snap."""
    if not windows or not isinstance(plan.get("slots"), list):
        return 0
    slots = [s for s in plan["slots"] if isinstance(s, dict)]
    av = [s for s in slots if str(s.get("kind") or "") in AVATAR_KINDS]
    av.sort(key=lambda s: float(s.get("start") or 0.0))
    changed = 0
    for slot, win in zip(av, windows):
        for key in ("start", "end"):
            val = float(win[key])
            if abs(float(slot.get(key) or 0.0) - val) > 1e-6:
                slot[key] = val
                changed += 1
        slot["duration"] = round(float(win["end"]) - float(win["start"]), 3)
        if win.get("block_id"):
            slot["block_id"] = win["block_id"]
    plan["avatar_segments"] = [
        {"index": i, "slot_index": s.get("index", i),
         "start": round(float(s["start"]), 3),
         "end": round(float(s["end"]), 3),
         "duration": round(float(s["end"]) - float(s["start"]), 3),
         "block_id": s.get("block_id"), "mode": s.get("mode"),
         "kind": s.get("kind")}
        for i, s in enumerate(av[:len(windows)])
    ]
    return changed


def run_step(ctx) -> dict[str, Any]:
    draft = ctx.read("draft_plan.json")
    words_doc = ctx.read("words.json")
    words = list(words_doc.get("words") or [])
    sync_overlays_from_script(draft, ctx.cfg.repo_root, words=words)
    # Persist remapped life-beat block_ids so P6+ karaoke/judge see «Погода».
    ctx.write("words.json", words_doc)

    built = build_slots(draft, words_doc, ctx.cfg)
    slots: list[Slot] = built["slots"]
    duration = built["duration"]
    if not slots:
        raise RedshiftError("монтажный план пуст: нет ни одного слота",
                            code="EMPTY_CUT_PLAN")

    warnings: list[str] = list(built["notes"])
    prepared_windows = load_prepared_avatar_windows(ctx.cfg, draft["video_id"])
    if prepared_windows:
        slots = apply_prepared_avatar_windows(
            slots, prepared_windows, duration=duration, notes=warnings)
        # Freeze clears events and can leave long footage gaps — densify
        # non-avatar shots + restore events without touching prepared windows.
        slots = densify_after_prepared_freeze(
            slots, ctx.cfg, draft=draft, words=words, notes=warnings)

    # Карта битов §6.1 — до статистики: счётчик битов уходит в неё же.
    beat_counts = annotate_slots(slots, draft["blocks"])

    stats = compute_stats(slots, duration)
    stats["beats"] = beat_counts
    limits = ctx.cfg.get("limits")
    lo_share, hi_share = limits.get("avatar_share", [0.35, 0.50])
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
        # Тема ролика едет дальше по конвейеру: приём «заголовок за головой»
        # ставит за ведущим именно её, а не обрывок текущей реплики.
        "title": draft.get("title", ""),
        "fps": ctx.cfg.fps,
        "duration_sec": round(duration, 3),
        "target_duration_sec": draft["target_duration_sec"],
        "music_mood": draft["music_mood"],
        "music_tags": draft.get("music_tags", []),
        "category": draft.get("category"),
        "sources": draft.get("sources", []),
        "cta": draft.get("cta", {}),
        "cta_window": [round(max(0.0, duration - cta_tail), 3), round(duration, 3)],
        "hook_window": [0.0, float(limits.get("hook_sec", 3.0))],
        "hook": draft.get("hook", {}),
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
    from ..lib.text import snap_block_windows_to_keywords
    snap_block_windows_to_keywords(
        plan_doc, words, repo_root=ctx.cfg.repo_root)
    if prepared_windows:
        enforce_prepared_avatar_on_plan(plan_doc, prepared_windows)
        # Keyword snap may stretch non-avatar windows; densify once more,
        # then hard-snap avatar bounds and refresh events/stats.
        plan_slots = densify_after_prepared_freeze(
            _slots_from_plan_dicts(plan_doc.get("slots") or []),
            ctx.cfg, draft=draft, words=words, notes=warnings)
        av_i = 0
        for i, slot in enumerate(plan_slots):
            if slot.kind not in AVATAR_KINDS:
                continue
            if av_i >= len(prepared_windows):
                break
            win = prepared_windows[av_i]
            slot.start = float(win["start"])
            slot.end = float(win["end"])
            if win.get("block_id"):
                slot.block_id = str(win["block_id"])
            av_i += 1
            if i > 0 and plan_slots[i - 1].kind not in AVATAR_KINDS:
                plan_slots[i - 1].end = slot.start
            if i + 1 < len(plan_slots) and plan_slots[i + 1].kind not in AVATAR_KINDS:
                plan_slots[i + 1].start = slot.end
        plan_slots = [s for s in plan_slots
                      if s.end > s.start + 1e-6 and (
                          s.kind in AVATAR_KINDS or s.end - s.start >= 0.05)]
        for i, slot in enumerate(plan_slots):
            slot.index = i
        # Last pass: keyword snap + neighbor clamp may have cleared the
        # seg_02→seg_03 hole again — force gap fills after all mutations.
        plan_slots = reinsert_gaps_between_prepared_avatars(
            plan_slots, notes=warnings)
        _add_internal_events(
            plan_slots,
            float(ctx.cfg.get("limits.max_event_gap_sec", 2.5)),
            float(ctx.cfg.get("limits.first_event_sec", 0.8)),
            warnings)
        _assign_transitions(plan_slots, ctx.cfg, warnings)
        plan_doc["slots"] = [s.to_dict() for s in plan_slots]
        plan_doc["avatar_segments"] = [
            {"index": i, "slot_index": s.index, "start": round(s.start, 3),
             "end": round(s.end, 3), "duration": round(s.duration, 3),
             "block_id": s.block_id, "mode": s.mode, "kind": s.kind}
            for i, s in enumerate(s for s in plan_slots if s.kind in AVATAR_KINDS)
        ]
        stats = compute_stats(plan_slots, duration)
        stats["beats"] = beat_counts
        plan_doc["stats"] = stats
        plan_doc["notes"] = warnings

    else:
        # Без замороженных окон весь ремонт выше не делается, а привязка к
        # ключевым словам границы всё равно двигает — и таймлайн остаётся
        # рваным. На 0050 r62 это дало наложения (слот кончался на 34.37, а
        # следующий начинался с 34.07), перебивку b6, уехавшую на четыре
        # секунды от своего места, и два огрызка по 0.7 сек подряд, из которых
        # второй остался вовсе без материала.
        #
        # Раньше не всплывало: 0050 всегда шёл с заявкой, где у сегментов были
        # `start`/`end`, — то есть по защищённой ветке. Заявка фазы 1 несёт
        # только длительности, и ветка оказалась другой.
        plan_slots = close_gaps(
            _slots_from_plan_dicts(plan_doc.get("slots") or []), duration)
        for i, slot in enumerate(plan_slots):
            slot.index = i
        _add_internal_events(
            plan_slots,
            float(ctx.cfg.get("limits.max_event_gap_sec", 2.5)),
            float(ctx.cfg.get("limits.first_event_sec", 0.8)),
            warnings)
        _assign_transitions(plan_slots, ctx.cfg, warnings)
        plan_doc["slots"] = [s.to_dict() for s in plan_slots]
        plan_doc["avatar_segments"] = [
            {"index": i, "slot_index": s.index, "start": round(s.start, 3),
             "end": round(s.end, 3), "duration": round(s.duration, 3),
             "block_id": s.block_id, "mode": s.mode, "kind": s.kind}
            for i, s in enumerate(s for s in plan_slots if s.kind in AVATAR_KINDS)
        ]
        stats = compute_stats(plan_slots, duration)
        stats["beats"] = beat_counts
        plan_doc["stats"] = stats
        plan_doc["notes"] = warnings

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

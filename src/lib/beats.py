"""Карта битов: из сценария в монтажный план (§6.1, R-1).

`script_playbook.md` §3 описывает пять битов — Удар / Вопрос / Затяжка /
Ответ / Осадок+CTA, — и P0 их валидирует (`PAYOFF_EARLIEST_SHARE`,
`PAYOFF_LATEST_SHARE`, `PAYOFF_RESTATES_SETUP`). Но до монтажа карта не
доезжала: в `edit_plan` не было поля `beat`, и `assemble` принимал решения по
`role`, которая говорит о **содержании** блока, а не о его месте в петле
удержания. Роль «evidence» бывает и затяжкой, и ответом.

Здесь карта считается один раз и кладётся в слот. Одно место правды: тот же
`answer_block_index` использует и P0 для своих предупреждений — иначе гейт и
монтаж разошлись бы в том, где именно ролик отвечает на хук.
"""

from __future__ import annotations

from typing import Any, Sequence

BEATS = ("hit", "question", "stretch", "payoff", "residue")

# Удар — это первые секунды, а не весь блок хука: длинный хук успевает
# превратиться в вопрос ещё до того, как кончится.
HIT_MAX_SEC = 1.6


def answer_block_index(blocks: Sequence[dict[str, Any]]) -> int | None:
    """Где закрывается гештальт хука.

    Явная пометка сценариста сильнее роли: ``answers_hook`` ставят там, где
    ответ не совпал с ``twist``.
    """
    for i, block in enumerate(blocks):
        if block.get("answers_hook"):
            return i
    for i, block in enumerate(blocks):
        if block.get("role") == "twist":
            return i
    return None


def beat_by_block(blocks: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Бит каждого блока сценария.

    Правило простое и целиком выводится из формы петли:

    * ``hook`` — удар;
    * блок, закрывающий хук, — ответ;
    * всё между ударом и ответом — вопрос (первый) и затяжка (остальные);
    * ``cta`` и всё после ответа — осадок.

    Если ответа в сценарии нет (P0 предупредит об этом отдельно), последний
    неCTA-блок считается ответом: ролик всё равно где-то заканчивает мысль, и
    монтажу нужно знать где.
    """
    if not blocks:
        return {}
    ids = [str(b.get("id") or f"b{i}") for i, b in enumerate(blocks)]
    roles = [str(b.get("role") or "") for b in blocks]

    answer_i = answer_block_index(blocks)
    if answer_i is None:
        body = [i for i, r in enumerate(roles) if r not in ("hook", "cta")]
        answer_i = body[-1] if body else None

    out: dict[str, str] = {}
    seen_question = False
    for i, block_id in enumerate(ids):
        if roles[i] == "hook":
            out[block_id] = "hit"
            continue
        if roles[i] == "cta":
            out[block_id] = "residue"
            continue
        if answer_i is not None and i == answer_i:
            out[block_id] = "payoff"
            continue
        if answer_i is not None and i > answer_i:
            out[block_id] = "residue"
            continue
        if not seen_question:
            out[block_id] = "question"
            seen_question = True
        else:
            out[block_id] = "stretch"
    return out


def beat_for_slot(slot_start: float, slot_block_id: str, block_beat: str, *,
                  hook_start: float = 0.0) -> str:
    """Бит слота: бит его блока, уточнённый по времени внутри блока хука.

    Хук длиной в четыре секунды — это удар и сразу за ним вопрос, а не четыре
    секунды удара: §6.1 запрещает на ударе «заставку и статичную голову», и
    держать этот запрет всю первую четверть ролика значило бы запретить
    ведущего там, где он как раз уместен.
    """
    if block_beat != "hit":
        return block_beat
    return "hit" if (slot_start - hook_start) <= HIT_MAX_SEC else "question"


def annotate_slots(slots: Sequence[Any], blocks: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Проставить ``beat`` каждому слоту. Работает и на `Slot`, и на словаре.

    Возвращает счётчик по битам — он уходит в `stats`, чтобы карту можно было
    прочитать в отчёте, а не выводить заново из плана.
    """
    mapping = beat_by_block(blocks)
    hook_start = 0.0
    for slot in slots:
        block_id = _get(slot, "block_id")
        if mapping.get(str(block_id)) == "hit":
            hook_start = float(_get(slot, "start") or 0.0)
            break

    counts: dict[str, int] = {}
    for slot in slots:
        block_id = str(_get(slot, "block_id") or "")
        block_beat = mapping.get(block_id, "stretch")
        beat = beat_for_slot(float(_get(slot, "start") or 0.0), block_id,
                             block_beat, hook_start=hook_start)
        _set(slot, "beat", beat)
        counts[beat] = counts.get(beat, 0) + 1
    return counts


def _get(slot: Any, key: str) -> Any:
    if isinstance(slot, dict):
        return slot.get(key)
    return getattr(slot, key, None)


def _set(slot: Any, key: str, value: Any) -> None:
    if isinstance(slot, dict):
        slot[key] = value
    else:
        setattr(slot, key, value)

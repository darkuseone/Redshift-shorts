"""Ротатор типов концовки (§6.4).

Канал закончился одинаково шесть роликов подряд: `redshift_0042…0047` все
писали ``cta.type: "question"``, а старый перечень знал ровно три типа. Восемь
типов сами по себе ничего не меняют — нужна **память**, иначе автор снова
выберет привычное. Память живёт в `config/editing_preferences.json` рядом с
остальными накопленными предпочтениями монтажа, а не в отдельном файле: это
то же самое знание «как канал монтируется», просто про последний кадр.

Правила §6.4, все три:

* тот же тип **не** два ролика подряд;
* ``soft_subscribe`` — не чаще одного раза на три ролика;
* ``visual_loop_seam`` разрешён, только если ролик проходит QC-27 — здесь это
  выражено как предусловие вызова: тип предлагается лишь тогда, когда монтаж
  умеет сомкнуть шов (``allow_loop_seam``).

Модуль ничего не решает за автора: если в сценарии тип задан, он остаётся.
Ротатор нужен там, где типа нет, и для предупреждения `CTA_TYPE_REPEATS`.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Sequence

from .jsonio import read_json_or, write_json
from .schema import CTA_TYPES

# Кольцо по умолчанию. Порядок не случайный: сильные типы («вопрос», «голосуй»,
# «вторая часть») стоят первыми, просьбы — последними, чтобы канал по умолчанию
# заканчивался интересом, а не просьбой.
ENDING_RING_DEFAULT: tuple[str, ...] = (
    "open_question", "binary_vote", "part2_cliff", "share_prompt",
    "source_tease", "save_prompt", "visual_loop_seam", "soft_subscribe",
)

# «≤ 1 из 3»: если просьба о подписке стоит в одном из двух предыдущих роликов,
# третьим её ставить нельзя.
SOFT_SUBSCRIBE = "soft_subscribe"
SOFT_SUBSCRIBE_WINDOW = 3

LOOP_SEAM = "visual_loop_seam"


def _prefs_path(cfg) -> Path:
    return cfg.repo_root / "config" / "editing_preferences.json"


def load_prefs(cfg) -> dict[str, Any]:
    return read_json_or(_prefs_path(cfg), {"version": 1, "runs": [],
                                           "situation_weights": {}, "defaults": {}})


def ending_ring(cfg, prefs: dict[str, Any] | None = None) -> list[str]:
    """Кольцо ротации: из предпочтений, отфильтрованное по известным типам."""
    prefs = load_prefs(cfg) if prefs is None else prefs
    ring = [str(t) for t in prefs.get("ending_ring", []) if t in CTA_TYPES]
    return ring or list(ENDING_RING_DEFAULT)


def ending_history(prefs: dict[str, Any]) -> list[str]:
    """Типы концовок последних роликов, свежий — последний."""
    return [str(r.get("type")) for r in prefs.get("ending_history", [])
            if r.get("type") in CTA_TYPES]


def last_ending_type(cfg, prefs: dict[str, Any] | None = None) -> str | None:
    prefs = load_prefs(cfg) if prefs is None else prefs
    history = ending_history(prefs)
    if history:
        return history[-1]
    last = prefs.get("ending_last_type")
    return str(last) if last in CTA_TYPES else None


def allowed_types(cfg, *, prefs: dict[str, Any] | None = None,
                  allow_loop_seam: bool = False) -> list[str]:
    """Типы, которые правила §6.4 разрешают следующему ролику.

    Пустым список не бывает: кольцо из восьми типов при двух запретах всегда
    оставляет чем закончить. Но если предпочтения сузили кольцо до одного типа
    и он же был последним, честнее вернуть его, чем сорвать сборку — правило
    «не два подряд» мягче, чем «ролик без концовки».
    """
    prefs = load_prefs(cfg) if prefs is None else prefs
    ring = ending_ring(cfg, prefs)
    history = ending_history(prefs)
    last = history[-1] if history else last_ending_type(cfg, prefs)
    recent = history[-(SOFT_SUBSCRIBE_WINDOW - 1):]

    allowed = []
    for kind in ring:
        if kind == last:
            continue
        if kind == SOFT_SUBSCRIBE and SOFT_SUBSCRIBE in recent:
            continue
        if kind == LOOP_SEAM and not allow_loop_seam:
            continue
        allowed.append(kind)
    return allowed or [k for k in ring if k != LOOP_SEAM or allow_loop_seam] or ring


def next_ending_type(cfg, *, allow_loop_seam: bool = False,
                     prefs: dict[str, Any] | None = None) -> str:
    """Следующий тип концовки по кольцу — детерминированно, без случайности.

    Берётся первый разрешённый тип, стоящий в кольце **после** последнего
    использованного: так канал идёт по кругу, а не колеблется между двумя
    любимыми типами.
    """
    prefs = load_prefs(cfg) if prefs is None else prefs
    ring = ending_ring(cfg, prefs)
    allowed = allowed_types(cfg, prefs=prefs, allow_loop_seam=allow_loop_seam)
    last = last_ending_type(cfg, prefs)
    start = ring.index(last) + 1 if last in ring else 0
    for offset in range(len(ring)):
        kind = ring[(start + offset) % len(ring)]
        if kind in allowed:
            return kind
    return allowed[0]


def repeats_previous(cfg, kind: str, *, video_id: str = "",
                     prefs: dict[str, Any] | None = None) -> bool:
    """Тот же тип, что и у предыдущего ролика (§6.4, первое правило).

    ``video_id`` обязателен там, где сценарий уже мог попасть в историю:
    пересборка 0042 иначе сообщает, что 0042 повторяет 0042. Ролик не
    повторяет сам себя — он и есть последняя запись.
    """
    prefs = load_prefs(cfg) if prefs is None else prefs
    history = prefs.get("ending_history") or []
    if video_id and history and str(history[-1].get("video_id")) == video_id:
        return False
    return bool(kind) and kind == last_ending_type(cfg, prefs)


def record_ending(cfg, *, video_id: str, kind: str,
                  history_max: int = 24) -> dict[str, Any]:
    """Запомнить, чем закончился ролик. Идемпотентно по ``video_id``.

    Пишется только после того, как ролик собран и прошёл QC: незачем сдвигать
    кольцо на прогонах, которые не дошли до выдачи.
    """
    if kind not in CTA_TYPES:
        return {"recorded": False, "reason": f"неизвестный тип концовки: {kind!r}"}
    path = _prefs_path(cfg)
    prefs = load_prefs(cfg)
    history = [r for r in prefs.get("ending_history", [])
               if r.get("video_id") != video_id]
    history.append({"video_id": video_id, "type": kind,
                    "recorded_at": _dt.date.today().isoformat()})
    prefs["ending_history"] = history[-history_max:]
    prefs["ending_last_type"] = kind
    prefs.setdefault("ending_ring", list(ENDING_RING_DEFAULT))
    prefs["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    write_json(path, prefs)
    return {"recorded": True, "video_id": video_id, "type": kind,
            "history": len(prefs["ending_history"])}


def normalize_cta_type(kind: Any, legacy: dict[str, str] | None = None) -> str | None:
    """Старое имя типа → новое. Неизвестное имя возвращается как есть.

    Схема отвергнет незнакомый тип сама и назовёт его в ошибке — подменять его
    здесь молча значило бы прятать опечатку.
    """
    from .schema import CTA_LEGACY

    if not isinstance(kind, str) or not kind:
        return None
    table = CTA_LEGACY if legacy is None else legacy
    return table.get(kind, kind)


def rotate_from(ring: Sequence[str], last: str | None) -> list[str]:
    """Кольцо, повёрнутое так, что после ``last`` идёт первый элемент."""
    items = list(ring)
    if last not in items:
        return items
    cut = items.index(last) + 1
    return items[cut:] + items[:cut]


# --- кольца звука (§10.1, §10.3) ---------------------------------------------
#
# Живут в том же файле предпочтений и по той же механике, что кольцо концовок:
# «что звучало в последних роликах». Отдельный модуль под них заводить незачем —
# это одно и то же знание о канале, просто про звук.

RING_MAX = 3


def push_ring(cfg, key: str, value: str, *, limit: int = RING_MAX) -> list[str]:
    """Добавить значение в кольцо последних N. Идемпотентно по значению.

    Возвращает кольцо после записи. Пустое значение игнорируется: писать в
    память «ничего не звучало» бессмысленно, а вычищать потом — работа.
    """
    if not value:
        return [str(v) for v in (load_prefs(cfg).get(key) or [])]
    prefs = load_prefs(cfg)
    ring = [str(v) for v in (prefs.get(key) or []) if str(v) != value]
    ring.append(value)
    prefs[key] = ring[-limit:]
    prefs["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    write_json(_prefs_path(cfg), prefs)
    return prefs[key]


def ring(cfg, key: str) -> list[str]:
    return [str(v) for v in (load_prefs(cfg).get(key) or [])]

"""Привязка к ключевым словам не двигает перебивку между аватар-планами.

0050 r62. `snap_block_windows_to_keywords` переписывает окна b5*/b6/b7 по
произнесённым ключевым словам — приём против съехавшего плана. Защита от
сдвига перебивок в ней была, но искала в причине слота подстроку ``gap fill``:
так подписывает вставки `reinsert_gaps_between_prepared_avatars`. P5 свои
подписывает по-русски, и защита их не узнавала.

Что из этого вышло в кадре: обе перебивки b6 уехали на четыре секунды вперёд и
легли двумя огрызками по 0.7 сек подряд, второй — вовсе без материала, а
соседний аватар-план растянулся на 1.4 сек сверх длины своего клипа. Ролик при
этом не выдали: VFX-фон под растянутым планом стал 5.05 сек при потолке 5.0, и
QC-33 закрыл выдачу.
"""
from src.lib.text import snap_block_windows_to_keywords

INTERSTITIAL = "перебивка между аватар-сегментами (§7.4.3, R-3)"


def _slot(index, start, end, kind, block_id, reason=""):
    return {"index": index, "start": start, "end": end,
            "duration": round(end - start, 3), "kind": kind,
            "block_id": block_id, "reason": reason}


def _words(spans):
    return [{"display": w, "start": s, "end": e, "block_id": b}
            for w, s, e, b in spans]


def _plan():
    return {
        "video_id": "redshift_0050",
        "slots": [
            _slot(0, 43.67, 48.20, "footage", "b5e"),
            _slot(1, 48.20, 51.89, "avatar", "b6"),
            _slot(2, 51.89, 53.29, "footage", "b6", INTERSTITIAL),
            _slot(3, 53.29, 56.65, "avatar", "b6"),
            _slot(4, 56.65, 58.05, "footage", "b6", INTERSTITIAL),
            _slot(5, 58.05, 62.94, "avatar", "b6"),
            _slot(6, 62.94, 65.57, "footage", "b7"),
        ],
        "blocks": [
            {"id": "b6", "text": "Lean проверяет каждый шаг. Но пункт без "
                                 "внешней силы Клей не принял."},
            {"id": "b7", "text": "Какую из оставшихся шести разберём следующей?"},
        ],
    }


WORDS = _words([
    ("Lean", 48.2, 48.6, "b6"),
    ("проверяет", 48.6, 49.2, "b6"),
    ("Клей", 56.9, 57.3, "b6"),      # ключевое слово далеко от перебивок
    ("не", 57.3, 57.5, "b6"),
    ("принял", 57.5, 58.0, "b6"),
    ("Какую", 63.1, 63.6, "b7"),
    ("шести", 64.0, 64.5, "b7"),
])


def _windows(plan, kind=None, block=None):
    return [(s["start"], s["end"]) for s in plan["slots"]
            if (kind is None or s["kind"] == kind)
            and (block is None or s["block_id"] == block)]


def test_the_interstitials_keep_their_windows():
    plan = _plan()
    before = [(s["start"], s["end"]) for s in plan["slots"]
              if s["reason"] == INTERSTITIAL]
    snap_block_windows_to_keywords(plan, WORDS)
    after = [(s["start"], s["end"]) for s in plan["slots"]
             if s["reason"] == INTERSTITIAL]
    assert after == before


def test_the_avatar_plans_keep_their_windows():
    plan = _plan()
    before = _windows(plan, kind="avatar")
    snap_block_windows_to_keywords(plan, WORDS)
    assert _windows(plan, kind="avatar") == before


def test_the_timeline_stays_continuous():
    plan = _plan()
    snap_block_windows_to_keywords(plan, WORDS)
    ordered = sorted(plan["slots"], key=lambda s: s["start"])
    for prev, nxt in zip(ordered, ordered[1:]):
        assert abs(prev["end"] - nxt["start"]) < 1e-6, (prev, nxt)


def test_no_slot_is_left_shorter_than_a_beat():
    # Огрызок в 0.7 сек читается как мигание, а не как кадр (§6.2 R-3).
    plan = _plan()
    snap_block_windows_to_keywords(plan, WORDS)
    assert [s["index"] for s in plan["slots"]
            if s["end"] - s["start"] < 1.0] == []


def test_plain_footage_of_the_block_still_snaps():
    # Смысл приёма сохраняется: обычный футажный слот блока к слову привязать
    # можно — нельзя только перебивку и аватар.
    plan = {
        "video_id": "redshift_0050",
        "slots": [_slot(0, 40.0, 42.0, "footage", "b5c")],
        "blocks": [{"id": "b5c", "text": "Крыло самолёта."}],
    }
    snap_block_windows_to_keywords(
        plan, _words([("Крыло", 44.0, 44.6, "b5c"),
                      ("самолёта", 44.6, 45.4, "b5c")]))
    assert plan["slots"][0]["start"] > 42.0

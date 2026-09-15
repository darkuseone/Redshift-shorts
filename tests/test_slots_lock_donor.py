"""Замок слотов обязан двигать слоты, а не выходить молча.

Девять раундов ``apply_lock_after_p8`` не переставил ни одного слота: он
спрашивал у принятой записи ключи ``file``/``dst``, которых P7 туда не кладёт
(там ``storage_key`` и ``local_file``). Ни одна строка заявки не доезжала до
кадра, а лог об этом молчал.
"""
from src.lib.slots_lock import _donor_has_media, apply_lock_after_p8

WORDS = [
    {"display": "Lean", "start": 10.2, "end": 10.8},
    {"display": "проверяет", "start": 10.9, "end": 11.5},
    {"display": "Миллион", "start": 20.0, "end": 20.2},
    {"display": "не", "start": 20.3, "end": 20.5},
    {"display": "берёт", "start": 20.6, "end": 21.0},
]


def test_a_local_base_row_counts_as_a_donor():
    assert _donor_has_media({"storage_key": "magnific/x.mp4"})


def test_a_downloaded_stock_row_counts_as_a_donor():
    assert _donor_has_media({"local_file": "/tmp/x.mp4"})


def test_a_row_without_any_file_is_not_a_donor():
    assert not _donor_has_media({"asset_id": "magnific_0050_stamp"})


class _Ctx:
    """Достаточный минимум: две записи в plan/doc и запись обратно в память."""

    storage = None
    cfg = None

    def __init__(self, plan, doc, words=None):
        self._files = {"cut_plan.json": plan, "accepted_assets.json": doc,
                       "words.json": {"words": words if words is not None else WORDS}}
        self.written = {}

    def read(self, name):
        return self._files[name]

    def read_or(self, name, default):
        return self._files.get(name, default)

    def write(self, name, payload):
        self.written[name] = payload
        self._files[name] = payload


def _plan():
    return {
        "video_id": "t_lock",
        "slots": [
            {"index": 0, "block_id": "b6", "needs_asset": True,
             "asset_role": "broll", "start": 10.0, "end": 12.0},
            {"index": 1, "block_id": "b6", "needs_asset": True,
             "asset_role": "broll", "start": 20.0, "end": 22.0},
        ],
        "slots_lock": [
            {"block": "b6", "on": "не берёт", "asset": "magnific_0050_stamp"},
        ],
    }


def test_the_lock_moves_the_named_asset_onto_the_spoken_slot():
    doc = {"accepted": {
        "0": {"asset_id": "magnific_0050_stamp", "storage_key": "magnific/stamp.mp4"},
        "1": {"asset_id": "magnific_0050_lean", "storage_key": "magnific/lean.mp4"},
    }}
    ctx = _Ctx(_plan(), doc)
    assert apply_lock_after_p8(ctx) == 1
    out = ctx.written["accepted_assets.json"]["accepted"]
    assert out["1"]["asset_id"] == "magnific_0050_stamp"
    assert out["1"]["speech_locked"] is True
    # non-reuse: материал не остаётся на прежнем слоте, но и дыры не будет —
    # прежний житель цели переезжает на освободившийся слот.
    assert out["0"]["asset_id"] == "magnific_0050_lean"


def test_a_lock_without_a_donor_anywhere_leaves_the_plan_alone():
    doc = {"accepted": {
        "1": {"asset_id": "magnific_0050_lean", "storage_key": "magnific/lean.mp4"},
    }}
    ctx = _Ctx(_plan(), doc)
    assert apply_lock_after_p8(ctx) == 0
    assert "accepted_assets.json" not in ctx.written


def _plan_two_lines():
    """Две строки заявки на одну реплику — как b6 «не берёт» на 0050."""
    plan = _plan()
    plan["slots"] = [
        {"index": 0, "block_id": "b6", "needs_asset": True,
         "asset_role": "broll", "start": 20.0, "end": 20.7},
        {"index": 1, "block_id": "b6", "needs_asset": True,
         "asset_role": "broll", "start": 20.7, "end": 21.4},
    ]
    plan["slots_lock"] = [
        {"block": "b6", "on": "не берёт", "asset": "magnific_0050_stamp"},
        {"block": "b6", "on": "не берёт", "asset": "magnific_0050_charcoalash"},
    ]
    return plan


def test_two_lines_on_one_phrase_take_two_slots():
    doc = {"accepted": {
        "0": {"asset_id": "magnific_0050_lean", "storage_key": "magnific/lean.mp4"},
        "1": {"asset_id": "magnific_0050_stamp", "storage_key": "magnific/stamp.mp4"},
        "2": {"asset_id": "magnific_0050_charcoalash",
              "storage_key": "magnific/ash.mp4"},
    }}
    ctx = _Ctx(_plan_two_lines(), doc)
    assert apply_lock_after_p8(ctx) == 2
    out = ctx.written["accepted_assets.json"]["accepted"]
    # первая строка забирает первый слот, вторая — следующий, а не тот же
    assert out["0"]["asset_id"] == "magnific_0050_stamp"
    assert out["1"]["asset_id"] == "magnific_0050_charcoalash"


def test_two_lines_naming_the_same_asset_create_a_qc5_duplicate():
    """``reuse: True`` was believed to make a second line safe. It does not.

    The flag only skips stripping the asset from wherever it already sits;
    the new entry still carries a copy of the donor's own phashes. QC-5 reads
    accepted_assets.json directly and does not know about ``reuse`` at all —
    two entries with matching phashes are a duplicate whatever put them
    there. Round 60 shipped exactly this shape (two slots_lock lines on
    tealmister for 0050's b5) and failed QC-5 in Actions.
    """
    from src.lib.phash import DEFAULT_THRESHOLD, video_is_duplicate

    plan = _plan()
    # Вторая строка на другую, непересекающуюся фразу того же блока — то,
    # чем на самом деле была «Страшное» в круге 60: тот же донор
    # (magnific_0050_lean), другой момент, reuse:True.
    plan["slots"].append(
        {"index": 2, "block_id": "b6", "needs_asset": True,
         "asset_role": "broll", "start": 30.0, "end": 31.0})
    plan["slots_lock"].append(
        {"block": "b6", "on": "третье", "asset": "magnific_0050_lean",
         "reuse": True})
    words = WORDS + [{"display": "третье", "start": 30.1, "end": 30.5}]
    doc = {"accepted": {
        "0": {"asset_id": "magnific_0050_lean",
              "storage_key": "magnific/lean.mp4",
              "phashes": ["e1e0c0c31737c73e"]},
        "1": {"asset_id": "magnific_0050_stamp",
              "storage_key": "magnific/stamp.mp4",
              "phashes": ["aaaaaaaaaaaaaaaa"]},
    }}
    ctx = _Ctx(plan, doc, words=words)
    moved = apply_lock_after_p8(ctx)
    assert moved >= 1
    out = ctx.written["accepted_assets.json"]["accepted"]
    phash_lists = [e["phashes"] for e in out.values() if e.get("phashes")]
    dup = any(
        video_is_duplicate(a, b, DEFAULT_THRESHOLD)
        for i, a in enumerate(phash_lists)
        for b in phash_lists[i + 1:]
    )
    assert dup, "reuse:True should reproduce the QC-5 collision it caused in round 60"

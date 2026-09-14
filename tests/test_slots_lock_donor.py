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

    def __init__(self, plan, doc):
        self._files = {"cut_plan.json": plan, "accepted_assets.json": doc,
                       "words.json": {"words": WORDS}}
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

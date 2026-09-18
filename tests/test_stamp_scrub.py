"""Чистка штампа щадит зазор, на который его прибила заявка."""
from src.p8_broll_judge.judge import _scrub_stamp_off_lean_gaps

WORDS = [
    {"display": "Lean", "start": 48.83, "end": 49.0},
    {"display": "проверяет", "start": 49.04, "end": 49.55},
    {"display": "шаг", "start": 49.97, "end": 50.35},
    {"display": "не", "start": 55.44, "end": 55.60},
    {"display": "берёт", "start": 55.64, "end": 56.08},
]
SLOTS = {
    21: {"start": 49.09, "end": 50.29, "reason": "gap fill around prepared avatar window"},
    23: {"start": 55.21, "end": 56.61, "reason": "gap fill around prepared avatar window"},
}


def _accepted():
    return {21: {"asset_id": "magnific_0050_stamp"},
            23: {"asset_id": "magnific_0050_stamp"}}


def test_the_lean_check_gap_still_loses_the_stamp():
    acc = _accepted()
    _scrub_stamp_off_lean_gaps(accepted=acc, slots_by_index=SLOTS, judged=[],
                               repeat_max=1, words=WORDS, keep_on="не берёт")
    assert "stamp" not in str(acc.get(21, {}).get("asset_id", ""))


def test_the_pinned_gap_keeps_the_stamp():
    acc = _accepted()
    _scrub_stamp_off_lean_gaps(accepted=acc, slots_by_index=SLOTS, judged=[],
                               repeat_max=1, words=WORDS, keep_on="не берёт")
    assert acc[23]["asset_id"] == "magnific_0050_stamp"


def test_without_a_pin_both_gaps_are_scrubbed_as_before():
    acc = _accepted()
    _scrub_stamp_off_lean_gaps(accepted=acc, slots_by_index=SLOTS, judged=[],
                               repeat_max=1, words=WORDS, keep_on="")
    for idx in (21, 23):
        assert "stamp" not in str(acc.get(idx, {}).get("asset_id", ""))

"""tools/voice_import.py: слова дубля идут без наездов (QC-10)."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "voice_import", Path(__file__).resolve().parents[1] / "tools" / "voice_import.py")
voice_import = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(voice_import)


def test_shared_start_is_split():
    # 0052: «Так» 24.677–24.717 и «что» 24.677–24.816 — общий старт от STT.
    out = voice_import._monotonic([(24.677, 24.717), (24.677, 24.816), (24.816, 25.09)])
    assert out[0][0] == 24.677
    assert out[1][0] >= out[0][1]
    assert out[2][0] >= out[1][1]
    assert all(e > s for s, e in out)


def test_long_overlap_moves_start_only():
    out = voice_import._monotonic([(1.0, 1.5), (1.3, 2.0)])
    assert out == [(1.0, 1.5), (1.5, 2.0)]


def test_clean_sequence_untouched():
    seq = [(0.0, 0.2), (0.2, 0.5), (0.6, 0.9)]
    assert voice_import._monotonic(seq) == seq


def test_zero_length_word_does_not_overlap_after_min_duration():
    # STT: «Так» нулевой длины в начале «что» — после минимума 40 мс не налезает.
    out = voice_import._monotonic([(24.677, 24.677), (24.677, 24.816)])
    assert out[1][0] >= out[0][1]
    assert out[0][1] > out[0][0]

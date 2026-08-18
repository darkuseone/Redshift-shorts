"""Перцептивные хеши и дедупликация (§3.6.6, §7.2.5).

pHash — 64 бита через DCT-II 32×32 по низкочастотному блоку 8×8.
dHash — 64 бита по градиенту яркости 9×8.
Порог совпадения по умолчанию: Hamming ≤ 8/64.

Видео хешируется по трём кадрам (10 %, 50 %, 90 %) — дубль засчитывается, если
совпадает хотя бы половина позиций.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

HASH_BITS = 64
DEFAULT_THRESHOLD = 8


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    x = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * x + 1) * k / (2 * n))
    m[0, :] *= 1.0 / np.sqrt(2.0)
    return m * np.sqrt(2.0 / n)


_DCT32 = _dct_matrix(32)


def _to_gray(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(image.convert("L").resize(size, Image.Resampling.LANCZOS), dtype=np.float64)


def phash_image(image: Image.Image | str | Path) -> str:
    """Классический pHash: DCT 32×32, низкочастотный блок 8×8, порог — медиана.

    DC-коэффициент из сравнения исключается: он несёт общую яркость кадра и
    ломает устойчивость хеша к изменению экспозиции и к ресемплингу. Вместо
    него старший бит берётся у коэффициента (0,1) — самой низкой ненулевой
    частоты, устойчивой к масштабированию.
    """
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    gray = _to_gray(image, (32, 32))
    dct = _DCT32 @ gray @ _DCT32.T
    block = dct[:8, :8].astype(np.float64).flatten()
    median = np.median(block[1:])          # медиана без DC
    bits = block > median
    bits[0] = block[1] > median            # позиция DC отдана первой АЧ-компоненте
    return _bits_to_hex(bits)


def dhash_image(image: Image.Image | str | Path) -> str:
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    gray = _to_gray(image, (9, 8))
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    return _bits_to_hex(bits)


def _bits_to_hex(bits: np.ndarray) -> str:
    value = 0
    for bit in bits.astype(bool):
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return HASH_BITS
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def is_duplicate(a: str, b: str, threshold: int = DEFAULT_THRESHOLD) -> bool:
    return hamming(a, b) <= threshold


def video_hashes(frame_paths: Sequence[str | Path]) -> list[str]:
    return [phash_image(p) for p in frame_paths]


def video_is_duplicate(a: Sequence[str], b: Sequence[str],
                       threshold: int = DEFAULT_THRESHOLD) -> bool:
    """Дубль видео: совпало ≥50 % сравниваемых позиций кадров."""
    if not a or not b:
        return False
    pairs = min(len(a), len(b))
    matches = sum(1 for i in range(pairs) if is_duplicate(a[i], b[i], threshold))
    return matches * 2 >= pairs


def find_duplicate(candidate: Sequence[str] | str, pool: Iterable[tuple[str, Sequence[str] | str]],
                   threshold: int = DEFAULT_THRESHOLD) -> str | None:
    """Вернуть id первого совпавшего элемента пула или None."""
    cand_list = [candidate] if isinstance(candidate, str) else list(candidate)
    for item_id, hashes in pool:
        pool_list = [hashes] if isinstance(hashes, str) else list(hashes)
        if video_is_duplicate(cand_list, pool_list, threshold):
            return item_id
    return None

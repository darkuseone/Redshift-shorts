"""Ключевание однотонного фона аватара (§7.7).

HeyGen не отдаёт прозрачность: запрос webm возвращает непрозрачный кадр со
вшитым фоном. Зато он умеет вырезать ведущего и положить его на заданный цвет —
и вырезает чисто, включая волосы, очки и микрофон. Поэтому альфа берётся своим
ffmpeg: просим у HeyGen однотонный фон и убираем его здесь.

Цвет по умолчанию — #00B140 (студийный chroma green). Он выбран не «потому что
зелёный»: в кадре нет ни одного объекта такого тона, а чёрный фон исходного
снимка ключевать нельзя — на нём тёмная одежда и волосы ведущего.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...errors import RenderError
from ..ffmpeg import ffmpeg_bin
from ..logging import get_logger

_log = get_logger("chroma")

CHROMA_GREEN = "#00B140"


def _hex_to_ffmpeg(color: str) -> str:
    return "0x" + color.lstrip("#").upper()[:6]


def key_out(src: Path, dst: Path, *, color: str = CHROMA_GREEN,
            similarity: float = 0.10, blend: float = 0.04,
            despill: bool = True, timeout: int = 900) -> Path:
    """Убрать однотонный фон и записать клип с альфой.

    ``similarity`` — радиус захвата вокруг цвета, ``blend`` — мягкость края.
    Числа малы не из осторожности, а по измерению: ``chromakey`` считает
    расстояние в YUV, а у чёрной футболки и тёмных волос цветность близка к
    нулю. При 0.18 они попадают в радиус захвата и ведущий становится
    полупрозрачным целиком — проверено на кадре. При 0.10 полутоновых пикселей
    остаётся 0.3 % (край волос), остальное — чистые 0 и 255.

    ``despill`` убирает зелёный отлив на волосах и плечах. Без него ведущий на
    светлом фоне отдаёт салатовым.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    key = _hex_to_ffmpeg(color)

    chain = [f"chromakey={key}:{similarity}:{blend}"]
    if despill:
        chain.append("despill=type=green:mix=0.35:expand=0.2")
    chain.append("format=rgba")

    args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src),
            "-vf", ",".join(chain),
            # QTRLE несёт альфу без потерь и читается ffmpeg'ом HyperFrames.
            "-c:v", "qtrle", "-an", str(dst)]

    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or not dst.exists():
        raise RenderError(
            f"не удалось выключить фон у {src.name}: {proc.stderr.strip()[-400:]}",
            code="CHROMA_KEY_FAILED")

    _log.info("фон аватара выключен", extra={
        "src": src.name, "dst": dst.name, "color": color,
        "mb": round(dst.stat().st_size / 1e6, 1)})
    return dst

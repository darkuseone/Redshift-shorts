"""Обёртка над ffmpeg/ffprobe.

Раннеры GitHub Actions — CPU-only (§10.5.1), поэтому вся тяжёлая геометрия
(масштаб, crop, Ken Burns, ресемпл до 30 fps) отдаётся ffmpeg, а покадровый
композитинг делает Python поверх уже нормализованных клипов.

Бинарь ищется в PATH, затем в imageio-ffmpeg (статическая сборка), затем в
переменных FFMPEG_BINARY/FFPROBE_BINARY.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import RenderError
from .logging import get_logger

_log = get_logger("ffmpeg")


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    env = os.environ.get("FFMPEG_BINARY")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - зависит от окружения
        raise RenderError(
            "ffmpeg не найден: установите системный ffmpeg либо пакет imageio-ffmpeg",
            hint="pip install imageio-ffmpeg",
        ) from exc


@lru_cache(maxsize=1)
def ffprobe_bin() -> str:
    env = os.environ.get("FFPROBE_BINARY")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    # Статическая сборка imageio-ffmpeg идёт без ffprobe — разбираем метаданные
    # через сам ffmpeg (см. probe()).
    return ""


def run(args: Sequence[str], *, what: str = "ffmpeg", timeout: int = 3600,
        capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", *args]
    _log.debug("запуск ffmpeg", extra={"what": what, "argc": len(cmd)})
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-4000:]
        raise RenderError(f"{what}: ffmpeg завершился с кодом {proc.returncode}",
                          stderr=err, args=" ".join(args[:40]))
    return proc


@dataclass
class MediaInfo:
    path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool
    codec: str = ""
    audio_sample_rate: int = 0
    audio_channels: int = 0
    nb_frames: int = 0

    @property
    def is_vertical(self) -> bool:
        return self.height >= self.width

    @property
    def aspect(self) -> float:
        return (self.width / self.height) if self.height else 0.0


def _probe_via_ffprobe(path: str | Path) -> dict[str, Any]:
    exe = ffprobe_bin()
    if not exe:
        return {}
    cmd = [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {}


def _probe_via_ffmpeg(path: str | Path) -> dict[str, Any]:
    """Фолбэк, когда ffprobe недоступен (статическая сборка imageio-ffmpeg)."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-i", str(path), "-f", "null", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    text = proc.stderr.decode("utf-8", "replace")
    info: dict[str, Any] = {"streams": [], "format": {}}

    import re

    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        info["format"]["duration"] = str(h * 3600 + mi * 60 + s)

    vm = re.search(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d+)x(\d+)[^,]*(?:,[^,]*)*?, "
                   r"(?:[\d.]+ kb/s, )?([\d.]+) (?:fps|tbr)", text)
    if not vm:
        vm = re.search(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d+)x(\d+).*?([\d.]+) fps", text)
    if vm:
        info["streams"].append({
            "codec_type": "video", "codec_name": vm.group(1),
            "width": int(vm.group(2)), "height": int(vm.group(3)),
            "r_frame_rate": f"{vm.group(4)}/1",
        })

    am = re.search(r"Stream #\d+:\d+.*?: Audio: (\w+).*?, (\d+) Hz, (\w+)", text)
    if am:
        channels = {"mono": 1, "stereo": 2}.get(am.group(3), 2)
        info["streams"].append({
            "codec_type": "audio", "codec_name": am.group(1),
            "sample_rate": am.group(2), "channels": channels,
        })
    # frame= NNNN в конце вывода -f null
    fm = re.findall(r"frame=\s*(\d+)", text)
    if fm:
        info["_nb_frames"] = int(fm[-1])
    return info


def _parse_rate(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> MediaInfo:
    path = str(path)
    if not Path(path).exists():
        raise RenderError("probe: файл не найден", path=path)
    data = _probe_via_ffprobe(path) or _probe_via_ffmpeg(path)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0.0)
    if not duration and video and video.get("duration"):
        duration = float(video["duration"])
    if not duration and audio and audio.get("duration"):
        duration = float(audio["duration"])

    fps = _parse_rate(video.get("r_frame_rate") if video else None) or 0.0
    nb_frames = int(video.get("nb_frames") or 0) if video else 0
    if not nb_frames:
        nb_frames = int(data.get("_nb_frames") or 0)
    if not nb_frames and fps and duration:
        nb_frames = int(round(duration * fps))

    return MediaInfo(
        path=path,
        duration_sec=duration,
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=fps,
        has_video=video is not None,
        has_audio=audio is not None,
        codec=str(video.get("codec_name", "")) if video else str(audio.get("codec_name", "")) if audio else "",
        audio_sample_rate=int(audio.get("sample_rate", 0)) if audio else 0,
        audio_channels=int(audio.get("channels", 0)) if audio else 0,
        nb_frames=nb_frames,
    )


def extract_frames(src: str | Path, out_dir: str | Path, positions: Iterable[float],
                   *, width: int = 640) -> list[Path]:
    """Кадры по относительным позициям (0..1) — вход для vision-критика (§7.3)."""
    info = probe(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    duration = info.duration_sec or 0.0
    for idx, rel in enumerate(positions):
        ts = max(0.0, min(duration * float(rel), max(duration - 0.05, 0.0))) if duration else 0.0
        out = out_dir / f"frame_{idx:02d}.jpg"
        run(["-y", "-ss", f"{ts:.3f}", "-i", str(src), "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-q:v", "4", str(out)],
            what="extract_frame")
        if out.exists():
            result.append(out)
    return result


def make_thumbnail(src: str | Path, out: str | Path, *, time_sec: float = 1.0,
                   width: int = 1080) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["-y", "-ss", f"{time_sec:.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "2", str(out)], what="thumbnail")
    return out


def alpha_opacity(src: str | Path, *, at_sec: float = 0.5) -> float | None:
    """Доля непрозрачных пикселей кадра. ``None`` — альфы в файле нет.

    Расширение о прозрачности не говорит **ничего**: HeyGen отдавал ``.webm``
    и с рабочей альфой, и без неё, и назывались они одинаково. Один такой файл
    ушёл в сборку как прозрачный, и приёмы за головой встали за непрозрачным
    планом — в кадре их просто не было. Поэтому канал измеряется.

    VP9 держит альфу отдельным блоком контейнера, и штатный декодер ffmpeg
    отдаёт по нему ``yuv420p`` — альфы будто нет. Достаёт её только
    ``libvpx-vp9``, поэтому для webm декодер называется явно.
    """
    src = Path(src)
    decoder = ["-c:v", "libvpx-vp9"] if src.suffix.lower() == ".webm" else []

    def _grab(seek: float) -> bytes:
        args = [ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, seek):.3f}",
                *decoder, "-i", str(src), "-frames:v", "1",
                "-vf", "alphaextract,scale=160:-1", "-f", "image2pipe",
                "-vcodec", "png", "-"]
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120)
        # «Requested planes not available» — в потоке нет альфа-плоскости.
        return proc.stdout if proc.returncode == 0 else b""

    raw = _grab(at_sec)
    if not raw and at_sec > 0:
        # Перемотка за конец короткого клипа кадра не даёт, и «кадра нет»
        # прочиталось бы как «альфы нет». Второй заход — с начала.
        raw = _grab(0.0)
    if not raw:
        return None
    try:
        import io

        from PIL import Image

        plane = Image.open(io.BytesIO(raw)).convert("L")
    except Exception:                                        # noqa: BLE001
        return None
    data = list(plane.getdata())
    if not data:
        return None
    return sum(data) / (255.0 * len(data))


def has_alpha(src: str | Path, *, at_sec: float = 0.5,
              max_opacity: float = 0.985) -> bool:
    """Есть ли в клипе **работающая** прозрачность.

    Непрозрачный кадр иногда приходит с формально существующей альфой,
    залитой единицами. Такой канал бесполезен, и считать его альфой — то же
    самое, что верить расширению.
    """
    opacity = alpha_opacity(src, at_sec=at_sec)
    return opacity is not None and opacity < max_opacity


def has_encoder(name: str) -> bool:
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    return name.encode() in proc.stdout

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


# Отношение высоты головы (макушка → подбородок) к её ширине с волосами.
# Антропометрическая пропорция, и мерка в паре с ней одна — ширина.
HEAD_ASPECT = 1.35
# Доля от самой широкой строки, начиная с которой строка считается плато
# черепа: по этим строкам и меряется ширина головы.
PLATEAU_SHARE = 0.95


def head_box(src: str | Path, *, at_sec: float = 0.5,
             width: int = 180) -> tuple[int, int, int, int] | None:
    """Голова ведущего, измеренная по альфа-каналу. ``None`` — если альфы нет.

    Раньше положение головы бралось константой из брендбука (полоса
    ``avatar.face_band_y``), и приёмы ставились относительно догадки. На новом
    аватаре догадка разъехалась с кадром: слово «за головой» пришлось ей ровно
    поперёк, и «НЕЧЕМ» читалось как «НЕ⋯ЕМ». Догадка тут вообще лишняя — с
    рабочей альфой силуэт известен точно.

    **Ширина** читается силуэтом. Профиль у портрета начинается одинаково:
    макушка (узко) → череп (плато), и плато — первый максимум профиля. Плечи
    при этом не ищутся вовсе: «наибольший прирост ширины» одинаково хорошо
    указывает и на них, и на разлёт причёски сразу под макушкой, а какой из
    двух окажется круче — дело причёски. Проверено: на портрете плечи находились
    четырьмя строками ниже темени.

    Строка профиля — длина самого длинного сплошного отрезка, а не число
    непрозрачных точек. Разница вся в реквизите: стойка микрофона входит в кадр
    отдельной полосой, по сумме точек неотличимой от плеч, — отрезком она в
    профиле просто не участвует. По размаху строки коробка получалась вдвое
    шире головы (x1=1074 вместо 756).

    **Подбородок силуэтом не читается** — и это не недоработка, а свойство
    съёмки. В портретном плане шея закрыта плечами и воротником: ниже челюсти
    ширина не проваливается, а сразу растёт. Прежний поиск «самого узкого места
    между черепом и плечами» находил не подбородок, а скулы — коробка кончалась
    на верхней губе, круг садился на 60 px выше головы, и в кадре голова
    вылезала из круга снизу при пустоте сверху (видно на кадре).

    Поэтому высота считается от ширины: у человека расстояние от макушки до
    подбородка — около 1.35 ширины головы с волосами (:data:`HEAD_ASPECT`).
    Мерка тут одна — ширина, измеренная по альфе; пропорция только переводит её
    в высоту. Силуэт всё же имеет право оборвать коробку раньше: если ниже
    черепа столбцы головы **пусты** (голова висит отдельно от тела — так устроен
    синтетический фикстур), подбородок там, и пропорция не нужна.
    """
    try:
        import io

        import numpy as np
        from PIL import Image
    except Exception:                                        # noqa: BLE001
        return None

    src = Path(src)
    decoder = ["-c:v", "libvpx-vp9"] if src.suffix.lower() == ".webm" else []
    args = [ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, at_sec):.3f}",
            *decoder, "-i", str(src), "-frames:v", "1",
            "-vf", f"alphaextract,scale={width}:-1", "-f", "image2pipe",
            "-vcodec", "png", "-"]
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=120)
    if proc.returncode != 0 or not proc.stdout:
        return None

    info = probe(src)
    mask = np.asarray(Image.open(io.BytesIO(proc.stdout)).convert("L")) > 16

    def longest_run(row: "np.ndarray") -> tuple[int, int]:
        """Самый длинный сплошной отрезок строки: (начало, конец]."""
        idx = np.where(row)[0]
        if idx.size == 0:
            return (0, 0)
        parts = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
        run = max(parts, key=len)
        return (int(run[0]), int(run[-1]) + 1)

    # Профиль строится по самому длинному отрезку строки, а не по числу
    # непрозрачных точек в ней. Разница вся в реквизите: стойка микрофона
    # входит в кадр отдельной полосой, и в сумме точек она неотличима от
    # плеч — прежний профиль принимал её появление за начало плеч и обрывал
    # голову на скулах. Отрезком она просто не участвует.
    spans = [longest_run(row) for row in mask]
    rows = np.array([b - a for a, b in spans])
    filled = np.where(rows > 0)[0]
    if filled.size < 8:
        return None
    top, bottom = int(filled[0]), int(filled[-1])

    # Сглаживание обязательно: без него одиночная строка с волосами читается
    # как перелом профиля.
    window = max(3, mask.shape[0] // 60)
    smooth = np.convolve(rows.astype(float), np.ones(window) / window, mode="same")

    # Череп — первый максимум профиля под макушкой. Плечи здесь не ищутся
    # вовсе, и это осознанно: «наибольший прирост ширины» с одинаковым
    # успехом указывает и на плечи, и на разлёт причёски сразу под макушкой —
    # он не менее крутой. На синтетическом портрете так и вышло: плечи
    # находились на 4 строки ниже темени, и от головы оставалась макушка.
    widest, skull = 0.0, top
    plateau_end = bottom
    for y in range(top, bottom + 1):
        value = float(smooth[y])
        if value > widest:
            widest, skull = value, y
        elif value < widest * PLATEAU_SHARE:
            plateau_end = y
            break
    if widest <= 0:
        return None

    plateau = [y for y in range(top, max(top + 1, plateau_end))
               if smooth[y] >= PLATEAU_SHARE * widest]
    x0 = min(spans[y][0] for y in plateau)
    x1 = max(spans[y][1] for y in plateau)

    # Макушка пересчитывается по столбцам головы: первая непрозрачная строка
    # кадра может принадлежать реквизиту, а не ведущему.
    column = mask[:, x0:x1].any(axis=1)
    crown = int(np.argmax(column)) if column.any() else top

    # Подбородок ищется вниз по столбцам головы: голова кончается там, где под
    # ней ничего нет. У портрета такой строки не бывает — шею закрывают плечи,
    # и высота берётся пропорцией от измеренной ширины.
    below = np.where(~column[skull:])[0]
    ends = skull + int(below[0]) if below.size else bottom
    chin = min(ends, crown + int(round(HEAD_ASPECT * (x1 - x0))), bottom)

    scale = (info.width or width) / float(mask.shape[1])
    return (int(x0 * scale), int(crown * scale),
            int(x1 * scale), int(chin * scale))


def has_encoder(name: str) -> bool:
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    return name.encode() in proc.stdout

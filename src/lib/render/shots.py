"""Подготовка планов: приведение исходников к 1080×1920 @ 30 fps (§3.1, §3.6).

Разделение труда: тяжёлую геометрию (масштаб, кроп, ресемпл, обрезку по
длительности) делает ffmpeg, а покадровые эффекты — Ken Burns, переходы,
графику — Python-композитор. Так раннер не захлёбывается, а эффекты остаются
полностью управляемыми.

Правила §3.6, которые обеспечивает этот модуль:

* растяжение кадра запрещено — только crop или letterbox;
* горизонтальный футаж режется по **детектированному субъекту**, а не по центру
  вслепую: центр кадра часто пустой, а субъект стоит в трети;
* blurred pillarbox — не чаще 2 раз за ролик, поэтому он выдаётся по явному
  разрешению, а не молча применяется ко всему, что не влезло.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from ..ffmpeg import extract_frames, probe, run
from ..logging import get_logger

_log = get_logger("shots")


@dataclass
class ShotSpec:
    """Как именно исходник превращается в план."""

    src: Path
    dst: Path
    duration_sec: float
    width: int
    height: int
    fps: int
    fit: str = "crop"            # crop | pillarbox
    focus_x: float = 0.5         # центр кропа по горизонтали, 0..1
    focus_y: float = 0.5
    compose_zoom: float = 1.0  # mild in-compose zoom for sparse Avatar V framing
    start_sec: float = 0.0
    loop: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"src": str(self.src), "dst": str(self.dst),
                "duration_sec": round(self.duration_sec, 3), "fit": self.fit,
                "focus_x": round(self.focus_x, 3), "focus_y": round(self.focus_y, 3),
                "compose_zoom": round(float(self.compose_zoom or 1.0), 3),
                "start_sec": round(self.start_sec, 3), "loop": self.loop}


def detect_focus(src: Path, *, samples: Sequence[float] = (0.2, 0.5, 0.8),
                 work_dir: Path | None = None) -> tuple[float, float]:
    """Центр внимания кадра как центроид плотности деталей.

    Это не нейросетевая детекция объекта, а устойчивый и дешёвый прокси:
    там, где есть субъект, выше локальный контраст. Для кропа 9:16 этого
    достаточно, и в отличие от кропа «всегда по центру» он не режет головы.
    """
    tmp = work_dir or src.parent / "_focus"
    frames = extract_frames(src, tmp, samples, width=192)
    if not frames:
        return 0.5, 0.5

    xs: list[float] = []
    ys: list[float] = []
    for frame in frames:
        with Image.open(frame) as img:
            gray = np.asarray(img.convert("L"), dtype=np.float64) / 255.0
        gx = np.abs(np.diff(gray, axis=1, append=gray[:, -1:]))
        gy = np.abs(np.diff(gray, axis=0, append=gray[-1:, :]))
        energy = gx + gy
        total = energy.sum()
        if total < 1e-6:
            continue
        col = energy.sum(axis=0)
        row = energy.sum(axis=1)
        xs.append(float((col * np.arange(len(col))).sum() / col.sum() / len(col)))
        ys.append(float((row * np.arange(len(row))).sum() / row.sum() / len(row)))

    if not xs:
        return 0.5, 0.5
    # Тянем к центру: чистый центроид на пёстром фоне гуляет по кадру.
    fx = 0.5 + (float(np.median(xs)) - 0.5) * 0.7
    fy = 0.5 + (float(np.median(ys)) - 0.5) * 0.5
    return min(max(fx, 0.18), 0.82), min(max(fy, 0.2), 0.8)


def build_filter(info, spec: ShotSpec) -> str:
    """Фильтр ffmpeg: покрыть кадр, обрезать по фокусу, никогда не растягивать."""
    target_w, target_h = spec.width, spec.height
    src_w, src_h = max(info.width, 1), max(info.height, 1)

    if spec.fit == "pillarbox":
        # §3.6.5: размытая подложка вместо растяжения. Используется по явному
        # разрешению и не чаще 2 раз за ролик.
        return (
            f"[0:v]fps={spec.fps},split=2[bg][fg];"
            f"[bg]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},gblur=sigma=28,eq=brightness=-0.08[bgb];"
            f"[fg]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )

    zoom = max(float(getattr(spec, "compose_zoom", 1.0) or 1.0), 1.0)
    scale = max(target_w / src_w, target_h / src_h) * zoom
    scaled_w = math.ceil(src_w * scale / 2) * 2
    scaled_h = math.ceil(src_h * scale / 2) * 2
    max_x = max(0, scaled_w - target_w)
    max_y = max(0, scaled_h - target_h)
    crop_x = int(round(max_x * spec.focus_x))
    crop_y = int(round(max_y * spec.focus_y))
    return (
        f"fps={spec.fps},scale={scaled_w}:{scaled_h}:flags=lanczos,"
        f"crop={target_w}:{target_h}:{crop_x}:{crop_y},setsar=1,format=rgb24"
    )


def prepare_shot(spec: ShotSpec) -> dict[str, Any]:
    """Нормализовать исходник в план ровно нужной длительности."""
    info = probe(spec.src)
    spec.dst.parent.mkdir(parents=True, exist_ok=True)
    filter_str = build_filter(info, spec)

    args: list[str] = ["-y"]
    is_image = not info.has_video or info.duration_sec < 0.05
    if is_image:
        args += ["-loop", "1", "-t", f"{spec.duration_sec:.3f}", "-i", str(spec.src)]
    else:
        if spec.start_sec > 0:
            args += ["-ss", f"{spec.start_sec:.3f}"]
        if spec.loop or info.duration_sec < spec.duration_sec:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(spec.src), "-t", f"{spec.duration_sec:.3f}"]

    if "[0:v]" in filter_str:
        args += ["-filter_complex", filter_str]
    else:
        args += ["-vf", filter_str]

    args += ["-an", "-r", str(spec.fps), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "16", "-pix_fmt", "yuv420p", "-g", str(spec.fps * 2),
             str(spec.dst)]
    run(args, what=f"prepare_shot {spec.dst.name}")

    out_info = probe(spec.dst)
    return {
        **spec.to_dict(),
        "source_size": [info.width, info.height],
        "source_duration_sec": round(info.duration_sec, 3),
        "output_size": [out_info.width, out_info.height],
        "output_duration_sec": round(out_info.duration_sec, 3),
        "output_frames": out_info.nb_frames,
        "was_image": is_image,
    }


def slim_video(src: Path, *, max_sec: float = 20.0, crf: int = 23,
               max_short_side: int = 1080) -> dict[str, Any]:
    """Ужать сток на приёме: столько, сколько ролик реально возьмёт.

    Материал лежит внутри репозитория — так решил заказчик, и это правильно:
    прогон идёт на чужом раннере, кэш Actions терялся уже трижды, а checkout
    переживает всё. Но один прогон 0047 положил в git 27 клипов Pexels на
    369 МБ, отдельные файлы по 35–45 МБ. Хранить их такими незачем ни по
    одной оси:

    * **длина.** Самый длинный слот ролика — 6.4 секунды, и футаж всегда
      играет с нуля: ``prepare_shot`` для стока вызывается без ``start_sec``.
      Клип на 65 секунд отдаёт ролику первые шесть.
    * **звук.** Все три пути подготовки кадра идут с ``-an``: звук стока
      не попадает в микс никогда.
    * **поток.** 5.5 Мбит/с при 1080×1920 — запас для монтажа, которого у
      нас нет: кадр всё равно кропается и жмётся ещё раз на выходе.

    Замер на самом тяжёлом файле прогона (45.5 МБ, 65.6 с): 20 секунд, CRF 23,
    без звука — 9.8 МБ при SSIM 0.980 к оригиналу. Разница 2 % по структуре
    не переживёт ни кроп Ken Burns, ни финальный H.264.

    Возвращает отчёт с байтами до и после; при неудаче ffmpeg исходник
    остаётся нетронутым — ужать не удалось, но материал есть.
    """
    before = src.stat().st_size
    report: dict[str, Any] = {"before": before, "after": before, "slimmed": False}
    try:
        info = probe(src)
    except Exception:                       # noqa: BLE001 — не наше дело ронять приём
        return report
    if not info.has_video:
        return report

    short = min(info.width or 0, info.height or 0)
    need_scale = bool(short and short > max_short_side)
    need_trim = bool(info.duration_sec and info.duration_sec > max_sec + 0.5)
    # Перекодировать заведомо лёгкий клип незачем: потеряем качество даром.
    if not (need_scale or need_trim or before > 8 * 1024 * 1024):
        return report

    dst = src.with_name(f"{src.stem}_slim.mp4")
    args = ["-y", "-i", str(src), "-t", f"{min(max_sec, info.duration_sec or max_sec):.3f}",
            "-an"]
    if need_scale:
        args += ["-vf", f"scale='if(gt(iw,ih),-2,{max_short_side})':"
                        f"'if(gt(iw,ih),{max_short_side},-2)'"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    try:
        run(args, what=f"ужать сток {src.name}")
    except Exception as exc:                # noqa: BLE001
        _log.warning("не удалось ужать %s: %s", src.name, exc)
        dst.unlink(missing_ok=True)
        return report

    after = dst.stat().st_size
    # Ужимать в больший файл смысла нет: короткий клип с высоким потоком
    # после перекодировки может вырасти.
    if after >= before:
        dst.unlink(missing_ok=True)
        return report
    dst.replace(src)
    return {"before": before, "after": after, "slimmed": True}


def choose_fit(info, *, pillarbox_used: int, pillarbox_limit: int) -> str:
    """Кроп по умолчанию; pillarbox — только когда кроп реально всё ломает."""
    if not info.width or not info.height:
        return "crop"
    aspect = info.width / info.height
    # Сверхширокий кадр при кропе 9:16 теряет ~75 % ширины — тут letterbox честнее.
    if aspect >= 2.1 and pillarbox_used < pillarbox_limit:
        return "pillarbox"
    return "crop"


def kenburns_window(progress: float, *, zoom_from: float, zoom_to: float,
                    pan: Sequence[float] = (0.0, 0.0), easing_fn=None
                    ) -> tuple[float, float, float]:
    """Окно кропа для Ken Burns: (масштаб, смещение X, смещение Y) в долях.

    §3.6.4 — масштаб 1.0→1.08…1.15, ease-out cubic. Возвращаются доли, а не
    пиксели: композитор применяет их к кадру любого размера.
    """
    eased = easing_fn(progress) if easing_fn else 1 - (1 - progress) ** 3
    zoom = zoom_from + (zoom_to - zoom_from) * eased
    shift_x = float(pan[0]) * eased * 0.5 * (1.0 - 1.0 / max(zoom, 1e-6))
    shift_y = float(pan[1]) * eased * 0.5 * (1.0 - 1.0 / max(zoom, 1e-6))
    return zoom, shift_x, shift_y


def apply_kenburns(frame: Image.Image, zoom: float, shift_x: float, shift_y: float,
                   size: tuple[int, int]) -> Image.Image:
    """Вырезать окно и вернуть к размеру кадра — без растяжения пропорций."""
    if abs(zoom - 1.0) < 1e-4 and abs(shift_x) < 1e-4 and abs(shift_y) < 1e-4:
        return frame if frame.size == size else frame.resize(size, Image.Resampling.LANCZOS)
    width, height = frame.size
    win_w = width / zoom
    win_h = height / zoom
    cx = width / 2 + shift_x * width
    cy = height / 2 + shift_y * height
    left = min(max(cx - win_w / 2, 0.0), width - win_w)
    top = min(max(cy - win_h / 2, 0.0), height - win_h)
    box = (left, top, left + win_w, top + win_h)
    return frame.resize(size, Image.Resampling.LANCZOS, box=box)


def prepare_split_shot(*, top_src: Path, bottom_src: Path, dst: Path,
                       duration_sec: float, width: int, height: int, fps: int,
                       top_start_sec: float = 0.0, bottom_start_sec: float = 0.0,
                       focus_x: float = 0.5, focus_y: float = 0.4,
                       divider_px: int = 4, divider_color: str = "0xC8453D",
                       bottom_has_alpha: bool = False,
                       bg_colors: tuple[str, str] = ("F7F5F3", "FFFFFF"),
                       ) -> dict[str, Any]:
    """Режим B (§3.5): верх — доказательный материал, низ — аватар.

    Половины склеиваются заранее в один нормализованный клип: композитор
    работает с одним источником на план, и это удерживает покадровый цикл
    простым и быстрым.
    """
    half = height // 2
    top_info = probe(top_src)
    bottom_info = probe(bottom_src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Нижняя половина — аватар. Если он с прозрачным фоном (§7.7), альфу надо
    # положить на фон здесь же: иначе в готовом клипе она станет чёрной.
    alpha_bg = ""
    bottom_label = "1:v"
    if bottom_has_alpha:
        c0, c1 = bg_colors
        alpha_bg = (f"color=c=0x{c0}:s={width}x{half}:d={duration_sec:.2f}:r={fps}[abg];"
                    f"[1:v]fps={fps},scale={width}:{half}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{half}:0:0,setsar=1[araw];"
                    f"[abg][araw]overlay=0:0:format=auto[bottomflat];")
        bottom_label = "bottomflat"
        del c1

    def _half_filter(info, label: str, focus: float) -> str:
        src_w, src_h = max(info.width, 1), max(info.height, 1)
        scale = max(width / src_w, half / src_h)
        sw = math.ceil(src_w * scale / 2) * 2
        sh = math.ceil(src_h * scale / 2) * 2
        x = int(round(max(0, sw - width) * 0.5))
        y = int(round(max(0, sh - half) * focus))
        return (f"[{label}]fps={fps},scale={sw}:{sh}:flags=lanczos,"
                f"crop={width}:{half}:{x}:{y},setsar=1")

    bottom_filter = (f"[{bottom_label}]setsar=1[bot]" if bottom_has_alpha
                     else f"{_half_filter(bottom_info, '1:v', focus_y)}[bot]")
    filter_complex = (
        f"{alpha_bg}"
        f"{_half_filter(top_info, '0:v', 0.5)}[top];"
        f"{bottom_filter};"
        f"[top][bot]vstack=inputs=2[stacked];"
        f"[stacked]drawbox=x=0:y={half - divider_px // 2}:w={width}:h={divider_px}:"
        f"color={divider_color}@0.9:t=fill[out]"
    )

    args = ["-y"]
    for src, start, info in ((top_src, top_start_sec, top_info),
                             (bottom_src, bottom_start_sec, bottom_info)):
        # Неподвижный кадр растягивается `-loop 1`, а не `-stream_loop -1`.
        # Разница не косметическая: у одиночного JPEG `-stream_loop`
        # бесконечно повторяет один и тот же пакет, метки времени не растут,
        # и `-t` не наступает никогда. Мок-прогон встал на split-кадре с
        # прессовым снимком наверху: 21 минута ffmpeg на 100 % процессора
        # ради клипа в 2.8 секунды, и так до потолка задачи.
        #
        # В prepare_shot этот случай разведён с самого начала — здесь его
        # просто забыли, и до вечнозелёной базы он почти не всплывал:
        # снимков в верхней половине сплита раньше почти не бывало.
        if not info.has_video or info.duration_sec < 0.05:
            args += ["-loop", "1", "-t", f"{duration_sec:.3f}"]
        else:
            if start > 0:
                args += ["-ss", f"{start:.3f}"]
            if info.duration_sec and info.duration_sec < start + duration_sec:
                args += ["-stream_loop", "-1"]
        args += ["-i", str(src)]

    args += ["-filter_complex", filter_complex, "-map", "[out]",
             "-t", f"{duration_sec:.3f}", "-an", "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
             "-pix_fmt", "yuv420p", str(dst)]
    run(args, what=f"prepare_split {dst.name}")

    out_info = probe(dst)
    return {
        "src": f"{top_src.name}+{bottom_src.name}", "dst": str(dst),
        "duration_sec": round(duration_sec, 3), "fit": "split",
        "focus_x": focus_x, "focus_y": focus_y,
        "bottom_has_alpha": bottom_has_alpha,
        "top_start_sec": round(top_start_sec, 3),
        "bottom_start_sec": round(bottom_start_sec, 3),
        "output_size": [out_info.width, out_info.height],
        "output_duration_sec": round(out_info.duration_sec, 3),
        "output_frames": out_info.nb_frames,
    }


def prepare_avatar_shot(*, avatar_src: Path, dst: Path, duration_sec: float,
                        width: int, height: int, fps: int, start_sec: float = 0.0,
                        background: str = "brand",
                        bg_colors: tuple[str, str] = ("F7F5F3", "FFFFFF"),
                        behind_layer: Path | None = None,
                        vfx_src: Path | None = None,
                        compose_zoom: float = 1.0) -> dict[str, Any]:
    """Avatar with alpha → ready plate (§7.7).

    Layer order: brand/VFX bg → text-behind-head → avatar. Optional compose_zoom
    scales then head-weighted-crops the avatar only (source files unchanged).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    filters: list[str] = []

    if vfx_src is not None and Path(vfx_src).exists():
        # Тот же капкан, что в prepare_split: на неподвижном источнике
        # `-stream_loop` не кончается.
        vfx_info = probe(Path(vfx_src))
        if not vfx_info.has_video or vfx_info.duration_sec < 0.05:
            inputs += ["-loop", "1", "-t", f"{duration_sec:.3f}", "-i", str(vfx_src)]
        else:
            inputs += ["-stream_loop", "-1", "-i", str(vfx_src)]
        filters.append(f"[0:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,"
                       f"crop={width}:{height},setsar=1[bg]")
    else:
        c0, c1 = bg_colors
        inputs += ["-f", "lavfi", "-i",
                   f"gradients=s={width}x{height}:c0=0x{c0}:c1=0x{c1}"
                   f":x0={width // 2}:y0=0:speed=0.006:d={duration_sec:.2f}:type=radial"]
        filters.append(f"[0:v]fps={fps},setsar=1[bg]")

    next_index = 1
    behind_index = None
    if behind_layer is not None and Path(behind_layer).exists():
        inputs += ["-loop", "1", "-i", str(behind_layer)]
        behind_index = next_index
        next_index += 1

    if start_sec > 0:
        inputs += ["-ss", f"{start_sec:.3f}"]
    inputs += ["-i", str(avatar_src)]
    avatar_index = next_index

    stage = "bg"
    if behind_index is not None:
        filters.append(f"[{behind_index}:v]fps={fps},scale={width}:{height},setsar=1[behind]")
        filters.append("[bg][behind]overlay=0:0:format=auto[withtext]")
        stage = "withtext"
    zoom = max(float(compose_zoom or 1.0), 1.0)
    if zoom > 1.001:
        # Scale up then head-weighted crop: Avatar V often leaves subject ~30% tall.
        sw = math.ceil(width * zoom / 2) * 2
        sh = math.ceil(height * zoom / 2) * 2
        crop_x = max(0, (sw - width) // 2)
        # Bias crop upward so head stays in frame; trim empty desk/floor below.
        crop_y = max(0, int(round((sh - height) * 0.32)))
        filters.append(
            f"[{avatar_index}:v]fps={fps},scale={sw}:{sh}:flags=lanczos,"
            f"crop={width}:{height}:{crop_x}:{crop_y},setsar=1[av]")
    else:
        filters.append(f"[{avatar_index}:v]fps={fps},scale={width}:{height},setsar=1[av]")
    filters.append(f"[{stage}][av]overlay=0:0:format=auto,format=yuv420p[out]")

    args = ["-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
            "-t", f"{duration_sec:.3f}", "-an", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p", str(dst)]
    run(args, what=f"prepare_avatar {dst.name}")

    out_info = probe(dst)
    return {
        "src": str(avatar_src), "dst": str(dst), "fit": "avatar_composite",
        "duration_sec": round(duration_sec, 3), "start_sec": round(start_sec, 3),
        "background": "vfx" if vfx_src else background,
        "text_behind_head": behind_layer is not None,
        "compose_zoom": round(zoom, 3),
        "output_size": [out_info.width, out_info.height],
        "output_duration_sec": round(out_info.duration_sec, 3),
        "output_frames": out_info.nb_frames,
    }

"""Провайдер аватара HeyGen (§7.4, скилл ``redshift-avatar``).

Live: посегментная генерация через HeyGen API. Сегменты — цельные фразы,
липсинк строится по **финальной** (уже обрезанной) озвучке, поэтому в API
уходит не текст, а конкретный кусок ``voice_final.wav``: только так липсинк
совпадёт с тем, что реально звучит в ролике (§7.4.4).

Look id аватара 5 берётся из ``heygen.avatar_id`` в конфиге. Секрет
``HEYGEN_AVATAR_ID`` его не подменяет.

Mock: локальный рендер говорящей фигуры, у которой раскрытие рта следует
огибающей той же дорожки. Это не «серый прямоугольник»: лицо стоит в полосе
``avatar.face_band_y`` брендбука, губы движутся по звуку, и на таком клипе можно
честно проверять QC-11 (рассинхрон липсинка) и правило кадрирования.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ...errors import ProviderError
from ..audio import load_wav, rms_envelope, save_wav
from ..ffmpeg import (ffmpeg_bin, has_alpha as ff_has_alpha,
                      head_box as ff_head_box, probe)
from ..logging import get_logger
from ..retry import call_with_retry
from .base import Provider, ProviderMode, resolve_mode

_log = get_logger("avatar")

# libmagic на PCM WAV часто даёт audio/x-wav. HeyGen 400543 сравнивает
# заголовок со снятым типом: «audio/wav != audio/x-wav» — это не отказ ключа.
HEYGEN_AUDIO_CONTENT_TYPE = "audio/x-wav"
_HEYGEN_CONTENT_TYPE_MISMATCH = re.compile(
    r"Content type not match\s+([\w.+-]+/[\w.+-]+)\s+!=\s+([\w.+-]+/[\w.+-]+)",
    re.IGNORECASE,
)


def heygen_sniffed_audio_type(body: str) -> str | None:
    """Тип, который HeyGen снял с байтов файла (правая сторона 400543)."""
    match = _HEYGEN_CONTENT_TYPE_MISMATCH.search(body or "")
    if not match:
        return None
    return match.group(2)


def heygen_v3_avatar_payload(*, avatar_id: str, audio_url: str,
                             engine: str = "avatar_v",
                             motion_prompt: str = "",
                             want_alpha: bool = True) -> dict[str, Any]:
    """POST /v3/videos — Avatar V + ElevenLabs wav. Не v2 (legacy, без transparent).

    ``expressiveness`` не кладём: это Avatar IV. ``background: transparent``
    v2 отвергает. webm сам снимает фон.
    """
    payload: dict[str, Any] = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "audio_url": audio_url,
        "aspect_ratio": "9:16",
        "resolution": "1080p",
        "engine": {"type": str(engine or "avatar_v")},
    }
    if want_alpha:
        payload["output_format"] = "webm"
    prompt = (motion_prompt or "").strip()
    if prompt:
        payload["motion_prompt"] = prompt
    return payload


def resolve_heygen_look_id(cfg) -> str:
    """Look id аватара 5. Config — замок; секрет чужой лук не подставляет.

    ``HEYGEN_AVATAR_ID`` в GitHub Secrets однажды оказался другим look
    (не оливковая рубашка ``99ccc74e…``). Тогда HTTP и ``avatar_request.json``
    уехали не к аватару 5. Заказчик: всегда этот лук, всегда Avatar V.
    Секрет читается только если ``heygen.avatar_id`` в конфиге пуст.
    """
    configured = str(cfg.get("heygen.avatar_id") or "").strip()
    if configured:
        return configured
    return str(
        cfg.secret_for("heygen.avatar_id_env", purpose="HeyGen avatar look") or ""
    ).strip()


@dataclass
class AvatarSegment:
    index: int
    start: float
    end: float
    block_id: str
    path: Path
    face_bbox: tuple[int, int, int, int]
    has_alpha: bool = False
    provider_mode: str = "mock"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "start": round(self.start, 3), "end": round(self.end, 3),
            "duration": round(self.duration, 3), "block_id": self.block_id,
            "file": str(self.path), "face_bbox": list(self.face_bbox),
            "has_alpha": self.has_alpha, "provider_mode": self.provider_mode,
            **({"meta": self.meta} if self.meta else {}),
        }


class AvatarProvider(Provider):
    name = "heygen"

    def generate(self, *, audio_path: Path, out_path: Path, duration_sec: float,
                 index: int) -> AvatarSegment:
        raise NotImplementedError


# --- mock ---------------------------------------------------------------------

class MockAvatar(AvatarProvider):
    """Говорящая фигура: раскрытие рта следует огибающей речи."""

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name="heygen")

    def generate(self, *, audio_path: Path, out_path: Path, duration_sec: float,
                 index: int) -> AvatarSegment:
        width, height = self.cfg.resolution
        fps = self.cfg.fps
        # Прозрачный фон запрашивается только при включённом матировании (§7.7):
        # без него альфа некуда девать, и она превратится в чёрный фон.
        transparent = (bool(self.cfg.get("features.avatar_matting", False))
                       and str(self.cfg.get("heygen.background", "")).startswith("transparent"))
        if transparent and out_path.suffix.lower() != ".mov":
            out_path = out_path.with_suffix(".mov")   # mp4 не переносит альфу

        audio, sr = load_wav(audio_path)
        mono = audio[:, 0] if audio.ndim == 2 else audio
        env = rms_envelope(mono, sr, window_ms=25.0)
        env = env / (float(np.percentile(env, 97)) or 1.0)

        # §3.5: лицо в нижней трети, субтитры над ним.
        face_top, face_bottom = self.cfg.brand("avatar.face_band_y", [1080, 1480])
        head_cx = width // 2
        head_cy = int((face_top + face_bottom) / 2)
        head_r = int((face_bottom - face_top) / 2)

        from ..render.canvas import parse_color

        bg = parse_color(self.cfg.color("bg_light"))
        pure = parse_color(self.cfg.color("bg_pure"))
        ink = parse_color(self.cfg.color("ink"))
        skin = parse_color(self.cfg.color("accent_soft"))
        deep = parse_color(self.cfg.color("accent_deep"))

        total_frames = max(1, int(round(duration_sec * fps)))
        encoder = subprocess.Popen(
            [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "rawvideo", "-pix_fmt", "rgba" if transparent else "rgb24",
             "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
             "-c:v", "png" if transparent else "libx264",
             *([] if transparent else ["-preset", "veryfast", "-crf", "18",
                                       "-pix_fmt", "yuv420p"]),
             "-r", str(fps), str(out_path)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert encoder.stdin is not None

        try:
            for frame_no in range(total_frames):
                t = frame_no / fps
                sample = int(t * sr)
                openness = float(np.clip(env[min(sample, len(env) - 1)], 0.0, 1.2))
                sway = math.sin(t * 1.1) * 8
                breathe = math.sin(t * 0.9) * 5

                mode = "RGBA" if transparent else "RGB"
                base = (0, 0, 0, 0) if transparent else self._hex(bg, mode)
                frame = Image.new(mode, (width, height), base)
                draw = ImageDraw.Draw(frame)

                if not transparent:
                    draw.ellipse((head_cx - 620, head_cy - 260, head_cx + 620, height),
                                 fill=self._hex(pure, mode))

                # Плечи
                shoulder_top = head_cy + head_r + 60 + breathe
                draw.rounded_rectangle(
                    (head_cx - 330 + sway, shoulder_top, head_cx + 330 + sway, height),
                    radius=180, fill=self._hex(ink, mode))
                # Голова
                draw.ellipse((head_cx - head_r + sway, head_cy - head_r + breathe,
                              head_cx + head_r + sway, head_cy + head_r + breathe),
                             fill=self._hex(skin, mode))
                # Глаза
                eye_y = head_cy - head_r * 0.18 + breathe
                blink = 1.0 if (t % 3.4) > 0.12 else 0.15
                for dx in (-head_r * 0.34, head_r * 0.34):
                    draw.ellipse((head_cx + dx - 22 + sway, eye_y - 16 * blink,
                                  head_cx + dx + 22 + sway, eye_y + 16 * blink),
                                 fill=self._hex(ink, mode))
                # Рот: высота следует огибающей речи — это и есть «липсинк»
                mouth_y = head_cy + head_r * 0.38 + breathe
                mouth_h = 10 + openness * 52
                mouth_w = 88 + openness * 26
                draw.ellipse((head_cx - mouth_w / 2 + sway, mouth_y - mouth_h / 2,
                              head_cx + mouth_w / 2 + sway, mouth_y + mouth_h / 2),
                             fill=self._hex(deep, mode))
                if not transparent:
                    frame = frame.filter(ImageFilter.SMOOTH)
                encoder.stdin.write(frame.tobytes())
        finally:
            try:
                encoder.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            stderr = encoder.stderr.read() if encoder.stderr else b""
            if encoder.wait() != 0:
                raise ProviderError("не удалось собрать mock-аватар",
                                    stderr=stderr.decode("utf-8", "replace")[-800:])

        self.charge("generate", duration_sec, "sec",
                    duration_sec * float(self.cfg.get("budget.price.heygen_per_second", 0.05)))
        return AvatarSegment(
            index=index, start=0.0, end=duration_sec, block_id="",
            path=Path(out_path),
            face_bbox=(head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r),
            has_alpha=transparent, provider_mode="mock",
            meta={"lipsync_source": "rms_envelope"},
        )

    @staticmethod
    def _hex(color: Sequence[int], mode: str = "RGB") -> tuple:
        rgba = tuple(int(c) for c in color)
        return rgba if mode == "RGBA" else rgba[:3]


# --- live ---------------------------------------------------------------------

class HeyGenAvatar(AvatarProvider):
    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="heygen")
        self.api_key = api_key

    def _upload_audio(self, path: Path) -> str:
        import requests

        payload = path.read_bytes()

        def _post(content_type: str):
            return requests.post(
                "https://upload.heygen.com/v1/asset",
                data=payload,
                headers={"x-api-key": self.api_key, "Content-Type": content_type},
                timeout=self._timeout())

        def _asset_url(resp) -> str:
            if resp.status_code >= 400:
                raise ProviderError(f"HeyGen upload вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300])
            data = resp.json().get("data", {})
            url = data.get("url") or data.get("asset_url")
            if not url:
                raise ProviderError("HeyGen upload не вернул ссылку на ассет")
            return str(url)

        def _call() -> str:
            content_type = HEYGEN_AUDIO_CONTENT_TYPE
            resp = _post(content_type)
            if resp.status_code >= 400:
                sniffed = heygen_sniffed_audio_type(resp.text)
                if sniffed and sniffed != content_type:
                    # 400543: заголовок не совпал со снятым типом. Это MIME,
                    # не 401 — MCP не вызываем, повторяем с тем типом, который
                    # сервис уже прочитал из файла.
                    _log.info("HeyGen upload: повтор с MIME файла", extra={
                        "sent": content_type, "sniffed": sniffed,
                    })
                    resp = _post(sniffed)
            return _asset_url(resp)

        return call_with_retry(_call, **self._retry_kwargs("HeyGen upload"))

    def generate(self, *, audio_path: Path, out_path: Path, duration_sec: float,
                 index: int) -> AvatarSegment:
        import time

        import requests

        base = str(self.cfg.get("heygen.api_base", "https://api.heygen.com"))
        audio_url = self._upload_audio(audio_path)

        avatar_id = resolve_heygen_look_id(self.cfg)
        if not avatar_id:
            raise ProviderError("HeyGen avatar_id пуст (config + HEYGEN_AVATAR_ID)")

        want_alpha = str(self.cfg.get("heygen.background", "")).startswith("transparent")
        payload = heygen_v3_avatar_payload(
            avatar_id=avatar_id,
            audio_url=audio_url,
            engine=str(self.cfg.get("heygen.engine") or "avatar_v"),
            motion_prompt=str(self.cfg.get("heygen.motion_prompt") or ""),
            want_alpha=want_alpha,
        )

        def _create() -> str:
            resp = requests.post(f"{base}/v3/videos", json=payload,
                                 headers={"x-api-key": self.api_key,
                                          "Content-Type": "application/json"},
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"HeyGen generate вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:400])
            body = resp.json() or {}
            nested = body.get("data")
            data = nested if isinstance(nested, dict) else body
            video_id = data.get("video_id") or data.get("id")
            if not video_id:
                raise ProviderError("HeyGen не вернул video_id")
            return str(video_id)

        video_id = call_with_retry(_create, **self._retry_kwargs("HeyGen generate"))

        interval = float(self.cfg.get("heygen.poll_interval_sec", 10))
        deadline = time.time() + float(self.cfg.get("heygen.poll_timeout_sec", 900))
        video_url = ""
        while time.time() < deadline:
            resp = requests.get(f"{base}/v3/videos/{video_id}",
                                headers={"x-api-key": self.api_key}, timeout=self._timeout())
            body = resp.json() or {}
            nested = body.get("data")
            data = nested if isinstance(nested, dict) else body
            status = str(data.get("status", ""))
            if status == "completed":
                video_url = str(data.get("video_url") or "")
                break
            if status in ("failed", "error"):
                detail = str(data.get("failure_message") or data.get("error") or "")[:300]
                raise ProviderError("HeyGen сообщил об ошибке генерации",
                                    video_id=video_id, detail=detail)
            time.sleep(interval)
        if not video_url:
            raise ProviderError("HeyGen не завершил генерацию за отведённое время",
                                video_id=video_id)

        if want_alpha and out_path.suffix.lower() != ".webm":
            out_path = out_path.with_suffix(".webm")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(video_url, stream=True, timeout=self._timeout()) as resp:
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)

        self.charge("generate", duration_sec, "sec",
                    duration_sec * float(self.cfg.get("budget.price.heygen_per_second", 0.05)),
                    video_id=video_id)
        info = probe(out_path)
        at = min(0.5, max(0.0, duration_sec / 2))
        # Альфа и здесь измеряется, а не выводится из расширения: живой ответ
        # HeyGen приходил и с прозрачностью, и без неё под одним именем.
        alpha = ff_has_alpha(out_path, at_sec=at)
        return AvatarSegment(
            index=index, start=0.0, end=info.duration_sec or duration_sec, block_id="",
            path=Path(out_path),
            face_bbox=measured_face_bbox(self.cfg, Path(out_path), info,
                                         at=at, alpha=alpha),
            has_alpha=alpha,
            provider_mode="live", meta={"video_id": video_id},
        )


def build_avatar_provider(cfg, costs, *, video_id: str = "") -> AvatarProvider:
    """Источник аватара: API, готовые клипы или заглушка.

    ``heygen.source`` разводит три случая. ``api`` — обычный live-путь по
    ключу. ``prepared`` — двухфазный конвейер: клипы приходят снаружи, потому
    что ключа HeyGen у прогона нет, а MCP-коннектор живёт в чате. ``auto`` —
    выбрать самому: ключ есть → API, ключа нет, но клипы лежат → prepared,
    иначе заглушка.
    """
    source = str(cfg.get("heygen.source", "auto")).lower()
    clips_dir = _prepared_dir(cfg, video_id)

    # Mock-режим отменяет любой источник: он означает «никаких внешних
    # зависимостей», и требовать заранее подготовленные клипы в нём бессмысленно.
    if str(cfg.get("providers.mode", "auto")).lower() == "mock":
        return MockAvatar(cfg, costs)

    if source == "prepared":
        return PreparedAvatar(cfg, costs, clips_dir)

    key = cfg.secret_for("heygen.api_key_env", purpose="HeyGen")

    if source == "auto":
        if key:
            return HeyGenAvatar(cfg, costs, key)
        # Ключа нет — идём в двухфазный конвейер, а не в заглушку. Молчаливый
        # мок-аватар в живом прогоне — худший из возможных исходов: ролик
        # соберётся, пройдёт QC и уедет к зрителю с болванкой вместо ведущего.
        # PreparedAvatar на отсутствие клипов падает с понятным кодом и
        # выкладывает avatar_request.json, по которому их и достают.
        #
        # Спрашивать здесь resolve_mode нельзя: при providers.mode=live он
        # падает на отсутствии ключа, и ветка ниже становится недостижимой —
        # ровно в том прогоне, ради которого она и написана. Для ``auto``
        # отсутствие ключа HeyGen не сбой настройки, а штатный режим проекта.
        _log.info("ключа HeyGen нет — аватар ожидается готовыми клипами",
                  extra={"dir": str(clips_dir)})
        return PreparedAvatar(cfg, costs, clips_dir)

    # ``api`` заказан явно: тут отсутствие ключа — именно ошибка настройки, и
    # resolve_mode обязан сказать об этом вслух.
    if source == "api" and \
            resolve_mode(cfg, api_key=key, service="heygen") is ProviderMode.LIVE:
        return HeyGenAvatar(cfg, costs, key or "")

    return MockAvatar(cfg, costs)


def _prepared_dir(cfg, video_id: str) -> Path:
    base = cfg.path("heygen.prepared_dir", "assets/avatar_clips")
    return base / video_id if video_id else base


# --- готовые клипы (двухфазный конвейер) --------------------------------------

def measured_face_bbox(cfg, clip: Path, info, *, at: float,
                       alpha: bool) -> tuple[int, int, int, int]:
    """Коробка головы: измеренная по альфе, иначе — полоса из брендбука.

    Полоса ``avatar.face_band_y`` — догадка «голова обычно вот тут», и на
    новом аватаре она разъехалась с кадром: 475 px ширины против настоящих
    354, центр мимо на 39 px. Приёмы, которые ставятся относительно головы,
    вставали по догадке. Там, где альфа есть, догадка не нужна вовсе.
    """
    if alpha:
        measured = ff_head_box(clip, at_sec=at)
        if measured:
            return measured
    face_top, face_bottom = cfg.brand("avatar.face_band_y", [1080, 1480])
    return (int(info.width * 0.30), int(face_top),
            int(info.width * 0.70), int(face_bottom))


class PreparedAvatar(AvatarProvider):
    """Аватар берётся из заранее подготовленных клипов, а не из API.

    Ключа HeyGen в прогоне нет, а цифровой двойник нужен. Разрыв закрывается
    двумя фазами: Actions доходит до P6 и останавливается, выложив нарезанные
    куски речи; клипы генерируются снаружи (MCP-коннектор HeyGen в чате) и
    кладутся в репозиторий; прогон возобновляется с P6 и находит их готовыми.

    Провайдер намеренно не умеет «выкрутиться»: без клипа он останавливает
    прогон и говорит, для какого куска речи чего не хватает. Тихая подмена
    заглушкой означала бы ролик без ведущего (§10.5.4).
    """

    name = "heygen"

    def __init__(self, cfg, costs, clips_dir: Path) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="heygen")
        self.clips_dir = clips_dir
        self.missing: list[dict[str, Any]] = []

    def _find(self, index: int) -> Path | None:
        # .mov несёт альфу, .webm — тоже; .mp4 берём как крайний случай:
        # без альфы фон аватара придётся оставить как есть.
        for suffix in (".mov", ".webm", ".mp4"):
            candidate = self.clips_dir / f"seg_{index:02d}{suffix}"
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
        return None

    def _face_bbox(self, clip: Path, info, *, at: float,
                   alpha: bool) -> tuple[int, int, int, int]:
        return measured_face_bbox(self.cfg, clip, info, at=at, alpha=alpha)

    def generate(self, *, audio_path: Path, out_path: Path, duration_sec: float,
                 index: int) -> AvatarSegment:
        clip = self._find(index)
        if clip is None:
            self.missing.append({
                "index": index,
                "audio": str(audio_path),
                "duration_sec": round(duration_sec, 3),
                "expected": str(self.clips_dir / f"seg_{index:02d}.mov"),
            })
            raise ProviderError(
                f"нет готового клипа аватара для сегмента {index}",
                code="AVATAR_CLIP_NOT_PREPARED",
                hint=f"положите файл в {self.clips_dir}/seg_{index:02d}.mov "
                     f"(липсинк по {audio_path.name}, {duration_sec:.2f} сек)")

        info = probe(clip)
        # Расхождение длительности сдвинуло бы липсинк: клип обязан совпасть с
        # куском речи, под который он сгенерирован.
        drift = abs(info.duration_sec - duration_sec)
        if drift > 0.20:
            raise ProviderError(
                f"клип аватара {clip.name} длиннее/короче своего куска речи на "
                f"{drift:.2f} сек — липсинк уедет",
                code="AVATAR_CLIP_DURATION_MISMATCH",
                hint=f"ожидается {duration_sec:.2f} сек, в файле {info.duration_sec:.2f}")

        # Клип с однотонным фоном превращается в альфу здесь, а не руками:
        # HeyGen прозрачности не отдаёт, и просить её бессмысленно — приходит
        # непрозрачный кадр. Просим у него ключевой цвет и убираем его сами.
        chroma = str(self.cfg.get("heygen.prepared_chroma", "") or "")
        if chroma and clip.suffix.lower() == ".mp4":
            from ..render.chroma import key_out

            keyed = out_path.with_name(f"{out_path.stem}_alpha.mov")
            clip = key_out(clip, keyed, color=chroma)

        dst = out_path.with_suffix(clip.suffix)
        if dst.resolve() != clip.resolve():
            dst.write_bytes(clip.read_bytes())

        # Альфа измеряется, а не выводится из расширения. Прошлый аватар
        # прислал .webm без прозрачности, провайдер поверил имени файла, и
        # приёмы за головой ушли за непрозрачный план — в кадре их не было.
        at = min(0.5, max(0.0, duration_sec / 2))
        has_alpha = ff_has_alpha(clip, at_sec=at)
        return AvatarSegment(
            index=index, start=0.0, end=duration_sec, block_id="",
            path=dst,
            face_bbox=self._face_bbox(clip, info, at=at, alpha=has_alpha),
            has_alpha=has_alpha, provider_mode="prepared",
            meta={"source_clip": str(clip), "lipsync_source": "prepared"},
        )

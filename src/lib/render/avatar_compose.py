"""Avatar compose_zoom vs face_band / caption safe (MUST-009).

``heygen.compose_zoom`` is a requested ceiling. The fitted zoom and pan must
keep the projected face inside ``avatar.face_band_y`` when it fits, and must
not intersect the caption strip or the bottom ``safe_zones.bottom_px``.

The talking head sits in the lower third (captions above it). Do not shrink
the clip below 1.0 unless the face cannot otherwise miss the caption / bottom
safe bands — scale < 1 exposes clip edges on the canvas.

## Natural placement (``heygen.compose_zoom: 1.0``)

That band-fit above was built for the old landscape look: HeyGen handed back
a 1920×1080 plate with the subject sitting small in the centre, and the only
way to make the face read on a phone screen was to blow the whole clip up
(``compose_zoom`` up to 2.7×) via CSS width/height on an already-encoded VP9
frame — a real upscale, the browser interpolates pixels that were never
there. The new look (0050 r63, ``cfcb3575…``) is shot vertically and already
fills the frame; the owner measured a reference crop in a photo editor and
was explicit: **stop stretching the HeyGen clip, crop it and pin it to the
bottom of frame instead**.

``fit_compose_zoom`` reads that as ``requested_zoom <= 1.0``: it skips the
band-fit entirely and calls :func:`_fit_natural`, which never scales
(``zoom`` is always exactly ``1.0``) and only translates the clip vertically
so the *measured* head top (:func:`~src.lib.ffmpeg.head_box`, real alpha, not
a guess) lands at ``avatar.head_top_frac`` of the frame height. Everything
below the visible frame — desk, floor, the rest of the studio — falls past
``#root``'s ``overflow:hidden`` and is simply never drawn; everything above
the head is transparent, so the scene backdrop (or the caption band, which
sits above the head by construction at that fraction) shows through. No
pixel is ever asked to be bigger than the camera actually recorded it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .canvas import caption_layout_bbox


def rect_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a)
    bx1, by1, bx2, by2 = (float(v) for v in b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def face_band_y(brandbook: dict[str, Any]) -> tuple[float, float]:
    band = (brandbook.get("avatar") or {}).get("face_band_y") or [1080, 1480]
    return float(band[0]), float(band[1])


def bottom_safe_rect(brandbook: dict[str, Any], *,
                     width: int, height: int) -> tuple[float, float, float, float]:
    bottom = int((brandbook.get("safe_zones") or {}).get("bottom_px", 400))
    return (0.0, float(height - bottom), float(width), float(height))


def collision_rects(brandbook: dict[str, Any], *,
                    width: int, height: int
                    ) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Bands the face must not occupy: on-avatar caption strip + bottom 400."""
    return [
        ("caption", caption_layout_bbox(brandbook, for_avatar=True)),
        ("bottom_safe", bottom_safe_rect(brandbook, width=width, height=height)),
    ]


def target_face_rect(brandbook: dict[str, Any], *,
                     width: int, height: int, mode: str = "A"
                     ) -> tuple[float, float, float, float]:
    """Where the face should sit after compose.

    Mode A: brandbook ``face_band_y`` (lower third), kept out of captions and
    the bottom safe band. Captions live *above* the head, so the clip is
    ``cap_bottom`` — not ``cap_top``.
    Mode B (split): lower half, still above bottom safe and not under captions;
    right ``safe_zones.right_px`` stays clear of the face (text/UI lane).
    """
    band_lo, band_hi = face_band_y(brandbook)
    cap = caption_layout_bbox(brandbook, for_avatar=True)
    bottom = int((brandbook.get("safe_zones") or {}).get("bottom_px", 400))
    right = int((brandbook.get("safe_zones") or {}).get("right_px", 250))
    y_ceil = float(height - bottom)
    cap_top, cap_bot = float(cap[1]), float(cap[3])
    if str(mode).upper() == "B":
        y0 = max(float(height) * 0.5, cap_bot)
        y1 = y_ceil
        if y1 <= y0 + 8:
            y0 = cap_bot
            y1 = y_ceil
        if y1 <= y0:
            y1 = y_ceil
            y0 = max(0.0, y1 - (band_hi - band_lo))
        return (0.0, y0, float(max(1, width - right)), y1)

    y0, y1 = band_lo, min(band_hi, y_ceil)
    if cap_bot <= y0 + 1:
        y0 = max(y0, cap_bot)
    elif cap_top >= y1 - 1:
        y1 = min(y1, cap_top)
    else:
        room_below = y_ceil - cap_bot
        room_above = cap_top
        if room_below >= (band_hi - band_lo) and room_below >= room_above:
            y0 = max(band_lo, cap_bot)
            y1 = min(band_hi, y_ceil)
        else:
            y1 = min(band_hi, cap_top, y_ceil)
            y0 = max(0.0, y1 - (band_hi - band_lo))
    if y1 <= y0:
        y1 = y_ceil
        y0 = max(cap_bot, y1 - (band_hi - band_lo))
        if y1 <= y0:
            y0 = max(0.0, y1 - (band_hi - band_lo))
    return (0.0, y0, float(width), y1)


def default_face_bbox(brandbook: dict[str, Any], *,
                      width: int, height: int) -> tuple[int, int, int, int]:
    lo, hi = face_band_y(brandbook)
    return (int(width * 0.30), int(lo), int(width * 0.70), int(hi))


def project_face(bbox: Sequence[float], zoom: float, left: float, top: float
                 ) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    z = float(zoom)
    return (left + x1 * z, top + y1 * z, left + x2 * z, top + y2 * z)


@dataclass(frozen=True)
class ComposeFit:
    zoom: float
    left: float
    top: float
    fx: float
    fy: float
    face: tuple[float, float, float, float]
    requested_zoom: float
    mode: str

    @property
    def crop_x(self) -> int:
        return int(round(-self.left))

    @property
    def crop_y(self) -> int:
        return int(round(-self.top))


def _fit_natural(
    face_bbox: tuple[float, float, float, float],
    *,
    brandbook: dict[str, Any],
    width: int,
    height: int,
    mode: str,
) -> ComposeFit:
    """Zoom pinned to 1.0: translate only, head anchored by ``head_top_frac``.

    See the module docstring — this is the r63 replacement for band-fit
    scaling, not a special case of it. ``left`` stays 0: the measured face
    box wobbles 60–80 px left/right frame to frame (a head turn mid-sentence,
    not a framing error), and correcting for one sampled frame would just
    trade a real jitter for an invented one. HeyGen's own camera already
    centres the subject; only the vertical anchor needs setting.
    """
    sx1, sy1, sx2, sy2 = face_bbox
    head_top_frac = float((brandbook.get("avatar") or {}).get("head_top_frac", 0.42))
    target_top = float(height) * head_top_frac
    # Floor, not a fight for the same pixels: captions live in a fixed band
    # above the head (§5.1), and a shorter head box (a tighter alpha read)
    # must not let the translation creep up underneath it.
    cap_bottom = float(caption_layout_bbox(brandbook, for_avatar=True)[3])
    if target_top < cap_bottom:
        target_top = cap_bottom
    left = 0.0
    top = target_top - sy1
    projected = project_face((sx1, sy1, sx2, sy2), 1.0, left, top)
    cx = (sx1 + sx2) / 2.0
    cy = (sy1 + sy2) / 2.0
    return ComposeFit(
        zoom=1.0,
        left=left,
        top=top,
        fx=min(max(cx / max(width, 1), 0.05), 0.95),
        fy=min(max(cy / max(height, 1), 0.05), 0.95),
        face=projected,
        requested_zoom=1.0,
        mode=str(mode).upper(),
    )


def fit_compose_zoom(
    face_bbox: Sequence[float] | None,
    requested_zoom: float,
    *,
    brandbook: dict[str, Any],
    width: int = 1080,
    height: int = 1920,
    mode: str = "A",
) -> ComposeFit:
    """Clamp zoom/pan so the face stays in band and misses caption/bottom safe.

    ``requested_zoom <= 1.0`` routes to :func:`_fit_natural` (crop-and-pin,
    no upscale) instead of the band-fit below it — see the module docstring.
    """
    req = max(float(requested_zoom or 1.0), 1.0)
    if not face_bbox or len(face_bbox) != 4:
        face_bbox = default_face_bbox(brandbook, width=width, height=height)
    sx1, sy1, sx2, sy2 = (float(v) for v in face_bbox)
    if float(requested_zoom or 0.0) <= 1.0 + 1e-6:
        return _fit_natural(
            (sx1, sy1, sx2, sy2), brandbook=brandbook,
            width=width, height=height, mode=mode)
    fw = max(sx2 - sx1, 1.0)
    fh = max(sy2 - sy1, 1.0)
    tx0, ty0, tx1, ty1 = target_face_rect(
        brandbook, width=width, height=height, mode=mode)
    tw = max(tx1 - tx0, 1.0)
    th = max(ty1 - ty0, 1.0)
    cap = caption_layout_bbox(brandbook, for_avatar=True)
    bottom = int((brandbook.get("safe_zones") or {}).get("bottom_px", 400))
    legal_lo = float(cap[3])
    legal_hi = float(height - bottom)
    if legal_hi <= legal_lo + 8:
        legal_lo = 0.0
    legal_h = max(legal_hi - legal_lo, 1.0)
    # Cap zoom by the legal gap (captions → bottom safe), not only the
    # preferred band — otherwise a 400 px band forces scale < 1 and the
    # clip edges show on the canvas.
    z_band = min(req, tw / fw, th / fh)
    z_legal = min(req, tw / fw, legal_h / fh)
    # Prefer the brandbook band when that does not shrink the clip; otherwise
    # use the full legal gap (captions → bottom safe) so scale stays ≥ 1.
    z = z_band if z_band >= 1.0 else z_legal
    out_w, out_h = fw * z, fh * z
    dest_x = tx0 + (tw - out_w) / 2.0
    # Sit in the lower part of the preferred band (head at the bottom).
    dest_y = ty0 + max(0.0, (th - out_h) * 0.55)
    if dest_y + out_h > legal_hi:
        dest_y = legal_hi - out_h
    if dest_y < legal_lo:
        dest_y = legal_lo
    left = dest_x - sx1 * z
    top = dest_y - sy1 * z
    projected = project_face((sx1, sy1, sx2, sy2), z, left, top)
    cx = (sx1 + sx2) / 2.0
    cy = (sy1 + sy2) / 2.0
    return ComposeFit(
        zoom=z,
        left=left,
        top=top,
        fx=min(max(cx / max(width, 1), 0.05), 0.95),
        fy=min(max(cy / max(height, 1), 0.05), 0.95),
        face=projected,
        requested_zoom=req,
        mode=str(mode).upper(),
    )


def face_in_band(face: Sequence[float], brandbook: dict[str, Any], *,
                 mode: str = "A") -> bool:
    tx0, ty0, tx1, ty1 = target_face_rect(
        brandbook, width=1080, height=1920, mode=mode)
    x1, y1, x2, y2 = (float(v) for v in face)
    return x1 >= tx0 - 1 and x2 <= tx1 + 1 and y1 >= ty0 - 1 and y2 <= ty1 + 1

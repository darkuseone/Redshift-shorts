"""Pre-baked US hex-grid positions, income data and polygon points.

Hex geometry: flat-top, hexW=80, hexS=40, hexH=40*sqrt(3)≈69.28.
Grid offset for 9:16 (1080×1920): startX=180, startY=310.
Catalog 16:9 uses startX=480, startY=200; we shift for portrait.

Color scale: #451a03 → #f59e0b → #fef3c7 (brown-amber-cream).
"""
from __future__ import annotations

import math
from typing import Any

_HEX_W = 80
_HEX_S = _HEX_W / 2  # 40
_HEX_H = _HEX_S * math.sqrt(3)  # ≈69.28

# 9:16 layout — hex grid centred in the map area
_START_X = 180.0
_START_Y = 310.0

UMH_VB = (0, 0, 1080, 1920)

# Grid positions (col, row) — identical to catalog
UMH_POSITIONS: dict[str, tuple[int, int]] = {
    "ME": (10, 0), "VT": (9, 1), "NH": (10, 1),
    "WA": (0, 2), "MT": (1, 2), "ND": (2, 2), "MN": (3, 2),
    "WI": (4, 2), "MI": (7, 2), "NY": (8, 2), "MA": (9, 2), "RI": (10, 2),
    "ID": (0, 3), "WY": (1, 3), "SD": (2, 3), "IA": (3, 3),
    "IL": (4, 3), "IN": (5, 3), "OH": (6, 3), "PA": (7, 3),
    "NJ": (8, 3), "CT": (9, 3),
    "OR": (0, 4), "NV": (1, 4), "CO": (2, 4), "NE": (3, 4),
    "MO": (4, 4), "KY": (5, 4), "WV": (6, 4), "VA": (7, 4),
    "MD": (8, 4), "DE": (9, 4),
    "CA": (0, 5), "UT": (1, 5), "NM": (2, 5), "KS": (3, 5),
    "AR": (4, 5), "TN": (5, 5), "NC": (6, 5), "SC": (7, 5), "DC": (8, 5),
    "AZ": (1, 6), "OK": (3, 6), "LA": (4, 6), "MS": (5, 6),
    "AL": (6, 6), "GA": (7, 6),
    "HI": (0, 7), "TX": (3, 7), "FL": (7, 7),
    "AK": (0, 8),
}

# Median household income (2024 ACS) — from catalog
UMH_INCOME: dict[str, int] = {
    "MD": 106998, "NJ": 101778, "MA": 101079, "CT": 92545, "HI": 91010,
    "NH": 90845, "WA": 90325, "CA": 89648, "CO": 87598, "VA": 87249,
    "UT": 86833, "MN": 84313, "AK": 83601, "NY": 81386, "RI": 81370,
    "IL": 79253, "OR": 76632, "DE": 75932, "WI": 72458, "NV": 71646,
    "VT": 71560, "PA": 71610, "ND": 71017, "NE": 70654, "TX": 70813,
    "AZ": 70821, "ID": 69973, "MT": 68091, "GA": 67992, "ME": 67587,
    "FL": 67917, "IA": 67684, "WY": 67249, "SD": 66894, "MI": 66986,
    "IN": 65834, "OH": 64018, "MO": 63594, "KS": 66354, "NC": 65070,
    "TN": 63426, "SC": 62064, "OK": 60438, "KY": 57584, "NM": 58257,
    "AL": 57563, "LA": 55728, "WV": 52520, "AR": 53289, "MS": 52434,
    "DC": 101722,
}

_MIN_INCOME = min(UMH_INCOME.values())
_MAX_INCOME = max(UMH_INCOME.values())

_COLOR_LOW = (0x45, 0x1a, 0x03)
_COLOR_MID = (0xf5, 0x9e, 0x0b)
_COLOR_HIGH = (0xfe, 0xf3, 0xc7)

UMH_TOP5 = ["MD", "NJ", "MA", "CT", "HI"]

UMH_TITLE = "Median Household Income by State"
UMH_SUBTITLE = "American Community Survey, 2024"
UMH_SOURCE = "Source: U.S. Census Bureau, American Community Survey 2024"
UMH_LEG_LOW = "$52k"
UMH_LEG_HIGH = "$107k"


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def umh_color(value: int) -> str:
    """Map income value to hex color on the brown-amber-cream scale."""
    t = max(0.0, min(1.0, (value - _MIN_INCOME) / (_MAX_INCOME - _MIN_INCOME)))
    if t < 0.5:
        t2 = t / 0.5
        r = _lerp(_COLOR_LOW[0], _COLOR_MID[0], t2)
        g = _lerp(_COLOR_LOW[1], _COLOR_MID[1], t2)
        b = _lerp(_COLOR_LOW[2], _COLOR_MID[2], t2)
    else:
        t2 = (t - 0.5) / 0.5
        r = _lerp(_COLOR_MID[0], _COLOR_HIGH[0], t2)
        g = _lerp(_COLOR_MID[1], _COLOR_HIGH[1], t2)
        b = _lerp(_COLOR_MID[2], _COLOR_HIGH[2], t2)
    return f"#{r:02x}{g:02x}{b:02x}"


def umh_is_light_text(value: int) -> bool:
    """Dark hexes (low income) need light text."""
    t = (value - _MIN_INCOME) / (_MAX_INCOME - _MIN_INCOME)
    return t < 0.35


def _hex_center(col: int, row: int) -> tuple[float, float]:
    cx = _START_X + col * (_HEX_W * 0.75)
    cy = _START_Y + row * _HEX_H
    if row % 2 == 1:
        cx += _HEX_W * 0.375
    return cx, cy


def _hex_points(cx: float, cy: float) -> str:
    pts = [
        (cx - _HEX_S, cy),
        (cx - _HEX_S / 2, cy - _HEX_H / 2),
        (cx + _HEX_S / 2, cy - _HEX_H / 2),
        (cx + _HEX_S, cy),
        (cx + _HEX_S / 2, cy + _HEX_H / 2),
        (cx - _HEX_S / 2, cy + _HEX_H / 2),
    ]
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)


def umh_build_hexes() -> list[dict[str, Any]]:
    """Build list of hex dicts with pre-computed SVG points.

    Each dict: {abbr, col, row, cx, cy, points, income, color, light_text}.
    Sorted by distance from grid centroid (for center-out stagger).
    """
    hexes: list[dict[str, Any]] = []
    centers: list[tuple[float, float]] = []
    for abbr, (col, row) in UMH_POSITIONS.items():
        cx, cy = _hex_center(col, row)
        centers.append((cx, cy))
        inc = UMH_INCOME.get(abbr, _MIN_INCOME)
        hexes.append({
            "abbr": abbr,
            "col": col,
            "row": row,
            "cx": cx,
            "cy": cy,
            "points": _hex_points(cx, cy),
            "income": inc,
            "color": umh_color(inc),
            "light_text": umh_is_light_text(inc),
        })
    avg_cx = sum(c[0] for c in centers) / len(centers)
    avg_cy = sum(c[1] for c in centers) / len(centers)
    for i, h in enumerate(hexes):
        dx = h["cx"] - avg_cx
        dy = h["cy"] - avg_cy
        h["dist"] = math.sqrt(dx * dx + dy * dy)
    hexes.sort(key=lambda h: h["dist"])
    return hexes

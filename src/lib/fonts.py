"""Разбор и проверка шрифтов — ядро скилла ``redshift-fonts`` (§3.4).

ТЗ требует проверять шрифт **до** вшивания в шаблон: полный кириллический
набор глифов и лицензия, разрешающая коммерческое использование и встраивание.
Bebas Neue, Anton и другие популярные condensed кириллицы не содержат — такой
шрифт обязан ронять прогон с ``FONT_MISSING_CYRILLIC``, а не рендерить
«квадратики».

Реализован минимальный парсер sfnt: таблицы ``cmap`` (форматы 4/6/12),
``name`` и ``OS/2`` (поле fsType). Внешних зависимостей нет намеренно —
fontTools не нужен ради трёх таблиц, а лишняя зависимость усложняет раннер.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from ..errors import FontLicenseError, FontMissingCyrillic

# Кириллица: основной блок + Ё/ё (§3.4)
CYRILLIC_RANGES: tuple[tuple[int, int], ...] = ((0x0410, 0x044F), (0x0401, 0x0401), (0x0451, 0x0451))
LATIN_DIGITS_RANGES: tuple[tuple[int, int], ...] = ((0x0030, 0x0039), (0x0041, 0x005A), (0x0061, 0x007A))

# fsType (OS/2): бит 1 — запрет встраивания, биты 8/9 — no-subsetting/bitmap-only
FSTYPE_RESTRICTED = 0x0002
FSTYPE_PREVIEW_PRINT = 0x0004
FSTYPE_EDITABLE = 0x0008
FSTYPE_NO_SUBSET = 0x0100
FSTYPE_BITMAP_ONLY = 0x0200

_COMMERCIAL_OK_MARKERS = (
    "open font license", "ofl", "sil open font", "apache license", "mit license",
    "ubuntu font licence", "ubuntu font license", "public domain", "cc0",
)
_COMMERCIAL_BAD_MARKERS = (
    "non-commercial", "noncommercial", "personal use only", "not for commercial",
    "demo version", "evaluation only",
)


@dataclass
class FontInfo:
    path: str
    family: str = ""
    subfamily: str = ""
    full_name: str = ""
    license_description: str = ""
    license_url: str = ""
    copyright: str = ""
    fs_type: int = 0
    codepoints: frozenset[int] = field(default_factory=frozenset)
    units_per_em: int = 1000

    # --- производные проверки ---
    @property
    def embedding_allowed(self) -> bool:
        return not bool(self.fs_type & FSTYPE_RESTRICTED)

    @property
    def commercial_use_allowed(self) -> bool:
        text = " ".join((self.license_description, self.license_url, self.copyright)).lower()
        if any(bad in text for bad in _COMMERCIAL_BAD_MARKERS):
            return False
        if any(good in text for good in _COMMERCIAL_OK_MARKERS):
            return True
        # Нет явного маркера — судим по fsType: installable/editable считаем годным.
        return self.embedding_allowed

    def missing(self, ranges: Sequence[tuple[int, int]] = CYRILLIC_RANGES) -> list[str]:
        out: list[str] = []
        for start, end in ranges:
            for cp in range(start, end + 1):
                if cp not in self.codepoints:
                    out.append(chr(cp))
        return out

    def covers(self, text: str) -> bool:
        return all(ord(ch) in self.codepoints for ch in text if not ch.isspace())

    def has_cyrillic(self) -> bool:
        return not self.missing()

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "family": self.family,
            "subfamily": self.subfamily,
            "full_name": self.full_name,
            "license": self.license_description or self.license_url or self.copyright,
            "fs_type": self.fs_type,
            "embedding_allowed": self.embedding_allowed,
            "commercial_use_allowed": self.commercial_use_allowed,
            "has_cyrillic": self.has_cyrillic(),
            "glyph_count": len(self.codepoints),
        }


# --- парсер sfnt --------------------------------------------------------------

def _read_tables(blob: bytes) -> dict[str, tuple[int, int]]:
    if len(blob) < 12:
        raise ValueError("файл слишком короткий для sfnt")
    tag = blob[:4]
    offset = 0
    if tag == b"ttcf":
        num_fonts = struct.unpack(">I", blob[8:12])[0]
        if num_fonts < 1:
            raise ValueError("пустая TrueType-коллекция")
        offset = struct.unpack(">I", blob[12:16])[0]
    elif tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        raise ValueError(f"неизвестная сигнатура шрифта: {tag!r}")

    num_tables = struct.unpack(">H", blob[offset + 4:offset + 6])[0]
    tables: dict[str, tuple[int, int]] = {}
    pos = offset + 12
    for _ in range(num_tables):
        if pos + 16 > len(blob):
            break
        rec_tag = blob[pos:pos + 4].decode("latin-1").strip()
        rec_off, rec_len = struct.unpack(">II", blob[pos + 8:pos + 16])
        tables[rec_tag] = (rec_off, rec_len)
        pos += 16
    return tables


def _parse_cmap_format4(blob: bytes, off: int) -> set[int]:
    seg_x2 = struct.unpack(">H", blob[off + 6:off + 8])[0]
    seg = seg_x2 // 2
    end_off = off + 14
    start_off = end_off + seg_x2 + 2
    delta_off = start_off + seg_x2
    range_off = delta_off + seg_x2
    out: set[int] = set()
    for i in range(seg):
        end = struct.unpack(">H", blob[end_off + i * 2:end_off + i * 2 + 2])[0]
        start = struct.unpack(">H", blob[start_off + i * 2:start_off + i * 2 + 2])[0]
        delta = struct.unpack(">h", blob[delta_off + i * 2:delta_off + i * 2 + 2])[0]
        rng = struct.unpack(">H", blob[range_off + i * 2:range_off + i * 2 + 2])[0]
        if start == 0xFFFF:
            continue
        for cp in range(start, min(end, 0xFFFE) + 1):
            if rng == 0:
                gid = (cp + delta) & 0xFFFF
            else:
                gi = range_off + i * 2 + rng + (cp - start) * 2
                if gi + 2 > len(blob):
                    continue
                gid = struct.unpack(">H", blob[gi:gi + 2])[0]
                if gid:
                    gid = (gid + delta) & 0xFFFF
            if gid:
                out.add(cp)
    return out


def _parse_cmap_format6(blob: bytes, off: int) -> set[int]:
    first, count = struct.unpack(">HH", blob[off + 6:off + 10])
    out: set[int] = set()
    for i in range(count):
        gi = off + 10 + i * 2
        if gi + 2 > len(blob):
            break
        if struct.unpack(">H", blob[gi:gi + 2])[0]:
            out.add(first + i)
    return out


def _parse_cmap_format12(blob: bytes, off: int) -> set[int]:
    n_groups = struct.unpack(">I", blob[off + 12:off + 16])[0]
    out: set[int] = set()
    for i in range(n_groups):
        gi = off + 16 + i * 12
        if gi + 12 > len(blob):
            break
        start, end, start_gid = struct.unpack(">III", blob[gi:gi + 12])
        if start_gid == 0 and end - start > 0x10000:
            continue
        for cp in range(start, min(end, start + 0x20000) + 1):
            out.add(cp)
    return out


def _parse_cmap(blob: bytes, off: int) -> set[int]:
    n_tables = struct.unpack(">H", blob[off + 2:off + 4])[0]
    best: set[int] = set()
    subtables: list[tuple[int, int, int]] = []
    for i in range(n_tables):
        rec = off + 4 + i * 8
        if rec + 8 > len(blob):
            break
        plat, enc, sub_off = struct.unpack(">HHI", blob[rec:rec + 8])
        subtables.append((plat, enc, off + sub_off))
    # Приоритет: Unicode full (3,10) → Unicode BMP (3,1) → всё остальное
    def rank(item: tuple[int, int, int]) -> int:
        plat, enc, _ = item
        if plat == 3 and enc == 10:
            return 0
        if plat == 0 and enc in (4, 6):
            return 1
        if plat == 3 and enc == 1:
            return 2
        if plat == 0:
            return 3
        return 4

    for _plat, _enc, sub_off in sorted(subtables, key=rank):
        if sub_off + 4 > len(blob):
            continue
        fmt = struct.unpack(">H", blob[sub_off:sub_off + 2])[0]
        try:
            if fmt == 4:
                best |= _parse_cmap_format4(blob, sub_off)
            elif fmt == 6:
                best |= _parse_cmap_format6(blob, sub_off)
            elif fmt == 12:
                best |= _parse_cmap_format12(blob, sub_off)
        except (struct.error, IndexError, ValueError):
            continue
        if best:
            break
    return best


def _parse_name(blob: bytes, off: int) -> dict[int, str]:
    count, string_off = struct.unpack(">HH", blob[off + 2:off + 6])
    storage = off + string_off
    out: dict[int, str] = {}
    for i in range(count):
        rec = off + 6 + i * 12
        if rec + 12 > len(blob):
            break
        plat, enc, _lang, name_id, length, str_off = struct.unpack(">HHHHHH", blob[rec:rec + 12])
        start = storage + str_off
        raw = blob[start:start + length]
        if not raw:
            continue
        try:
            if plat == 3 or (plat == 0):
                text = raw.decode("utf-16-be", "replace")
            else:
                text = raw.decode("latin-1", "replace")
        except (UnicodeDecodeError, LookupError):
            continue
        text = text.strip("\x00").strip()
        # Английские записи (plat 3) приоритетнее — перезаписываем.
        if name_id not in out or plat == 3:
            out[name_id] = text
    return out


@lru_cache(maxsize=64)
def read_font(path: str | Path) -> FontInfo:
    path = str(path)
    with open(path, "rb") as fh:
        blob = fh.read()
    tables = _read_tables(blob)

    codepoints: set[int] = set()
    if "cmap" in tables:
        codepoints = _parse_cmap(blob, tables["cmap"][0])

    names: dict[int, str] = {}
    if "name" in tables:
        names = _parse_name(blob, tables["name"][0])

    fs_type = 0
    if "OS/2" in tables:
        off = tables["OS/2"][0]
        if off + 10 <= len(blob):
            fs_type = struct.unpack(">H", blob[off + 8:off + 10])[0]

    upem = 1000
    if "head" in tables:
        off = tables["head"][0]
        if off + 20 <= len(blob):
            upem = struct.unpack(">H", blob[off + 18:off + 20])[0] or 1000

    return FontInfo(
        path=path,
        family=names.get(1, ""),
        subfamily=names.get(2, ""),
        full_name=names.get(4, names.get(1, "")),
        license_description=names.get(13, ""),
        license_url=names.get(14, ""),
        copyright=names.get(0, ""),
        fs_type=fs_type,
        codepoints=frozenset(codepoints),
        units_per_em=upem,
    )


# --- проверки (§8.2, skill redshift-fonts) -----------------------------------

def validate_font(path: str | Path, *, require_cyrillic: bool = True,
                  sample_text: str | None = None) -> FontInfo:
    """Проверить шрифт перед использованием. Бросает FONT_* при провале."""
    info = read_font(path)
    if require_cyrillic:
        missing = info.missing()
        if missing:
            raise FontMissingCyrillic(
                f"шрифт {info.family or Path(path).name!r} не содержит кириллицы",
                path=str(path), missing_sample="".join(missing[:12]),
                missing_count=len(missing),
            )
    if sample_text and not info.covers(sample_text):
        absent = sorted({ch for ch in sample_text if not ch.isspace() and ord(ch) not in info.codepoints})
        raise FontMissingCyrillic(
            f"шрифт {info.family or Path(path).name!r} не покрывает контрольный текст",
            path=str(path), missing="".join(absent[:20]),
        )
    if not info.embedding_allowed:
        raise FontLicenseError(
            f"лицензия шрифта {info.family or Path(path).name!r} запрещает встраивание (fsType={info.fs_type})",
            path=str(path), fs_type=info.fs_type,
        )
    if not info.commercial_use_allowed:
        raise FontLicenseError(
            f"лицензия шрифта {info.family or Path(path).name!r} не разрешает коммерческое использование",
            path=str(path), license=info.license_description[:200],
        )
    return info


def pick_font(candidates: Iterable[str | Path], *, require_cyrillic: bool = True,
              sample_text: str | None = None) -> tuple[Path, FontInfo, list[dict]]:
    """Первый годный шрифт из списка + журнал отказов (для лога и отчёта)."""
    rejected: list[dict] = []
    for cand in candidates:
        p = Path(cand)
        if not p.exists():
            rejected.append({"path": str(p), "reason": "файл не найден"})
            continue
        try:
            info = validate_font(p, require_cyrillic=require_cyrillic, sample_text=sample_text)
            return p, info, rejected
        except (FontMissingCyrillic, FontLicenseError) as exc:
            rejected.append({"path": str(p), "reason": exc.message, "code": exc.code})
        except (ValueError, struct.error, OSError) as exc:
            rejected.append({"path": str(p), "reason": f"не удалось разобрать: {exc}"})
    raise FontMissingCyrillic(
        "ни один шрифт-кандидат не прошёл проверку (кириллица + лицензия)",
        rejected=rejected,
    )

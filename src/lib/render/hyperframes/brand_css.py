"""Брендбук → CSS для композиции HyperFrames.

Брендбук остаётся единственным источником правды по цвету, типографике и safe
zones (§3). Раньше эти значения читал Python-композитор, теперь их читает
Chrome, поэтому нужен мост: те же числа, но в виде CSS-переменных и @font-face.

Гарнитуры подключаются локальными файлами, а не через Google Fonts: шрифты уже
прошли проверку кириллицы и лицензии (§3.4), а CDN в рендере — лишняя сетевая
зависимость и риск подмены начертания.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .captions import caption_css
from .templates import dataviz_css, hero_css, overlay_css, split_css, transition_css

# Слои кадра. Порядок задаётся здесь, а не data-track-index: трек в HyperFrames
# отвечает за пересечения во времени, а не за то, что лежит поверх чего.
Z_STAGE = 0        # заливка кадра
Z_SHOT = 10        # футаж / фон режима A
Z_BEHIND_HEAD = 15 # слово за головой — под аватаром, но над фоном (§5.3)
Z_AVATAR = 20      # аватар с альфой
Z_OVERLAY = 30     # карточки источников, плашки, полноэкранный текст
Z_SUBTITLE = 40    # субтитры поверх всего (§5.1)


def _font_face(family: str, file_name: str) -> str:
    return (
        "@font-face{"
        f"font-family:'{family}';"
        f"src:url('fonts/{file_name}') format('truetype');"
        "font-weight:normal;font-style:normal;font-display:block}"
    )


def _stack(role: dict[str, Any], css_family: str) -> str:
    """Стек гарнитур: проверенная основная + системные подстраховки."""
    tail = "Arial, Helvetica, sans-serif"
    if role.get("primary", "").startswith("JetBrains"):
        tail = "'Courier New', monospace"
    return f"'{css_family}', {tail}"


def build_css(brandbook: dict[str, Any], fonts: dict[str, str]) -> str:
    """Собрать таблицу стилей композиции.

    ``fonts`` — соответствие роли (display/subtitle/mono) имени ttf-файла,
    который уже скопирован в ``fonts/`` проекта.
    """
    colors = brandbook["colors"]
    canvas = brandbook["canvas"]
    safe = brandbook["safe_zones"]["work_area"]
    subs = brandbook["subtitles"]
    typo = brandbook["typography"]["roles"]

    width, height = int(canvas["width"]), int(canvas["height"])

    parts: list[str] = []

    for role, file_name in fonts.items():
        parts.append(_font_face(f"RS {role.title()}", file_name))

    var_lines = [f"--color-{name.replace('_', '-')}: {value};"
                 for name, value in colors.items()]
    var_lines += [
        f"--frame-w: {width}px;",
        f"--frame-h: {height}px;",
        f"--safe-x-min: {int(safe['x_min'])}px;",
        f"--safe-x-max: {int(safe['x_max'])}px;",
        f"--safe-y-min: {int(safe['y_min'])}px;",
        f"--safe-y-max: {int(safe['y_max'])}px;",
        f"--font-display: {_stack(typo['display'], 'RS Display')};",
        f"--font-subtitle: {_stack(typo['subtitle'], 'RS Subtitle')};",
        f"--font-mono: {_stack(typo['mono'], 'RS Mono')};",
    ]
    parts.append(":root{" + "".join(var_lines) + "}")

    parts.append(
        "*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}"
        "html,body{width:var(--frame-w);height:var(--frame-h);overflow:hidden;"
        "background:#000}"
        # Заливка кадра живёт на full-bleed ребёнке: фон самого корня продюсер
        # при компоновке кадра теряет, и рендер уходит в чёрное.
        f"#root{{position:relative;width:var(--frame-w);height:var(--frame-h);"
        f"overflow:hidden;font-family:var(--font-subtitle)}}"
        f".stage-bg{{position:absolute;inset:0;z-index:{Z_STAGE};"
        "background:var(--color-bg-light)}"
    )

    # --- шоты -----------------------------------------------------------
    parts.append(
        f".shot{{position:absolute;inset:0;z-index:{Z_SHOT};"
        "width:var(--frame-w);height:var(--frame-h);object-fit:cover;"
        "will-change:transform}"
        f".shot-bg{{position:absolute;inset:0;z-index:{Z_SHOT};overflow:hidden}}"
    )

    # --- аватар ---------------------------------------------------------
    parts.append(
        f".avatar{{position:absolute;inset:0;z-index:{Z_AVATAR};"
        "width:var(--frame-w);height:var(--frame-h);object-fit:cover}"
    )

    # --- слово за головой (§5.3) ---------------------------------------
    tbh = brandbook["text_behind_head"]
    parts.append(
        f".behind-head{{position:absolute;left:0;right:0;top:{int(height * 0.34)}px;"
        f"z-index:{Z_BEHIND_HEAD};text-align:center;"
        "font-family:var(--font-display);text-transform:uppercase;"
        f"font-size:{int(tbh['size_px'][1])}px;line-height:0.94;"
        "color:var(--color-ink);opacity:0.55;transform:translateY(-50%)}"
    )

    # --- субтитры (§5.1) ------------------------------------------------
    # Жесты живут в caption_css: pop-in Nunito больше не рисуется.
    parts.append(caption_css(brandbook))

    # --- полноэкранный текст (§5.2) ------------------------------------
    fs = brandbook["fullscreen_text"]
    parts.append(
        f".fullscreen-text{{position:absolute;inset:0;z-index:{Z_OVERLAY};"
        "display:flex;align-items:center;justify-content:center;"
        "padding:0 var(--safe-x-min);text-align:center;"
        "background:var(--color-bg-pure);color:var(--color-ink);"
        "font-family:var(--font-display);text-transform:uppercase;"
        f"font-size:{int(fs['size_px'][1])}px;line-height:0.94}}"
        ".fullscreen-text.invert{background:var(--color-ink);color:var(--color-bg-pure)}"
        ".fullscreen-text .accent{color:var(--color-accent)}"
    )

    # --- мем ------------------------------------------------------------
    parts.append(
        f".meme{{position:absolute;inset:0;z-index:{Z_SHOT};"
        "width:var(--frame-w);height:var(--frame-h);object-fit:contain;"
        "background:var(--color-bg-light)}"
    )

    # --- плашки и карточки (§5.4, §5.6) ---------------------------------
    plaque = brandbook["plaque"]
    shadow = plaque["shadow"]
    parts.append(
        f".overlay{{position:absolute;z-index:{Z_OVERLAY}}}"
        ".plaque{left:var(--safe-x-min);right:calc(var(--frame-w) - var(--safe-x-max));"
        f"bottom:{height - int(safe['y_max']) + 60}px;padding:26px 34px;"
        f"border-radius:{int(plaque['radius_px_default'])}px;"
        f"background:rgba(247,245,243,{plaque['bg_alpha']});color:var(--color-ink);"
        f"border:{int(plaque['border_px'])}px solid rgba(192,57,43,{plaque['border_alpha']});"
        "font-family:var(--font-subtitle);font-weight:800;font-size:44px;"
        f"box-shadow:0 {int(shadow['offset_y_px'])}px {int(shadow['blur_px'])}px "
        f"rgba(0,0,0,{shadow['alpha']})}}"
        ".plaque .kicker{display:block;font-size:28px;color:var(--color-muted);"
        "margin-top:8px;font-weight:700}"
    )
    # Карточка источника прижимается снизу к полосе субтитров, а не ставится по
    # верхней координате: высота у неё content-driven, и при длинном заголовке
    # нижний край наезжал на слово.
    subtitle_top = int(subs["baseline_y_default"]) - int(subs["size_px"][1]) // 2 - 30
    parts.append(
        ".source-card{left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        f"bottom:{height - subtitle_top}px;max-height:{subtitle_top - int(safe['y_min'])}px;"
        "border-radius:22px;overflow:hidden;"
        "background:var(--color-bg-pure);color:var(--color-ink);"
        "box-shadow:0 18px 48px rgba(0,0,0,0.22)}"
        ".source-card .bar{display:flex;align-items:center;gap:10px;"
        "padding:18px 22px;background:var(--color-bg-light)}"
        ".source-card .dot{width:14px;height:14px;border-radius:50%;background:var(--color-muted)}"
        ".source-card .domain{margin-left:10px;font-family:var(--font-mono);"
        "font-size:26px;color:var(--color-muted)}"
        ".source-card .title{padding:22px 26px 6px;font-family:var(--font-display);"
        "font-size:52px;line-height:1.04}"
        ".source-card .snippet{padding:6px 26px 26px;font-size:30px;"
        "line-height:1.3;color:var(--color-muted)}"
        ".source-card .hl{background:var(--color-accent-soft);"
        "box-shadow:0 0 0 6px var(--color-accent-soft)}"
    )

    # --- CTA (§5.7) ------------------------------------------------------
    parts.append(
        ".cta{left:0;right:0;"
        f"bottom:{height - int(safe['y_max']) + 40}px;text-align:center}}"
        ".cta .pill{display:inline-block;"
        "padding:30px 56px;border-radius:999px;"
        "background:var(--color-accent);color:var(--color-bg-pure);"
        "font-family:var(--font-display);text-transform:uppercase;"
        "font-size:62px;box-shadow:0 12px 34px rgba(0,0,0,0.25);"
        "will-change:transform}"
    )

    # --- VFX-фон режима A (§7.7) ----------------------------------------
    # Мягкий градиент бренда вместо видеофона: он не спорит с аватаром и
    # держит долю акцента ниже потолка §3.3.1.
    parts.append(
        ".vfx{position:absolute;inset:0;"
        "background:radial-gradient(120% 90% at 50% 18%,"
        "var(--color-bg-pure) 0%,var(--color-bg-light) 46%,#EDE7E4 100%)}"
        ".vfx::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(70% 45% at 50% 78%,"
        "var(--color-accent-soft) 0%,transparent 70%);opacity:0.5}"
    )

    # Слои переходов (§4.3, §15) — отдельный модуль: их 9 рендереров,
    # и геометрия у них считается от кадра, а не от рабочей зоны.
    parts.append(transition_css(brandbook))
    parts.append(dataviz_css(brandbook))
    parts.append(overlay_css(brandbook))
    parts.append(split_css(brandbook))
    parts.append(hero_css(brandbook))

    return "\n".join(parts) + "\n"


def copy_fonts(fonts_dir: Path, dest: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Скопировать проверенные гарнитуры в проект и вернуть роль → имя файла."""
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for font in manifest.get("fonts", []):
        role, file_name = font.get("role"), font.get("file")
        if not role or not file_name:
            continue
        src = fonts_dir / file_name
        if not src.exists():
            continue
        (dest / file_name).write_bytes(src.read_bytes())
        out[role] = file_name
    return out

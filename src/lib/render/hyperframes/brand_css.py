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

from ...backdrop import backdrop_css
from .templates import dataviz_css, hero_css, split_css, transition_css

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


def _text_rim(radius: int, color: str, *, rays: int = 12) -> str:
    """Обводка текста кольцом теней.

    ``-webkit-text-stroke`` рисует обводку **по центру** контура глифа и на
    таком радиусе съедает просветы букв; ``paint-order`` это чинит, но за его
    поддержку в продюсере поручиться нечем. Кольцо теней даёт тот же контур
    гарантированно. Двенадцать лучей, а не восемь: на восьми между лучами
    остаётся заметный зазор.
    """
    import math

    steps = []
    for i in range(rays):
        angle = 2.0 * math.pi * i / rays
        dx = round(math.cos(angle) * radius, 1)
        dy = round(math.sin(angle) * radius, 1)
        steps.append(f"{dx}px {dy}px 0 {color}")
    return ",".join(steps)


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
        # Цвет того, что рисуется **прямо на фоне**: заголовок за головой, тема
        # за головой, знаки, накопительный список. На тёмной сцене чернильная
        # надпись пропадает, и тон сцены эти две переменные переключает.
        "--color-on-stage: var(--color-ink);",
        "--stage-halo: rgba(247,245,243,0.9);",
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
    # Центр — оптический центр кадра, а не середина рабочей зоны: правое поле
    # ужато под колонку лайк/коммент/шер и увело бы слово влево.
    #
    # Читаемость держится мягкой тенью, а не обводкой. Обводка обводит каждое
    # слово красным контуром, и цвет перестаёт что-либо значить: выделять
    # смысловое слово нечем. Здесь белое слово идёт потоком, а важное — светлым
    # красным, и это единственное место в кадре, где цвет несёт смысл.
    halo = subs.get("shadow", {})
    blur = int(halo.get("blur_px", 20))
    offset = int(halo.get("offset_y_px", 4))
    alpha = float(halo.get("alpha", 0.5))
    accent_var = str(subs.get("accent_color", "accent_soft")).replace("_", "-")
    stroke_color = colors.get(str(subs.get("stroke_color", "ink")), "#111214")
    # Тень под словом — всегда: она сажает слово на кадр. Обводка — по режиму
    # брендбука, и она не украшение. Пока аватар приходил непрозрачным, слово
    # ложилось на тёмный кадр и белого с тенью хватало. С рабочей альфой фон
    # под ведущим светлый (.vfx), и белое слово на нём пропадает — на карточке
    # приёма исчезало совсем. Обводка держит слово на обоих грунтах.
    shadow = (f"0 {offset}px {blur}px rgba(0,0,0,{alpha:.2f}),"
              f"0 {max(1, offset // 2)}px {max(2, blur // 5)}px "
              f"rgba(0,0,0,{alpha * 0.8:.2f})")
    if str(subs.get("readability_mode", "shadow")) == "stroke":
        shadow = f"{_text_rim(int(subs['stroke_px'][0]), stroke_color)},{shadow}"
    parts.append(
        f".word{{position:absolute;left:0;right:0;top:{int(subs['baseline_y_default'])}px;"
        f"z-index:{Z_SUBTITLE};text-align:center;transform:translateY(-50%);"
        "font-family:var(--font-subtitle);font-weight:800;"
        f"font-size:{int(subs['size_px_default'])}px;"
        f"line-height:{typo['subtitle']['line_height']};"
        f"color:{subs['color']};"
        f"text-shadow:{shadow}}}"
        ".word > span{display:inline-block;will-change:transform}"
        f".word.emphasis{{color:var(--color-{accent_var})}}"
    )

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
        "padding:18px 22px;background:#ECEAE7}"
        ".source-card .dot{width:14px;height:14px;border-radius:50%;background:#C9C6C2}"
        ".source-card .domain{margin-left:10px;font-family:var(--font-mono);"
        "font-size:26px;color:var(--color-muted)}"
        ".source-card .title{padding:22px 26px 6px;font-family:var(--font-display);"
        "font-size:52px;line-height:1.04}"
        ".source-card .snippet{padding:6px 26px 26px;font-size:30px;"
        "line-height:1.3;color:#3A3D42}"
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
        backdrop_css()
        +
        # Тёмная сцена переворачивает цвет надписей на фоне и их ореол. Не
        # `--color-ink` целиком: он же красит текст на белых карточках, и его
        # переворот сделал бы их нечитаемыми.
        #
        # Селектор без `#root` намеренно: в ролике класс стоит на корне
        # композиции, на витрине — на рамке карточки, и таблица стилей одна на
        # обоих. Привязка к `#root` молча оставляла бы витрину со светлыми
        # надписями на тёмной сцене.
        ".stage-dark{--color-on-stage:var(--color-bg-light);"
        "--stage-halo:rgba(6,8,12,0.85)}"
    )

    # Слои переходов (§4.3, §15) — отдельный модуль: их 9 рендереров,
    # и геометрия у них считается от кадра, а не от рабочей зоны.
    parts.append(transition_css(brandbook))
    parts.append(dataviz_css(brandbook))
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

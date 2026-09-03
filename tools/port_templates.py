#!/usr/bin/env python3
"""Перенос приёмов из ветки шаблонов в основную работу.

Ветка курсора отпочкована от первого коммита проекта: слить её файлами нельзя,
в ней нет полутора сотен коммитов основной работы, и `git merge` даёт конфликт
на весь файл целиком. Зато перенести из неё **определения** можно механически —
это и делает этот инструмент.

Что переносится:

* записи каталога из их ``tools/gen_templates.py`` — они и решают, что вообще
  переносить: приём есть у них и нет у нас;
* замыкание по зависимостям от рендерера приёма: сама функция и всё, чем она
  пользуется, чего у нас нет;
* соседние модули с геометрией (карты), если перенесённое их зовёт;
* правила CSS новых классов — вычисляются исполнением, а не разбором строк:
  их пять функций стиля вызываются на нашем брендбуке, наши тоже, и берётся
  разница по селекторам;
* строки реестров (``DATAVIZ["x"] = fn``), которыми движок находит рендерер.

Что не переносится и почему: всё, что у нас уже есть. Их версия общих функций
старше нашей на полторы сотни коммитов, и брать её значит откатывать работу.

    python tools/port_templates.py origin/cursor/hyperframes-sci-templates-647c
    python tools/port_templates.py <ref> --dry-run
"""

from __future__ import annotations

import argparse
import ast
import colorsys
import importlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PKG = "src/lib/render/hyperframes"
TEMPLATES_PY = f"{PKG}/templates.py"
# Перенесённое живёт отдельным файлом. Замыкание одного переноса — семь тысяч
# строк на наши пять: вмешать их в наш файл значит потерять его читаемость и
# перестать различать, что чьё. Отдельный модуль ещё и чинится отдельно.
SCI_PY = f"{PKG}/templates_sci.py"
GEN_PY = "tools/gen_templates.py"

# Их версии этих определений старше наших: переносить их — откат работы.
NEVER_PORT = {
    "hero_burst",          # лучи за головой заменены знаками о предмете речи
    "RAY_CAP_PAD", "RAY_LEN_MIN", "RAY_LEN_SPAN",
}

# Приёмы каталога, которых у нас быть не должно.
NEVER_PORT_TEMPLATES = {
    "burst-behind-head",   # тот же приём лучей
    # Карты одной страны. Канал говорит по-русски и про весь мир; признак
    # «место» в блоке есть у любого места, и подбор по смыслу поставил бы
    # карту Испании под фразу про Кольскую скважину. Мир — переносим,
    # он умеет подсветить любую страну.
    "spain-map", "us-map", "us-map-flow", "us-map-hex",
    # Экран айфона с перепиской на весь кадр. Белая плита от края до края,
    # половину занимает клавиатура, и подсказки в ней английские — «How Can
    # My». У нас уже есть окно переписки, которое живёт внутри кадра и
    # говорит по-русски: `browser-ui/chat-thread` и `chat-ai-typing`.
    "ai-chat-reveal",
}

# Реестры движка: имя в каталоге → функция.
REGISTRIES = ("HERO", "TRANSITIONS", "MOTION", "DATAVIZ", "FULLSCREEN", "OVERLAYS")

# Функции стиля, между которыми делится вся вёрстка страницы.
CSS_FUNCTIONS = ("transition_css", "dataviz_css", "overlay_css", "split_css",
                 "hero_css")

MARK = "# --- перенесено из ветки шаблонов "


def sh(*args: str) -> str:
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def at_ref(ref: str, path: str) -> str:
    return sh("git", "show", f"{ref}:{path}")


def registry_map(source: str) -> dict[str, tuple[str, str]]:
    """Ключ реестра → (имя реестра, имя функции).

    Ключ бывает двух родов. У ``HERO``/``FULLSCREEN``/``TRANSITIONS`` это имя
    рендерера из каталога, у ``DATAVIZ`` — id самого приёма: там рендерер один
    на категорию (``render_dataviz``) и разводит по id.
    """
    mapping: dict[str, tuple[str, str]] = {}
    for name in REGISTRIES:
        match = re.search(rf"^{name}(?:: [^=]+)? = \{{(.*?)^\}}", source, re.S | re.M)
        if match:
            for key, fn in re.findall(r'"([^"]+)":\s*([A-Za-z_][\w]*)', match.group(1)):
                mapping[key] = (name, fn)
    for reg, key, fn in re.findall(
            r'^(%s)\["([^"]+)"\]\s*=\s*([A-Za-z_][\w]*)' % "|".join(REGISTRIES),
            source, re.M):
        mapping[key] = (reg, fn)
    return mapping


def top_level(source: str) -> dict[str, tuple[int, int]]:
    """Имя верхнеуровневого определения → строки, которые его составляют."""
    tree = ast.parse(source)
    found: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if not name:
            continue
        start = min([d.lineno for d in getattr(node, "decorator_list", [])]
                    + [node.lineno]) - 1
        found[name] = (start, node.end_lineno)
    return found


def catalog_of(source: str, label: str) -> dict[str, tuple[int, list]]:
    """CATALOG из генератора: категория → (сколько заявлено, записи)."""
    # `__file__` генератору нужен только чтобы найти корень репозитория:
    # подставляем настоящий путь, чтобы модуль исполнился как обычно.
    namespace: dict[str, object] = {"__name__": f"gen_templates_{label}",
                                    "__file__": str(ROOT / GEN_PY)}
    exec(compile(source, f"<{label} gen_templates>", "exec"), namespace)  # noqa: S102
    catalog = namespace.get("CATALOG")
    if not isinstance(catalog, dict):
        raise SystemExit(f"в генераторе {label} нет CATALOG")
    return catalog


def catalog_sources(source: str) -> dict[str, str]:
    """id приёма → его запись каталога исходным текстом, как она написана."""
    tree = ast.parse(source)
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Tuple) and node.elts):
            continue
        head = node.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str) \
                and len(node.elts) >= 6:
            text = ast.get_source_segment(source, node)
            if text and text.lstrip().startswith("("):
                out[head.value] = text
    return out


def closure(theirs_src: str, seeds: set[str], have: set[str]) -> list[str]:
    """Замыкание по зависимостям: приём плюс всё, чем он пользуется.

    Переносить всё, чего у нас нет, нельзя: у них общие функции старше наших
    на полторы сотни коммитов, и слепой перенос откатил бы работу. Поэтому
    идём от новых приёмов вглубь — только их собственные помощники и
    константы, которых у нас и правда нет.
    """
    tree = ast.parse(theirs_src)
    nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            nodes[node.targets[0].id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            nodes[node.target.id] = node

    ordered: list[str] = []
    seen: set[str] = set()

    def walk(name: str) -> None:
        if name in seen or name in have or name in NEVER_PORT or name not in nodes:
            return
        seen.add(name)
        for child in ast.walk(nodes[name]):
            if isinstance(child, ast.Name) and child.id in nodes:
                walk(child.id)
            elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                if child.value.id in nodes:
                    walk(child.value.id)
        ordered.append(name)          # зависимости раньше того, кто их зовёт
    for seed in sorted(seeds):
        walk(seed)
    return ordered


def sibling_modules(theirs_src: str, chunks: str) -> dict[str, list[str]]:
    """Соседние модули, чьи имена зовёт перенесённое: модуль → что берём."""
    needed: dict[str, list[str]] = {}
    for node in ast.parse(theirs_src).body:
        if not (isinstance(node, ast.ImportFrom) and node.level == 1 and node.module):
            continue
        # Проверять, есть ли файл у нас, здесь нельзя: модуль, перенесённый
        # прошлым прогоном, тогда выпадал бы из списка импортов, и имя из него
        # оставалось бы необъявленным — падение не на импорте, а в кадре.
        used = [a.name for a in node.names if re.search(rf"\b{a.name}\b", chunks)]
        if used:
            needed[node.module] = used
    return needed


def imported_from(theirs_src: str, wanted: set[str]) -> dict[str, list[str]]:
    """Где у них лежат имена, которых нет в их же templates.py.

    Приём может целиком жить в своём модуле — тогда в реестр он попадает
    импортом, а не определением. Такой приём переносится файлом.
    """
    found: dict[str, list[str]] = {}
    for node in ast.parse(theirs_src).body:
        if not (isinstance(node, ast.ImportFrom) and node.level == 1 and node.module):
            continue
        hit = [a.name for a in node.names if a.name in wanted]
        if hit:
            found.setdefault(node.module, []).extend(hit)
    return found


def used_names(body: str) -> set[str]:
    """Все имена, к которым обращается перенесённый текст."""
    tree = ast.parse(body)
    return ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})


def sci_module(ref: str, body: str, modules: dict[str, list[str]],
               borrowed: list[str], css: str, extra_css: list[str]) -> str:
    """Текст модуля перенесённых приёмов."""
    head = [
        '"""Приёмы, перенесённые из ветки шаблонов (см. tools/port_templates.py).',
        "",
        "Отдельный файл, а не вперемешку с нашими: перенос — механический, и",
        "граница обязана быть видна. Чинится и снимается он тоже отдельно.",
        "",
        f"Источник: {ref}",
        "",
        "Правила движка те же, что и у наших приёмов: кадр — чистая функция",
        "времени, прозрачность клипа трогать нельзя, два твина на одно свойство",
        "одного элемента запрещены. Перенесённое проходит те же тесты.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import html",
        "import json",
        "import math",
        "import re",
        "from dataclasses import dataclass, field",
        "from functools import lru_cache",
        "from pathlib import Path",
        "from typing import Any, Callable",
        "",
    ]
    for module, used in sorted(modules.items()):
        head.append(f"from .{module} import {', '.join(sorted(used))}")
    if borrowed:
        head.append("from .templates import (")
        head.append("    " + ", ".join(borrowed) + ",")
        head.append(")")
    head += ["", "TemplateCtx = Any  # подсказка типа: настоящий класс — в templates.py",
             "", ""]
    text = "\n".join(head) + body + "\n"
    # `ported_css` пишется всегда, даже пустой: на неё уже ссылается
    # brand_css, и модуль без неё не импортируется — а первый, пустой проход
    # именно затем и нужен, чтобы импорт состоялся.
    tail = "".join(f" + {name}()" for name in extra_css)
    text += ('\n\ndef ported_css(brandbook: dict[str, Any]) -> str:\n'
                 '    """Стиль перенесённых приёмов.\n\n'
                 '    Считался исполнением обеих сторон на нашем брендбуке:\n'
                 '    взяты правила тех классов, которых у нас не было.\n'
                 '    Приём, живущий отдельным модулем, приносит свой стиль сам.\n'
                 '    """\n'
             '    rules = (\n' + (css or '        ""') + "\n    )\n"
             f"    return rules{tail}\n")
    return text



# --- приведение к брендбуку ---------------------------------------------------
#
# Перенос тащит чужой канал целиком: 81 цветное значение по всему кругу
# оттенков — бирюза, охра, маджента — и шрифт `Inter`, которого в проекте нет.
# Ни то ни другое не безобидно. Цвет — узнаваемость канала, а `Inter` молча
# подменяется системным шрифтом, который шире модели ширины на восемнадцать
# процентов: подпись вылезает за рабочую зону.
#
# Правило простое и всего одно: цвет решается насыщенностью и светлотой.
# Ненасыщенное — нейтральная лестница от чернил до белого; синее попадает в
# «космос» (у #0B132B тон 218°, синий чужого канала ложится туда сам); всё
# остальное, какого бы тона ни было, идёт в лестницу акцента. Лестница, а не
# один цвет: у графика должны различаться столбики.

BLUE_CORRIDOR = (195.0, 255.0)     # «космос» брендбука: #0B132B — это 218°

NEUTRAL_RAMP = ((0.93, "bg_pure"), (0.80, "bg_light"), (0.55, "text_soft"),
                (0.35, "muted"), (0.12, "panel"), (0.0, "ink"))
SPACE_RAMP = ((0.75, "text_soft"), (0.45, "muted"), (0.20, "panel"),
              (0.0, "space_deep"))
ACCENT_RAMP = ((0.72, "accent_soft"), (0.38, "accent"), (0.0, "accent_deep"))


def brand_token(red: float, green: float, blue: float) -> str:
    """Имя цвета брендбука, которым замещается чужой."""
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    ramp = NEUTRAL_RAMP if sat < 0.18 else (
        SPACE_RAMP if BLUE_CORRIDOR[0] <= hue * 360 <= BLUE_CORRIDOR[1]
        else ACCENT_RAMP)
    for edge, name in ramp:
        if light >= edge:
            return name
    return ramp[-1][1]


def normalize_colors(text: str, colors: dict[str, str]) -> tuple[str, int]:
    """Чужие цвета — в переменные брендбука, полупрозрачные — в его же rgb."""
    rgb_of = {}
    for name, value in colors.items():
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            rgb_of[name] = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    count = 0

    def channels(raw: str) -> tuple[float, float, float]:
        digits = raw.lstrip("#")
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))

    # Цвет, который считают, а не пишут. Карта мира смешивает два цвета
    # шкалы арифметикой: `int(h[0:2], 16)`. Подстановка переменной CSS
    # ломала её на `int('va', 16)` — приём падал, а не выглядел иначе.
    # Признак прямой: цветом занят весь строковый литерал целиком.
    kept: list[str] = []

    def by_value(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        quote, digits = match.group(1), match.group(2)
        kept.append(f"{quote}{colors[brand_token(*channels(digits))]}{quote}")
        # Метка, а не цвет: общий проход ниже иначе заменил бы только что
        # поставленный цвет брендбука на переменную — и сломал бы то же место.
        return f"@@RS{len(kept) - 1}@@"

    text = re.sub(r"""(['"])(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\1""", by_value, text)

    def by_hex(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"var(--color-{brand_token(*channels(match.group(0))).replace('_', '-')})"

    text = re.sub(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", by_hex, text)

    def by_rgba(match: re.Match[str]) -> str:
        nonlocal count
        red, green, blue = (int(x) for x in match.group(1, 2, 3))
        _hue, _light, sat = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        if sat < 0.18:
            return match.group(0)          # вуали и тени — оставляем как есть
        count += 1
        r, g, b = rgb_of[brand_token(red / 255, green / 255, blue / 255)]
        return f"rgba({r},{g},{b},{match.group(4)})"

    text = re.sub(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\)",
                  by_rgba, text)
    text = re.sub(r"@@RS(\d+)@@", lambda m: kept[int(m.group(1))], text)
    return text, count


def normalize_fonts(text: str) -> tuple[str, int]:
    """Любое семейство — в шрифт проекта: чужой молча подменяется системным.

    Разбирается не «до точки с запятой»: значение живёт внутри строкового
    литерала питона, и своя кавычка в имени шрифта (``"JetBrains Mono"``)
    сломала бы такой разбор. Поэтому список читается по одному имени.
    """
    name = r"""(?:'[^']*'|\\?"[^"\\]*\\?"|var\(--[\w-]+\)|[A-Za-z][\w -]*)"""
    pattern = re.compile(rf"font-family:\s*({name}(?:\s*,\s*{name})*)")
    count = 0

    def pick(match: re.Match[str]) -> str:
        nonlocal count
        stack = match.group(1)
        if stack.startswith("var(--font-") and "," not in stack:
            return match.group(0)          # уже наш
        count += 1
        low = stack.lower()
        if "mono" in low or "courier" in low:
            return "font-family:var(--font-mono)"
        if "--font-display" in low or "oswald" in low or "bebas" in low \
                or "anton" in low:
            return "font-family:var(--font-display)"
        return "font-family:var(--font-subtitle)"

    return pattern.sub(pick, text), count


def normalize(path: Path, colors: dict[str, str]) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    text, colors_hit = normalize_colors(text, colors)
    text, fonts_hit = normalize_fonts(text)
    path.write_text(text, encoding="utf-8")
    return colors_hit, fonts_hit



# --- поверхность канала не бывает белой ---------------------------------------
#
# Перенос приносит чужую подачу: график на белой карточке, нижняя треть на
# белой плашке. У канала сцена тёмная, и белый прямоугольник посреди ролика
# читается дырой — заказчик сказал это прямо, увидев «180 ГРАДУСОВ» белым по
# белому. Правка адресная и живёт здесь, а не в сгенерированном файле: перенос
# повторяем, и следующий прогон применит её сам.
#
# Вспышки в списке нет намеренно: `mix-blend-mode:difference` и `overlay`
# работают именно белым операндом — это не поверхность, а операция.
SURFACE_FIXES: tuple[tuple[str, str], ...] = (
    # Столбчатый график: холст, карточка и надписи разом.
    (r"(\.abc-chart\{[^}]*background:)var\(--color-bg-pure\)",
     r"\1var(--color-space-deep)"),
    (r"(\.abc-card\{[^}]*background:)var\(--color-bg-pure\)",
     r"\1var(--color-panel)"),
    (r"(\.abc-(?:title|kpi)\{[^}]*color:)var\(--color-space-deep\)",
     r"\1var(--color-bg-pure)"),
    (r"(\.abc-fill\{[^}]*background:)rgba\(11,19,43,0\.72\)",
     r"\1var(--color-accent)"),
    # Линейный график: холст, подложка, значения и ось.
    (r"(\.mlg-chart\{[^}]*background:)var\(--color-bg-pure\)",
     r"\1var(--color-space-deep)"),
    (r"(\.mlg-chart\{[^}]*color:)var\(--color-ink\)", r"\1var(--color-bg-pure)"),
    (r"(\.mlg-bg\{[^}]*background:)var\(--color-bg-pure\)",
     r"\1var(--color-space-deep)"),
    (r"(\.mlg-val\{[^}]*color:)var\(--color-ink\)", r"\1var(--color-bg-pure)"),
    (r"(\.mlg-axis\{[^}]*stroke:)rgba\(29,29,31,0\.22\)",
     r"\1rgba(199,201,209,0.35)"),
    # Нижняя треть «светлая полоса»: плашка канала, а не чужой интерфейс.
    (r"(\.lt-cb-body\{[^}]*background:)var\(--color-bg-pure\)",
     r"\1var(--color-panel)"),
    (r"(\.lt-cb-name\{[^}]*color:)var\(--color-ink\)", r"\1var(--color-bg-pure)"),
    (r"(\.lt-cb-role\{[^}]*color:)var\(--color-muted\)",
     r"\1var(--color-text-soft)"),
    # Гонка столбиков: холст во весь кадр был светлым, и приведение цвета
    # сделало его не белым, а лососевым — плита осталась плитой. Сцена
    # тёмная, столбики светлые, заголовок белый.
    (r"(\.bcr-(?:chart|bg)\{[^}]*background:)var\(--color-accent-soft\)",
     r"\1var(--color-space-deep)"),
    (r"(\.bcr-title\{[^}]*color:)var\(--color-ink\)", r"\1var(--color-bg-pure)"),
    (r"(\.bcr-bar\{[^}]*background-color:)var\(--color-ink\)",
     r"\1var(--color-accent)"),
    # Стена клонов: под плитками стоит фон кадра, а не белый лист.
    (r"(\.tr-mk-clone-wall \.cw-wall\{background:)var\(--color-bg-pure\)",
     r"\1var(--color-space-deep)"),
    # `fromTo` по самому кадру без запрета откатывает кадр в начальное
    # состояние с нулевой секунды: до перехода на 4.5 секунде ведущий уже
    # сидит в масштабе 1.16. Твины по вложенным узлам этого не делают —
    # правка только по клипу, которым управляет движок.
    (r"(tl\.fromTo\(\\?\"#\{ctx\.target\}[^\n]*\n\s*f'\{\{)(?!immediateRender)",
     r"\1immediateRender:false,"),
)


def fix_surfaces(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    hits = 0
    for pattern, replacement in SURFACE_FIXES:
        text, done = re.subn(pattern, replacement, text)
        hits += done
    path.write_text(text, encoding="utf-8")
    return hits


def css_rules(text: str) -> list[str]:
    """Правила CSS по одному. Медиазапросов и вложенности здесь не бывает."""
    return [part.strip() + "}" for part in text.split("}") if part.strip()]


def selector_classes(rule: str) -> set[str]:
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", rule.split("{", 1)[0]))


def new_css(ref: str, ported: set[str]) -> str:
    """Правила их стиля, которых у нас нет, — для классов перенесённого.

    Считается исполнением: обе стороны собирают CSS на одном брендбуке, и
    сравниваются селекторы. Разбирать исходник глазами тут нельзя — стиль
    собирается из f-строк, и в тексте функции классов не видно целиком.
    """
    import json
    import shutil
    import tempfile

    brandbook = json.loads((ROOT / "config" / "brandbook.json").read_text("utf-8"))
    ours_mod = importlib.import_module("src.lib.render.hyperframes.templates")
    ours_classes: set[str] = set()
    for name in CSS_FUNCTIONS:
        for rule in css_rules(getattr(ours_mod, name)(brandbook)):
            ours_classes |= selector_classes(rule)

    # Их модуль исполняется в песочнице: копия пакета, куда положен их файл.
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "theirs"
        shutil.copytree(ROOT / PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
        their_templates = at_ref(ref, TEMPLATES_PY)
        (pkg / "templates.py").write_text(their_templates, encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        # Их файл ссылается на соседей на уровне модуля — все, а не только те,
        # чьи приёмы переносятся; иначе он просто не импортируется.
        for node in ast.parse(their_templates).body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module \
                    and not (pkg / f"{node.module}.py").exists():
                (pkg / f"{node.module}.py").write_text(
                    at_ref(ref, f"{PKG}/{node.module}.py"), encoding="utf-8")
        sys.path.insert(0, tmp)
        try:
            theirs_mod = importlib.import_module("theirs.templates")
            blocks: list[str] = []
            for name in CSS_FUNCTIONS:
                fn = getattr(theirs_mod, name, None)
                if fn is None:
                    continue
                # Правило берётся, если вводит класс, которого у нас нет.
                # Отбрасывать его из-за общего родителя нельзя: их
                # полноэкранные приёмы написаны как `.fullscreen-text
                # .ct-code{…}`, и по строгому условию пропала вся их
                # вёрстка — приём выходил пустым кадром.
                fresh = [rule for rule in css_rules(fn(brandbook))
                         if (classes := selector_classes(rule))
                         and (classes & ported) - ours_classes]
                # `repr`, а не кавычки руками: в правилах попадается
                # `font-family:"JetBrains Mono"`, и своя кавычка ломает строку.
                if fresh:
                    blocks.append("\n".join(f"        {r!r}" for r in fresh))
        finally:
            sys.path.remove(tmp)
            sys.modules.pop("theirs.templates", None)
            sys.modules.pop("theirs", None)
    return "\n".join(blocks)


def port(ref: str, *, dry_run: bool = False) -> int:
    ours_src = (ROOT / TEMPLATES_PY).read_text(encoding="utf-8")
    theirs_src = at_ref(ref, TEMPLATES_PY)
    ours, theirs = top_level(ours_src), top_level(theirs_src)
    their_lines = theirs_src.split("\n")

    # Что переносить, решает каталог: приём есть в их каталоге и нет в нашем.
    their_gen = at_ref(ref, GEN_PY)
    our_catalog = catalog_of((ROOT / GEN_PY).read_text(encoding="utf-8"), "ours")
    their_catalog = catalog_of(their_gen, "theirs")
    catalog_new: dict[str, list] = {}
    for category, (_count, items) in their_catalog.items():
        have_ids = {item[0] for item in our_catalog.get(category, (0, []))[1]}
        fresh = [item for item in items
                 if item[0] not in have_ids and item[0] not in NEVER_PORT_TEMPLATES]
        if fresh:
            catalog_new[category] = fresh

    registry = registry_map(theirs_src)
    seeds: set[str] = set()
    lines_registry: list[str] = []
    unknown: list[str] = []
    for items in catalog_new.values():
        for item in items:
            # Ключ реестра — либо имя рендерера, либо id приёма (data-viz).
            by_renderer = registry.get(str(item[5]))
            hit = by_renderer or registry.get(item[0])
            if not hit:
                unknown.append(item[0])
                continue
            reg, fn = hit
            seeds.add(fn)
            key = str(item[5]) if by_renderer else item[0]
            lines_registry.append(f'{reg}["{key}"] = _sci.{fn}')

    names = closure(theirs_src, seeds, set(ours))
    chunks = ["\n".join(their_lines[theirs[n][0]:theirs[n][1]]) for n in names]
    body = "\n\n\n".join(chunks)
    modules = sibling_modules(theirs_src, body)
    # Приём, который целиком живёт в своём модуле, замыканием не берётся:
    # в templates.py его нет, он там только импортирован. Берём файлом.
    whole = imported_from(theirs_src, seeds - set(theirs))
    for module, got in whole.items():
        modules.setdefault(module, []).extend(got)

    ported_classes = set(re.findall(r'class="([^"]*)"', body))
    ported_classes = {c for group in ported_classes for c in group.split()}
    ported_classes |= set(re.findall(r"'([a-z][\w-]*)'", body))

    print(f"перенос с {ref}")
    print(f"  новых приёмов каталога: {sum(len(v) for v in catalog_new.values())}")
    for category, items in sorted(catalog_new.items()):
        print(f"    {category}: {', '.join(item[0] for item in items)}")
    print(f"  рендереров: {len(seeds)}"
          + (f", не найдено в реестре: {unknown}" if unknown else ""))
    print(f"  определений в замыкании: {len(names)}")
    print(f"  соседних модулей: {', '.join(sorted(modules)) or '—'}")
    if dry_run:
        return 0

    for module, used in sorted(modules.items()):
        (ROOT / PKG / f"{module}.py").write_text(
            at_ref(ref, f"{PKG}/{module}.py"), encoding="utf-8")
        print(f"    + {module}.py ({', '.join(used[:4])}…)")

    borrowed = sorted(name for name in used_names(body)
                      if name in ours and name not in set(names))
    # Модуль пишется дважды. Стиль считается исполнением обеих сторон, а наша
    # сторона к этой минуте уже импортирует `templates_sci`: без первого,
    # пустого прохода импорт просто не состоится.
    (ROOT / SCI_PY).write_text(sci_module(ref, body, modules, borrowed, "", []),
                               encoding="utf-8")
    css = new_css(ref, ported_classes)
    # Модуль-приём приносит свой стиль своей же функцией; её надо позвать.
    extra_css: list[str] = []
    for module in sorted(whole):
        source = at_ref(ref, f"{PKG}/{module}.py")
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef) and node.name.endswith("_css") \
                    and not node.args.args:
                extra_css.append(node.name)
                modules[module].append(node.name)
    (ROOT / SCI_PY).write_text(
        sci_module(ref, body, modules, borrowed, css, extra_css), encoding="utf-8")
    import json
    palette = json.loads((ROOT / "config" / "brandbook.json").read_text("utf-8"))
    hits = [normalize(ROOT / SCI_PY, palette["colors"])]
    hits += [normalize(ROOT / PKG / f"{name}.py", palette["colors"])
             for name in sorted(modules)]
    fixed = fix_surfaces(ROOT / SCI_PY)
    print(f"  приведено к брендбуку: цветов {sum(h[0] for h in hits)}"
          f", шрифтов {sum(h[1] for h in hits)}, поверхностей {fixed}")
    print(f"  записано в {SCI_PY}: определений {len(chunks)}"
          f", взято у нас {len(borrowed)}"
          f", правил CSS {css.count(chr(10)) + 1 if css else 0}")

    if lines_registry and MARK not in ours_src:
        seam = ("\n\n" + MARK + "-" * max(4, 50 - len(MARK)) + "\n"
                "# Импорт внизу файла намеренно: перенесённое зовёт наши\n"
                "# `Piece`, `fit_size` и прочее, а к этой строке они уже\n"
                "# определены. Реестры пополняются здесь же, чтобы движок\n"
                "# находил новый приём по тому же имени, что и старый.\n"
                "from . import templates_sci as _sci  # noqa: E402\n\n"
                + "\n".join(sorted(set(lines_registry))) + "\n")
        (ROOT / TEMPLATES_PY).write_text(ours_src.rstrip("\n") + seam,
                                         encoding="utf-8")
        print(f"  реестры пополнены в {TEMPLATES_PY}: {len(lines_registry)}")

    # Каталог: записи как они написаны у них, плюс счётчик категории.
    sources = catalog_sources(their_gen)
    our_gen = (ROOT / GEN_PY).read_text(encoding="utf-8")
    for category, items in sorted(catalog_new.items()):
        block = "\n".join("        " + sources[item[0]].replace("\n", "\n ").rstrip()
                          + "," for item in items if item[0] in sources)
        anchor = re.search(rf'^    "{re.escape(category)}": \((\d+), \[',
                           our_gen, re.M)
        if not anchor or not block:
            print(f"    ! категория {category} не найдена в нашем каталоге")
            continue
        count = int(anchor.group(1)) + len(items)
        our_gen = (our_gen[:anchor.start()]
                   + f'    "{category}": ({count}, ['
                   + our_gen[anchor.end():])
        end = our_gen.index("    ]),", anchor.start())
        our_gen = our_gen[:end] + block + "\n" + our_gen[end:]
    (ROOT / GEN_PY).write_text(our_gen, encoding="utf-8")
    print(f"  каталог дополнен: {GEN_PY}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", help="ветка или коммит с приёмами")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать, что переносится")
    args = parser.parse_args()
    return port(args.ref, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

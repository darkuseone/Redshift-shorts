#!/usr/bin/env python3
"""Каталог приёмов для режиссёра: ``docs/director/TEMPLATES.md``.

Режиссёр в чате выбирает шаблоны сам, и ему нужен один короткий документ:
какой id куда ставится (shot/transition/motion/hero/overlay), какой рендерер
его рисует и какие ``params`` этот рендерер реально читает. Ключи params
вынимаются из исходника рендерера статически — ``params.get("…")`` и
``params["…"]`` — поэтому документ не врёт, когда рендерер меняется.

    python tools/gen_director_catalog.py           # переписать
    python tools/gen_director_catalog.py --check   # код 1, если устарел

Файл производный, как и индексы каталога: руками не правится.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "docs" / "director" / "TEMPLATES.md"

_KEY_RE = re.compile(r"""(?:params|p|ctx\.params|prm|par)\s*(?:\.get\(\s*|\[\s*)["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_SKIP_KEYS = {"renderer", "available_px", "enter_delay", "accent_family", "enter_ms"}

SLOT = {
    "intro-hooks": "shot.fullscreen (хук первых 3 с)",
    "text-fullscreen": "shot.fullscreen",
    "outro-cta": "overlay (финал) / shot.fullscreen",
    "transitions": "shot.transition",
    "avatar-entry": "shot.transition (вход ведущего)",
    "kenburns": "shot.motion",
    "parallax": "shot.motion",
    "hero-devices": "shot.hero",
    "data-viz": "overlay",
    "lower-thirds": "overlay",
    "frames-cards": "overlay",
    "browser-ui": "overlay",
}


_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\(")


def _keys(fn, depth: int = 2, seen: set | None = None) -> list[str]:
    """Ключи params рендерера и функций, которым он передаёт работу."""
    seen = set() if seen is None else seen
    if fn is None or id(fn) in seen:
        return []
    seen.add(id(fn))
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return []
    found = [k for k in dict.fromkeys(_KEY_RE.findall(src)) if k not in _SKIP_KEYS]
    if depth > 0:
        module_globals = getattr(fn, "__globals__", {})
        for name in dict.fromkeys(_CALL_RE.findall(src)):
            callee = module_globals.get(name)
            if (inspect.isfunction(callee)
                    and callee.__module__.startswith("src.lib.render")
                    and callee is not fn):
                for key in _keys(callee, depth - 1, seen):
                    if key not in found:
                        found.append(key)
    return found


def build() -> str:
    from src.lib.render.hyperframes import templates as T

    registries = {"transition": T.TRANSITIONS, "motion": T.MOTION, "hero": T.HERO,
                  "fullscreen": T.FULLSCREEN, "overlay": T.OVERLAYS, "dataviz": T.DATAVIZ}
    manifest = json.loads((REPO / "templates" / "manifest.json").read_text(encoding="utf-8"))
    templates = [t for t in manifest["templates"] if t.get("status") != "retired"]

    def fn_for(tpl: dict) -> object | None:
        name = tpl["id"].split("/")[-1]
        ren = str(tpl.get("renderer") or "")
        if tpl["category"] == "data-viz":
            return T.DATAVIZ.get(name)
        for reg in registries.values():
            if ren in reg:
                return reg[ren]
            if ren.rsplit("/", 1)[-1] in reg:
                return reg[ren.rsplit("/", 1)[-1]]
        return None

    lines = [
        "# Каталог приёмов для режиссёра",
        "",
        "> Производный файл: `python tools/gen_director_catalog.py`. Руками не править.",
        "> Как ставить приём в ролик — `docs/director/TIMELINE.md`.",
        "",
        "Колонка **куда** — поле таймлайна. **params** — ключи, которые рендерер",
        "реально читает (вынуты из исходника); значения по умолчанию — в",
        "`templates/manifest.json`. Текст на экране — капсом, 1–4 слова.",
        "",
    ]
    by_cat: dict[str, list[dict]] = {}
    for tpl in templates:
        by_cat.setdefault(tpl["category"], []).append(tpl)
    for cat in sorted(by_cat):
        lines += [f"## {cat} — {len(by_cat[cat])}", "",
                  f"Куда: `{SLOT.get(cat, 'overlay')}`", "",
                  "| id | что это | рендерер | сек | params |",
                  "|---|---|---|---|---|"]
        for tpl in sorted(by_cat[cat], key=lambda t: t["id"]):
            fn = fn_for(tpl)
            keys = _keys(fn) if fn else []
            dur = tpl.get("duration_range") or []
            dur_s = f"{dur[0]}–{dur[1]}" if len(dur) == 2 else ""
            title = str(tpl.get("title") or "").replace("|", "/")
            ren = tpl.get("renderer") or ""
            if fn is None and ren not in ("plaque", "footage", "avatar", "cta_button", "split"):
                ren += " ⚠нет рендерера"
            lines.append(f"| `{tpl['id']}` | {title} | {ren} | {dur_s} | "
                         f"{', '.join(keys[:10]) or '—'} |")
        lines.append("")

    in_catalog = {str(t.get("renderer")) for t in templates} | {
        t["id"].split("/")[-1] for t in templates}
    extra = []
    for kind, reg in (("overlay", T.OVERLAYS), ("dataviz", T.DATAVIZ), ("fullscreen", T.FULLSCREEN)):
        for name, fn in sorted(reg.items()):
            if name not in in_catalog:
                extra.append((kind, name, _keys(fn)))
    lines += ["## Рендеры вне каталога", "",
              "Зарегистрированы в движке, но без карточки в каталоге. В таймлайн —",
              "через `\"renderer\": \"<имя>\"` вместо `template` (оверлей).", "",
              "| вид | renderer | params |", "|---|---|---|"]
    for kind, name, keys in extra:
        lines.append(f"| {kind} | `{name}` | {', '.join(keys[:10]) or '—'} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    text = build()
    if "--check" in args:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} устарел: python tools/gen_director_catalog.py")
            return 1
        print("каталог режиссёра актуален")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"записан {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

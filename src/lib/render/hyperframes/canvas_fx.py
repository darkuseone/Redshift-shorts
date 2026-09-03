"""Слой canvas в композиции: то, чего CSS не даёт.

CSS хорошо двигает прямоугольники и плохо рисует тысячу точек. Звёздное поле,
орбиты, пыль и линия-кардиограмма из брендбука — это рисование, и делать их
градиентами значит подделывать: у CSS-«звёзд» фиксированный узор, который
виден повтором, а линию по кривой он не проведёт вовсе.

**Контракт движка.** Рендер идёт перемоткой одной приостановленной ленты GSAP:
движок ставит время и снимает кадр. Значит кадр обязан быть **чистой функцией
времени**:

* никакого ``requestAnimationFrame`` — он привязан к настоящему времени
  браузера, а не к ленте, и на перемотке отдаст другой кадр;
* никакого ``Math.random()`` и ``Date.now()`` — два прогона одного ролика
  обязаны совпасть до пикселя, иначе A/B-сравнение и кэш шага бессмысленны;
* рисование вызывается из ``onUpdate`` твина: GSAP зовёт его и при
  проигрывании, и при перемотке, и это единственный способ попасть в такт.

Случайность здесь есть, но своя: линейный конгруэнтный генератор с зерном от
номера кадра. Одно зерно — одно поле звёзд, всегда одно и то же.
"""

from __future__ import annotations

from typing import Any

# Идентификатор общего реестра эффектов на странице.
REGISTRY = "__RSFX"

# --- эффекты -----------------------------------------------------------------

EFFECTS: tuple[str, ...] = ("starfield", "orbit", "dust", "pulse-line", "scan-grid")

EFFECT_TITLES: dict[str, str] = {
    "starfield": "звёздное поле с параллаксом",
    "orbit": "орбитальные кольца со спутником",
    "dust": "медленная пыль туманности",
    "pulse-line": "линия-кардиограмма брендбука",
    "scan-grid": "техническая сетка со сканом",
}


def canvas_js(colors: dict[str, Any]) -> str:
    """Реестр эффектов одной строкой скрипта.

    Пишется в страницу до ленты: твины зовут ``__RSFX.draw`` по имени.
    Цвета приходят из брендбука, а не стоят числами — палитра канала меняется
    в одном месте.
    """
    accent = str(colors.get("accent", "#E63946"))
    accent_soft = str(colors.get("accent_soft", "#ED747D"))
    space = str(colors.get("space_deep", "#0B132B"))
    panel = str(colors.get("panel", "#1A1F2E"))
    light = str(colors.get("bg_pure", "#FFFFFF"))
    soft = str(colors.get("text_soft", "#C7C9D1"))
    return (
        "window." + REGISTRY + " = (function () {"
        # Линейный конгруэнтный генератор: те же числа при том же зерне.
        # Math.random здесь запрещён — кадр обязан повторяться при перемотке.
        "  function rng(seed) {"
        "    let s = (seed >>> 0) || 1;"
        "    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };"
        "  }"
        "  const C = {"
        f"    accent: '{accent}', accentSoft: '{accent_soft}', space: '{space}',"
        f"    panel: '{panel}', light: '{light}', soft: '{soft}'"
        "  };"
        # --- звёздное поле: три слоя с разной скоростью
        "  function starfield(g, w, h, t, p) {"
        "    const n = p.count || 320, drift = p.drift || 0.06;"
        "    const r = rng(p.seed || 7);"
        "    for (let i = 0; i < n; i++) {"
        "      const x0 = r() * w, y0 = r() * h, layer = 1 + Math.floor(r() * 3);"
        "      const size = (0.9 + r() * 2.0) * layer * 0.7;"
        "      const y = (y0 + t * h * drift * layer) % h;"
        "      const twinkle = 0.45 + 0.55 * Math.abs(Math.sin((i + t * 4) * 1.7));"
        "      g.globalAlpha = (0.45 + 0.55 * (layer / 3)) * twinkle;"
        "      g.fillStyle = i % 17 === 0 ? C.accentSoft : C.light;"
        "      g.beginPath(); g.arc(x0, y, size, 0, 6.283); g.fill();"
        "    }"
        "    g.globalAlpha = 1;"
        "  }"
        # --- орбиты: пунктирные кольца и точка по кольцу, как в знаке канала
        "  function orbit(g, w, h, t, p) {"
        "    const cx = (p.cx == null ? 0.5 : p.cx) * w, cy = (p.cy == null ? 0.42 : p.cy) * h;"
        "    const rings = p.rings || 3, base = (p.radius || 0.34) * Math.min(w, h);"
        "    for (let k = 0; k < rings; k++) {"
        "      const rr = base * (1 + k * 0.34), tilt = (p.tilt || 0.42);"
        "      g.save(); g.translate(cx, cy); g.scale(1, tilt);"
        "      g.strokeStyle = k === 0 ? C.accent : C.soft;"
        "      g.globalAlpha = k === 0 ? 0.9 : 0.28;"
        "      g.lineWidth = k === 0 ? 3 : 2;"
        "      g.setLineDash(k === 0 ? [] : [14, 18]);"
        "      g.lineDashOffset = -t * 120 * (k + 1);"
        "      g.beginPath(); g.arc(0, 0, rr, 0, 6.283); g.stroke();"
        "      g.restore();"
        "      if (k === 0) {"
        "        const a = t * 6.283 * (p.speed || 0.6);"
        "        const px = cx + Math.cos(a) * rr, py = cy + Math.sin(a) * rr * tilt;"
        "        g.globalAlpha = 1; g.fillStyle = C.accent;"
        "        g.beginPath(); g.arc(px, py, 9, 0, 6.283); g.fill();"
        "      }"
        "    }"
        "    g.globalAlpha = 1; g.setLineDash([]);"
        "  }"
        # --- пыль: крупные мягкие частицы, дрейф по диагонали
        "  function dust(g, w, h, t, p) {"
        "    const n = p.count || 70, r = rng(p.seed || 21);"
        "    for (let i = 0; i < n; i++) {"
        "      const x0 = r() * w, y0 = r() * h, size = 12 + r() * 46;"
        "      const sp = 0.02 + r() * 0.05;"
        "      const x = (x0 + t * w * sp) % w, y = (y0 - t * h * sp * 0.6 + h) % h;"
        "      const grad = g.createRadialGradient(x, y, 0, x, y, size);"
        "      grad.addColorStop(0, i % 9 === 0 ? C.accent : C.panel);"
        "      grad.addColorStop(1, 'rgba(0,0,0,0)');"
        "      g.globalAlpha = 0.34 + 0.26 * r();"
        "      g.fillStyle = grad;"
        "      g.beginPath(); g.arc(x, y, size, 0, 6.283); g.fill();"
        "    }"
        "    g.globalAlpha = 1;"
        "  }"
        # --- кардиограмма из брендбука: линия проводится слева направо
        "  function pulseLine(g, w, h, t, p) {"
        "    const y = (p.y == null ? 0.5 : p.y) * h, amp = (p.amp || 0.06) * h;"
        "    const upto = w * Math.min(1, Math.max(0, t / (p.draw || 0.8)));"
        "    g.strokeStyle = C.accent; g.lineWidth = p.width || 5;"
        "    g.lineJoin = 'round'; g.lineCap = 'round';"
        "    g.beginPath();"
        "    for (let x = 0; x <= upto; x += 4) {"
        "      const u = x / w;"
        "      const beat = Math.exp(-Math.pow((u % 0.25 - 0.12) * 26, 2));"
        "      const yy = y - beat * amp * (u % 0.5 < 0.25 ? 1 : 0.55)"
        "               + Math.sin(u * 42) * amp * 0.06;"
        "      if (x === 0) g.moveTo(x, yy); else g.lineTo(x, yy);"
        "    }"
        "    g.stroke();"
        "    if (upto > 0) {"
        "      g.fillStyle = C.accent;"
        "      g.beginPath(); g.arc(upto, y, 7, 0, 6.283); g.fill();"
        "    }"
        "  }"
        # --- техническая сетка со сканирующей полосой
        "  function scanGrid(g, w, h, t, p) {"
        "    const step = p.step || 96;"
        "    g.strokeStyle = C.soft; g.globalAlpha = 0.16; g.lineWidth = 1;"
        "    for (let x = 0; x <= w; x += step) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }"
        "    for (let y = 0; y <= h; y += step) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }"
        "    const band = (t * (p.speed || 0.5)) % 1 * (h + 400) - 200;"
        "    const grad = g.createLinearGradient(0, band - 180, 0, band + 180);"
        "    grad.addColorStop(0, 'rgba(0,0,0,0)');"
        "    grad.addColorStop(0.5, C.accent);"
        "    grad.addColorStop(1, 'rgba(0,0,0,0)');"
        "    g.globalAlpha = 0.30; g.fillStyle = grad;"
        "    g.fillRect(0, band - 180, w, 360);"
        "    g.globalAlpha = 1;"
        "  }"
        "  const FX = {starfield: starfield, orbit: orbit, dust: dust,"
        "              'pulse-line': pulseLine, 'scan-grid': scanGrid};"
        "  function draw(id, name, t, params) {"
        "    const el = document.getElementById(id);"
        "    if (!el || !el.getContext) return;"
        "    const g = el.getContext('2d');"
        "    const w = el.width, h = el.height;"
        "    g.setTransform(1, 0, 0, 1, 0, 0);"
        "    g.clearRect(0, 0, w, h);"
        "    const fn = FX[name];"
        "    if (fn) fn(g, w, h, t, params || {});"
        "  }"
        "  return {draw: draw, effects: Object.keys(FX)};"
        "})();"
    )


def canvas_node(node_id: str, *, timing: str, css: str = "",
                width: int = 1080, height: int = 1920) -> str:
    """Холст как обычный клип: движок сам управляет его видимостью."""
    classes = " ".join(x for x in ("clip", "fx-canvas", css) if x)
    return (f'<canvas id="{node_id}" class="{classes}" '
            f'width="{width}" height="{height}" {timing}></canvas>')


def canvas_tween(node_id: str, effect: str, *, start: float, duration: float,
                 params: dict[str, Any] | None = None) -> str:
    """Твин, который ведёт рисование по времени ленты.

    Прокси-объект вместо DOM: анимируется число ``t`` от 0 до 1, а ``onUpdate``
    перерисовывает холст. Перемотка вызывает ``onUpdate`` так же, как
    проигрывание, — кадр совпадает с точностью до пикселя.
    """
    import json

    body = json.dumps(params or {}, ensure_ascii=False, separators=(",", ":"))
    return (
        f"(function(){{const s={{t:0}};"
        f"tl.to(s,{{t:1,duration:{duration:.3f},ease:'none',"
        f"onUpdate:function(){{window.{REGISTRY}.draw('{node_id}','{effect}',s.t,{body});}}}},"
        f"{start:.3f});}})();"
    )

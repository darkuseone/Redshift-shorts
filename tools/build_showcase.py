#!/usr/bin/env python3
"""Витрина приёмов вокруг ведущего: живая страница вместо контактного листа.

Каждая карточка — настоящая композиция: та же разметка, тот же CSS и те же
твины GSAP, которые уйдут в рендер. Не пересказ и не запись экрана: приём,
который сломается в кадре, сломается и здесь.

Аватар на витрине — силуэт, а не ведущий: приёмы за головой читаются только по
альфе, а живого клипа с альфой пока нет (аватар 5 в работе). Силуэт стоит там
же, где стоит голова в кадре, поэтому композиция читается честно.

Запуск: python tools/build_showcase.py [-o out.html]
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.lib.config import load_config                                  # noqa: E402
from src.lib.backdrop import pick_scene, tone as scene_tone            # noqa: E402
from src.lib.ffmpeg import HEAD_ASPECT                                  # noqa: E402
from src.lib.render.hyperframes.brand_css import build_css              # noqa: E402
from src.lib.render.hyperframes.templates import (                      # noqa: E402
    TemplateCtx, render_hero,
)
from src.p11_assemble.assemble import (                                 # noqa: E402
    _HERO_NEEDS, _hero_content, hero_params,
)

# Демо-содержимое — реальный сценарий, а не рыба: приём судят по тому, как в
# нём лежит живая фраза, а «Lorem ipsum» не ломается ни в одном кегле.
DEMO_SCRIPTS = [ROOT / "scripts" / "redshift_0046.json",
                ROOT / "scripts" / "redshift_0042.json"]

# Окну генерации нужна реплика про генерацию — иначе `_gen_prompt` молчит и
# приём собирается пустым (витрина это ловит и падает). Ни один сценарий
# репозитория пока не про нейросети, и это правильно: приём включается смыслом,
# а не расписанием. Поэтому реплика для витрины лежит здесь, а не в scripts/ —
# сценарий там означал бы ролик, который никто не собирался снимать.
GEN_BLOCK = {
    "id": "gen", "role": "develop",
    "text": ("Я попросил нейросеть дорисовать недостающий кусок кадра, "
             "и она дорисовала то, чего на снимке никогда не было."),
    "emphasis_word": "дорисовать",
    "broll_queries": ["ai generated image closeup"],
    "overlay": {"type": "none"},
}

# Роль блока меняет кикер над заголовком, поэтому у карточек она разная.
ROLES = ["hook", "develop", "turn", "payoff"]

# Что приём делает с кадром — одной строкой, для человека, который выбирает
# приём, а не читает исходник.
NOTES = {
    "plate-behind-back": "Кадр по теме встаёт за плечом и живёт своей жизнью, "
                         "пока ведущий говорит.",
    "headline-over-head": "Кикер, слово и подчёркивание: слово выходит из-за "
                          "головы и садится на место.",
    "headline-behind-head": "То же слово крупнее и ниже — голова перекрывает "
                            "его низ, и надпись уходит за спину.",
    "icons-behind-head": "Знаки о предмете речи вспыхивают очередью по дуге за головой и гаснут. Выбираются по тексту реплики, а логотип бренда идёт первым, когда бренд назван.",
    "split-panel-right": "Кадр делится: ведущий уходит влево и укрупняется, "
                         "справа встаёт слово столбцом.",
    "knockout-negative": "Заливка на весь кадр, слово вырезано насквозь — "
                         "ведущий виден сквозь буквы.",
    "text-column-left": "Реплика колонкой слева, акцентная строка красным. "
                        "Субтитр этого кадра — сам приём.",
    "bubble-card": "Ведущий в круге, реплика карточкой под ним.",
    "brand-pill": "Пилюля с логотипом у плеча — когда в реплике назван "
                  "продукт.",
    "card-stack-top": "Карточка с заголовком сверху, материал под ней, "
                      "ведущий снизу.",
    "phone-mock": "Экран приложения поверх расфокуса: показывает, а не "
                  "рассказывает.",
    "script-stack": "Реплика строками с толстой обводкой — приём из первого "
                    "присланного ролика.",
    "chat-typing": "Запрос набирается словами, ответ ждёт скелетоном. Пауза "
                   "и есть приём.",
    "title-behind-head": "Тема ролика двумя строками за головой, вторая "
                         "строка — акцентом.",
    "exhibit-card": "Материал в раме, под ним музейная подпись: имя, "
                    "уточнение и источник. Ведущий отъезжает вниз.",
    "statement-slam": "Фраза забирает кадр плашкой и уходит, вырастая на "
                      "зрителя. Секунда-две, не дольше.",
    "phrase-log": "Куски реплики копятся слева по ходу речи — каждый приходит "
                  "на своём слове и остаётся.",
    "oversize-word": "Слово набрано крупнее кадра: края обрезаны, буквы "
                     "медленно едут.",
    "figure-swap": "Числа реплики встают одно за другим на одном месте, "
                   "последнее — акцентом.",
    "verdict-card": "Светлая плашка с приговором: вторая строка приходит "
                    "серой и наливается чёрным.",
    "bubble-typed": "Тот же круг с ведущим, но реплика в карточке не стоит "
                    "готовой — она набирается кусками по ходу речи, "
                    "последний приходит акцентом.",
    "source-paper": "Страница источника: домен в адресной строке, по цитате "
                    "из статьи идёт маркер. Текст страницы — полосы: "
                    "сочинённый абзац был бы выдуманной цитатой.",
}

# Силуэт ведущего: голова и плечи там же, где они в настоящем кадре. Овал
# головы почти совпал с промером живого клипа (402, 372, 756, 786) — рисовался
# он по тому же медиуму.
#
# Числа овала не нарисованы дважды: из них же собирается коробка головы,
# которая уходит приёмам. Приём за головой садится по макушке, и если бы
# витрина отдавала ему константу пресета, а конвейер — измерение, она
# показывала бы не то, что соберётся в ролике.
# Пропорция овала — та самая, которой конвейер переводит измеренную
# ширину головы в высоту (`ffmpeg.HEAD_ASPECT`). Нарисованная голова
# другой формы показывала бы приёмы не там, где они встанут в ролике.
HEAD_CX, HEAD_CY, HEAD_RX = 540, 570, 163
HEAD_RY = round(HEAD_RX * HEAD_ASPECT)
HEAD_BOX = (HEAD_CX - HEAD_RX, HEAD_CY - HEAD_RY,
            HEAD_CX + HEAD_RX, HEAD_CY + HEAD_RY)

# Силуэт серединного тона намеренно. Чернильный читался только на светлой
# подложке, а сцены за ведущим теперь в основном тёмные — на них силуэт
# сливался с фоном, и карточка «ведущий в круге» показывала пустой круг.
# Середина между тёмной сценой и светлой комнатой видна на обеих.
SILHOUETTE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920">'
    '<g fill="#5A6069">'
    f'<ellipse cx="{HEAD_CX}" cy="{HEAD_CY}" rx="{HEAD_RX}" ry="{HEAD_RY}"/>'
    '<path d="M540 792c-52 0-96 10-96 10l-8 44c-118 30-206 128-232 250'
    'l-52 824h776l-52-824c-26-122-114-220-232-250l-8-44s-44-10-96-10z"/>'
    "</g></svg>"
)

# Материал для приёмов с картинкой. Настоящий футаж живёт в прогоне и в
# репозиторий не попадает, а сток ради витрины качать незачем: здесь нужен не
# сюжет, а прямоугольник в палитре — иначе чужой кадр перетянет на себя всё
# внимание с самого приёма.
PLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 560">'
    '<defs><radialGradient id="g" cx="38%" cy="30%" r="82%">'
    '<stop offset="0%" stop-color="#3A3B40"/>'
    '<stop offset="58%" stop-color="#1B1C20"/>'
    '<stop offset="100%" stop-color="#111214"/></radialGradient>'
    '<radialGradient id="h" cx="72%" cy="76%" r="46%">'
    '<stop offset="0%" stop-color="#C8453D" stop-opacity=".42"/>'
    '<stop offset="100%" stop-color="#C8453D" stop-opacity="0"/>'
    '</radialGradient></defs>'
    '<rect width="660" height="560" fill="url(#g)"/>'
    '<rect width="660" height="560" fill="url(#h)"/>'
    '<circle cx="250" cy="168" r="86" fill="none" stroke="#F7F5F3"'
    ' stroke-opacity=".16" stroke-width="2"/>'
    '<circle cx="250" cy="168" r="140" fill="none" stroke="#F7F5F3"'
    ' stroke-opacity=".08" stroke-width="2"/>'
    "</svg>"
)


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


PLATE_URI = _svg_uri(PLATE)


def _fonts_css() -> str:
    """Те же ttf, что и в рендере, — файлами внутрь страницы.

    Не Google Fonts: кегль каждой надписи подобран измерением по этим файлам
    (``fit_size``), и подмена гарнитуры увела бы вёрстку — с запасным Arial
    «МОЛЧА» вылезает за кадр. Лицензия OFL встраивание разрешает.
    """
    manifest = json.loads(
        (ROOT / "assets" / "fonts" / "fonts_manifest.json").read_text("utf-8"))
    out = []
    for font in manifest["fonts"]:
        raw = (ROOT / "assets" / "fonts" / font["file"]).read_bytes()
        uri = "data:font/ttf;base64," + base64.b64encode(raw).decode()
        out.append(f"@font-face{{font-family:'RS {font['role'].title()}';"
                   f"src:url({uri}) format('truetype');"
                   "font-weight:normal;font-style:normal;font-display:block}")
    return "".join(out)


def _composition_css(cfg) -> str:
    """CSS композиции без правил, которые в браузере страницы всё сломают.

    ``build_css`` пишет размеры кадра прямо на ``html, body`` — на витрине это
    сжало бы страницу до одного кадра. Кадр здесь живёт в ``.rs-frame``, а
    глобальный сброс сужается до его содержимого: чужие отступы приёмам не
    нужны, но и страницу трогать нельзя.
    """
    css = build_css(cfg.brandbook, fonts={})
    css = css.replace(
        "html,body{width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;background:#000}", "")
    css = css.replace("*,*::before,*::after{",
                      ".rs-frame,.rs-frame *,.rs-frame *::before,.rs-frame *::after{")
    css = css.replace("#root{", ".rs-frame{")
    return _fonts_css() + css


def _content_for(block: dict, title: str, role: str) -> dict:
    """Содержимое блока для приёма — теми же функциями, что и в конвейере."""
    slot = {"role": role, "queries": block.get("broll_queries") or [],
            "start": 0.0, "end": 12.0}
    # Тайминги слов на витрине условные, но такие же по форме, как в прогоне:
    # без них «список копится» нечем наполнить.
    spoken = [{"display": w, "start": 0.42 * n, "end": 0.42 * n + 0.36,
               "block_id": block["id"]}
              for n, w in enumerate(str(block.get("text") or "").split())]
    content = _hero_content(
        block, slot, None,
        ((HEAD_BOX[0] + HEAD_BOX[2]) // 2, (HEAD_BOX[1] + HEAD_BOX[3]) // 2),
        title=title, words=spoken, head_box=HEAD_BOX)
    # Кредит приходит с материалом: на витрине материал условный, но строка
    # та же, что встанет в кадр. Иконок брендов в репозитории пока нет.
    content["credit"] = "NASA · public domain"
    content["brand"] = {"label": "БРЕНД", "icon": ""}
    return content


def _devices(cfg) -> list[dict]:
    manifest = json.loads((ROOT / "templates" / "manifest.json").read_text("utf-8"))
    items = [t for t in manifest["templates"]
             if t["id"].startswith("hero-devices/")]
    demos = [json.loads(path.read_text("utf-8")) for path in DEMO_SCRIPTS]
    pool = [(block, script["meta"]["title"])
            for script in demos for block in script["blocks"]]
    pool.append((GEN_BLOCK, "Что нейросеть дорисовывает за нас"))

    plate_uri = PLATE_URI

    out = []
    for i, template in enumerate(items):
        role = ROLES[i % len(ROLES)]
        # Блок берётся не по кругу, а тот, которым приём вообще можно накормить:
        # конвейер выбирает приём ровно так же — по совпадению с потребностями
        # (`_HERO_NEEDS`). Прокрутка по кругу поставила бы «смену чисел» на
        # реплику без единой цифры, и витрина показала бы пустой кадр.
        needs = _HERO_NEEDS.get(template["renderer"], ())
        best = None
        for offset in range(len(pool)):
            block, title = pool[(i + offset) % len(pool)]
            content = _content_for(block, title, role)
            score = sum(1 for key in needs if key != "plate" and content.get(key))
            if best is None or score > best[0]:
                best = (score, block, title, content)
            if score == len([k for k in needs if k != "plate"]):
                break
        _, block, title, content = best
        slot = {"role": role, "queries": block.get("broll_queries") or [],
                "start": 0.0, "end": 12.0}
        params = hero_params(template["renderer"], template.get("params", {}),
                             content, slot)
        if "plate" in _HERO_NEEDS.get(template["renderer"], ()):
            params["src"] = plate_uri
        duration = float(template["duration_range"][1])
        ctx = TemplateCtx(index=i, start=0.0, duration=duration,
                          target=f"av-{i:02d}", track=13, params=params)
        piece = render_hero(template["renderer"], ctx)
        if not piece.nodes:
            raise SystemExit(f"приём {template['id']} собрался пустым")
        out.append({
            "id": template["id"].split("/", 1)[1],
            "full_id": template["id"],
            "renderer": template["renderer"],
            "title": template["title"],
            "note": NOTES.get(template["id"].split("/", 1)[1], ""),
            "range": template["duration_range"],
            "tags": template.get("tags", []),
            "duration": duration,
            "index": i,
            "nodes": [_as_image(n) for n in piece.nodes],
            "tweens": piece.tweens,
            # Сцена у карточки своя — по её же реплике, тем же выбором, что и
            # в ролике. На витрине это единственный способ показать приём на
            # том фоне, на котором он окажется: на тёмной сцене надписи,
            # лежащие прямо на фоне, меняют цвет.
            "scene": pick_scene(title, block.get("text") or ""),
        })
    return out


def _as_image(node: str) -> str:
    """Видео в кадре — картинка на витрине: браузер не проигрывает кадр из плана."""
    if not node.startswith("<video"):
        return node
    node = node.replace("<video", "<img", 1)
    node = node.replace(" muted playsinline></video>", " alt=\"\" />")
    return node.replace("></video>", " alt=\"\" />")


PAGE_CSS = """
:root{
  --ground:#E9E7E3; --surface:#FFFFFF; --ink:#141416; --muted:#6E6F73;
  --hair:#D8D4CE; --accent:#C8453D; --shadow:0 18px 44px rgba(20,18,16,.14);
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#121213; --surface:#1A1A1C; --ink:#F2F1EE; --muted:#95959B;
    --hair:#2B2B2E; --accent:#E4726A; --shadow:0 18px 44px rgba(0,0,0,.5);
  }
}
:root[data-theme="dark"]{
  --ground:#121213; --surface:#1A1A1C; --ink:#F2F1EE; --muted:#95959B;
  --hair:#2B2B2E; --accent:#E4726A; --shadow:0 18px 44px rgba(0,0,0,.5);
}
body{
  background:var(--ground); color:var(--ink);
  font-family:var(--font-subtitle);
  font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1220px; margin:0 auto; padding:0 28px 96px;}

header.top{padding:76px 0 34px; display:flex; flex-direction:column; gap:18px;}
.eyebrow{
  font-family:var(--font-mono); font-size:12px;
  letter-spacing:.18em; text-transform:uppercase; color:var(--muted);
}
h1{
  font-family:var(--font-display); font-weight:700;
  font-size:clamp(38px,6vw,68px); line-height:.98; letter-spacing:-.01em;
  text-transform:uppercase; text-wrap:balance; margin:0;
}
.lede{max-width:62ch; color:var(--muted); font-size:18px;}
.lede b{color:var(--ink); font-weight:800;}

.bar{
  position:sticky; top:0; z-index:40; display:flex; flex-wrap:wrap; gap:10px;
  align-items:center; padding:12px 0; margin-bottom:26px;
  background:color-mix(in srgb, var(--ground) 86%, transparent);
  backdrop-filter:blur(14px); border-bottom:1px solid var(--hair);
}
button.ctl{
  font-family:var(--font-mono); font-size:12px;
  letter-spacing:.06em; text-transform:uppercase; color:var(--ink);
  background:var(--surface); border:1px solid var(--hair); border-radius:999px;
  padding:9px 16px; cursor:pointer; transition:border-color .18s, color .18s;
}
button.ctl:hover{border-color:var(--ink);}
button.ctl[aria-pressed="true"]{border-color:var(--accent); color:var(--accent);}
button.ctl:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
.bar .sep{flex:1;}
.bar .count{
  font-family:var(--font-mono); font-size:12px;
  color:var(--muted);
}

.grid{
  display:grid; gap:34px 26px;
  grid-template-columns:repeat(auto-fill,minmax(var(--card-w),1fr));
}
.size-s{--k:.185;} .size-m{--k:.245;} .size-l{--k:.40;}
.grid{--card-w:calc(1080px * var(--k));}

.card{display:flex; flex-direction:column; gap:12px;}
.viewport{
  position:relative; width:100%; aspect-ratio:1080 / 1920; overflow:hidden;
  border-radius:calc(28px * var(--k) * 3); background:#F7F5F3;
  box-shadow:var(--shadow); isolation:isolate;
}
.rs-frame{
  position:absolute; left:0; top:0; width:1080px; height:1920px;
  transform:scale(var(--k)); transform-origin:top left;
}
.vfx{z-index:0;}
.avatar{background:var(--rs-silhouette) center/cover no-repeat;}
.progress{
  position:absolute; left:0; bottom:0; height:2px; width:100%; z-index:60;
  background:transparent;
}
.progress i{
  display:block; height:100%; width:0; background:var(--accent);
  transform-origin:left center;
}
.meta{display:flex; flex-direction:column; gap:5px;}
.meta h3{
  font-family:var(--font-display); font-weight:600; font-size:19px;
  letter-spacing:.005em; text-transform:uppercase; margin:0;
}
.meta p{margin:0; font-size:14.5px; color:var(--muted); text-wrap:pretty;}
.tags{
  display:flex; flex-wrap:wrap; gap:6px; margin-top:3px;
  font-family:var(--font-mono); font-size:11px;
  color:var(--muted); font-variant-numeric:tabular-nums;
}
.tags span{border:1px solid var(--hair); border-radius:5px; padding:2px 7px;}
.tags span.dur{border-color:transparent; padding-left:0;}

.notes{
  margin-top:78px; display:grid; gap:34px;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
}
.notes section{
  border-top:2px solid var(--ink); padding-top:16px;
}
.notes h2{
  font-family:var(--font-display); font-weight:600; font-size:15px;
  letter-spacing:.1em; text-transform:uppercase; margin:0 0 10px;
}
.notes li{margin:0 0 9px 18px; font-size:14.5px; color:var(--muted);}
.notes li b{color:var(--ink); font-weight:800;}
footer{
  margin-top:70px; padding-top:20px; border-top:1px solid var(--hair);
  font-family:var(--font-mono); font-size:12px;
  color:var(--muted); display:flex; flex-wrap:wrap; gap:14px 28px;
}
@media (prefers-reduced-motion: reduce){
  .progress i{transition:none;}
}
"""


def _card(device: dict) -> str:
    tags = "".join(f"<span>{t}</span>" for t in device["tags"][:4])
    lo, hi = device["range"]
    scene = device["scene"]
    stage = scene_tone(scene)
    return f"""
    <article class="card">
      <div class="viewport">
        <div class="rs-frame stage-{stage}" id="fr-{device['index']:02d}">
          <!-- Тот же фон, что и в кадре режима A с альфой: сцена (§7.7), а не
               белая подложка — приёмы читаются именно на нём. -->
          <div class="stage-bg"></div>
          <div class="vfx scene-{scene}"></div>
          <div class="avatar" id="av-{device['index']:02d}"></div>
          {''.join(device['nodes'])}
        </div>
        <div class="progress"><i data-p="{device['index']:02d}"></i></div>
      </div>
      <div class="meta">
        <h3>{device['title']}</h3>
        <p>{device['note']}</p>
        <div class="tags"><span class="dur">{lo}–{hi} c</span>{tags}</div>
      </div>
    </article>"""


def build(out_path: Path) -> Path:
    cfg = load_config()
    devices = _devices(cfg)
    # Тот же GSAP, что уходит в рендер: витрина не имеет права двигать иначе.
    gsap = (ROOT / "render" / "hyperframes" / "vendor" / "gsap.min.js").read_text("utf-8")

    timelines = []
    for d in devices:
        body = "".join(d["tweens"])
        timelines.append(
            f"TL['{d['id']}']=(function(){{"
            f"const tl=gsap.timeline({{paused:true}});{body}"
            f"tl.to({{}},{{duration:0.001}},{d['duration']:.3f});"
            f"return tl;}})();")

    silhouette = _svg_uri(SILHOUETTE)

    html = f"""<title>Приёмы вокруг ведущего</title>
<style>{_composition_css(cfg)}</style>
<style>{PAGE_CSS}
:root{{--rs-silhouette:url("{silhouette}");}}
</style>

<div class="wrap">
  <header class="top">
    <div class="eyebrow">REDSHIFT · каталог §15.11 · {len(devices)} приёмов</div>
    <h1>Приёмы вокруг ведущего</h1>
    <p class="lede">Каждый кадр здесь живой: та же разметка, тот же CSS и те же
      твины, которые уходят в рендер. <b>Приём, который сломается в ролике,
      сломается и на этой странице.</b> Вместо ведущего — силуэт: он стоит там
      же, где голова в кадре, и приёмы за головой читаются честно.</p>
  </header>

  <div class="bar">
    <button class="ctl" id="play" aria-pressed="true">Пауза</button>
    <button class="ctl" id="again">Сначала</button>
    <button class="ctl size" data-k="s">S</button>
    <button class="ctl size" data-k="m" aria-pressed="true">M</button>
    <button class="ctl size" data-k="l">L</button>
    <button class="ctl speed" data-v="0.5">0,5×</button>
    <button class="ctl speed" data-v="1" aria-pressed="true">1×</button>
    <button class="ctl speed" data-v="1.5">1,5×</button>
    <span class="sep"></span>
    <span class="count">петля 0,9 c паузы</span>
  </div>

  <main class="grid size-m" id="grid">{''.join(_card(d) for d in devices)}
  </main>

  <div class="notes">
    <section>
      <h2>Чего движок не сделает</h2>
      <ul>
        <li><b>filter</b> — не в списке разрешённых свойств: перемотка после
          него даёт не тот кадр. Значит, ни блюра, ни перевода
          чёрно-белого в цвет в браузерном слое.</li>
        <li><b>Видео внутри клипа</b> не проигрывается: материал обязан быть
          самим клипом.</li>
        <li><b>Клип нулевой площади</b> вырезается вместе с детьми, а
          выступающее за края — нет.</li>
        <li><b>opacity на клипе</b> запрещена, трансформации — можно.</li>
      </ul>
    </section>
    <section>
      <h2>Словарь появления</h2>
      <ul>
        <li>Всё <b>приближается</b>, ничего не «включается»: вход без движения
          читается как подмена кадра.</li>
        <li>Замедляющиеся кривые, малый масштаб, плотная очередь по строкам.</li>
        <li>После входа кадр не замирает: остаётся дрейф.</li>
      </ul>
    </section>
    <section>
      <h2>Как добавить приём</h2>
      <ul>
        <li>Присылаете короткий ролик — я снимаю с него движение, а не
          картинку.</li>
        <li>Палитра остаётся своей: чёрный, белый, приглушённый красный.
          Золото из референсов не переносится.</li>
        <li>Приём попадает в каталог с диапазоном длительности и тегами —
          дальше конвейер сам ставит его в подходящий кадр.</li>
      </ul>
    </section>
  </div>

  <footer>
    <span>палитра: #111214 · #F7F5F3 · #C8453D</span>
    <span>гарнитуры: Oswald · Nunito · JetBrains Mono</span>
    <span>кадр 1080×1920, 30 fps</span>
  </footer>
</div>

<script>{gsap}</script>
<script>
const TL = {{}};
{''.join(timelines)}
const IDS = Object.keys(TL);
const BARS = {{}};
document.querySelectorAll('.progress i').forEach(function (el) {{
  BARS[el.dataset.p] = el;
}});
const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let speed = 1, playing = !still;

const LOOP_GAP = 0.9;
IDS.forEach(function (id, i) {{
  const tl = TL[id];
  tl.eventCallback('onComplete', function () {{
    gsap.delayedCall(LOOP_GAP / speed, function () {{ if (playing) tl.play(0); }});
  }});
  tl.eventCallback('onUpdate', function () {{
    const bar = BARS[String(i).padStart(2, '0')];
    if (bar) bar.style.width = (tl.progress() * 100).toFixed(1) + '%';
  }});
}});

function setAll(fn) {{ IDS.forEach(function (id) {{ fn(TL[id]); }}); }}

if (still) {{
  // Кадр приёма, а не его последний кадр: у приёмов с уходом на конце
  // остаётся пустая сцена, и витрина показывала бы пустоту.
  setAll(function (tl) {{ tl.progress(0.55).pause(); }});
  document.getElementById('play').textContent = 'Играть';
  document.getElementById('play').setAttribute('aria-pressed', 'false');
}} else {{
  setAll(function (tl) {{ tl.play(0); }});
}}

document.getElementById('play').addEventListener('click', function (e) {{
  playing = !playing;
  e.target.textContent = playing ? 'Пауза' : 'Играть';
  e.target.setAttribute('aria-pressed', String(playing));
  setAll(function (tl) {{ playing ? tl.play() : tl.pause(); }});
}});

document.getElementById('again').addEventListener('click', function () {{
  playing = true;
  const play = document.getElementById('play');
  play.textContent = 'Пауза';
  play.setAttribute('aria-pressed', 'true');
  setAll(function (tl) {{ tl.play(0); }});
}});

document.querySelectorAll('.ctl.size').forEach(function (b) {{
  b.addEventListener('click', function () {{
    document.querySelectorAll('.ctl.size').forEach(function (o) {{
      o.setAttribute('aria-pressed', String(o === b));
    }});
    const grid = document.getElementById('grid');
    grid.className = 'grid size-' + b.dataset.k;
  }});
}});

document.querySelectorAll('.ctl.speed').forEach(function (b) {{
  b.addEventListener('click', function () {{
    document.querySelectorAll('.ctl.speed').forEach(function (o) {{
      o.setAttribute('aria-pressed', String(o === b));
    }});
    speed = parseFloat(b.dataset.v);
    setAll(function (tl) {{ tl.timeScale(speed); }});
  }});
}});
</script>
"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", default=str(ROOT / "build" / "showcase.html"))
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build(out)
    size = out.stat().st_size
    print(f"витрина собрана: {out} ({size / 1024:.0f} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

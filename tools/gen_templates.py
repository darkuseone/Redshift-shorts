#!/usr/bin/env python3
"""Генератор каталога шаблонов §15.

Каталог описан в ТЗ списками имён; держать их в коде удобнее, чем править JSON
вручную — генератор гарантирует, что состав и счётчики категорий совпадают
с §15.1–15.11, а параметры каждого пресета остаются машиночитаемыми.

Запуск: python tools/gen_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

# Референсы с examples HyperFrames: жесты, не готовые 16:9-фильмы.
_EX_TEXTURE = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
               "launch-texture-launch-video-v1-s.mp4")
_EX_K3 = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
          "launch-k3-promo-v1-s.mp4")
_EX_SPACEX = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
              "launch-spacex-launch-v1-s.mp4")
_EX_WEBSITE = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
               "launch-website-to-hyperframes-v1-s.mp4")
_EX_PR = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
          "launch-pr-to-video-launch-v1-s.mp4")
_EX_SRINIKA = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
               "reverse-srinika-replica.mp4")
_EX_STRIPE = ("https://static.heygen.ai/hyperframes-oss/docs/images/showcase/"
              "launch-HF-heygen-stripe-v1-s.mp4")

# (id, описание, duration_range, params, tags, renderer[, example_video])
CATALOG: dict[str, tuple[int, list[tuple]]] = {
    "intro-hooks": (8, [
        ("hook-question-flash", "Вопрос вспышкой на однотонном фоне", [0.8, 2.0],
         {"flash_ms": 120, "bg": "bg_pure"}, ["hook", "text", "flash"], "fullscreen_text"),
        ("hook-number-slam", "Цифра-удар с ударным SFX", [0.8, 1.6],
         {"scale_from": 1.35, "sfx": "hit_impact", "slam": True},
         ["hook", "number"], "fullscreen_text"),
        ("hook-blackout-word", "Одно слово на чёрном", [0.6, 1.4],
         {"invert": True}, ["hook", "text", "dark"], "fullscreen_text"),
        ("hook-footage-cold-open", "Холодный вход футажом без текста", [1.0, 3.0],
         {"kenburns": "zoom-in-center"}, ["hook", "footage"], "footage"),
        ("hook-split-reveal", "Сплит раскрывается сверху", [1.2, 2.6],
         {"enter_ms": 260}, ["hook", "split"], "split"),
        ("hook-typing-search", "Печать запроса в поисковой строке", [1.4, 3.0],
         {"cps": 18, "template": "search"}, ["hook", "ui", "typing"], "source_card"),
        ("hook-countdown-3", "Отсчёт 3-2-1", [1.2, 2.0],
         {"steps": 3}, ["hook", "number"], "fullscreen_text"),
        ("hook-avatar-direct", "Аватар говорит в камеру сразу", [1.5, 3.0],
         {"entry": "hero-zoom-in"}, ["hook", "avatar"], "avatar"),
    ]),
    "text-fullscreen": (23, [
        ("impact-01", "Гигантская цифра", [0.8, 2.0],
         {"size_px": [260, 420], "uppercase": True, "slam": True},
         ["number", "impact"], "fullscreen_text"),
        ("impact-02", "Слово с подчёркиванием accent", [0.8, 2.0],
         {"underline": True}, ["word", "impact"], "fullscreen_text"),
        ("stack-3lines", "Три строки лесенкой", [1.2, 2.0],
         {"max_lines": 3, "align": "left"}, ["text", "stack"], "fullscreen_text"),
        ("word-swap", "Слова сменяются на месте", [1.0, 2.0],
         {"swap_ms": 260}, ["text", "swap"], "fullscreen_text"),
        ("quote-frame", "Цитата в рамке", [1.2, 2.0],
         {"quotes": True, "max_words": 15}, ["quote", "text"], "fullscreen_text"),
        ("date-marker", "Дата крупно", [0.8, 1.4],
         {"mono": True}, ["date", "mono"], "fullscreen_text"),
        ("vs-compare", "Два значения через VS", [1.2, 2.0],
         {"split": True}, ["compare"], "fullscreen_text"),
        ("label-strip", "Полоса-ярлык поперёк кадра", [0.8, 1.6],
         {"strip_height": 220}, ["label"], "fullscreen_text"),
        ("bigtext-mask-footage", "Текст-маска с футажом внутри", [1.0, 2.0],
         {"mask": True}, ["text", "footage", "mask"], "fullscreen_text"),
        ("fact-card", "Карточка факта", [1.2, 2.0],
         {"card": True}, ["fact", "card"], "fullscreen_text"),
        ("kinetic-stack", "Слова входят rise со стаггером — Texture / OBLIST",
         [0.8, 2.0], {"stagger_ms": 55, "kinetic": True},
         ["text", "kinetic"], "kinetic_stack", _EX_TEXTURE),
        ("blur-out-up", "Слова выходят из размытия и уходят вверх — blur-out-up",
         [0.8, 2.0], {"stagger_ms": 55, "blur_out": True, "direction": "up",
                      "distance": "standard", "blur": "standard"},
         ["text", "kinetic", "blur"], "blur_out_up"),
        ("bottom-up-letters", "Буквы поднимаются снизу со стаггером — bottom-up-letters",
         [0.8, 2.0], {"stagger_ms": 25, "bottom_up": True, "unit": "letter",
                      "direction": "up", "travel": "standard"},
         ["text", "kinetic", "letters"], "bottom_up_letters"),
        ("kinetic-type-swap", "Фраза стоит, в маске катится слово — kinetic-type-swap",
         [0.8, 4.0], {"kinetic_swap": True, "exit": "none"},
         ["text", "kinetic", "swap"], "kinetic_type_swap"),
        ("line-by-line-slide", "Строки заезжают слева со стаггером — line-by-line-slide",
         [0.8, 2.4], {"line_slide": True, "direction": "left", "size": "standard",
                      "density": "standard", "tone": "ink"},
         ["text", "kinetic", "stack"], "line_by_line_slide"),
        ("particle-text-dissolve",
         "Строка собирается из облака пыли — particle-text-dissolve",
         [0.8, 4.0],
         {"particle_dissolve": True, "direction": "in", "density": "med",
          "exit": "none"},
         ["text", "kinetic", "particles"], "particle_text_dissolve"),
        ("per-word-crossfade",
         "Слова входят из блюра с коротким подъёмом — per-word-crossfade",
         [0.8, 2.4],
         {"word_crossfade": True, "drift": "standard", "blur": "standard",
          "tone": "ink", "exit": "none"},
         ["text", "kinetic", "blur"], "per_word_crossfade"),
        ("scan-band",
         "Диагональная полоса с RGB-сдвигом по вордмарку — scan-band",
         [0.8, 4.0],
         {"scan_band": True, "band_angle": 12},
         ["text", "kinetic", "scan", "chromatic"], "scan_band"),
        ("scramble-reveal",
         "Строка собирается из детерминированного шума — scramble-reveal",
         [0.8, 4.0],
         {"scramble_reveal": True, "accent": "green", "style": "terminal",
          "exit": "none"},
         ["text", "kinetic", "scramble", "reveal"], "scramble_reveal"),
        ("shared-axis-z",
         "Слова набухают по оси Z со стаггером — shared-axis-z",
         [0.8, 2.4],
         {"shared_axis_z": True, "direction": "in", "depth": "standard",
          "tone": "ink"},
         ["text", "kinetic", "scale"], "shared_axis_z"),
        ("code-3d-extrude",
         "Код на скошенной плите, посадка из глубины — code-3d-extrude",
         [1.5, 8.0],
         {"code_3d_extrude": True},
         ["code", "code-animation", "3d", "developer"], "code_3d_extrude"),
        ("code-diff",
         "Правка как цветной diff: минус схлопывается, плюс раскрывается — code-diff",
         [1.5, 6.0],
         {"code_diff": True},
         ["code", "code-animation", "diff", "developer"], "code_diff"),
        ("number-slam-card", "Цифра-удар на карточке — K3 promo", [0.8, 2.0],
         {"slam": True, "scale_from": 1.35, "uppercase": True},
         ["number", "impact", "card"], "number_slam", _EX_K3),
    ]),
    "lower-thirds": (11, [
        ("name-title", "Имя и должность", [1.5, 4.0],
         {"position": "bottom", "direction": "left"}, ["person"], "plaque"),
        ("accent-underline", "Имя и роль с акцентной чертой", [1.5, 4.8],
         {"accent_underline": True, "position": "bottom"},
         ["person", "lower-third", "overlay", "minimal"], "lt_accent_underline"),
        ("clean-bar", "Белая плашка с акцентной полоской", [1.5, 4.8],
         {"clean_bar": True, "position": "bottom"},
         ["person", "lower-third", "overlay", "podcast"], "lt_clean_bar"),
        ("dark-card", "Угольная карточка на светлом футаже", [1.5, 4.8],
         {"dark_card": True, "position": "bottom"},
         ["person", "lower-third", "overlay", "dark"], "lt_dark_card"),
        ("source-domain", "Домен источника", [1.5, 3.0],
         {"position": "bottom", "direction": "left", "icon": "link"}, ["source"], "plaque"),
        ("metric-badge", "Значение метрики", [1.5, 3.0],
         {"position": "top", "direction": "up", "mono": True}, ["metric"], "plaque"),
        ("note-pin", "Короткая ремарка", [1.5, 3.0],
         {"position": "middle", "direction": "right"}, ["note"], "plaque"),
        ("warning-strip", "Предупреждающая полоса", [1.5, 3.0],
         {"position": "top", "accent": True}, ["warning"], "plaque"),
        ("progress-step", "Шаг N из M", [1.5, 3.0],
         {"position": "top", "mono": True}, ["progress"], "plaque"),
        ("tag-chips", "Ряд тегов", [1.5, 3.0],
         {"position": "bottom", "chips": True}, ["tags"], "plaque"),
        ("timestamp-marker", "Отметка времени", [1.5, 2.5],
         {"position": "top", "mono": True}, ["time"], "plaque"),
    ]),
    "frames-cards": (7, [
        ("article-card", "Карточка статьи", [1.5, 4.0], {"template": "browser"},
         ["source", "article"], "source_card"),
        ("arxiv-card", "Карточка arXiv", [1.5, 4.0], {"template": "arxiv_card"},
         ["source", "science"], "paper_reveal"),
        ("patent-card", "Карточка патента", [1.5, 4.0], {"template": "patent_card"},
         ["source", "patent"], "source_card"),
        ("profile-card", "Карточка персоны", [1.5, 3.5], {"template": "notepad"},
         ["person"], "source_card"),
        ("product-card", "Карточка продукта", [1.5, 3.5], {"template": "browser"},
         ["product"], "source_card"),
        ("chart-card", "Карточка с графиком", [1.5, 4.0], {"template": "notepad",
         "chart": True}, ["data"], "source_card"),
        ("paper-reveal", "Строки статьи проявляются, одна вспыхивает", [1.5, 4.0],
         {"template": "arxiv_card"}, ["source", "science", "reveal"],
         "paper_reveal", _EX_PR),
    ]),
    "browser-ui": (8, [
        ("browser-scroll", "Скролл статьи с подсветкой строки", [2.0, 4.5],
         {"template": "browser", "scroll": True, "highlight": True},
         ["ui", "source"], "article_scroll"),
        ("google-typing", "Печать в поисковой строке", [1.5, 3.5],
         {"template": "search", "typing": True}, ["ui", "typing"], "source_card"),
        ("chat-ai-typing", "Запрос в нейросеть с курсором", [1.5, 3.5],
         {"template": "chat_ai", "typing": True}, ["ui", "ai"], "chat_thread"),
        ("notepad-typing", "Печать в блокноте", [1.5, 3.5],
         {"template": "notepad", "typing": True}, ["ui", "typing"], "source_card"),
        ("terminal-lines", "Строки терминала", [1.5, 3.5],
         {"template": "notepad", "mono": True}, ["ui", "code"], "source_card"),
        ("phone-notification", "Уведомление на телефоне", [1.2, 2.5],
         {"template": "notepad", "compact": True}, ["ui", "notification"], "plaque"),
        ("chat-thread", "Окно чата: запрос слева, ответ справа", [1.5, 4.0],
         {"template": "chat_ai"}, ["ui", "ai", "chat"], "chat_thread", _EX_SPACEX),
        ("article-highlight", "Статья в браузере со скроллом и вырезом цитаты",
         [2.0, 4.5], {"template": "browser", "scroll": True, "highlight": True},
         ["ui", "source", "highlight"], "article_scroll", _EX_WEBSITE),
    ]),
    "transitions": (13, [
        ("cut", "Прямая склейка — база ≥70 %", [0.0, 0.0], {}, ["cut", "base"], "cut"),
        ("whip-pan-l", "Резкий пан влево", [0.16, 0.28], {"direction": -1, "blur": 24},
         ["dynamic", "pan"], "whip_pan"),
        ("whip-pan-r", "Резкий пан вправо", [0.16, 0.28], {"direction": 1, "blur": 24},
         ["dynamic", "pan"], "whip_pan"),
        ("zoom-punch-in", "Удар зумом внутрь", [0.16, 0.26], {"from_scale": 1.35},
         ["dynamic", "zoom"], "zoom_punch"),
        ("zoom-punch-out", "Удар зумом наружу", [0.16, 0.26], {"from_scale": 0.72},
         ["dynamic", "zoom"], "zoom_punch"),
        ("mask-wipe-circle", "Круговая маска", [0.2, 0.32], {"shape": "circle"},
         ["dynamic", "mask"], "mask_wipe"),
        ("mask-wipe-diagonal", "Диагональная маска", [0.2, 0.32], {"shape": "diagonal"},
         ["dynamic", "mask"], "mask_wipe"),
        ("light-sweep", "Световой блик поперёк кадра", [0.24, 0.36], {},
         ["dynamic", "light"], "light_sweep"),
        ("glitch-short", "Короткий глитч", [0.16, 0.26], {"bars": 7},
         ["dynamic", "glitch"], "glitch"),
        ("paper-slide", "Сдвиг «листом»", [0.2, 0.3], {"direction": 1},
         ["dynamic", "slide"], "paper_slide"),
        ("blur-dip", "Провал в размытие", [0.18, 0.28], {"max_blur": 18},
         ["dynamic", "blur"], "blur_dip"),
        ("white-flash", "Вспышка в белое", [0.14, 0.24], {"peak": 0.85},
         ["dynamic", "flash"], "white_flash"),
        ("zoom-through", "Наезд в деталь на склейке — жест SpaceX", [0.18, 0.30],
         {"from_scale": 1.22}, ["dynamic", "zoom"], "zoom_through", _EX_SPACEX),
    ]),
    "avatar-entry": (6, [
        ("hero-zoom-in", "Вход зумом на аватар", [0.2, 0.4], {"from_scale": 1.18},
         ["avatar", "entry"], "zoom_punch"),
        ("slide-from-bottom", "Выезд снизу", [0.22, 0.36], {"axis": "y", "direction": 1},
         ["avatar", "entry"], "paper_slide"),
        ("circle-mask-grow", "Круг раскрывается", [0.24, 0.4], {"shape": "circle"},
         ["avatar", "entry"], "mask_wipe"),
        ("split-slide-up", "Половина кадра уезжает вверх", [0.24, 0.4],
         {"axis": "y", "direction": -1}, ["avatar", "entry", "split"], "paper_slide"),
        ("flash-cut-in", "Вход через вспышку", [0.14, 0.24], {"peak": 0.7},
         ["avatar", "entry", "flash"], "white_flash"),
        ("scale-pop", "Пружинистое появление", [0.2, 0.34], {"overshoot": 0.08},
         ["avatar", "entry"], "zoom_punch"),
    ]),
    "kenburns": (10, [
        ("zoom-in-center", "Наезд в центр", [2.5, 5.0], {"zoom": [1.0, 1.12]},
         ["kenburns", "zoom"], "kenburns"),
        ("zoom-in-subject", "Наезд на субъект", [2.5, 5.0],
         {"zoom": [1.0, 1.15], "anchor": "subject"}, ["kenburns", "zoom"], "kenburns"),
        ("zoom-out-reveal", "Отъезд с раскрытием", [2.5, 5.0], {"zoom": [1.15, 1.0]},
         ["kenburns", "zoom"], "kenburns"),
        ("pan-left", "Панорама влево", [2.5, 5.0], {"zoom": [1.1, 1.1], "pan": [-1, 0]},
         ["kenburns", "pan"], "kenburns"),
        ("pan-right", "Панорама вправо", [2.5, 5.0], {"zoom": [1.1, 1.1], "pan": [1, 0]},
         ["kenburns", "pan"], "kenburns"),
        ("pan-up", "Панорама вверх", [2.5, 5.0], {"zoom": [1.1, 1.1], "pan": [0, -1]},
         ["kenburns", "pan"], "kenburns"),
        ("pan-down", "Панорама вниз", [2.5, 5.0], {"zoom": [1.1, 1.1], "pan": [0, 1]},
         ["kenburns", "pan"], "kenburns"),
        ("diag-drift", "Диагональный дрейф", [2.5, 5.0],
         {"zoom": [1.05, 1.14], "pan": [0.7, 0.7]}, ["kenburns", "drift"], "kenburns"),
        ("push-tilt", "Наезд с наклоном", [2.5, 5.0],
         {"zoom": [1.0, 1.13], "pan": [0, -0.5]}, ["kenburns", "push"], "kenburns"),
        ("micro-parallax", "Микро-параллакс слоёв", [2.5, 5.0],
         {"zoom": [1.02, 1.08], "layers": 2}, ["kenburns", "parallax"], "kenburns"),
    ]),
    "parallax": (4, [
        ("text-behind-object", "Текст за объектом переднего плана", [1.5, 3.5],
         {"layers": 2, "shift_pct": 0.04}, ["parallax", "text"], "parallax"),
        ("two-layer-drift", "Два слоя расходятся", [1.5, 3.5],
         {"layers": 2, "shift_pct": 0.03}, ["parallax"], "parallax"),
        ("depth-push", "Наезд с разной скоростью слоёв", [1.5, 3.5],
         {"layers": 2, "shift_pct": 0.05}, ["parallax", "push"], "parallax"),
        ("foreground-sweep", "Передний план проходит по кадру", [1.0, 2.5],
         {"layers": 2, "shift_pct": 0.05}, ["parallax", "sweep"], "parallax"),
    ]),
    "data-viz": (7, [
        ("bar-race-mini", "Мини-гонка столбиков", [2.0, 4.0], {"bars": 4},
         ["data", "bars"], "dataviz"),
        ("line-rise", "Линия идёт вверх", [1.5, 3.5], {"points": 8},
         ["data", "line"], "dataviz"),
        ("counter-roll", "Цифра прокручивается", [1.0, 2.5], {"digits": 6},
         ["data", "number"], "dataviz"),
        ("donut-fill", "Кольцо заполняется", [1.5, 3.0], {"percent": True},
         ["data", "donut"], "dataviz"),
        ("timeline-dots", "Точки на таймлайне", [1.5, 3.5], {"dots": 5},
         ["data", "timeline"], "dataviz"),
        ("compare-bars", "Сравнение двух столбиков", [1.5, 3.0], {"bars": 2},
         ["data", "compare"], "dataviz"),
        ("stat-countup-card", "Набегающая метрика на карточке", [1.2, 3.0],
         {"steps": 12}, ["data", "number", "card"], "dataviz", _EX_SPACEX),
    ]),
    "outro-cta": (6, [
        ("subscribe-pulse", "Пульсирующая кнопка подписки", [1.5, 2.5],
         {"pulse_hz": 1.6}, ["cta", "subscribe"], "cta_button"),
        ("question-card", "Вопрос в карточке", [1.5, 2.5], {"card": True},
         ["cta", "question"], "plaque"),
        ("loop-back", "Замыкание на первый кадр", [1.0, 2.0], {"loop": True},
         ["cta", "loop"], "footage"),
        ("next-teaser", "Тизер следующего ролика", [1.5, 2.5], {"teaser": True},
         ["cta", "teaser"], "plaque"),
        ("logo-stamp", "Штамп логотипа", [1.0, 2.0], {"stamp": True},
         ["cta", "brand"], "fullscreen_text"),
        ("logo-brand-close", "Вордмарк каскадом и точка бренда — logo-brand-close",
         [1.5, 4.5],
         {"logo_close": True, "exit": "none", "wordmark": "РЕДШИФТ",
          "tagline": "Пиши код. Шли на орбиту.", "url": "redshift.shorts"},
         ["cta", "brand", "logo", "end-card"], "logo_brand_close"),
    ]),
    # Приёмы вокруг ведущего. Категория заведена по референсам заказчика:
    # ведущий за столом, а кадр вокруг него живёт — картинка за спиной, текст
    # над головой, панель сбоку, выбивка. Тег ``alpha`` помечает приёмы, для
    # которых аватар обязан прийти с прозрачным фоном: они рисуются ПОД ним, и
    # без альфы зритель их не увидит.
    "hero-devices": (13, [
        ("plate-behind-back", "Кадр появляется за спиной ведущего", [1.4, 4.0],
         {"top": 300}, ["hero", "avatar", "alpha", "footage"], "hero-plate"),
        ("headline-over-head", "Заголовок вырастает над головой", [1.2, 3.4],
         {"top": 190}, ["hero", "avatar", "alpha", "text"], "hero-headline"),
        # Тот же рендерер, но крупнее и ниже: голова перекрывает нижнюю часть
        # слова, и оно читается как надпись позади ведущего, а не над ним.
        ("headline-behind-head", "Крупный заголовок из-за головы", [1.2, 3.4],
         {"top": 300, "size": 232}, ["hero", "avatar", "alpha", "text"],
         "hero-headline"),
        ("burst-behind-head", "Лучи расходятся из-за головы", [1.0, 3.0],
         {"rays": 9, "spread_deg": 150, "center_y": 560},
         ["hero", "avatar", "alpha"], "hero-burst"),
        ("split-panel-right", "Кадр делится: ведущий слева, слово справа", [1.4, 4.0],
         {"subject_shift": -210, "subject_zoom": 1.14},
         ["hero", "avatar", "split", "text"], "hero-split"),
        ("knockout-negative", "Негатив: слово прорезано в заливке", [1.2, 3.0],
         {"size": 300, "margin": 60}, ["hero", "avatar", "text"], "hero-knockout"),
        ("text-column-left", "Строки колонкой слева от ведущего", [1.6, 4.5],
         {"top": 700}, ["hero", "avatar", "text", "lines"], "hero-text-column"),
        ("bubble-card", "Ведущий в круге, реплика карточкой под ним", [1.6, 4.5],
         {"accent_last": True}, ["hero", "avatar", "text", "lines"],
         "hero-bubble-card"),
        ("brand-pill", "Пилюля с логотипом бренда у плеча", [1.0, 3.0],
         {"top": 1180}, ["hero", "avatar", "brand"], "hero-brand-pill"),
        ("card-stack-top", "Карточка с заголовком сверху, ведущий снизу",
         [1.6, 4.5], {"height": 860}, ["hero", "avatar", "text", "footage"],
         "hero-card-stack"),
        ("phone-mock", "Экран приложения поверх расфокуса", [1.8, 4.5],
         {}, ["hero", "avatar", "text", "lines", "ui"], "hero-phone-mock"),
        ("type-slab", "Плита типа слева от ведущего — Srinika × Mercury",
         [1.4, 4.0], {"top": 420}, ["hero", "avatar", "text", "lines"],
         "hero-type-slab", _EX_SRINIKA),
        ("footage-plate-pop", "Футаж в рамке въезжает поверх кадра", [1.4, 4.0],
         {"width": 920, "height": 580, "top": 210},
         ["hero", "avatar", "footage"], "hero-plate-pop", _EX_STRIPE),
    ]),
}


def main() -> int:
    manifest: dict = {
        "_comment": ("Каталог шаблонов §15. Генерируется tools/gen_templates.py — "
                     "правьте генератор, а не этот файл. Поле last_used_in обновляет "
                     "P11 после каждого прогона и служит основой ротации §15.12."),
        "version": 2,
        "counts": {},
        "rotation_rules": {
            "avoid_if_used_in_last_n_videos_same_role": 3,
            "ab_min_difference": 3,
            "prefer_least_recently_used": True,
        },
        "templates": [],
    }

    # last_used_in копится прогонами P11 и в генераторе не описан. Перезаписать
    # манифест «с нуля» значит обнулить ротацию §15.12 и заставить каталог
    # заново сойтись на первых попавшихся шаблонах.
    history: dict[str, list[str]] = {}
    added_on: dict[str, str] = {}
    existing = TEMPLATES / "manifest.json"
    if existing.exists():
        for entry in json.loads(existing.read_text(encoding="utf-8"))["templates"]:
            history[entry["id"]] = entry.get("last_used_in", [])
            added_on[entry["id"]] = entry.get("added", "2026-08-18")

    total = 0
    for category, (expected, items) in CATALOG.items():
        assert len(items) == expected, f"{category}: {len(items)} != {expected} из §15"
        (TEMPLATES / category).mkdir(parents=True, exist_ok=True)
        for item in items:
            tid, title, duration, params, tags, renderer, *rest = item
            example_video = rest[0] if rest else ""
            entry = {
                "id": f"{category}/{tid}",
                "name": tid,
                "category": category,
                "title": title,
                "duration_range": duration,
                "params": params,
                "tags": tags,
                "renderer": renderer,
                "last_used_in": history.get(f"{category}/{tid}", []),
                "added": added_on.get(f"{category}/{tid}") or "2026-09-03",
            }
            if example_video:
                entry["example_video"] = example_video
            manifest["templates"].append(entry)
            preset_path = TEMPLATES / category / f"{tid}.json"
            preset_path.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            total += 1
        manifest["counts"][category] = expected

    manifest["counts"]["_total"] = total
    (TEMPLATES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"шаблонов сгенерировано: {total}")
    for category, count in manifest["counts"].items():
        if not category.startswith("_"):
            print(f"  {category}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

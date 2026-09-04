"""edit-план → HTML-композиция HyperFrames.

Контракт движка (skill ``hyperframes-core``) задаёт несколько правил, каждое из
которых ломает рендер молча, поэтому они вынесены сюда явно:

* корень несёт ``data-start="0"``, размеры и ``data-duration``;
* визуальные клипы с ``class="clip"`` — **прямые дети** корня, обёртка вокруг
  клипа отменяет его тайминг, и элемент висит весь ролик;
* ``data-track-index`` управляет пересечением во времени, а не слоями: два
  клипа на одном треке не имеют права перекрываться, а порядок наложения
  задаётся CSS ``z-index``;
* каждый ``id`` уникален по всей странице — у ``<video>``/``<img>`` дубль id
  приводит к пустому кадру, потому что продюсер инжектит кадры по
  ``getElementById``;
* ровно один ``gsap.timeline({paused:true})`` в ``window.__timelines``;
* заливка кадра — на full-bleed ребёнке, а не на корне.

Раскладка треков. Шоты чередуются между двумя треками: соседние шоты стыкуются
встык, а окно видимости клипа включает оба конца, поэтому на одном треке они
пересеклись бы ровно в точке стыка. Чередование заодно оставляет место
переходам с наложением.
"""

from __future__ import annotations

import html
from typing import Any

from ..text_rules import subtitle_word
from .canvas_fx import canvas_js, canvas_node, canvas_tween
from .templates import brand_marks_node
from ...backdrop import SCENES, pick_scene, tone as scene_tone
from .captions import (
    TRACK_CAPTION_ACCENT_EVEN, TRACK_CAPTION_ACCENT_ODD,
    TRACK_CAPTION_EVEN, TRACK_CAPTION_ODD,
    build_blend_difference, build_camera_follow, build_clip_wipe,
    build_gradient_fill, resolve_caption,
)
from .templates import (
    OVERLAYS, TemplateCtx, enter_and_drift, entrance_tweens, fit_size,
    fit_size as fit_text_size, render_dataviz, render_fullscreen, render_hero,
    render_motion, render_overlay, render_transition, text_width,
)

TRACK_STAGE = 0
TRACK_SHOT_EVEN = 1
TRACK_SHOT_ODD = 2
TRACK_AVATAR = 3
TRACK_BEHIND_HEAD = 4
TRACK_OVERLAY = 5      # и следующие, если плашки пересекаются во времени
TRACK_TRANSITION = 11
# Фразы camera-follow стыкуются встык — два трека, как шоты. Не 13/14:
# там герой. 18/19 не пересекаются со звуком (20).
# TRACK_SUBTITLE — алиас на чётный caption-трек для старых тестов.
TRACK_SUBTITLE = TRACK_CAPTION_EVEN
# Приёмы вокруг ведущего чередуют треки по той же причине, что и шоты: соседние
# кадры стыкуются встык, а окно видимости клипа включает оба конца.
TRACK_HERO_EVEN = 13
TRACK_HERO_ODD = 14
# Фон под полноэкранным текстом. Свой трек, а не трек шота: сам текст уже
# занимает трек шота, а видео внутри клипа с таймингом застывает первым кадром
# (lint: video_nested_in_timed_element) — значит, фон обязан быть отдельным
# клипом, и класть его на соседний трек нельзя, там встык стоят соседние шоты.
TRACK_FS_BG = 15
# Графика брендбука: свой трек, иначе она встаёт на трек шота и пересекается
# с ним по времени — движок считает это конфликтом клипов.
TRACK_MARKS = 16
# Фразы camera-follow стыкуются встык — два трека, как шоты. Не 13/14:
# там герой. 18/19 не пересекаются со звуком (20).
assert TRACK_CAPTION_EVEN == 18 and TRACK_CAPTION_ODD == 19
TRACK_AUDIO = 20
assert TRACK_CAPTION_ACCENT_EVEN == 21 and TRACK_CAPTION_ACCENT_ODD == 22

# Слово субтитра короче этого мигает, а не читается.
MIN_WORD_SEC = 0.05

COMPOSITION_ID = "redshift"


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _num(value: float) -> str:
    """Секунды в атрибут: три знака хватает для кадра на 30 fps."""
    return f"{float(value):.3f}".rstrip("0").rstrip(".") or "0"


def _timing(start: float, end: float, track: int) -> str:
    """Атрибуты тайминга клипа. Границы округляются один раз — до вычитания.

    Движок читает начало и длительность, а конец складывает сам. Пока начало и
    длительность округлялись порознь, сумма могла перескочить настоящий конец:
    начало 49.3568 печаталось как 49.357, длительность 0.4996 — как 0.5, и клип
    заканчивался в 49.857 при следующем клипе с 49.856. Миллисекунда наезда, и
    lint валит рендер целиком — на 0047 это случилось на 134 словах субтитра
    после 804 секунд работы конвейера.

    Округление к сетке монотонно: если конец не позже начала соседа, то и
    округлённый конец не позже. Поэтому считаем длительность как разность уже
    округлённых границ — тогда напечатанный конец совпадает с напечатанным
    началом соседа и наезд невозможен в принципе, а не по везению. Пять
    предыдущих роликов прошли именно по везению: перекрытий не было ни одного,
    но и защиты от них тоже.
    """
    head = round(float(start), 3)
    return (f'data-start="{_num(head)}" '
            f'data-duration="{_num(round(float(end), 3) - head)}" '
            f'data-track-index="{track}"')


def _mark_phrase(text: str, phrase: str) -> str:
    """Отметить в тексте ключевую строку источника маркером (§5.5).

    Подсветка была объявлена в плане, но в кадре её не было: слой ``highlight``
    рисовать нечем — у строки внутри абзаца нет координат снаружи. Маркер
    поэтому лежит в самом тексте.

    Полосой под текстом это не сделать: фраза переносится, а абсолютная полоса
    внутри многострочного inline-элемента считается по одной коробке и в кадре
    осталась красной чёрточкой на месте переноса — проверено кадром. Маркер
    поэтому красит фон самого фрагмента, а ``box-decoration-break: clone``
    повторяет его на каждой строке.

    Совпадение ищется без учёта регистра и по первому вхождению: строка в
    сценарии выписана из статьи и в ней же и стоит.
    """
    text = str(text or "")
    phrase = str(phrase or "").strip()
    if not phrase:
        return _esc(text)
    at = text.lower().find(phrase.lower())
    if at < 0:
        return _esc(text)
    head, hit, tail = text[:at], text[at:at + len(phrase)], text[at + len(phrase):]
    return f'{_esc(head)}<span class="hl">{_esc(hit)}</span>{_esc(tail)}'


def _lay_out_tracks(items: list[dict[str, Any]], first_track: int) -> list[int]:
    """Разложить пересекающиеся во времени элементы по свободным трекам."""
    ends: list[float] = []
    tracks: list[int] = []
    for item in items:
        # По округлённым границам: раскладка обязана судить о пересечении по
        # тем же числам, которые прочитает движок, а не по исходным.
        start, end = round(float(item["start"]), 3), round(float(item["end"]), 3)
        for track, busy_until in enumerate(ends):
            if start >= busy_until:
                ends[track] = end
                tracks.append(first_track + track)
                break
        else:
            ends.append(end)
            tracks.append(first_track + len(ends) - 1)
    return tracks


class CompositionBuilder:
    """Собирает index.html по edit-плану.

    ``assets`` — соответствие исходного пути имени файла внутри проекта:
    HyperFrames резолвит медиа относительно каталога проекта, а пути из
    ``work/`` за его пределами.
    """

    def __init__(self, plan: dict[str, Any], brandbook: dict[str, Any],
                 assets: dict[str, str]) -> None:
        self.plan = plan
        self.brandbook = brandbook
        self.assets = assets
        self.width, self.height = plan["resolution"]
        self.duration = float(plan["duration_sec"])
        self.fps = int(plan["fps"])
        self.tweens: list[str] = []
        # Какие эффекты холста понадобились: их реестр пишется в страницу
        # только когда он и правда нужен.
        self.canvas_used: set[str] = set()
        # Сколько раз графика брендбука уже вышла в кадр.
        self.marks_placed = 0
        self.stats = {"shots": 0, "overlay_draws": 0, "subtitle_words": 0,
                      "avatar_clips": 0}

    # --- вспомогательное ------------------------------------------------
    def _asset(self, path: str | None) -> str | None:
        if not path:
            return None
        return self.assets.get(str(path))

    def _ease(self, name: str) -> str:
        """Кривая брендбука → запись, понятная GSAP."""
        curve = self.brandbook.get("easing", {}).get(name)
        if not curve:
            return "power2.out"
        return f"cubic-bezier({curve[0]},{curve[1]},{curve[2]},{curve[3]})"

    @property
    def scene(self) -> str:
        """Сцена фона: из плана, иначе — по теме ролика.

        Фон держится весь ролик и посреди него не меняется: это фон, а не
        мигание. Поэтому сцена одна на композицию, а не на шот.
        """
        chosen = str((self.plan.get("backdrop") or {}).get("scene") or "")
        if chosen in SCENES:
            return chosen
        return pick_scene(self.plan.get("title") or "",
                          " ".join(str(b.get("text") or "")
                                   for b in self.plan.get("_blocks", [])))

    def _stage_class(self) -> str:
        return "stage-dark" if scene_tone(self.scene) == "dark" else "stage-light"

    def _plate(self) -> str:
        """Разметка плиты сцены. Пусто — сцена рисуется одними градиентами.

        Путь берётся из набора медиа проекта: в плане лежит путь на диске, а в
        разметку обязан уйти путь внутри проекта.
        """
        plate = str((self.plan.get("backdrop") or {}).get("plate") or "")
        src = self.assets.get(plate) if plate else ""
        # Слой, а не <img>: картинка фона одна на весь ролик и повторяется в
        # каждом шоте с альфой. Четыре одинаковых <img> продюсер считает
        # четырьмя источниками с совпадающим временем и предупреждает о риске
        # перепутать их при инжекте кадров. Фоном в стиле того же не случается —
        # это не медиа плана, а оформление слоя.
        return (f'<div class="vfx-plate" style="background-image:url(\'{src}\')">'
                f'</div>') if src else ""

    # --- шоты -----------------------------------------------------------
    def _alpha_slots(self) -> set[int]:
        """Слоты, где аватар лёг альфой и под ним нужен собственный фон.

        Фото-аватар HeyGen возвращает кадр с вшитым фоном и без альфы. Тогда
        собирать под ним градиент бессмысленно: он всё равно перекрыт. Слои
        имеют смысл только там, где альфа реально есть.
        """
        return {idx for seg in self.plan.get("avatar", [])
                if seg.get("has_alpha")
                for idx in seg.get("slot_indices", [])}

    def _avatar_node_by_slot(self) -> dict[int, str]:
        """Слот шота → id клипа аватара, который его занимает.

        Переход в режиме A обязан двигать самого ведущего, а не подложку: она
        либо перекрыта им, либо вовсе не рисуется. Без этой карты твин целился
        бы в ``#shot-NN``, которого для непрозрачного аватара просто нет, и
        переход пропадал бы молча.
        """
        out: dict[int, str] = {}
        for seg in self.plan.get("avatar", []):
            node_id = f"avatar-{int(seg['index']):02d}"
            for slot in seg.get("slot_indices", []):
                out[int(slot)] = node_id
        return out

    # Какой холст живёт под какой сценой. Комната остаётся без него: там за
    # ведущим студия, и звёзды в ней читались бы декорацией.
    SCENE_FX: dict[str, str] = {
        "space": "starfield",
        "grid": "scan-grid",
        "horizon": "orbit",
        "depth": "dust",
    }

    def _scene_backdrop(self, node_id: str, timing: str, *,
                        start: float | None = None,
                        duration: float | None = None) -> str:
        """Запасной фон слота: сцена ролика вместо дыры в кадре.

        Дыра в кадре не чёрная, а светлая: ``.stage-bg`` заливает кадр
        ``--color-bg-light`` (#F7F5F3), и слот без медиа показывает именно её.
        На пересборке 0047 так вышло три кадра подряд — белое полотно с
        одиноким субтитром посреди тёмного ролика («ГРАНИТ», «ТУНДРЫ»).

        Слот остаётся пустым по законной причине: генерация вывела бы долю
        AI-футажа за 35 %, и P9 честно отказался. Отказ от генерации не повод
        показывать зрителю пустой лист — сцена ролика по теме, она тёмная и
        она уже собрана.
        """
        # Поверх градиента сцены — холст: звёздное поле, орбиты, пыль или
        # сетка. Это рисование, а не прямоугольники: CSS даёт фиксированный
        # узор, который виден повтором, а линию по кривой не проводит вовсе.
        effect = self.SCENE_FX.get(self.scene, "")
        canvas = ""
        if effect and start is not None and duration is not None and duration > 0:
            fx_id = f"{node_id}-fx"
            canvas = canvas_node(fx_id, timing="", css=f"fx-{effect}",
                                 width=self.width, height=self.height)
            # Зерно от места на ленте: два фона одного ролика не повторяют
            # друг друга, но каждый повторяем сам по себе.
            seed = int(round(float(start) * 1000)) % 9973 + 7
            self.tweens.append(canvas_tween(
                fx_id, effect, start=float(start), duration=float(duration),
                params={"seed": seed}))
            self.canvas_used.add(effect)
        return (f'<div id="{node_id}" class="clip shot-bg" {timing}>'
                f'<div class="vfx scene-{self.scene}">{self._plate()}{canvas}</div></div>')

    def _shot_nodes(self) -> list[str]:
        nodes: list[str] = []
        alpha_slots = self._alpha_slots()
        avatar_nodes = self._avatar_node_by_slot()

        for shot in self.plan["shots"]:
            index = int(shot["index"])
            track = TRACK_SHOT_EVEN if index % 2 == 0 else TRACK_SHOT_ODD
            start, duration = float(shot["start"]), float(shot["duration"])
            kind = shot.get("kind")
            node_id = f"shot-{index:02d}"
            timing = _timing(start, start + duration, track)
            # Цель перехода: для аватар-слотов — сам аватар, иначе — шот.
            target = avatar_nodes.get(index, node_id)
            # Переход и Ken Burns тянут одни и те же свойства одного элемента.
            # Наложение запрещено контрактом: порядок перезаписи в GSAP зависит
            # от очерёдности и может переключиться между рендерами. Поэтому
            # медленный проезд начинается там, где кончается вход.
            tr_sec = self._transition_duration(shot)

            if kind == "fullscreen_text":
                # Фон под полноэкранным текстом кладётся всегда: без него
                # фраза встаёт на сплошную заливку, и на 0047 «180 ГРАДУСОВ»
                # шло белыми буквами по белому листу посреди тёмного ролика.
                # Материала нет — берётся сцена ролика, та же, что за ведущим.
                src = self._asset(shot.get("file"))
                if src:
                    nodes.append(self._media_node(
                        f"{node_id}-bg", src,
                        _timing(start, start + duration, TRACK_FS_BG), css="fs-bg"))
                else:
                    nodes.append(self._scene_backdrop(
                        f"{node_id}-bg",
                        _timing(start, start + duration, TRACK_FS_BG),
                        start=start, duration=duration))
                # Сам кадр рисует приём шаблона: renderer и params, а не одна
                # заготовка на все девятнадцать `text-fullscreen`.
                piece = self._fullscreen_piece(node_id, shot, start, duration,
                                               track, tr_sec)
                nodes.extend(piece.nodes)
                self.tweens.extend(piece.tweens)
                # Графика брендбука (раздел 06) — на карточные моменты, и не
                # больше потолка: рамка в каждом кадре перестаёт читаться
                # приёмом и становится шумом.
                marks = self._brand_marks(node_id, start, duration, TRACK_MARKS)
                if marks:
                    nodes.append(marks)
            elif index in alpha_slots:
                # Режим A с альфой: фон собирается в браузере, а не берётся
                # сплющенным кадром — в этом и смысл переезда на HyperFrames.
                # Prefer per-shot B-roll (`bg_file`) so the plate behind the
                # talking head actually changes; static scene plate is fallback.
                bg_src = self._asset(shot.get("bg_file"))
                if bg_src:
                    nodes.append(self._media_node(
                        f"{node_id}-bg", bg_src, timing, css="shot avatar-bg"))
                else:
                    nodes.append(self._scene_backdrop(node_id, timing,
                                                      start=start, duration=duration))
            elif index in avatar_nodes or kind == "avatar":
                # Аватар без альфы приходит со своим фоном и занимает кадр
                # целиком: подкладывать под него нечего. Но переход ему нужен.
                pass
            elif kind == "meme":
                src = self._asset(shot.get("file"))
                if src:
                    nodes.append(self._media_node(node_id, src, timing, css="meme"))
                else:
                    nodes.append(self._scene_backdrop(node_id, timing,
                                                      start=start, duration=duration))
            else:
                src = self._asset(shot.get("file"))
                if src:
                    nodes.append(self._media_node(node_id, src, timing, css="shot",
                                                  media_start=shot.get("avatar_offset_sec")))
                    self._add_kenburns(node_id, shot, start + tr_sec,
                                       max(0.1, duration - tr_sec))
                else:
                    nodes.append(self._scene_backdrop(node_id, timing,
                                                      start=start, duration=duration))
            nodes += self._add_transition(target, shot, start)
            self.stats["shots"] += 1
        return nodes

    def _media_node(self, node_id: str, src: str, timing: str, *, css: str,
                    media_start: float | None = None) -> str:
        # Видео обязано быть muted+playsinline: звук ролика идёт отдельной
        # дорожкой микса, иначе он сложится дважды.
        offset = ""
        if media_start:
            offset = f' data-media-start="{_num(media_start)}"'
        return (f'<video id="{node_id}" class="{css}" src="{_esc(src)}" '
                f'{timing}{offset} muted playsinline></video>')

    def _brand_marks(self, node_id: str, start: float, duration: float,
                     track: int) -> str:
        """Технические уголки брендбука поверх карточного кадра."""
        spec = self.brandbook.get("brand_marks") or {}
        limit = int(spec.get("per_video_max", 0))
        if limit <= 0 or self.marks_placed >= limit:
            return ""
        self.marks_placed += 1
        mark_id = f"{node_id}-marks"
        svg = brand_marks_node(mark_id, spec, self.brandbook["safe_zones"]["work_area"],
                               width=self.width, height=self.height)
        enter = float(spec.get("enter_ms", 260)) / 1000.0
        # Уголки приезжают из-за края рабочей зоны, а не проявляются: словарь
        # появления §H7 — всё приближается, ничего не включается.
        self.tweens.append(
            f'tl.fromTo("#{mark_id}",{{scale:1.06}},{{scale:1,'
            f'duration:{enter:.3f},ease:"power2.out"}},{_num(start)});')
        timing = _timing(start, start + duration, track)
        return f'<div class="clip" {timing}>{svg}</div>'

    def _fullscreen_piece(self, node_id: str, shot: dict[str, Any],
                          start: float, duration: float, track: int,
                          tr_sec: float):
        """Полноэкранный кадр читает renderer и params шаблона, не одну заготовку."""
        fs = self.brandbook["fullscreen_text"]
        safe_x = int(self.brandbook["safe_zones"]["work_area"]["x_min"])
        available = self.width - 2 * safe_x
        params = dict(shot.get("params") or {})
        params.update({
            "content": shot.get("content") or "",
            "accent_word": shot.get("accent_word") or "",
            "invert": bool(shot.get("invert")),
            "renderer": shot.get("renderer") or params.get("renderer") or "",
            "available_px": available,
            "enter_delay": tr_sec,
        })
        if "size_px" not in params:
            params["size_px"] = int(fs["size_px"][1])
        piece = render_fullscreen(TemplateCtx(
            index=int(shot["index"]), start=start, duration=duration,
            target=node_id, track=track, params=params))
        # Под кадром всегда лежит материал или сцена, поэтому сплошная заливка
        # `.fullscreen-text` обязана уступить место затемнению: класс
        # `over-media` гасит фон и оставляет скрим. Ставится здесь, а не в
        # каждом из десяти рендереров, — иначе первый же новый приём про него
        # забудет и вернёт белую плиту.
        if piece.nodes:
            piece.nodes[0] = piece.nodes[0].replace(
                'class="clip fullscreen-text', 'class="clip fullscreen-text over-media', 1)
        return piece


    def _add_kenburns(self, node_id: str, shot: dict[str, Any],
                      start: float, duration: float) -> None:
        kb = shot.get("kenburns")
        if not kb:
            return
        # fromTo, а не CSS-transform + tween: контракт запрещает задавать
        # стартовое значение в CSS, когда его же тянет GSAP.
        piece = render_motion("kenburns", TemplateCtx(
            index=int(shot["index"]), start=start, duration=duration,
            target=node_id, track=TRACK_SHOT_EVEN, params=dict(kb)))
        self.tweens.extend(piece.tweens)

    @staticmethod
    def _transition_duration(shot: dict[str, Any]) -> float:
        """Сколько длится вход кадра. Прямая склейка не занимает времени."""
        spec = shot.get("transition") or {}
        if str(spec.get("renderer") or "cut") == "cut":
            return 0.0
        return float(spec.get("duration") or 0.32)

    def _add_transition(self, node_id: str, shot: dict[str, Any],
                        start: float) -> list[str]:
        """Переход относится к началу шота: он показывает, как кадр входит."""
        spec = shot.get("transition") or {}
        renderer = str(spec.get("renderer") or "cut")
        if renderer == "cut":
            return []
        duration = float(spec.get("duration") or 0.32)
        piece = render_transition(renderer, TemplateCtx(
            index=int(shot["index"]), start=start, duration=duration,
            target=node_id, track=TRACK_TRANSITION,
            params=dict(spec.get("params") or {})))
        self.tweens.extend(piece.tweens)
        self.stats["transitions"] = self.stats.get("transitions", 0) + 1
        return piece.nodes

    # --- аватар ---------------------------------------------------------
    def _avatar_nodes(self) -> list[str]:
        nodes: list[str] = []
        for seg in self.plan.get("avatar", []):
            src = self._asset(seg.get("file"))
            if not src:
                continue
            index = int(seg["index"])
            node_id = f"avatar-{index:02d}"
            nodes.append(
                f'<video id="{node_id}" class="avatar" src="{_esc(src)}" '
                + _timing(float(seg["start"]),
                          float(seg["start"]) + float(seg["duration"]), TRACK_AVATAR)
                + ' muted playsinline></video>')
            # Опора для перемотки. Переходы и приёмы двигают сам клип ведущего,
            # и все их твины помечены `immediateRender:false`, чтобы начальное
            # состояние не уходило назад по ленте. Но перемотка назад через уже
            # отыгранный твин возвращает его в это самое начальное состояние, а
            # кадр по seek обязан совпадать с кадром по проигрыванию. Явная
            # установка в начале клипа делает исход одинаковым в обе стороны.
            self.tweens.append(
                f'tl.set("#{node_id}",{{scale:1,x:0,y:0}},'
                f'{_num(float(seg["start"]))});')
            self.stats["avatar_clips"] += 1
        return nodes

    def _behind_head_nodes(self) -> list[str]:
        """Слово за головой (§5.3) — под аватаром, поверх фона.

        Рисуется только там, где у аватара есть альфа. Иначе слово окажется за
        непрозрачным видео: рендер потратит на него кадры, а в ролике его не
        будет — брендбук и требует для §5.3 матовую маску.
        """
        nodes: list[str] = []
        alpha_slots = self._alpha_slots()
        by_block = {b["id"]: b for b in self.plan.get("_blocks", [])}
        for shot in self.plan["shots"]:
            if not shot.get("text_behind_head") or int(shot["index"]) not in alpha_slots:
                continue
            block = by_block.get(shot.get("block_id"), {})
            word = str(block.get("emphasis_word") or "").strip()
            if not word:
                continue
            index = int(shot["index"])
            node_id = f"behind-{index:02d}"
            nodes.append(
                f'<div id="{node_id}" class="clip behind-head"'
                f' style="font-size:{self._behind_head_size(word)}px" '
                + _timing(float(shot["start"]),
                          float(shot["start"]) + float(shot["duration"]),
                          TRACK_BEHIND_HEAD)
                + f'>{_esc(word)}</div>')
            # Слово за головой держится весь кадр, и без движения оно
            # превращается в надпись на обоях. Медленный наезд даёт ту самую
            # глубину: ведущий стоит, фон еле едет.
            self.tweens.extend(enter_and_drift(
                node_id and f"#{node_id}", float(shot["start"]),
                float(shot["duration"]), name="zoom-in"))
        return nodes

    def _behind_head_size(self, word: str) -> int:
        """Кегль слова за головой: наибольший, при котором слово влезает.

        Кегль стоял константой — верхней границей ``size_px`` из брендбука, —
        и слово шире кадра просто обрезалось краями. На 0047 «ДВЕНАДЦАТЬ» при
        260 px занимает 1498 px в кадре шириной 1080: зритель видел «ДВ…АДЦ».
        Обрезок читается как поломка, а не как приём: смысл слова за головой в
        том, что его читают.

        Поле по краям берётся из рабочей зоны брендбука (§3.2), а не выдумано.
        Слово при этом остаётся во всю ширину кадра, а не в рабочей зоне:
        оно фон, и заезжать под колонку интерфейса ему можно — за кромку кадра
        нельзя. Нижняя граница ``size_px`` тут пожелание, а не предел: слово,
        которому и её мало, лучше набрать мельче, чем обрезать.
        """
        spec = self.brandbook["text_behind_head"]
        margin = int(self.brandbook["safe_zones"]["work_area"]["x_min"])
        available = int(self.brandbook["canvas"]["width"]) - 2 * margin
        return fit_text_size(word.upper(), available, int(spec["size_px"][1]),
                             role=str(spec.get("font_role", "display")))

    # --- приёмы вокруг ведущего -----------------------------------------
    def _hero_nodes(self) -> list[str]:
        """Приёмы из референсов: картинка за спиной, заголовок над головой,
        лучи, сплит с панелью, выбивка.

        Приём начинается там, где кончается вход кадра. Сплит тянет ``x`` и
        ``scale`` самого аватара — те же свойства, что и переход входа, — и
        наложение двух твинов на одном элементе движок считает ошибкой: порядок
        перезаписи в GSAP зависит от очерёдности и может смениться между
        рендерами.
        """
        nodes: list[str] = []
        avatar_nodes = self._avatar_node_by_slot()
        for shot in self.plan.get("shots", []):
            hero = shot.get("hero")
            if not hero:
                continue
            index = int(shot["index"])
            tr_sec = self._transition_duration(shot)
            start = float(shot["start"]) + tr_sec
            duration = max(0.4, float(shot["duration"]) - tr_sec)
            if hero.get("duration"):
                # Приём со своим материалом живёт по его длине, а не по длине
                # кадра: иначе панель досидит кадр пустой.
                duration = max(0.4, min(duration, float(hero["duration"])))
            params = dict(hero.get("params") or {})
            src = self._asset(hero.get("file"))
            if src:
                params["src"] = src
            # Пути к медиа в плане абсолютные, а HyperFrames резолвит их от
            # каталога проекта. Незаменённый путь — не ошибка сборки, а пустой
            # прямоугольник в кадре.
            for key in ("icon",):
                mapped = self._asset(params.get(key))
                if mapped:
                    params[key] = mapped
                elif params.get(key):
                    params.pop(key)
            piece = render_hero(str(hero.get("renderer") or ""), TemplateCtx(
                index=index, start=start, duration=duration,
                target=avatar_nodes.get(index, f"shot-{index:02d}"),
                track=TRACK_HERO_EVEN if index % 2 == 0 else TRACK_HERO_ODD,
                params=params))
            if not piece.nodes:
                continue
            nodes += piece.nodes
            self.tweens.extend(piece.tweens)
            self.stats["hero_devices"] = self.stats.get("hero_devices", 0) + 1
        return nodes

    # --- оверлеи --------------------------------------------------------
    def _overlay_nodes(self) -> list[str]:
        overlays = list(self.plan.get("overlays", []))
        tracks = _lay_out_tracks(overlays, TRACK_OVERLAY)
        nodes: list[str] = []
        for i, (ovl, track) in enumerate(zip(overlays, tracks)):
            start = float(ovl["start"])
            duration = max(0.0, float(ovl["end"]) - start)
            node_id = f"ovl-{i:02d}"
            piece = self._overlay_piece(node_id, ovl, start, duration, track)
            if piece is not None:
                nodes += piece.nodes
                self.tweens.extend(piece.tweens)
                if piece.nodes:
                    self.stats["overlay_draws"] += 1
                continue
            timing = _timing(start, float(ovl["end"]), track)
            body = self._overlay_body(node_id, ovl)
            if not body:
                continue
            nodes.append(body.replace("__TIMING__", timing))
            self.stats["overlay_draws"] += 1
            self._add_overlay_entrance(node_id, ovl, start)
        return nodes

    def _overlay_piece(self, node_id: str, ovl: dict[str, Any],
                       start: float, duration: float, track: int):
        """Карточки источника, чат, статья и data-viz идут в рендереры каталога."""
        from .templates import Piece

        kind = ovl.get("type") or ""
        template_id = str(ovl.get("template") or ovl.get("id") or "")
        renderer = str(ovl.get("renderer") or "")
        params = dict(ovl.get("params") or {})
        ctx = TemplateCtx(index=int(node_id.split("-")[-1]), start=start,
                          duration=duration, target=node_id, track=track,
                          params=params)
        if kind == "dataviz" or template_id.startswith("data-viz/"):
            piece = render_dataviz(template_id or renderer, ctx)
            return piece if piece.nodes else Piece()
        if (renderer == "logo_brand_close" or params.get("logo_close")
                or template_id.endswith("logo-brand-close")):
            safe_x = int(self.brandbook["safe_zones"]["work_area"]["x_min"])
            params.setdefault("available_px", self.width - 2 * safe_x)
            params["renderer"] = "logo_brand_close"
            ctx = TemplateCtx(index=int(node_id.split("-")[-1]), start=start,
                              duration=duration, target=node_id, track=track,
                              params=params)
            piece = render_fullscreen(ctx)
            return piece if piece.nodes else Piece()
        if (renderer == "lt_accent_underline" or params.get("accent_underline")
                or template_id.endswith("accent-underline")):
            work = self.brandbook["safe_zones"]["work_area"]
            params.setdefault("available_px", int(work["x_max"]) - int(work["x_min"]))
            ctx = TemplateCtx(index=int(node_id.split("-")[-1]), start=start,
                              duration=duration, target=node_id, track=track,
                              params=params)
            piece = render_overlay("lt_accent_underline", ctx)
            return piece if piece.nodes else None
        if (renderer == "lt_clean_bar" or params.get("clean_bar")
                or template_id.endswith("clean-bar")):
            work = self.brandbook["safe_zones"]["work_area"]
            params.setdefault("available_px", int(work["x_max"]) - int(work["x_min"]))
            ctx = TemplateCtx(index=int(node_id.split("-")[-1]), start=start,
                              duration=duration, target=node_id, track=track,
                              params=params)
            piece = render_overlay("lt_clean_bar", ctx)
            return piece if piece.nodes else None
        if (renderer == "lt_dark_card" or params.get("dark_card")
                or template_id.endswith("dark-card")):
            work = self.brandbook["safe_zones"]["work_area"]
            params.setdefault("available_px", int(work["x_max"]) - int(work["x_min"]))
            ctx = TemplateCtx(index=int(node_id.split("-")[-1]), start=start,
                              duration=duration, target=node_id, track=track,
                              params=params)
            piece = render_overlay("lt_dark_card", ctx)
            return piece if piece.nodes else None
        overlay_name = renderer if renderer in OVERLAYS else ""
        if not overlay_name and kind in OVERLAYS:
            overlay_name = kind
        if not overlay_name and kind == "source_card":
            overlay_name = "source_card"
        if overlay_name:
            piece = render_overlay(overlay_name, ctx)
            return piece if piece.nodes else None
        return None

    def _overlay_body(self, node_id: str, ovl: dict[str, Any]) -> str | None:
        kind = ovl.get("type")
        params = ovl.get("params") or {}
        if kind == "source_card":
            return self._source_card_body(node_id, params)
        if kind == "plaque":
            # Ключи те, которыми плашку и заполняет P11: `text` и `subtitle`.
            # Читались `content` и `kicker` — таких в плане нет ни одного, и
            # плашка выходила пустой: в кадре белая полоса без единой буквы.
            # Видно это только на кадре готового ролика, поэтому и прожило
            # долго: разметка валидна, lint молчит, QC меряет не текст.
            raw = (params.get("text") or params.get("content")
                   or ovl.get("content") or "")
            if not str(raw).strip():
                return None  # no empty solid plaque
            content = _esc(raw)
            kicker = (params.get("subtitle") or params.get("kicker")
                      or params.get("domain"))
            extra = f'<span class="kicker">{_esc(kicker)}</span>' if kicker else ""
            return (f'<div id="{node_id}" class="clip overlay plaque" __TIMING__>'
                    f'{content}{extra}</div>')
        if kind == "cta":
            # Тот же разнобой ключей: план пишет `text`, и без него кнопка
            # молча показывала запасное «Подпишись» вместо заказанного слова.
            text = _esc(params.get("text") or params.get("content")
                        or ovl.get("content") or "Подпишись")
            return (f'<div id="{node_id}" class="clip overlay cta" __TIMING__>'
                    f'<span id="{node_id}-pill" class="pill">{text}</span></div>')
        # highlight рисуется поверх карточки источника её же стилем — отдельный
        # слой не нужен, подсветку несёт .hl внутри карточки.
        return None

    def _source_card_body(self, node_id: str, params: dict[str, Any]) -> str:
        """Страница издания, а не карточка «сайт вообще».

        Заказчик просил, чтобы контент выглядел живым и меньше походил на
        AI-генерацию. Разница здесь в том, что на карточке стоит: строка адреса
        с настоящим путём статьи, дата, знак издания, начало текста и маркер на
        той строке, ради которой источник и показан (§5.5). Это и есть та самая
        страница, с которой конвейер берёт кадр, — а не абстрактное окно.
        """
        domain = str(params.get("domain") or "")
        url = str(params.get("url") or "")
        # Путь берём от первой косой черты, а не отрезая домен: у ссылки почти
        # всегда есть «www.», а в сценарии домен записан без него — вычитание
        # промахивалось, и в адресной строке оставалось голое имя сайта.
        rest = url.split("://", 1)[-1].removeprefix("www.") if url else ""
        cut = rest.find("/")
        path = rest[cut:] if cut >= 0 else ""
        path = path[:34] + ("…" if len(path) > 34 else "")
        published = str(params.get("published") or "").strip()
        # Дата приходит как ISO-строка со страницы или из сценария; в кадре от
        # неё нужен только день, время читать некому.
        kicker = published.split("T")[0] if published else "источник"
        mark = (domain[:1] or "·").upper()
        highlight = str(params.get("highlight") or "")
        title = _mark_phrase(str(params.get("title") or ""), highlight)
        snippet = _mark_phrase(str(params.get("snippet") or ""), highlight)
        return (f'<div id="{node_id}" class="clip overlay source-card" __TIMING__>'
                f'<div class="bar"><span class="dot"></span><span class="dot"></span>'
                f'<span class="dot"></span>'
                f'<span class="url"><b>{_esc(domain)}</b>{_esc(path)}</span></div>'
                f'<div class="page">'
                f'<div class="kicker">{_esc(kicker)}</div>'
                f'<div class="title">{title}</div>'
                f'<div class="byline"><span class="favicon">{_esc(mark)}</span>'
                f'{_esc(domain)}</div>'
                f'<div class="snippet">{snippet}</div>'
                f'<div class="lines"><i></i><i></i><i></i></div>'
                f'</div></div>')

    def _add_overlay_entrance(self, node_id: str, ovl: dict[str, Any],
                              start: float) -> None:
        kind = ovl.get("type")
        if kind == "cta":
            # §5.7: пульс кнопки. repeat конечный — бесконечный запрещён
            # контрактом детерминизма.
            hz = float(self.brandbook["cta"].get("button_pulse_hz", 1.6))
            period = 1.0 / hz
            duration = float(ovl["end"]) - start
            # Пульс начинается ровно там, где кончается появление. Раньше он
            # заходил на него сотней миллисекунд, и два твина сидели на scale
            # одного элемента разом: чем это кончится, решает порядок
            # перезаписи GSAP, а не разметка. Своё же правило — «два твина на
            # одном свойстве одного элемента пересекаться не имеют права» —
            # lint и ловил все прогоны подряд.
            appear = 0.42
            pulse_start = start + appear
            repeats = max(0, int((duration - appear) / period) - 1)
            self.tweens.append(
                f'tl.fromTo("#{node_id}-pill",{{scale:0.6}},'
                f'{{scale:1,duration:{appear},ease:"power3.out"}},{_num(start)});')
            self.tweens.append(
                f'tl.to("#{node_id}-pill",{{scale:1.035,duration:{period / 2:.3f},'
                f'yoyo:true,repeat:{repeats},ease:"sine.inOut"}},{_num(pulse_start)});')
            return
        if kind == "source_card":
            params = ovl.get("params") or {}
            if params.get("highlight"):
                # Маркер приходит после карточки, а не вместе с ней: §5.5 про
                # фокус, а фокус — это отдельное движение глаза. Цвет задаётся
                # литералом: var() GSAP в цвет не разворачивает.
                # Полупрозрачный, как настоящий маркер: заголовок переносится,
                # и непрозрачная плашка следующей строки срезала хвост буквы на
                # предыдущей — «Quantum» читался как «Ouantum». Проверено кадром.
                soft = str(self.brandbook["colors"].get("accent_soft", "#E4726A"))
                rgb = ",".join(str(int(soft.lstrip("#")[i:i + 2], 16)) for i in (0, 2, 4))
                self.tweens.append(
                    f'tl.fromTo("#{node_id} .hl",'
                    f'{{backgroundColor:"rgba({rgb},0)"}},'
                    f'{{backgroundColor:"rgba({rgb},0.55)",duration:0.42,'
                    f'ease:"power2.out"}},{_num(start + 0.6)});')
            if params.get("scroll"):
                # Страница едет вверх ровно столько, чтобы это читалось как
                # прокрутка, а не как съезжающая вёрстка.
                hold = max(0.4, float(ovl["end"]) - start - 0.9)
                self.tweens.append(
                    f'tl.to("#{node_id} .page",{{y:-46,duration:{_num(hold)},'
                    f'ease:"none"}},{_num(start + 0.7)});')

        # Плашка всплывает и приближается, а не выезжает плоско: подъём без
        # масштаба читается как «панель подали снизу», с масштабом — как
        # «карточку поднесли». Дрейф на удержании не нужен: карточка стоит
        # рядом с движущимся словом субтитра и без него.
        self.tweens.extend(entrance_tweens(f"#{node_id}", start, name="rise"))

    def _credit_nodes(self) -> list[str]:
        """Подпись источника мелким шрифтом (§1, правило 8).

        Ставится только там, где её требуют права: список источников с
        ``attribution_required`` ведёт P11, сюда приходит уже готовая строка.
        Место — левый нижний угол рабочей зоны, над полосой субтитров: правый
        занят колонкой лайк/коммент/шер площадки, а верх — приёмами.
        """
        nodes: list[str] = []
        for shot in self.plan["shots"]:
            credit = str(shot.get("credit") or "").strip()
            if not credit:
                continue
            index = int(shot["index"])
            start = float(shot["start"])
            # Подпись живёт вместе с кадром, но появляется чуть позже него:
            # одновременный въезд читается как часть монтажа, а не как сноска.
            nodes.append(
                f'<div id="credit-{index:02d}" class="clip credit" '
                + _timing(start + 0.25, start + float(shot["duration"]), TRACK_OVERLAY + 5)
                + f'>{_esc(credit)}</div>')
            self.tweens.extend(entrance_tweens(f"#credit-{index:02d}", start + 0.25,
                                               name="dim"))
        return nodes

    # --- субтитры -------------------------------------------------------
    def _subtitle_nodes(self) -> list[str]:
        caption = resolve_caption(
            str(self.plan.get("subtitle_style", {}).get("caption") or ""))
        builders = {
            "clip-wipe": build_clip_wipe,
            "camera-follow": build_camera_follow,
            "gradient-fill": build_gradient_fill,
            "blend-difference": build_blend_difference,
        }
        builder = builders.get(caption, build_gradient_fill)
        nodes, tweens, count = builder(
            self.plan, self.brandbook, duration=self.duration)
        self.tweens.extend(tweens)
        self.stats["subtitle_words"] += count
        return nodes

    # --- звук -----------------------------------------------------------
    def _audio_node(self, mix_name: str) -> str:
        return (f'<audio id="mix" src="{_esc(mix_name)}" data-start="0" '
                f'data-duration="{_num(self.duration)}" '
                f'data-track-index="{TRACK_AUDIO}" data-volume="1"></audio>')


    def _avatar_zoom_css(self) -> str:
        """Size transparent Avatar V so the subject fills the frame.

        HyperFrames alpha path plays the raw webm with object-fit:cover — the
        prepare_avatar_shot compose_zoom never reached the screen. Enlarge via
        width/height (not transform:scale) so GSAP entry tweens that end at
        scale:1 keep the resting fill.
        """
        zoom = max(float(self.plan.get("avatar_compose_zoom") or 1.0), 1.0)
        # Subject mid-frame on 0042 seg_00 (~40% x, ~51% y of opaque bbox).
        fx = 0.40
        fy = 0.48
        faces = []
        for seg in self.plan.get("avatar", []) or []:
            box = seg.get("face_bbox")
            if box and len(box) == 4:
                faces.append(box)
        if faces:
            # Average face centre as focus.
            cx = sum((b[0] + b[2]) / 2 for b in faces) / len(faces) / max(self.width, 1)
            cy = sum((b[1] + b[3]) / 2 for b in faces) / len(faces) / max(self.height, 1)
            fx = min(max(cx, 0.2), 0.8)
            fy = min(max(cy, 0.25), 0.7)
        if zoom <= 1.001:
            return (".avatar{width:var(--frame-w);height:var(--frame-h);"
                    "left:0;top:0;object-fit:cover}")
        # left/top place the focus point at frame centre after enlarge.
        return (
            f".avatar{{width:calc(var(--frame-w) * {zoom:.3f});"
            f"height:calc(var(--frame-h) * {zoom:.3f});"
            f"left:calc(var(--frame-w) * (1 - {zoom:.3f}) * {fx:.3f});"
            f"top:calc(var(--frame-h) * (1 - {zoom:.3f}) * {fy:.3f});"
            f"object-fit:cover;max-width:none;max-height:none}}"
        )

    # --- сборка ---------------------------------------------------------
    def build(self, mix_name: str) -> str:
        body: list[str] = [
            f'<div id="stage-bg" class="clip stage-bg" data-start="0" '
            f'data-duration="{_num(self.duration)}" '
            f'data-track-index="{TRACK_STAGE}"></div>'
        ]
        body += self._shot_nodes()
        body += self._credit_nodes()
        body += self._behind_head_nodes()
        body += self._avatar_nodes()
        body += self._hero_nodes()
        body += self._overlay_nodes()
        body += self._subtitle_nodes()
        body.append(self._audio_node(mix_name))

        indented = "\n      ".join(body)
        tweens = "\n      ".join(self.tweens)
        # Реестр эффектов холста пишется только тогда, когда холст в кадре
        # есть: страница без него не носит лишнего килобайта скрипта.
        canvas_registry = (canvas_js(self.brandbook.get("colors", {}))
                           if self.canvas_used else "")
        title = f'{self.plan["video_id"]} {self.plan["variant"]}'

        return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={self.width}, height={self.height}" />
    <title>{_esc(title)}</title>
    <script src="vendor/gsap.min.js"></script>
    <link rel="stylesheet" href="brand.css" />
    <style id="avatar-compose-zoom">{self._avatar_zoom_css()}</style>
  </head>
  <body>
    <div
      id="root"
      class="{self._stage_class()}"
      data-composition-id="{COMPOSITION_ID}"
      data-start="0"
      data-duration="{_num(self.duration)}"
      data-width="{self.width}"
      data-height="{self.height}"
      data-fps="{self.fps}"
    >
      {indented}
    </div>
    <script>
      {canvas_registry}
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {tweens}
      window.__timelines["{COMPOSITION_ID}"] = tl;
    </script>
  </body>
</html>
"""

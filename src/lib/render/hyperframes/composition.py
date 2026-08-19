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
from .templates import (
    TemplateCtx, enter_and_drift, entrance_tweens, fit_size, render_hero,
    render_motion, render_transition, text_width,
)

TRACK_STAGE = 0
TRACK_SHOT_EVEN = 1
TRACK_SHOT_ODD = 2
TRACK_AVATAR = 3
TRACK_BEHIND_HEAD = 4
TRACK_OVERLAY = 5      # и следующие, если плашки пересекаются во времени
TRACK_TRANSITION = 11
TRACK_SUBTITLE = 12
# Приёмы вокруг ведущего чередуют треки по той же причине, что и шоты: соседние
# кадры стыкуются встык, а окно видимости клипа включает оба конца.
TRACK_HERO_EVEN = 13
TRACK_HERO_ODD = 14
TRACK_AUDIO = 20

COMPOSITION_ID = "redshift"


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _num(value: float) -> str:
    """Секунды в атрибут: три знака хватает для кадра на 30 fps."""
    return f"{float(value):.3f}".rstrip("0").rstrip(".") or "0"


def _lay_out_tracks(items: list[dict[str, Any]], first_track: int) -> list[int]:
    """Разложить пересекающиеся во времени элементы по свободным трекам."""
    ends: list[float] = []
    tracks: list[int] = []
    for item in items:
        start, end = float(item["start"]), float(item["end"])
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
            timing = (f'data-start="{_num(start)}" data-duration="{_num(duration)}" '
                      f'data-track-index="{track}"')
            # Цель перехода: для аватар-слотов — сам аватар, иначе — шот.
            target = avatar_nodes.get(index, node_id)
            # Переход и Ken Burns тянут одни и те же свойства одного элемента.
            # Наложение запрещено контрактом: порядок перезаписи в GSAP зависит
            # от очерёдности и может переключиться между рендерами. Поэтому
            # медленный проезд начинается там, где кончается вход.
            tr_sec = self._transition_duration(shot)

            if kind == "fullscreen_text":
                nodes.append(self._fullscreen_text_node(node_id, shot, timing))
                # Раньше полноэкранный текст просто включался: клип открывался,
                # и надпись стояла. На фоне пословных субтитров, которые всё
                # время движутся, это читалось как подвисший кадр.
                self.tweens.extend(enter_and_drift(
                    f"#{node_id}-inner", start + tr_sec,
                    max(0.2, duration - tr_sec), name="zoom-in"))
            elif index in alpha_slots:
                # Режим A с альфой: фон собирается в браузере, а не берётся
                # сплющенным кадром — в этом и смысл переезда на HyperFrames.
                nodes.append(
                    f'<div id="{node_id}" class="clip shot-bg" {timing}>'
                    f'<div class="vfx"></div></div>')
            elif index in avatar_nodes or kind == "avatar":
                # Аватар без альфы приходит со своим фоном и занимает кадр
                # целиком: подкладывать под него нечего. Но переход ему нужен.
                pass
            elif kind == "meme":
                src = self._asset(shot.get("file"))
                if src:
                    nodes.append(self._media_node(node_id, src, timing, css="meme"))
            else:
                src = self._asset(shot.get("file"))
                if src:
                    nodes.append(self._media_node(node_id, src, timing, css="shot",
                                                  media_start=shot.get("avatar_offset_sec")))
                    self._add_kenburns(node_id, shot, start + tr_sec,
                                       max(0.1, duration - tr_sec))
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

    def _fullscreen_text_node(self, node_id: str, shot: dict[str, Any],
                              timing: str) -> str:
        content = str(shot.get("content") or "").strip()
        accent = str(shot.get("accent_word") or "").strip()
        invert = " invert" if shot.get("invert") else ""
        markup = _esc(content)
        if accent and accent.upper() in content.upper():
            # §3.3.2: красным выделяется одно слово, не строка.
            idx = content.upper().index(accent.upper())
            markup = (_esc(content[:idx])
                      + f'<span class="accent">{_esc(content[idx:idx + len(accent)])}</span>'
                      + _esc(content[idx + len(accent):]))
        # Кегль подбирается под самое длинное слово, а не берётся потолком из
        # брендбука. С фиксированными 420 px «ПЕРЕЖИВЁШЬ» занимало 2400 px и
        # уезжало за оба края кадра — видно было «ЕЖИВЁ». Поймано кадром
        # готового MP4, а не разметкой: QC меряет safe zones по оверлеям, а
        # полноэкранный текст оверлеем не является.
        fs = self.brandbook["fullscreen_text"]
        safe_x = int(self.brandbook["safe_zones"]["work_area"]["x_min"])
        available = self.width - 2 * safe_x
        longest = max(content.upper().split(), key=len, default="")
        size = fit_size(longest, available, int(fs["size_px"][1]))
        return (f'<div id="{node_id}" class="clip fullscreen-text{invert}" {timing}>'
                f'<span id="{node_id}-inner" style="font-size:{size}px">'
                f'{markup}</span></div>')

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
                f'data-start="{_num(seg["start"])}" '
                f'data-duration="{_num(seg["duration"])}" '
                f'data-track-index="{TRACK_AVATAR}" muted playsinline></video>')
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
                f'<div id="{node_id}" class="clip behind-head" '
                f'data-start="{_num(shot["start"])}" '
                f'data-duration="{_num(shot["duration"])}" '
                f'data-track-index="{TRACK_BEHIND_HEAD}">{_esc(word)}</div>')
            # Слово за головой держится весь кадр, и без движения оно
            # превращается в надпись на обоях. Медленный наезд даёт ту самую
            # глубину: ведущий стоит, фон еле едет.
            self.tweens.extend(enter_and_drift(
                node_id and f"#{node_id}", float(shot["start"]),
                float(shot["duration"]), name="zoom-in"))
        return nodes

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
            duration = float(ovl["end"]) - start
            node_id = f"ovl-{i:02d}"
            timing = (f'data-start="{_num(start)}" data-duration="{_num(duration)}" '
                      f'data-track-index="{track}"')
            body = self._overlay_body(node_id, ovl)
            if not body:
                continue
            nodes.append(body.replace("__TIMING__", timing))
            self.stats["overlay_draws"] += 1
            self._add_overlay_entrance(node_id, ovl, start)
        return nodes

    def _overlay_body(self, node_id: str, ovl: dict[str, Any]) -> str | None:
        kind = ovl.get("type")
        params = ovl.get("params") or {}
        if kind == "source_card":
            domain = _esc(params.get("domain"))
            title = _esc(params.get("title"))
            snippet = _esc(params.get("snippet"))
            return (f'<div id="{node_id}" class="clip overlay source-card" __TIMING__>'
                    f'<div class="bar"><span class="dot"></span><span class="dot"></span>'
                    f'<span class="dot"></span><span class="domain">{domain}</span></div>'
                    f'<div class="title">{title}</div>'
                    f'<div class="snippet">{snippet}</div></div>')
        if kind == "plaque":
            content = _esc(params.get("content") or ovl.get("content"))
            kicker = params.get("kicker") or params.get("domain")
            extra = f'<span class="kicker">{_esc(kicker)}</span>' if kicker else ""
            return (f'<div id="{node_id}" class="clip overlay plaque" __TIMING__>'
                    f'{content}{extra}</div>')
        if kind == "cta":
            text = _esc(params.get("content") or ovl.get("content") or "Подпишись")
            return (f'<div id="{node_id}" class="clip overlay cta" __TIMING__>'
                    f'<span id="{node_id}-pill" class="pill">{text}</span></div>')
        # highlight рисуется поверх карточки источника её же стилем — отдельный
        # слой не нужен, подсветку несёт .hl внутри карточки.
        return None

    def _add_overlay_entrance(self, node_id: str, ovl: dict[str, Any],
                              start: float) -> None:
        kind = ovl.get("type")
        if kind == "cta":
            # §5.7: пульс кнопки. repeat конечный — бесконечный запрещён
            # контрактом детерминизма.
            hz = float(self.brandbook["cta"].get("button_pulse_hz", 1.6))
            period = 1.0 / hz
            duration = float(ovl["end"]) - start
            repeats = max(0, int(duration / period) - 1)
            self.tweens.append(
                f'tl.fromTo("#{node_id}-pill",{{scale:0.6}},'
                f'{{scale:1,duration:0.32,ease:"back.out(1.7)"}},{_num(start)});')
            self.tweens.append(
                f'tl.to("#{node_id}-pill",{{scale:1.035,duration:{period / 2:.3f},'
                f'yoyo:true,repeat:{repeats},ease:"sine.inOut"}},{_num(start + 0.32)});')
            return
        # Плашка всплывает и приближается, а не выезжает плоско: подъём без
        # масштаба читается как «панель подали снизу», с масштабом — как
        # «карточку поднесли». Дрейф на удержании не нужен: карточка стоит
        # рядом с движущимся словом субтитра и без него.
        self.tweens.extend(entrance_tweens(f"#{node_id}", start, name="rise"))

    # --- субтитры -------------------------------------------------------
    def _subtitle_nodes(self) -> list[str]:
        spec = self.brandbook["subtitles"]
        pop_ms = float(spec["pop_in_ms"][0]) / 1000.0
        scale_from = float(spec["pop_scale_from"])
        baseline = self.plan.get("subtitle_style", {}).get(
            "baseline_y", spec["baseline_y_default"])

        case_mode = spec.get("case", "lower")
        nodes: list[str] = []
        for i, word in enumerate(self.plan.get("subtitles", [])):
            display = subtitle_word(str(word.get("display") or ""), case_mode)
            if not display:
                continue
            start = float(word["start"])
            duration = max(0.05, float(word["end"]) - start)
            node_id = f"w-{i:04d}"
            css = "clip word emphasis" if word.get("emphasis") else "clip word"
            style = f' style="top:{int(baseline)}px"'
            nodes.append(
                f'<div id="{node_id}" class="{css}"{style} '
                f'data-start="{_num(start)}" data-duration="{_num(duration)}" '
                f'data-track-index="{TRACK_SUBTITLE}">'
                f'<span id="{node_id}-t">{_esc(display)}</span></div>')
            # Pop-in анимируется на внутреннем span: сам клип отдан движку,
            # его видимостью управляет фреймворк.
            self.tweens.append(
                f'tl.fromTo("#{node_id}-t",{{scale:{scale_from}}},'
                f'{{scale:1,duration:{pop_ms:.3f},ease:"back.out(1.7)"}},{_num(start)});')
            self.stats["subtitle_words"] += 1
        return nodes

    # --- звук -----------------------------------------------------------
    def _audio_node(self, mix_name: str) -> str:
        return (f'<audio id="mix" src="{_esc(mix_name)}" data-start="0" '
                f'data-duration="{_num(self.duration)}" '
                f'data-track-index="{TRACK_AUDIO}" data-volume="1"></audio>')

    # --- сборка ---------------------------------------------------------
    def build(self, mix_name: str) -> str:
        body: list[str] = [
            f'<div id="stage-bg" class="clip stage-bg" data-start="0" '
            f'data-duration="{_num(self.duration)}" '
            f'data-track-index="{TRACK_STAGE}"></div>'
        ]
        body += self._shot_nodes()
        body += self._behind_head_nodes()
        body += self._avatar_nodes()
        body += self._hero_nodes()
        body += self._overlay_nodes()
        body += self._subtitle_nodes()
        body.append(self._audio_node(mix_name))

        indented = "\n      ".join(body)
        tweens = "\n      ".join(self.tweens)
        title = f'{self.plan["video_id"]} {self.plan["variant"]}'

        return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={self.width}, height={self.height}" />
    <title>{_esc(title)}</title>
    <script src="vendor/gsap.min.js"></script>
    <link rel="stylesheet" href="brand.css" />
  </head>
  <body>
    <div
      id="root"
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
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {tweens}
      window.__timelines["{COMPOSITION_ID}"] = tl;
    </script>
  </body>
</html>
"""

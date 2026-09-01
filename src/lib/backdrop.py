"""Фон за ведущим: сцена под тему ролика.

Пока аватар приходил непрозрачным, фона не было вовсе — кадр занимал сам клип.
С рабочей альфой под ведущим появилось место, и первое, чем его заняли, был
светлый градиент. Он честно работал подложкой и ровно ничего не говорил: белый
прямоугольник за человеком, который рассказывает про чёрную дыру.

Сцена выбирается **по теме ролика** — по заголовку и репликам, тем же разбором
основ, что и знаки (:mod:`src.lib.glyphs`). Ролик про горизонт событий получает
космос, ролик про чип — техническую сетку, разговорный — комнату. Тема ролика,
а не отдельного кадра: фон держится весь ролик и меняться посреди него не
имеет права, иначе это не фон, а мигание.

Сцена рисуется в два слоя. Нижний — **плита**: настоящая картинка из стока,
затемнённая и приглушённая до брендовой палитры. Верхний — градиенты и маски в
самой композиции: свечение, виньетка, кольцо. Один градиент без плиты читается
дёшево, одна плита без градиентов перетягивает внимание на себя; вместе они
дают глубину и всё же уступают речи.

Плита обязана быть приглушена **до** попадания в репозиторий, а не фильтром в
кадре: ``filter`` продюсер не поддерживает (проверено), и яркий сток за спиной
ведущего пришлось бы гасить накладкой, которая съела бы и его собственные
цвета. Поэтому в ``assets/backdrops`` лежат уже готовые кадры 1080×1920.

Сцены без плиты рисуются одними градиентами — это не поломка, а запасной путь:
набор плит конечен, а тем у роликов больше.

У каждой сцены есть **тон**. Он решает, каким цветом рисуется то, что лежит
прямо на фоне: заголовок за головой, тема за головой, знаки, накопительный
список. На тёмной сцене чернильная надпись пропадает — цвет берётся из
``--color-on-stage``, и тон его переключает.
"""

from __future__ import annotations


# Сцена → основы слов, по которым она узнаётся, и тон.
#
# Порядок важен: первая совпавшая и выигрывает, а «чёрная дыра» обязана дать
# горизонт событий, а не просто космос.
SCENES: dict[str, dict[str, object]] = {
    "horizon": {
        "tone": "dark",
        "stems": ("горизонт", "сингулярн", "коллапс", "гравитац"),
        # «Дыра» сама по себе сцены не решает: на 0047 («самая глубокая дыра на
        # Земле») она поставила за спину ведущего аккреционный диск, и ролик про
        # скважину шёл на фоне чёрной дыры. Судья §11.2 отметил это дважды —
        # «мужчина на фоне космоса». Пара слов однозначна, одна основа — нет.
        "pairs": (("чёрн", "дыр"),),
        "why": "чёрная дыра: тёмное поле и раскалённое кольцо аккреции",
    },
    "depth": {
        "tone": "dark",
        "stems": ("бур", "скважин", "глубин", "глубок", "недр", "пород",
                  "геолог", "грунт", "шахт", "тоннел", "туннел", "разлом",
                  "гранит", "базальт", "керн", "рудник", "вулкан", "магм"),
        "why": "недра: слои породы, уходящие вниз, и жар на глубине",
    },
    "space": {
        "tone": "dark",
        "stems": ("космос", "космич", "звезд", "галактик", "планет", "орбит",
                  "вселенн", "ракет", "телескоп", "астроном"),
        "why": "космос: глубина, звёздная пыль, дальнее свечение",
    },
    "grid": {
        "tone": "dark",
        "stems": ("чип", "процессор", "кубит", "квант", "алгоритм", "нейросет",
                  "код", "сервер", "вычислит", "данн"),
        "why": "техника: тёмная сетка с подсветкой",
    },
    "room": {
        "tone": "light",
        "stems": ("компан", "рынок", "деньг", "суд", "патент", "закон",
                  "рекламн", "продукт", "стартап"),
        "why": "разговор: мягкая стена студии с боковым светом",
    },
}

DEFAULT_SCENE = "room"

# Сцена → файл плиты в ``assets/backdrops``. Плиты есть не у всех сцен: набор
# растёт по мере роликов, а не закупается разом.
PLATES: dict[str, str] = {
    "horizon": "horizon.jpg",
    "grid": "grid.jpg",
}


def plate_name(scene: str) -> str:
    """Имя файла плиты сцены. Пустая строка — плиты нет, рисуем градиентами."""
    return PLATES.get(scene, "")


def _matches(word: str, stems: tuple[str, ...]) -> bool:
    """Основа сцены — всегда приставка, даже короткая.

    У знаков (:mod:`src.lib.glyphs`) короткая основа сверяется словом целиком:
    там «ток» поймал бы «только». Здесь правило другое, и это не небрежность.
    Основы сцен — не слова, а корни («дыр», «код»), и требование целого слова
    их убивает: «чёрной дыры» не совпало бы с «дыр», и ролик про горизонт
    событий получил бы нейтральную комнату. Проверено — именно так и вышло.

    Цена ошибки тоже разная. Знак — утверждение о том, про что реплика, и
    лишний знак в кадре врёт. Сцена — настроение фона; промах даёт не ту
    атмосферу, а не ложь.
    """
    return any(word.startswith(stem) for stem in stems)


def pick_scene(*texts: str) -> str:
    """Сцена по теме ролика. Совпадений нет — комната, она нейтральна.

    Пара основ проверяется раньше одиночных: «чёрная дыра» — это горизонт
    событий, а просто «дыра» в тексте про бурение — это недра. Одиночная основа
    короткая и жадная, и разбирать спор двух сцен ей нельзя.
    """
    words = [w.strip(".,!?;:»«\"'()—–-").lower()
             for w in " ".join(str(t or "") for t in texts).split()]
    words = [w for w in words if w]
    for name, scene in SCENES.items():
        for pair in scene.get("pairs", ()):                   # type: ignore[union-attr]
            if all(any(_matches(w, (stem,)) for w in words) for stem in pair):
                return name
    for name, scene in SCENES.items():
        stems = scene["stems"]                                # type: ignore[index]
        if any(_matches(w, stems) for w in words):            # type: ignore[arg-type]
            return name
    return DEFAULT_SCENE


def tone(scene: str) -> str:
    return str(SCENES.get(scene, SCENES[DEFAULT_SCENE])["tone"])


def describe(scene: str) -> str:
    return str(SCENES.get(scene, SCENES[DEFAULT_SCENE])["why"])


def backdrop_css() -> str:
    """Стили сцен. Каждая — слоями градиентов, без единого файла.

    Звёздная пыль — повторяющийся ``radial-gradient`` мелким шагом: сотня
    отдельных точек в разметке весила бы больше и рисовалась бы дольше, а
    выглядит так же.
    """
    return (
        ".vfx{position:absolute;inset:0;overflow:hidden}"
        # Плита лежит под градиентами сцены и растягивается по кадру. `cover`
        # здесь не нужен: кадры заготовлены ровно 1080×1920.
        ".vfx-plate{position:absolute;inset:0;background-size:cover;"
        "background-position:center;z-index:0}"
        # Слои сцены поверх плиты. Без этого ::before и ::after ложились бы
        # под картинку и в кадре их бы не было.
        ".vfx::before,.vfx::after{z-index:1}"

        # --- комната: мягкая стена студии с боковым светом ---
        ".vfx.scene-room{background:"
        "radial-gradient(120% 90% at 28% 22%,#FFFFFF 0%,#F2EEEB 42%,#E4DCD7 100%)}"
        ".vfx.scene-room::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(60% 40% at 78% 88%,"
        "var(--color-accent-soft) 0%,transparent 68%);opacity:0.34}"
        # Виньетка сажает ведущего в комнату, а не наклеивает на плоскость.
        ".vfx.scene-room::before{content:'';position:absolute;inset:0;"
        "background:radial-gradient(105% 80% at 50% 42%,"
        "transparent 55%,rgba(40,32,28,0.20) 100%)}"

        # --- космос: глубина и звёздная пыль ---
        ".vfx.scene-space{background:"
        "radial-gradient(120% 100% at 50% 30%,#1B2130 0%,#0C1018 52%,#05070C 100%)}"
        ".vfx.scene-space::before{content:'';position:absolute;inset:-20%;"
        "background:"
        "radial-gradient(1.6px 1.6px at 12% 18%,rgba(255,255,255,0.85),transparent),"
        "radial-gradient(1.4px 1.4px at 68% 8%,rgba(255,255,255,0.7),transparent),"
        "radial-gradient(1.8px 1.8px at 84% 42%,rgba(255,255,255,0.8),transparent),"
        "radial-gradient(1.2px 1.2px at 32% 62%,rgba(255,255,255,0.6),transparent),"
        "radial-gradient(1.5px 1.5px at 54% 84%,rgba(255,255,255,0.7),transparent),"
        "radial-gradient(1.3px 1.3px at 8% 76%,rgba(255,255,255,0.55),transparent);"
        "background-size:340px 340px,420px 420px,300px 300px,"
        "380px 380px,460px 460px,320px 320px}"
        ".vfx.scene-space::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(60% 38% at 26% 74%,"
        "rgba(200,69,61,0.30) 0%,transparent 70%),"
        "radial-gradient(50% 30% at 78% 22%,"
        "rgba(120,140,200,0.22) 0%,transparent 72%)}"

        # --- горизонт событий: тёмное поле и раскалённое кольцо ---
        ".vfx.scene-horizon{background:"
        "radial-gradient(80% 60% at 50% 40%,#000000 0%,#05060A 46%,#0B0E15 100%)}"
        # Кольцо — конический градиент: у аккреционного диска яркость идёт по
        # кругу, а не от центра, и радиальный этого не даёт.
        ".vfx.scene-horizon::before{content:'';position:absolute;"
        "left:50%;top:34%;width:1180px;height:1180px;margin:-590px 0 0 -590px;"
        # Кольцо приглушено намеренно. На яркости из первой версии акцентное
        # слово заголовка — тот же выцветший красный — вставало на диск и
        # переставало читаться: два красных одной светлоты спорят. Фон обязан
        # уступать надписи, а не соревноваться с ней.
        "border-radius:50%;background:conic-gradient(from 210deg,"
        "rgba(200,69,61,0) 0deg,rgba(228,114,106,0.52) 78deg,"
        "rgba(255,214,170,0.60) 132deg,rgba(200,69,61,0.34) 196deg,"
        "rgba(200,69,61,0) 300deg);"
        # Дырка в кольце — сама сингулярность: маска, а не второй круг сверху,
        # иначе поверх него не проступит свечение.
        "mask:radial-gradient(circle,transparent 41%,#000 43%,#000 49%,"
        "transparent 52%);"
        "-webkit-mask:radial-gradient(circle,transparent 41%,#000 43%,"
        "#000 49%,transparent 52%)}"
        ".vfx.scene-horizon::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(38% 26% at 50% 34%,"
        "rgba(255,190,140,0.16) 0%,transparent 70%)}"

        # --- недра: слои породы и жар внизу ---
        # Слои чуть завалены: ровно горизонтальные полосы читаются как
        # интерфейс, а не как порода. Свечение снизу — та самая температура,
        # ради которой ролик и снят: чем глубже, тем горячее.
        ".vfx.scene-depth{background:"
        "linear-gradient(180deg,#181310 0%,#0E0B0A 40%,#070506 100%)}"
        ".vfx.scene-depth::before{content:'';position:absolute;inset:-8%;"
        # Пласты — широкие мягкие полосы неравной толщины, а не линии в
        # клеточку: тонкие ровные штрихи давали тетрадный лист, проверено
        # скриншотом. Два слоя под разными углами не дают рисунку повториться
        # в кадре, а размытые края — краю пласта выглядеть линейкой.
        "background:repeating-linear-gradient(183.4deg,"
        "rgba(232,214,192,0.055) 0 22px,transparent 22px 74px,"
        "rgba(158,120,92,0.075) 74px 132px,transparent 132px 178px,"
        "rgba(232,214,192,0.032) 178px 214px,transparent 214px 296px),"
        # Второй слой наклонён в ту же сторону, что и первый. Встречный угол
        # давал решётку — кадр читался как плетёнка, а не как порода.
        "repeating-linear-gradient(182.1deg,"
        "rgba(96,74,60,0.10) 0 34px,transparent 34px 128px);"
        "filter:blur(2.4px);"
        "mask:linear-gradient(180deg,transparent 0%,#000 16%,#000 74%,"
        "transparent 100%);"
        "-webkit-mask:linear-gradient(180deg,transparent 0%,#000 16%,#000 74%,"
        "transparent 100%)}"
        ".vfx.scene-depth::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(72% 34% at 50% 100%,"
        "rgba(200,69,61,0.36) 0%,rgba(200,69,61,0.10) 46%,transparent 74%)}"

        # --- сетка: техническая глубина ---
        ".vfx.scene-grid{background:"
        "radial-gradient(120% 90% at 50% 26%,#141A22 0%,#0A0D13 60%,#06080C 100%)}"
        ".vfx.scene-grid::before{content:'';position:absolute;inset:0;"
        "background:"
        "repeating-linear-gradient(0deg,rgba(160,180,210,0.10) 0 1px,"
        "transparent 1px 96px),"
        "repeating-linear-gradient(90deg,rgba(160,180,210,0.10) 0 1px,"
        "transparent 1px 96px);"
        # Сетка гаснет к краям — иначе кадр читается как миллиметровка.
        "mask:radial-gradient(80% 60% at 50% 40%,#000 0%,transparent 78%);"
        "-webkit-mask:radial-gradient(80% 60% at 50% 40%,#000 0%,transparent 78%)}"
        ".vfx.scene-grid::after{content:'';position:absolute;inset:0;"
        "background:radial-gradient(55% 34% at 50% 30%,"
        "rgba(200,69,61,0.22) 0%,transparent 72%)}"
    )

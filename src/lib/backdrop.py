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

Рисуется сцена в самой композиции — градиентами и SVG, без единого файла.
Причина не в экономии: сгенерированная картинка одна на все ролики надоест
через три выпуска, а сток за спиной ведущего перетягивает внимание на себя.
Абстрактная сцена держит глубину и не спорит с речью.

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
        "stems": ("дыр", "горизонт", "сингулярн", "коллапс", "гравитац"),
        "why": "чёрная дыра: тёмное поле и раскалённое кольцо аккреции",
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
    """Сцена по теме ролика. Совпадений нет — комната, она нейтральна."""
    words = [w.strip(".,!?;:»«\"'()—–-").lower()
             for w in " ".join(str(t or "") for t in texts).split()]
    for name, scene in SCENES.items():
        stems = scene["stems"]                                # type: ignore[index]
        if any(w and _matches(w, stems) for w in words):      # type: ignore[arg-type]
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

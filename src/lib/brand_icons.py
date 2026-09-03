"""Библиотека иконок брендов (§14).

Накапливается попутно: когда в кадре впервые понадобился логотип, он
сохраняется сюда и в следующих роликах уже не ищется. Это не разовая закупка —
набор растёт ровно на те бренды, которые реально прозвучали.

Почему в репозитории, а не в кэше футажей: знак весит килобайты, и держать его
рядом с кодом дешевле, чем каждый раз ходить за ним в сеть и заново проверять,
что нашёлся именно официальный.

Вариант ``mono`` — одноцветный вектор, который красится через ``currentColor``.
Он заменяет пару «светлый + тёмный»: тот же контур читается и на тёмной сцене, и
на белой карточке, а размер у него любой. Пара PNG остаётся для знаков, которые
одним цветом не передать.

Права. Логотип — товарный знак владельца. Мы берём его из официального
press-kit и используем номинативно: называем продукт, о котором идёт речь. Не
перекрашиваем, не искажаем пропорции и не ставим так, будто бренд ролик
одобрил.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_json
from .logging import get_logger

_log = get_logger("brand_icons")

MANIFEST_NAME = "brand_icons_manifest.json"


def slugify(name: str) -> str:
    """Имя бренда → безопасное имя файла.

    Кириллица транслитерируется, а не выбрасывается: «Яндекс» должен дать
    ``yandex``, а не пустую строку.
    """
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    lowered = (name or "").strip().lower()
    out = "".join(table.get(ch, ch) for ch in lowered)
    out = unicodedata.normalize("NFKD", out).encode("ascii", "ignore").decode()
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out or "brand"


VARIANTS = ("light", "dark", "mono")

# Падежные окончания, на которые имя бренда меняется в русской речи. Список
# закрытый, и в этом смысл: «гугл» + «а» — это «гугла», а «мета» + «лл» уже
# «металл», и знак Meta в кадре про металлургию был бы враньём. Открытый
# префиксный поиск такую разницу не видит, поэтому его здесь нет.
CASE_ENDINGS = ("", "а", "е", "и", "ы", "у", "ю", "я", "ов", "ом", "ой",
                "ам", "ах", "ами", "ей", "ье")

# Короче трёх букв слаг не ищется по тексту: «x» и «go» совпали бы с любой
# латинской буквой в реплике, и знак вставал бы наугад.
MIN_SLUG_LEN = 3


def _inflected(word: str, stem: str) -> bool:
    """Слово — это основа с русским падежным окончанием и ничем больше."""
    return word.startswith(stem) and word[len(stem):] in CASE_ENDINGS



@dataclass
class BrandIcon:
    brand: str
    slug: str
    variant: str          # light | dark | mono
    file: str
    hex: str = ""
    source_url: str = ""
    added: str = ""
    used_in: list[str] = field(default_factory=list)
    root: Path | None = None

    @property
    def path(self) -> str:
        """Путь к файлу знака — то, что уходит в приём.

        Приём получает путь, а не байты: разметка ссылается на файл, и читать
        его в память ради этого незачем. Без корня возвращается имя как есть —
        так запись остаётся годной и без библиотеки за спиной.
        """
        return str(self.root / self.file) if self.root else self.file

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand, "slug": self.slug, "variant": self.variant,
            "file": self.file, "hex": self.hex, "source_url": self.source_url,
            "added": self.added, "used_in": self.used_in,
        }


class BrandIconLibrary:
    """Манифест иконок: поиск, добавление, отметка использования."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / MANIFEST_NAME
        self.data = read_json(self.manifest_path)

    @property
    def policy(self) -> dict[str, Any]:
        return self.data.get("policy", {})

    def find(self, brand: str, variant: str | None = None) -> list[BrandIcon]:
        slug = slugify(brand)
        found = [BrandIcon(root=self.root,
                           **{k: v for k, v in entry.items()
                              if k in BrandIcon.__dataclass_fields__ and k != "root"})
                 for entry in self.data.get("brands", [])
                 if entry.get("slug") == slug]
        if variant:
            found = [icon for icon in found if icon.variant == variant]
        return [icon for icon in found if (self.root / icon.file).exists()]

    @property
    def aliases(self) -> dict[str, list[str]]:
        """Русские основы названий: слаг → список основ."""
        return self.data.get("aliases", {})

    def match_text(self, text: str) -> BrandIcon | None:
        """Знак бренда, который реплика действительно называет.

        Сценарии пишутся по-русски, а слаги латиницей. Транслитерация закрывает
        часть случаев («Тесла» → tesla), но «Гугл» даёт ``gugl``, «Ютуб» —
        ``yutub``, и библиотека из ста знаков оказывалась недостижима: за весь
        прогон 0047 в кадр не попал ни один логотип. Поэтому сначала русские
        основы из манифеста, потом транслитерация.

        Длинная основа проверяется раньше короткой: «гугл клауд» обязан дать
        знак облака, а не общий гугловский.
        """
        words = [w.strip('.,!?;:»«"\'()—–').lower()
                 for w in str(text or "").split()]
        words = [w for w in words if w]
        phrases = words + [f"{a}{b}" for a, b in zip(words, words[1:])]

        by_stem: list[tuple[str, str]] = [
            (stem.replace(" ", ""), slug)
            for slug, stems in self.aliases.items() for stem in stems]
        for stem, slug in sorted(by_stem, key=lambda p: -len(p[0])):
            if any(_inflected(w, stem) for w in phrases):
                found = self.find(slug)
                if found:
                    return found[0]

        for word in sorted(set(words), key=lambda w: (-len(w), w)):
            if len(word) < MIN_SLUG_LEN:
                continue
            found = self.find(word)
            if found:
                return found[0]
        return None

    def has(self, brand: str) -> bool:
        """Есть ли бренд в библиотеке — вопрос, ради которого она заведена."""
        return bool(self.find(brand))

    def variants_left(self, brand: str) -> int:
        limit = int(self.policy.get("variants_per_brand", 2))
        return max(0, limit - len(self.find(brand)))

    def add(self, brand: str, variant: str, file_bytes: bytes, *,
            source_url: str = "", video_id: str = "") -> BrandIcon:
        """Положить иконку в библиотеку.

        Отказ вместо тихой перезаписи: лимит вариантов — часть правила, а не
        рекомендация, иначе один бренд разрастётся десятком почти одинаковых
        файлов.
        """
        if variant not in VARIANTS:
            raise ValueError(f"вариант должен быть одним из {', '.join(VARIANTS)}, "
                             f"получено {variant!r}")
        if self.find(brand, variant):
            raise ValueError(f"иконка {brand} ({variant}) уже есть — "
                             f"библиотека пополняется, а не перезаписывается")
        if not self.variants_left(brand):
            raise ValueError(f"для {brand} уже {len(self.find(brand))} вариантов, "
                             f"лимит {self.policy.get('variants_per_brand', 2)}")

        max_bytes = int(self.policy.get("max_bytes", 120_000))
        if len(file_bytes) > max_bytes:
            raise ValueError(f"иконка {brand} весит {len(file_bytes)} байт при "
                             f"лимите {max_bytes}: пережмите или уменьшите сторону")

        slug = slugify(brand)
        # Расширение — по содержимому, а не по договорённости: одноцветные знаки
        # приходят вектором, снятые с press-kit — растром, и назвать SVG «.png»
        # значит сломать его в разметке молча.
        suffix = "svg" if file_bytes.lstrip()[:1] == b"<" else "png"
        name = f"{slug}_{variant}.{suffix}"
        (self.root / name).write_bytes(file_bytes)

        icon = BrandIcon(brand=brand, slug=slug, variant=variant, file=name,
                         source_url=source_url, added=date.today().isoformat(),
                         used_in=[video_id] if video_id else [])
        self.data.setdefault("brands", []).append(icon.to_dict())
        self._save()
        _log.info("иконка добавлена", extra={"brand": brand, "variant": variant,
                                             "file": name})
        return icon

    def mark_used(self, brand: str, video_id: str) -> None:
        for entry in self.data.get("brands", []):
            if entry.get("slug") == slugify(brand) and video_id not in entry.get("used_in", []):
                entry.setdefault("used_in", []).append(video_id)
        self._save()

    def _save(self) -> None:
        self.data["updated"] = date.today().isoformat()
        write_json(self.manifest_path, self.data)


def load_library(cfg) -> BrandIconLibrary:
    root = cfg.path("paths.assets_dir", "assets") / "brand_icons"
    root.mkdir(parents=True, exist_ok=True)
    return BrandIconLibrary(root)

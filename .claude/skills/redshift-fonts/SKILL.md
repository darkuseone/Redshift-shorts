---
name: redshift-fonts
description: Проверка кириллицы и лицензии шрифта, подключение гарнитур и фолбэков. Используй перед добавлением любого шрифта, при ошибке FONT_MISSING_CYRILLIC и при правке fonts_manifest.json.
---
# redshift-fonts

Правило §3.4, обязательное к исполнению: **перед вшиванием гарнитуры в шаблон
проверь полный кириллический набор глифов и лицензию**, разрешающую
коммерческое использование и встраивание. Шрифт без кириллицы обязан **ронять
прогон**, а не рендерить «квадратики».

## Как проверять

```bash
python -m src.cli fonts-check
```

```python
from src.lib.fonts import validate_font, pick_font

info = validate_font("assets/fonts/Oswald-Bold.ttf")   # бросает FONT_* при провале
path, info, rejected = pick_font(candidates)           # первый годный + журнал отказов
```

`src/lib/fonts.py` разбирает таблицы sfnt напрямую:
* `cmap` (форматы 4/6/12) — реальное покрытие кодовых точек;
* `name` — лицензия (nameID 13/14) и копирайт;
* `OS/2` → `fsType` — бит 1 запрещает встраивание.

Требуемый набор: `А–я` (U+0410–U+044F) плюс `Ё`/`ё` (U+0401, U+0451).

## Известные ловушки

**Bebas Neue, Anton** и большинство популярных condensed-гарнитур кириллицу
**не содержат**. Проверено: Bebas Neue отклоняется с `FONT_MISSING_CYRILLIC`
(66 отсутствующих кодовых точек).

Подходят: **Oswald** (display), **Nunito** (subtitle), **JetBrains Mono** (mono) —
все под OFL-1.1, `fsType = 0`.

## Добавление новой гарнитуры

1. Положи файл в `assets/fonts/`.
2. Прогони `validate_font` — он либо примет, либо назовёт причину отказа.
3. Добавь запись в `assets/fonts/fonts_manifest.json` с лицензией и её URL.
4. Впиши в `fallback_chain` нужной роли.
5. Запусти `python -m src.cli fonts-check` — он должен вернуть `ok: true`.

Отклонённые гарнитуры записывай в раздел `rejected` манифеста с кодом причины:
это экономит время следующему, кто захочет взять «красивый condensed».

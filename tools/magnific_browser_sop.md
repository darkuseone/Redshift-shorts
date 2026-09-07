# Magnific через браузер — SOP

Источник: живой survey + Opus lock. **Kling Unlimited = 720p.** API-коннектор
для «безлимита» запрещён (`unlimited_applies_to_api: false`).
Для полировки 0042 по умолчанию **не вызывается** (`skip_generate=true`).
Только по прямому запросу Маркуса.

Конфиг: `config/magnific_models.json` → блок `web_unlimited`.
Блоки `image` / `video` в том же файле — **API за кредиты**, не путать.

## URL

| Поверхность | URL |
|---|---|
| База приложения | https://www.magnific.com/app |
| Генератор изображений | https://www.magnific.com/app/ai-image-generator |
| Генератор видео | https://www.magnific.com/app/ai-video-generator |
| Апскейлер | https://www.magnific.com/app/tools/upscaler |
| Редирект | https://magnific.ai → www.magnific.com/app |

## Безлимитные (∞) модели — только эти

| Тип | Модель | Параметры |
|---|---|---|
| Stills, предпочтительно | **Nano Banana 2** | Multiple; refs Style/Character до 14 |
| Stills, тоже ∞ | Nano Banana 2 Lite, Nano Banana (старая) | — |
| Stills, альтернатива | **Seedream 5 Pro** | + 5 Lite / 4 / 4 4K / 4.5 — все ∞ |
| Video | **Kling 2.5 Unlimited** | **720p**, 5–10 с, Start/End frames, Multiple |

Модели «C Dream» не существует: имелся в виду **Seedream**.

## Разрешение видео

**Kling 2.5 Unlimited = 720p.** Если UI предлагает 1080p — это платный режим.
Не брать.

## Платное — не трогать

Nano Banana Pro (75–150) · Cinematic (75–150) · GPT 2 (15–975) · прочие
credit-video.

## Апскейл — отдельный инструмент

`…/tools/upscaler`: **Creative** vs **Precision**, модель Magnific, 2×.
Документальные кадры (чип, JWST, фото) → Precision.
Стилизованные → Creative.
Creative выдумывает научные детали. Для фактов — только Precision.

## Контракт результата

`assets/gen/{video_id}/{slot}.{mp4|png}`

Индекс: `source=magnific_browser`, `model_slug` ∈
`kling-25 | nano-banana-2 | seedream-5-pro`, `prompt`, `max_h` (720 для видео).

Прогнать через те же гейты P8, что и сток. Генерация не даёт иммунитета.

## Шаги агента

1. Открыть нужный URL в залогиненной сессии Personal project.
2. Выбрать **только ∞** модель: Nano Banana 2 / Seedream 5 Pro / Kling 2.5 Unlimited.
3. Промпт: буквальное существительное из VO; 9:16; тёмный грейд; акценты только
   red/cyan; без водяных знаков; без читаемого фальшивого текста на бумаге/экране.
4. Видео: **720p**, 5–10 с. Stills: Multiple при батче.
5. Скачать с карточки создания в `assets/gen/{video_id}/{slot}.{mp4|png}`.
6. Зарегистрировать в индексе (`source=magnific_browser`, slug, prompt, max_h).
7. P8 гейты (палитра, когерентность, светлота).
8. Апскейл отдельно, Precision/Creative по типу кадра.
9. **Никогда** не включать Magnific API в расчёте на безлимит.

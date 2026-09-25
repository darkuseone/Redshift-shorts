# Режиссёрский таймлайн — секция `director` сценария

Таймлайн — это решение режиссёра, которое станок исполняет буквально
(`src/lib/director.py`). Что в нём указано — то и будет в кадре; эвристика
P11 не спорит. Проверка до пуша: `python tools/director_check.py scripts/<id>.json`.

## Время = слова, а не секунды

Окна привязаны к **словам речи**: `"at": "лапшу"` — окно начинается там, где
голос произносит «лапшу». Паузы режутся после синтеза, поэтому секунды из
чата к рендеру не совпадут, а слово — совпадёт. Повтор слова: `"кот#2"`.
Сдвиг: `"offset": -0.2` (сек). Без `at` — начало блока. Первый шот ролика
всегда стартует с 0.

## Структура

```json
"director": {
  "footage":  { "<id>": { …футаж… } },
  "shots":    [ { …окно картинки… } ],
  "overlays": [ { …графика поверх… } ],
  "stock_search": false,
  "keep_auto_cta": true
}
```

### footage

| Поле | Обязательно | Что |
|---|---|---|
| `src` | да | прямой URL или путь в репо |
| `source` | да | nasa, wikimedia, magnific, pexels, press… |
| `license` | да | см. `FOOTAGE.md` |
| `page_url` | желательно | страница источника (для спора о правах) |
| `kind` | нет | `video` / `image` (по расширению) |
| `in_sec` | нет | с какой секунды клипа брать |
| `focus` | нет | `[x, y]` 0..1 — центр кропа 9:16 |
| `credit` | нет | подпись в кадре (CC BY, ESA) |
| `ai_generated` | для генерации | `true` — идёт в лимит 20 % |

### shots — окна картинки (по порядку блоков)

Ровно одно из: `footage` · `fullscreen` · `avatar` · `scene`.

| Поле | Что |
|---|---|
| `block` | id блока сценария |
| `at`, `offset` | якорь начала окна |
| `footage` | id из `director.footage` |
| `in_sec`, `fit` | точка входа клипа; `crop` / `pillarbox` |
| `motion` | движение кадра: `kenburns/zoom-in-center`, `kenburns/pan-left`, `parallax/depth-push`… (картинка без motion получает медленный наезд) |
| `transition` | вход окна: `transitions/whip-pan`, `transitions/glitch`, `transitions/gravitational-lens`… или `{ "template": …, "duration": 0.4 }` |
| `hero` | приём поверх кадра: `{ "template": "hero-devices/oversize-word", "params": { "word": "ГОРИЗОНТ" } }` |
| `fullscreen` | полноэкранный текст: `{ "template": "text-fullscreen/kinetic-stack", "content": "КРАСИВО И ЖУТКО", "footage": "<фон>", "accent_word": "ЖУТКО" }` |
| `avatar` | `true` — окно отдаётся ведущему (клипы HeyGen, см. `CLAUDE.md` правило 4) |
| `scene` | `true` — фон бренда (без футажа) |
| `sfx` | звук склейки вместо подобранного по приёму: роль библиотеки (`hit_impact`, `sub_drop`, `riser`, `swipe`, `whoosh_in`, `reveal`, `pop`, `tick`…) или `none` |
| `why` | зачем этот кадр — одна фраза, для QC |

Окно длится до начала следующего. Повторное использование того же видео
продолжает клип, а не крутит его с начала.

### overlays — графика поверх

| Поле | Что |
|---|---|
| `template` | id каталога: `data-viz/counter-roll`, `lower-thirds/source-domain`, `browser-ui/chat-thread`… |
| `renderer` | вместо template — рендер вне каталога: `x_post`, `macos_notification`, `notification_cascade`, `us-map`… |
| `block`, `at`, `offset` | начало |
| `dur` или `until` | длительность (сек, по умолчанию 1.8) или слово конца |
| `params` | содержимое; ключи — в `TEMPLATES.md` для каждого приёма |
| `sfx` | звук появления вместо подобранного (как у шота) |

Финальная кнопка подписки из P11 остаётся, если своей в `overlays` нет
(`keep_auto_cta: false` — убрать).

### Обложка

`meta.cover` — путь в репо к готовой обложке 9:16 (`.jpg`/`.png`), например из
Canva. P12 кладёт её в `thumbnail.jpg` как есть — без генерации и без кадра
ролика. Чистый вариант той же картинки без надписей удобно поставить фоном
хука (`fullscreen.footage`), тогда первый кадр ролика и обложка — одно целое.

## Нормы динамики

- смена картинки или событие каждые **1.5–2.5 с** (движение внутри кадра тоже событие);
- окно без смены и без `motion`/`hero` дольше 4 с — линт предупредит;
- **≥6 разных приёмов на 30 с**: переходы, движения, hero, полноэкранный текст, графика;
- переход-VFX — на смысловом переломе (хук → развитие, ответ, финал), а не на каждой склейке; остальное — прямой рез;
- полноэкранный текст — 1–4 слова, капсом, 2–4 раза за ролик;
- цифра в речи → счётчик/график (`data-viz/*`), источник → плашка (`lower-thirds/source-domain`);
- не накрывать субтитры: графика — в верхней половине, субтитры в центре.

## Пример (30 с, без аватара)

```json
"meta": { "video_id": "redshift_9001", "avatar_mode": "none", … },
"blocks": [ { "id": "b1", "role": "hook", "text": "Что будет с котом в чёрной дыре?" }, … ],
"director": {
  "footage": {
    "cat":  { "src": "https://upload.wikimedia.org/…/cat_jump.webm", "source": "wikimedia",
              "license": "cc-by-sa", "page_url": "https://commons.wikimedia.org/wiki/File:…",
              "credit": "Wikimedia / Автор" },
    "bh":   { "src": "https://svs.gsfc.nasa.gov/vis/…/bh.mp4", "source": "nasa",
              "license": "public_domain", "page_url": "https://svs.gsfc.nasa.gov/…", "credit": "NASA" }
  },
  "shots": [
    { "block": "b1", "fullscreen": { "template": "intro-hooks/hook-question-flash", "content": "КОТ?", "footage": "cat" } },
    { "block": "b1", "at": "чёрной", "footage": "bh", "transition": "transitions/gravitational-lens",
      "motion": "kenburns/zoom-in-center" },
    { "block": "b2", "footage": "cat", "transition": "transitions/whip-pan", "motion": "kenburns/pan-left" }
  ],
  "overlays": [
    { "template": "data-viz/counter-roll", "block": "b3", "at": "сто", "dur": 1.8,
      "params": { "value": 100, "suffix": " КМ" } }
  ]
}
```

## Что делает станок

1. P0 проверяет таймлайн (`DIRECTOR_INVALID` — ошибки, `DIRECTOR_WARN` — советы).
2. P7 (сток) и P9 (генерация) не запускаются — футаж уже выбран.
3. P10 ставит SFX на окна таймлайна — те же, по которым P11 режет кадр:
   каждая склейка звучит — переход-вжух,
   `zoom-punch` — удар, полноэкранный текст — раскрытие, счётчик — тик,
   плашка — щелчок. Порог плотности — `limits.sfx_min_gap_director_sec`
   (0.7 с). Свой звук на кадр — ключ `sfx`.
4. P11 собирает кадр эвристикой, затем `apply_director` переписывает шоты и
   оверлеи по таймлайну: скачивает футаж, режет 9:16, ставит приёмы,
   пересчитывает субтитры.
5. P12 рендерит. Творческие QC-гейты (доля склеек, красного, повтор шаблонов)
   в director-режиме — предупреждения; брак (звук, лицензии, субтитры,
   длительность, генерация >20 %) — блокирует.

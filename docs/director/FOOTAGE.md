# Футаж: где искать, как отбирать, как отдавать станку

Правило: **реальный материал ≥80 %** хронометража, генерация **≤20 %**
(`limits.ai_footage_share_max: 0.20`, QC-14 блокирует). Выбирает режиссёр
своими глазами. В Actions поиск по тегам не запускается (`director` в сценарии
выключает P7 и P9).

## 1. План поиска

Для каждого окна таймлайна — что именно должно быть в кадре и **2–4
кандидата**. Запросы на английском, от конкретного к общему:
«tidal disruption event animation» → «black hole accretion disk» →
«galaxy spiral». Для героя ролика (кот, девушка) — живая съёмка с движением:
кот прыгает, смотрит в камеру, падает на лапы.

**Субагент.** В Claude Code — `Agent` с задачей «найди 3 прямые ссылки на
видео/фото под окно X, лицензия, страница источника». В GrokBot / Gemini —
свой браузер/поиск. Субагент приносит ссылки, отбирает режиссёр.

## 2. Источники (по приоритету)

| Источник | Что там | Лицензия | Как брать |
|---|---|---|---|
| NASA SVS `svs.gsfc.nasa.gov` | научные визуализации: чёрные дыры, TDE, Солнце, Земля | public domain (указать NASA) | прямые mp4 на странице |
| NASA Images `images.nasa.gov` (`images-api.nasa.gov`) | фото и видео миссий | public domain | API без ключа |
| ESA / ESO / NOIRLab | телескопы, иллюстрации | CC BY 4.0 — `credit` обязателен | прямые файлы |
| Wikimedia Commons | всё подряд, в т.ч. животные | CC0 / CC BY / CC BY-SA — смотри страницу | `upload.wikimedia.org/...` |
| Internet Archive | архивная хроника | по позиции | `archive.org/download/...` |
| Magnific / Freepik stock | качественный сток, логотипы | лицензия подписки | **сайт**: 100 бесплатных скачиваний/день (браузер GrokBot); **MCP API**: 150 кредитов за видео — только если есть кредиты (`account_balance`) |
| Pexels / Pixabay | живая съёмка, животные | Pexels / Pixabay license | сайт или API по ключу |
| Пресс-кит компании | логотипы, скриншоты продукта | press kit / editorial | с подписью источника |

Предпросмотры Magnific (`videoPreviewUrl`) — только посмотреть, в ролик не идут.

## 3. Смотреть своими глазами

```
curl -L -o /tmp/cand.mp4 "<url>"
ffprobe -v error -show_entries format=duration:stream=width,height -of json /tmp/cand.mp4
ffmpeg -loglevel error -i /tmp/cand.mp4 -vf "fps=1/2,scale=320:-1,tile=4x2" -frames:v 1 /tmp/cand_grid.jpg
```
Открыть сетку и решить: про ту ли фразу кадр, нет ли водяного знака, текста
на чужом языке, логотипов конкурентов, рывков; где лучший кусок (`in_sec`).
Вертикаль не обязательна — станок кропает 9:16 по центру внимания (`focus`
задаёт точку вручную: `[0.3, 0.5]`).

## 4. Генерация ≤20 %

Только когда реального кадра нет в природе (кот внутри горизонта событий).
1. Инструмент агента по подписке: GrokBot → Magnific в браузере (бесплатные
   модели) или Grok Imagine.
2. Magnific MCP — сначала `account_balance`; нет кредитов → не генерировать.
3. xAI API (ключ в secrets Actions) — не из чата. Нет баланса → пропуск.
4. Ничего не доступно → окно закрывается реальным материалом или
   полноэкранным текстом/графикой. Не растягивать генерацию.

В таймлайне такой футаж помечается `"ai_generated": true`.

## 5. Как отдать станку

В `director.footage` сценария:
```json
"bh_tde": {
  "src": "https://svs.gsfc.nasa.gov/vis/<путь к файлу>.mp4",
  "kind": "video", "source": "nasa", "license": "public_domain",
  "page_url": "https://svs.gsfc.nasa.gov/<id страницы>", "credit": "NASA",
  "in_sec": 3.0
}
```
- `src` — прямой URL файла (Actions скачает сам) или путь в репо.
- Временные ссылки (с `token=`/`exp=`) протухают — такой файл кладётся в
  репо: `assets/footage/director/<video_id>/<id>.mp4`, ≤15 МБ
  (пережать: `ffmpeg -i in.mp4 -t 12 -vf scale=-2:1080 -crf 26 out.mp4`).
- `license` из списка: public_domain, cc0, cc-by, cc-by-sa, pexels, pixabay,
  magnific, freepik, owner, generated-owned, press_kit, editorial_source_figure, nasa, esa.
- `credit` — если лицензия требует подписи (CC BY, ESA, ESO) — мелко в углу.

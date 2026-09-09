# TZ-REDSHIFT-GROK

Техническое задание исполнителю (Grok). Сессия автора ТЗ: **только эти два файла**. Код пайплайна не менять по этому коммиту. Build не требуется.

Соседний индекс: `TZ-REDSHIFT-INDEX.md`.

Если факт не подтверждён чтением файла в этой сессии или явным правилом заказчика — в карточке стоит **«не подтверждено»**. Внешние субагенты (лицензии стоков, бенчмарк Shorts, поля API HeyGen/EL/GLM) в этот документ **не прислали payload** — их URL, цифры каналов и списки полей API **не выдумывать**.

---

## 0. Конституция

1. Продукт не переизобретается. Остаётся: JSON-сценарий → Short **1080×1920**, **35–70 с**, версии **A/B**, аватар, стоки + Ken Burns + HyperFrames, **QC-19** blocking (§11.1). Цель — система работает **как задумано** + закрыть **10 жалоб заказчика** + умный отбор (шаблоны / карты / футаж), не новая архитектура.
2. Канал: физика, космос, астрофизика, медицина, генетика, молекулярка, ИИ **как научный инструмент**. Тон: quiet awe. Кликбейт, Caps, жёлтый «YouTube», чужие hue — запрет.
3. Истина бренда: `config/brandbook.json`. Ink `#111214`, white, paper `#F7F5F3`, accent `#C8453D`, cyan `#36EFFF`, space `#0B132B`, panel `#1A1F2E`. Safe: top **150** / bottom **400** / right **250**. `face_band_y` **350–750**. Plaque enter **200–280 мс**. Accent share **≤12%**.
4. Не плодить оркестраторы, «ещё один пайплайн», новые P-шаги. Правки — в существующих P0–P12, `src/lib/`, `config/`, `templates/`, тестах.
5. Один тикет = один diff. После каждого: pytest затронутого пакета + `validate` на 0042 и 0047.
6. Не сканировать `assets/`, `cache/`, `output/` ради «на всякий случай».
7. Голос: не менять `voice_id` / клоны `voice_pool` без отдельного тикета.
8. Правила заказчика, которые **перебивают** текущие docs/config:
   - доля AI-генерации футажа **≤10%** (не 40% в `instruction.md` §5.9 и не 0.35 в `config.yaml`);
   - скачивание стоков **≤1080p**;
   - **+30%** запас кандидатов **до** платной критики;
   - Grok Vision **только серая зона**; дешёвый mid-critic — **GLM**.
9. Жалобы 1–10 закрываются MUST, не SHOULD.
10. Нет приёмки вида «сделать умнее». Только число, тест, CLI, артефакт (`build_report`, `edit_plan`, SRT, `assets_manifest`, `cost_report`).

### 10 жалоб заказчика (якоря)

1. Слабый хук / петля.
2. VO ≠ SRT ≠ картинка ≠ карта.
3. Аватар вылезает из кадра / деревянный кадр.
4. Анимации / Ken Burns / шаблоны не в смысл.
5. Тупой поиск футажа.
6. Слишком много шаблонов, нет смысла (world-map на «миров», NK на CTA, chat на «нейросет», beat-freeze на «бит»).
7. Карты / VFX off-brand (жёлтый, mint, GitHub-dark, розовый 0047).
8. Деревянный аватар (жесты API — LATER, **не подтверждено**).
9. SFX мимо / кровати повторяются.
10. Слишком много генерации.

---

## 1. Карта P0–P12

Что обещает `instruction.md` / playbook vs что делает код **на момент чтения** (без повторного скана).

| Шаг | Файлы | Обещание docs | Факт кода |
|---|---|---|---|
| **P0** | `src/p0_validate/validator.py` | Блокирующие коды §8.2; хук ≤3 с (`script_playbook.md`, `limits.hook_sec: 3.0` в config для окна P5) | `HOOK_MAX_SEC = 5.0`. Длина хука / петля — **warnings**. `HOOK_GREETING` — blocking. Filler: хезитации blocking, дискурсивные — warnings. `NO_SOURCE` только для `ai/space/tech/medicine`. Категория `science` (0047) может уйти без `sources[]`. |
| **P1** | `src/p1_plan/planner.py` | Режимы по роли; первый аватар ≤0:06 | `AVATAR_FIRST_APPEARANCE_LATE` — **conflict warning**, не блок выдачи. `mode_hint` из сценария побеждает. |
| **P2** | `src/p2_tts/tts.py` | Буфер +18–25% | Блочный TTS; fingerprint speech-only. ElevenLabs: `stability 0.30`, `style 0.45`, `eleven_v3`. |
| **P3** | `src/p3_speech_opt/optimizer.py` | Срез пауз; punch hold 320 мс | `punch_hold_ms: 320`. `remap_time` сдвигает SRT вместе с вставленной тишиной (последний покрывающий сегмент). |
| **P4** | `src/p4_align/aligner.py` | Word SRT 250–450 мс | Провайдер → energy fallback. `top_up_emphasis` до 1/6–8 слов. SRT через `glue_short_cues`. |
| **P5** | `src/p5_replan/replanner.py` | Аватар 35–60%; события ≤2.5 с; нет соседних full-frame аватаров | Итеративно share / interstitial / appearance. FS-карты синкаются к spoken punch (`accent_card_start`). Внутренние события = `kenburns_restart` / `push_in` **по таймеру**, не word-lock. `punch_in` в первую секунду, если первый слот >0.8 с. |
| **P6** | `src/p6_avatar/avatar.py`, `src/providers/avatar.py` | По сегментам HeyGen | Склейка соседних same-block. Adjacent-without-gap — **warn**. Без API key — two-phase prepared. Payload: `avatar_id`, `avatar_style: normal`, `engine`, `model_version`, transparent bg, audio URL. **Жестов / look-at / рук в коде нет.** Mock — RMS рта. `heygen.compose_zoom: 2.7` от `face_bbox`. |
| **P7** | `src/p7_broll_search/search.py` | EN-запросы; ≤50 скачиваний; дешёвый stage1 | Stage1: лицензия, **короткая сторона ≤1080**, duration, ultrawide, watermark-строки, thematic junk; **палитра после скачивания**. Press `og:image` для evidence+`source_ref`. Sci pad extras. **Mixkit = MockStock даже в live.** Роутинг: `config/stock_sources.yaml` (nasa, esa, freepik, pexels, pixabay, mixkit, internet_archive, press, magnific). ESA как live-клиент в `stock.py` **не реализован** (только nasa, pexels, pixabay, freepik, IA, mock mixkit). |
| **P8** | `src/p8_broll_judge/judge.py` | Cheap → Gemini → Grok arbiter 8 | `vision.primary/arbiter = gemini`, `allow_xai: false`. Арбитраж **всех** evidence/twist, не только серой зоны. Незаполненное → P9. `skip_live` → `SEED_SCORE 0.62`. GLM-адаптера **нет**. |
| **P9** | `src/p9_generate/generate.py` | Пустые слоты; AI ≤40% (instruction) | Cap `limits.ai_footage_share_max: 0.35`. 3 попытки → empty. Generated vs `reject_threshold 0.45`. В footage library не пишется. Пустой слот уже предпочтительнее после 3 фейлов. |
| **P10** | `src/p10_audio/audio_build.py`, `src/lib/sfx_library.py` | SFX из библиотеки; кровати ≤15 | INTENTS: `card_appear` vs `picture_in`. Script SFX + density ≤1/2 с (collapse может съесть card SFX). `pick_bed` tags+hash+`used_in`; **запрета «не из соседнего ролика» нет**. |
| **P11** | `src/p11_assemble/assemble.py` (~4052) | A/B; meaning pick; source cards | Hook picker есть. Source bulky cards на аватаре скипаются. Ladder для пустых слотов. `_rich_terminal_copy` **выдумывает** `# willow_check` / `surface_code`. `soften_on_screen_copy` может разъехаться с VO. Gaze plaque — **хардкод regex «кубит»**. CTA Subscribe скрыт только для `redshift_0042`. `_force_ab_difference` крутит KB/transitions от seed, не смысловые пулы. |
| **P12** | `src/p12_render_qc/{render,qc,vision_qc}.py` | 19 blocking QC; §11.2 vision | QC-1…19 + extra 20–25, 29, 30. **§11.2 `blocking: False`**. QC-14 всё ещё 40%/0.35. QC-17 fail только при overlap **< 1.0** (почти никогда). `_subtitle_drift` почти не меряет. Accent share QC-30 non-blocking. QC-21: ungrounded share ≤30% шаблонов **с** needs; need-less игнорируются. QC-3: таймерный KB считается visual event. QC-11: offset клипа vs timeline, **не рот vs аудио**. QC-7: overlay bboxes; HyperFrames path может **не заполнять** `safe_zone_violations`. |
| **HF** | `src/lib/render/hyperframes/{composition.py,~1022; templates.py,~14723; captions.py,~1172}` | Бренд, safe zone, смысл | Off-brand hex: **876 литералов в 25 файлах**, хуже всех `templates.py` (439). Файл шаблонов **не прочитан целиком**. |
| **Schema** | `src/lib/schema` / script schema | Категории канала | `CATEGORIES`: `ai, space, tech, medicine, science`. Отдельных `genetics` / `molecular` / `physics` **нет**. `SCREEN_TEMPLATES` включает `browser, notepad, search, chat_ai, arxiv_card, patent_card`; assemble mapping использует `browser, search, chat, paper, arxiv`. |
| **Шаблоны** | `templates/` + `template_scenarios.json` | 204 шаблона, ротация, A/B | 204 / 12 cat; frequency signature 52, variant 122, rare 30; retired 9, gated 2. 105 intents. `specific_weight_min: 20`. **Пустые `needs`/`signals_any` = always match.** `FrequencyBudget` saturates signature после 4 пиков на 80%. `template_scenarios.index.json` **не существует**. |
| **Сценарии** | `scripts/redshift_0042.json` … `0047.json` | Хук, sources, meta | `meta.hook` есть **только у 0042**. 0047: хук ~7.2 с, `avatar: on` на хуке, `source_ref: nature.com` при **пустом** `sources[]`. Хуки 0042–0046 ~3.1–4.4 с (часть уже >3 с playbook). |
| **Топик** | `config/sources.yaml`, `config.yaml` | Автопоиск тем | NASA, ESA, arXiv `cs.AI` + `quant-ph`, Nature, MIT TR, ScienceDaily. RSS генетики/медицины **нет**. `auto_topic_search: false`. |
| **VFX** | instruction §1.10 vs config | VFX ≤2× по 2–5 с | `limits.bg_vfx_per_video: 6`, `bg_vfx_sec: [1.5, 8]`. |

Эмпирика подбора (жалоба 6), уже наблюдалась на прогонах:

| Текст / слот | Что выстрелило | Почему |
|---|---|---|
| Кольская кора / «миров» | `geo-world-map` | keyword `миров` |
| 0047 CTA, empty fired | `north-korea-locked-down` | fallback + intent `geo-north-korea` (`закрыт`/`изоляц`) |
| белок + «нейросет» | `ai-chat-reveal` | keyword нейросети |
| «Квантовый бит живёт» | `beat-freeze-cut` | `бит` |

---

## 2. Gaps: жалоба × шаг × улика × слот

| ID | Жалоба | Шаг | Файлы | Улика | Слот |
|---|---|---|---|---|---|
| G01 | 1 хук | P0, P5, P12 | `validator.py` (`HOOK_MAX_SEC`), `qc.py` (QC-29), 0047 | Playbook ≤3 с; P0 warn при 5.0 с; 0047 ~7.2 с + avatar on; QC-29 смотрит on-screen ≤1 с, не «не talking head» | **S0** MUST-001,002 |
| G02 | 1 петля | P0 | `validator.py` loop checks | Warnings, никогда не блок | **S0** MUST-003 |
| G03 | 2 рассинхрон | P3, P11, P12 | `optimizer.py` `remap_time`; `assemble.py` `_rich_terminal_copy`; `vision_qc.py` | Punch-hold SRT двигает; терминал Willow выдуман; §11.2 non-blocking; `skip_live` = pass | **S0** MUST-004,006 |
| G04 | 2 source card | P0, P11 | `validator.py` `NO_SOURCE`; assemble source card | Карта требует `show_on_screen` **и** (`proof_card`/`snippet`/`highlight_line`). 0047 `source_ref` без `sources[]`. `science` не в NO_SOURCE | **S0** MUST-005,015 |
| G05 | 3 кадр аватара | P1, P5, P6, P12 | `planner.py` LATE warn; `compose_zoom: 2.7`; QC-7 | Late = warning. Zoom давит. Mode B 50/50, лицо под капшн. Gaze = regex кубит / 0042 | **S0** MUST-008,009,028 |
| G06 | 3 губы | P12 | `qc.py` QC-11 | Offset клипа, не рот. Честный статус — MUST-026; настоящий lip-sync — LATER-003 | **S0** / LATER |
| G07 | 4 KB/события | P5, P11 | `replanner.py` timer events; `_force_ab_difference` | KB по duration/rotation; A/B = seed, не meaning pools | **S0** MUST-014; SHOULD-002 |
| G08 | 5 поиск | P7, P8 | `search.py`, `judge.py` | Запросы = script EN + CONCEPTS + role metaphors + pads. Палитра после download. Mixkit mock. Arbiter на каждый evidence/twist. дыры → text/gen | **S0** MUST-016…020 |
| G09 | 6 шаблоны | P11, picker | `template_scenarios.json`, `templates.py`, FrequencyBudget | 204 / 105 intents; empty triggers always-fire; geo-generic weight 2 тянет NK/Spain/US | **S0** MUST-010…013 |
| G10 | 7 бренд | HF, P12 | `templates.py` hex; QC-30; instruction changelog yellow/mint | 876 off-brand hex. Нет QC чужого hue в оверлеях HF (только footage palette + accent share) | **S0** MUST-021,013 |
| G11 | 8 дерево | P2, P6 | `providers/avatar.py` | Нет gestures в payload. Mock RMS. API жестов **не подтверждено** | **LATER** LATER-001 |
| G12 | 9 звук | P10 | `audio_build.py`, `sfx_library.py` | Density collapse ест card SFX. Кровать не банится по соседнему ролику | **S0** MUST-022 |
| G13 | 10 gen | P9, P12, docs | `generate.py`, QC-14, instruction §5.9, `config.yaml` | 0.35 / 40% / заказчик **10%**. Empty после 3 фейлов уже есть | **S0** MUST-007 |
| G14 | hard-rule bypass | P12 | `vision_qc.py`, QC-17, QC-21 | Зелёный QC при мусоре на глазу | **S0** MUST-024 |
| G15 | VFX cap drift | P11/config | instruction §1.10 vs `bg_vfx_per_video: 6` | Docs и конфиг врут друг другу | **S0** MUST-021,024 |
| G16 | доноры | config | `sources.yaml`, `stock_sources.yaml` | Нет genetics/medicine RSS. ESA yaml без клиента. Лицензии URL **не подтверждено** | **S0** MUST-027 |

Слоты S1–S3 не открываются, пока S0 по жалобе не закрыт тестом.

---

## 3. MUST

Формат карточки обязателен. `files cannot` — оркестратор, новые P-шаги, `voice_id`, сканы `output/`.

---

### MUST-001 — M-HOOK — хук ≤3 с блокирует P0

**S/M/L:** S  
**Жалоба:** 1  
**Зависимости:** —

**Проблема.** Playbook и `limits.hook_sec: 3.0` требуют хук ≤3 с. Валидатор держит `HOOK_MAX_SEC = 5.0` и не блокирует. 0047 (~7.2 с) проходит. Хуки 0042–0046 ~3.1–4.4 с тоже могут проходить как warning.

**Корень.** `src/p0_validate/validator.py` → `HOOK_MAX_SEC`, проверка длины хука (warning, не blocking code `HOOK_TOO_LONG`).

**Изменение.** `HOOK_MAX_SEC = 3.0`. `HOOK_TOO_LONG` — blocking §8.2. Согласовать сообщение с `script_playbook.md`. Не трогать `limits.hook_sec` в P5 иначе, чем синхронизировать константу (один источник: config или общий const).

**Можно трогать:** `validator.py`, тесты P0, при необходимости `instruction.md` §8.2 (код ошибки уже обещан).  
**Нельзя:** переписывать P5 окно ради «мягче»; менять сценарии 0042–0047 содержимое VO без отдельного тикета (они **должны начать падать** — это приёмка).

**Тест + CLI.**
- pytest: хук 3.1 с → blocking `HOOK_TOO_LONG`; хук 2.9 с без greeting → pass.
- `python -m src.cli validate scripts/redshift_0047.json` → fail.
- Хотя бы один из 0042–0046 с хуком >3 с → fail (зафиксировать в тесте имена файлов).

**Приёмка.** Ни один скрипт с spoken hook >3.0 с не получает `ok` от P0. 0047 красный.

---

### MUST-002 — M-HOOK — первая секунда не talking head

**S/M/L:** M  
**Жалоба:** 1, 3  
**Зависимости:** MUST-001 (длина уже жёсткая)

**Проблема.** Хук с `avatar: on` (0047) и/или первый слот >0.8 с даёт talking head в первую секунду. QC-29 проверяет, что хук **на экране** ≤1 с, но не запрещает, что это лицо. P5 ставит `punch_in`, если первый слот >0.8 с — это зум, не смена роли.

**Корень.** `src/p5_replan/replanner.py` (логика первого слота / `punch_in`); `src/p12_render_qc/qc.py` QC-29; сценарии с `avatar: on` на hook-блоке.

**Изменение.** Правило: интервал **[0.00, 1.00)** не может быть `role=avatar` / talking-head full-frame. Допустимы: card / b-roll / title / freeze кадра, не лицо. QC-29 (или новый QC-hook-face) **blocking**, если в первую секунду лицо аватара занимает кадр. P1/P5 не планируют avatar-слот, стартующий <1.0 с.

**Можно:** `planner.py`, `replanner.py`, `qc.py`, тесты.  
**Нельзя:** запрещать аватар во всём хуке после 1.0 с; менять `compose_zoom` здесь (это MUST-009).

**Тест + CLI.** Фикстура edit_plan: avatar slot `start=0` → QC fail. Слот `start=1.0` + card 0–1 → pass. Прогон mock 0042: в `edit_plan` первый кадр не avatar.

**Приёмка.** На 0047-классе (avatar on hook) P0 или P5/QC блокируют до рендера. QC-29 не зелёный, если хук = talking head.

---

### MUST-003 — M-HOOK — loop / payoff / late-avatar больше не warning-only

**S/M/L:** M  
**Жалоба:** 1, 3  
**Зависимости:** MUST-001, MUST-008 (late avatar — соседний код)

**Проблема.** Проверки петли и payoff-too-early в P0 — warnings. Ролик с незакрытой петлёй уходит в выдачу. `AVATAR_FIRST_APPEARANCE_LATE` тоже warning (закрывается MUST-008; здесь — loop/payoff).

**Корень.** `src/p0_validate/validator.py` — loop / payoff checks (warning path, не blocking codes).

**Изменение.** Коды вроде `LOOP_UNCLOSED` / `HOOK_UNANSWERED` / `PAYOFF_TOO_EARLY` (имена свернуть к существующим §8.2, не плодить синонимы) — **blocking**. Порог payoff: не раньше окна, которое уже описано в playbook (не выдумывать новое число; если в коде порог есть как warn — поднять до block). Если символа нет в §8.2 — добавить **одну** строку в instruction §8.2 в том же diff.

**Можно:** `validator.py`, `instruction.md` §8.2, тесты P0.  
**Нельзя:** semantic vision вместо структурной петли.

**Тест + CLI.** Скрипт без ответа на хук в последнем блоке → blocking. Скрипт с ответом → pass. `validate` 0042 (есть `meta.hook`) остаётся зелёным **только если** петля структурно закрыта; если 0042 сам нарушает — падает, не «исключение для демо».

**Приёмка.** Warning-only loop не существует. Выдача с незакрытой петлёй невозможна через P0.

---

### MUST-004 — M-SYNC — запрет галлюцинаций overlay / terminal

**S/M/L:** M  
**Жалоба:** 2  
**Зависимости:** —

**Проблема.** `_rich_terminal_copy` в сборщике **изобретает** строки `# willow_check`, `surface_code` и подобное, которых нет в VO/source. `soften_on_screen_copy` может увести карточку от сказанного.

**Корень.** `src/p11_assemble/assemble.py` → `_rich_terminal_copy`, `soften_on_screen_copy`.

**Изменение.** Любой on-screen текст (terminal, FS, plaque, source card, chat) ⊆ объединение: `blocks[].text` + `sources[]` + явные `on_screen` / `highlight_line` / `snippet` / `proof_card` сценария. Нет шаблонных «научных» идентификаторов. Если нечего показать — шаблон не берётся (пустой слот / text card из **сказанного** слова), а не выдумка.

**Можно:** `assemble.py`, hyperframes copy-builders, тесты assemble.  
**Нельзя:** расширять промпты LLM «дописать терминал».

**Тест + CLI.** Фикстура 0042-like Willow: в слоях нет `# willow_check` / `surface_code`, если их нет в JSON. pytest по дереву оверлеев. CLI mock assemble: grep артефакта / dump layers.

**Приёмка.** Нет токена на экране, которого нет в script∪sources. Регрессия на выдуманный Willow — обязательный тест.

---

### MUST-005 — M-SYNC — `source_ref` ⇒ `sources[]`; NO_SOURCE для science

**S/M/L:** S  
**Жалоба:** 2  
**Зависимости:** —

**Проблема.** `NO_SOURCE` не действует на `category: science`. 0047 имеет `source_ref: nature.com` и пустой `sources[]`. Карта источника в P11 требует `show_on_screen` и (`proof_card`|`snippet`|`highlight_line`) — при пустом массиве карта не из чего честно собрать.

**Корень.** `src/p0_validate/validator.py` → `NO_SOURCE` allowlist категорий. Схема `sources[]`. P11 source-card guard.

**Изменение.** Если в блоке/`meta` есть `source_ref` **или** категория `ai|space|tech|medicine|science` — нужен непустой `sources[]` с полями, которые уже требует схема (не выдумывать новые обязательные поля сверх схемы). `NO_SOURCE` blocking для `science`. Несогласованность `source_ref` без записи в `sources[]` — отдельный blocking код (или тот же `NO_SOURCE`).

**Можно:** `validator.py`, схема, тесты P0.  
**Нельзя:** подставлять фейковый Nature title в assemble «чтобы карта была».

**Тест + CLI.** 0047 → `NO_SOURCE` (или новый код) fail. Копия 0047 с валидным `sources[]` → pass. Категория `science` без sources → fail.

**Приёмка.** Нет ok-validate при `source_ref` и пустом `sources[]`.

---

### MUST-006 — M-SYNC — vision_qc §11.2 blocking при mismatch >10%

**S/M/L:** M  
**Жалоба:** 2  
**Зависимости:** MUST-004 (иначе critic ловит свой же выдуманный текст)

**Проблема.** Смысловой QC §11.2 в коде **non-blocking** (`blocking: False`). `skip_live` рапортует pass. Ролик с картинкой не про то уходит как success.

**Корень.** `src/p12_render_qc/vision_qc.py` (флаг blocking, `mismatch_share`); вызов из `qc.py` / render pipeline; `features.vision_qc: true` в `config.yaml`.

**Изменение.** Если `mismatch_share > 0.10` — **blocking**, ролик не success. `skip_live` **не** имеет права ставить semantic pass; либо skip явно `qc_skipped_semantic` и статус не «выдан», либо гоняется дешёвый текстовый matcher overlay⊆script (MUST-004) как суррогат в mock. Порог 10% — заказчик/конституция; записать в config ключ с комментарием, QC читает его.

**Можно:** `vision_qc.py`, `qc.py`, `config.yaml`, тесты P12.  
**Нельзя:** слать каждый кадр в Grok Vision (это MUST-019).

**Тест + CLI.** Фикстура mismatch_share=0.11 → blocking fail. 0.09 → pass. Тест skip_live: нет `status=success` с пустой semantic. Mock run: в `build_report` видно semantic result.

**Приёмка.** Ролик с >10% mismatch не shipped. skip_live не маскирует это зелёным success.

---

### MUST-007 — M-GEN — доля генерации ≤10%

**S/M/L:** S  
**Жалоба:** 10  
**Зависимости:** —

**Проблема.** Заказчик: gen **≤10%**. Код: `limits.ai_footage_share_max: 0.35`. Instruction §5.9: **40%**. QC-14 завязан на старые 40%/0.35. Пустой слот после 3 фейлов уже предпочтительнее слабой генерации — сохранить.

**Корень.** `config.yaml` → `limits.ai_footage_share_max`; `instruction.md` §5.9; `src/p9_generate/generate.py` cap; `src/p12_render_qc/qc.py` QC-14.

**Изменение.** Везде **0.10**. Instruction §5.9 переписать на 10% (не «потом подкрутим»). QC-14 fail если share >0.10. P9 не заказывает gen, если текущий план уже на границе. Empty > weak gen — без изменения этой политики.

**Можно:** config, instruction §5.9, `generate.py`, `qc.py`, тесты P9/P12.  
**Нельзя:** поднимать cap «на сложный ролик»; генерировать весь фильм.

**Тест + CLI.** Plan с 12% gen duration → QC-14 fail. 9% → pass. Unit: генератор отказывается от 4-го слота, если суммарно выйдет >10%.

**Приёмка.** Три числа совпали: docs, config, QC. Ни один shipped mock/live с >10% AI footage.

---

### MUST-008 — M-AVATAR — late first appearance блокирует выдачу

**S/M/L:** S  
**Жалоба:** 3  
**Зависимости:** MUST-002 (первая секунда пустая от лица — не противоречит: первый аватар после 1.0 с и ≤0:06)

**Проблема.** Docs: первый аватар ≤0:06. Код: `AVATAR_FIRST_APPEARANCE_LATE` — warning в P1. Ролик без лица до середины уходит.

**Корень.** `src/p1_plan/planner.py` → `AVATAR_FIRST_APPEARANCE_LATE`.

**Изменение.** Conflict → **delivery block** (P1 error или QC, но один путь). Сохранить окно ≤6 с после старта **речи/ролика** как в instruction. Сочетать с MUST-002: старт аватара ∈ [1.0, 6.0].

**Можно:** `planner.py`, QC если нужен dual-check, тесты P1.  
**Нельзя:** двигать порог 6 с без тикета.

**Тест + CLI.** План с first avatar at 7.0 с → fail. at 2.0 с → pass. at 0.0 с → fail (MUST-002).

**Приёмка.** Warning-only LATE не существует.

---

### MUST-009 — M-AVATAR — zoom / face_band / captions; не regex «кубит»

**S/M/L:** M  
**Жалоба:** 3  
**Зависимости:** MUST-025 (safe-zone QC должен начать видеть HF)

**Проблема.** `heygen.compose_zoom: 2.7` от `face_bbox` плющит голову и выносит её из `face_band_y 350–750` / под капшн. Brandbook baseline капшна 1100–1280 vs instruction 940–1010 — **два числа в docs**. Mode B split 50/50. Gaze plaque захардкожен под «кубит» / ролик 0042 (часть выносится в MUST-028).

**Корень.** `config.yaml` `heygen.compose_zoom`; композиция аватара в P6 / hyperframes `composition.py`; капшн `captions.py`; assemble gaze helper.

**Изменение.** Zoom не может вытолкнуть лицо из `face_band_y` brandbook. Если bbox после zoom ∩ caption band (нижние 400 px safe) — уменьшить zoom или сдвинуть layout, не «надеемся». Выбрать **один** caption baseline из brandbook (истина — `brandbook.json`); instruction поправить в том же diff, если врёт. Mode B: лицо не под текстовой полосой (safe right 250 / bottom 400).

**Можно:** config zoom (число подобрать тестом, не вслепую 2.7), composition, captions, тесты геометрии.  
**Нельзя:** жесты HeyGen (LATER-001); смена voice.

**Тест + CLI.** Синтетический face_bbox: после compose лицо внутри band, IoU с caption band = 0. QC-7 fail если вылезло. Не завязывать тест на слово «кубит».

**Приёмка.** Нет shipped кадра, где лицо ∩ bottom safe 400. compose_zoom не константа «на глаз» без проверки bbox.

---

### MUST-010 — M-TEMPLATES — пустые needs/signals не always-fire

**S/M/L:** M  
**Жалоба:** 6  
**Зависимости:** —

**Проблема.** Intents с пустыми `needs` / `signals_any` / keywords+patterns всё равно матчятся (пустое = истина). QC-21 считает ungrounded только среди шаблонов **с** needs — need-less невидимы.

**Корень.** Подбор: код picker (template picker / `template_scenarios.json` matcher). QC-21 в `qc.py`.

**Изменение.** Пустой триггер **не матчится**, кроме явно помеченных `catchall: true` (их должно стать 0 или 1 на категорию с весом 0 по умолчанию). QC-21: need-less выбранный шаблон = ungrounded. `specific_weight_min: 20` не спасает пустой триггер.

**Можно:** matcher, `template_scenarios.json`, QC-21, тесты `test_template_picker`.  
**Нельзя:** оставлять «универсальный» geo-generic как always-on.

**Тест + CLI.** Intent с пустыми needs+signals+keywords+patterns → 0 fire на любом тексте. pytest: текст без entity не берёт world-map / NK / chat.

**Приёмка.** Always-match по пустоте невозможен. QC-21 видит need-less.

---

### MUST-011 — M-TEMPLATES — rare geo/finance/social = 0 без entity

**S/M/L:** M  
**Жалоба:** 6  
**Зависимости:** MUST-010, MUST-013 (часть файлов уйдёт)

**Проблема.** `geo-world-map` на «миров»; `north-korea-locked-down` на пустой CTA; `ai-chat-reveal` на «нейросет»; `beat-freeze-cut` на «бит»; `apple-money-count` на «доллар»; `geo-generic` weight 2 тащит NK/Spain/US maps.

**Корень.** `template_scenarios.json` keywords; rarity в манифесте шаблонов; picker weights.

**Изменение.** Для rare geo / finance / social / brand-app: `weight=0` если в сценарии нет **именованной сущности** (страна, биржа, тикер, конкретный продукт, URL домена). World-map: триггер не подстрока `миров` / `мир`. Beat-freeze: не подстрока `бит` без музыкального/ритм-контекста **или** DELETE (предпочтительно DELETE, §9). ChatGPT/Claude exchange — только если в VO названа эта модель/продукт.

**Можно:** JSON intents, манифест rarity, picker, тесты на 4 эмпирических кейса таблицы §1.  
**Нельзя:** «чуть снизить вес» без нуля.

**Тест + CLI.** Фикстуры точных строк из §1 → **не** те шаблоны. Скрипт с entity «North Korea» → NK позволен. `validate`/picker unit.

**Приёмка.** Четыре эмпирических промаха не воспроизводятся.

---

### MUST-012 — M-TEMPLATES — таксономия rarity / topics / requires / forbids / cooldown / brand_ok

**S/M/L:** L  
**Жалоба:** 6  
**Зависимости:** MUST-010, MUST-011, MUST-013

**Проблема.** 204 шаблона, 105 intents, нет единого контракта «когда можно». FrequencyBudget saturates signature после 4 пиков на 80% — variant/rare не живут как задумано (SHOULD-007 дополняет).

**Корень.** Манифесты `templates/`, `template_scenarios.json`, FrequencyBudget (picker).

**Изменение.** У каждого **активного** шаблона поля: `rarity` ∈ {signature, variant, rare}, `topics[]` (из канала), `requires[]`, `forbids[]`, `cooldown_videos` (int), `brand_ok` (bool, default false пока не проверен hue). Picker не выбирает `brand_ok=false`. Cooldown: шаблон не чаще 1 раз в N роликов (N из поля; для signature N≥3 если не задано — **не выдумывать магию**: взять существующий FrequencyBudget и сделать его **жёстким**, не advisory). Документировать поля в `templates/` README или instruction § шаблоны — одна секция.

**Можно:** JSON schema шаблонов, picker, FrequencyBudget, тесты.  
**Нельзя:** новый микросервис ротации.

**Тест + CLI.** Шаблон без `requires` при пустом тексте не берётся. Два подряд mock video_id не берут один signature (если cooldown≥1). `brand_ok=false` → 0 pick.

**Приёмка.** Нет активного шаблона без таксономии. Picker читает поля, не комментарии в markdown.

---

### MUST-013 — M-TEMPLATES — выполнить DELETE LIST

**S/M/L:** M  
**Жалоба:** 6, 7  
**Зависимости:** —

**Проблема.** 9 шаблонов already retired в манифесте, файлы/intents могут жить. Активные нише-чужие стреляют. «На всякий случай» запрещено.

**Корень.** `templates/**`, `template_scenarios.json`, манифест retired. Список §9.

**Изменение.** Удалить **файлы** + записи JSON + intents. Не comment-out. Grok имеет право удалять. После удаления — picker не резолвит id. Retired манифест не ссылается на отсутствующие файлы.

**Можно:** templates, scenarios JSON, тесты, которые импортировали id.  
**Нельзя:** оставить файл «вдруг CTA».

**Тест + CLI.** Тест: каждый id из §9 DELETE отсутствует в индексе picker. `pytest tests/test_template_picker.py`. Сборка 0042/0047 mock не требует удалённых id.

**Приёмка.** `rg` по id удалённых шаблонов в `templates/` и scenarios — пусто (кроме этого ТЗ и changelog).

---

### MUST-014 — M-TEMPLATES — A/B из разных пулов; QC-17 умеет падать

**S/M/L:** M  
**Жалоба:** 4, 6  
**Зависимости:** MUST-012 (пулы), MUST-013

**Проблема.** A/B отличаются seed + `_force_ab_difference` (KB/transitions), не смысловыми пулами. QC-17 требует overlap **< 1.0** чтобы упасть — почти мёртвая проверка. Instruction QC-17 / AB_TOO_SIMILAR.

**Корень.** `src/p11_assemble/assemble.py` → `_force_ab_difference`, hook picker; `qc.py` QC-17.

**Изменение.** Версии A и B берут **разные** шаблоны на hook / hero / cta из **разрешённого** пула (после DELETE). Не «другой Ken Burns того же NK map». QC-17: fail если Jaccard/overlap шаблонных id ≥ порога, который **может сработать** (например ≥0.8, не «только 100%»). Если в instruction уже есть порог — использовать его; если только `< 1.0` в коде — исправить код под docs, docs не под мёртвый код.

**Можно:** assemble A/B, qc.py QC-17, тесты AB.  
**Нельзя:** два разных оркестратора A и B.

**Тест + CLI.** Один сценарий → два edit_plan: `hook_template_id_A ≠ B`, то же для hero/cta если слот есть. Фикстура identical ids → QC-17 fail. `pytest` AB_TOO_SIMILAR.

**Приёмка.** QC-17 падает на копии A==B. Живой прогон 0042 A/B: три слота не клоны.

---

### MUST-015 — M-CARDS — copy из script/source; enter 200–280 мс + SFX

**S/M/L:** M  
**Жалоба:** 2, 7, 9  
**Зависимости:** MUST-004, MUST-022 (SFX библиотека)

**Проблема.** Карты берут смягчённый/выдуманный текст. Brandbook: plaque enter **200–280 мс**. SFX `card_appear` есть в INTENTS, но density collapse и разъезд `picture_in` vs `card_appear` срывают акцент.

**Корень.** assemble card builders; hyperframes enter duration; `audio_build.py` density; `sfx_library.py` INTENTS.

**Изменение.** Текст карты = поля сценария/source (MUST-004). Enter duration clamp **[200, 280] мс** из brandbook, не «сколько шаблон захотел». На appear карты — SFX role `card_appear` (если файла нет — skip **и** запись в `build_report`, не тишина без следа). Не подменять `picture_in`.

**Можно:** assemble, hyperframes enter, audio_build, тесты.  
**Нельзя:** синтезировать SFX.

**Тест + CLI.** Карта с highlight_line «X» показывает «X». Enter duration в edit_plan ∈ [0.20, 0.28]. Если sfx файла нет — `build_report.sfx_skipped[]` не пуст, тест на skip path.

**Приёмка.** Нет карты с текстом вне script∪sources. Нет appear без попытки SFX + отчёта.

---

### MUST-016 — M-SEARCH — смысловые EN-запросы 3–5 + entities + negatives

**S/M/L:** M  
**Жалоба:** 5  
**Зависимости:** —

**Проблема.** Запросы склеиваются из EN сценария + CONCEPTS + role metaphors + sci pads. Много мусорных query, мало сущностей. `queries_per_slot: 7`, `max_candidates_per_query: 14` — объём есть, смысл нет.

**Корень.** `src/p7_broll_search/search.py` (построение queries).

**Изменение.** На слот: **3–5** EN-запросов. Обязательны: именованные сущности из блока (прибор, миссия, вид, метод) + 1–2 визуальных якоря. Negatives: talking head, watermark, UI screenshot, clickbait thumbnail, «stock smile lab» если не медицина-процедура. Убрать pads, которые не связаны с entity блока. Не увеличивать `queries_per_slot` «чтобы умнее» — уменьшить до 5 max.

**Можно:** `search.py`, конфиг queries_per_slot, тесты поиска.  
**Нельзя:** качать 4K; слать сырой пул на Gemini (MUST-018).

**Тест + CLI.** Блок про Willow/квант → queries содержат entity, не содержат «north korea» / random pad. Длина списка 3–5. pytest snapshot queries.

**Приёмка.** На фикстуре 0042/0047 query dump в `build_report.search.queries` 3–5 на слот, с entity.

---

### MUST-017 — M-SEARCH — +30% surplus до платной критики

**S/M/L:** M  
**Жалоба:** 5  
**Зависимости:** MUST-016, MUST-018

**Проблема.** Заказчик: запас **+30%** кандидатов **до** paid critic. Сейчас `target_pool_size: [50,100]` не выражает surplus относительно слотов. Дыры сразу → P9/text.

**Корень.** `search.py` / лимиты `target_pool_size`, `max_candidates_per_query`; переход в `judge.py`.

**Изменение.** Перед первым вызовом Gemini/Grok/Magnific: `len(candidates) >= ceil(1.3 * slots_needing_footage)`. Если нет — добрать **дешёвым** поиском (ещё query), не vision. Если после добора всё ещё <1.3x — не звать paid critic пачками по одному; пометить слот empty / ladder (P11), не жечь arbiter.

**Можно:** search.py, judge.py gate, config, `build_report` счётчик surplus.  
**Нельзя:** добирать генерацией Magnific до 1.3x.

**Тест + CLI.** 10 слотов, 12 кандидатов → critic **не** зовётся, статус underfilled. 13+ → critic может. Метрика в `build_report`.

**Приёмка.** Нет paid vision при surplus <30%. Число в отчёте.

---

### MUST-018 — M-SEARCH — stage1-мертвые не на vision; 1080p тест

**S/M/L:** S  
**Жалоба:** 5  
**Зависимости:** —

**Проблема.** Stage1 уже режет license / short-side ≤1080 / duration / ultrawide / watermark strings. Палитра — **после** download. Есть риск слать отбракованное на Gemini. Заказчик: download **≤1080p** — в config уже `max_download_height: 1080`, нужен регрессионный тест чтобы никто не вернул 4K.

**Корень.** `search.py` stage1; download path; `config.yaml` `max_download_height`.

**Изменение.** Явный deny-list status: не передавать в `judge.py` клипы, не прошедшие stage1. Палитру по возможности на probe до полного download (если probe уже есть — использовать; если нет — не обещать без кода: тогда «палитра после download» остаётся, но **не** vision до stage1). Тест: запрос 4K не сохраняет файл с short-side >1080.

**Можно:** search.py, judge input filter, тесты.  
**Нельзя:** 4K «для качества».

**Тест + CLI.** Mock candidate height=2160 → не в judge list, не на диске как 2160. Stage1 fail reason в report. pytest.

**Приёмка.** `max_download_height==1080` покрыт тестом. Judge input ∩ stage1_fail = ∅.

---

### MUST-019 — M-CRITIC — cheap ≥50% kill; GLM mid; Grok только 0.45–0.70

**S/M/L:** L  
**Жалоба:** 5  
**Зависимости:** MUST-017, MUST-018, MUST-020

**Проблема.** Заказчик: дешёвый фильтр, GLM как cheap critic, Grok Vision **только серая зона**. Сейчас primary/arbiter = **gemini**, `allow_xai: false`. GLM адаптера нет. Арбитраж всех evidence/twist (MUST-020). `vision.arbiter_max_calls: 8`.

**Корень.** `src/p8_broll_judge/judge.py`; `config.yaml` vision.*; отсутствие GLM provider.

**Изменение.**
1. Cheap (без LLM): ≥**50%** входящего пула kill (цель 50–60%). Если cheap kill <50% на фикстуре с заведомым мусором — фильтр дырявый, тикет не закрыт.
2. Mid: адаптер **GLM** (OpenAI-совместимый или тот клиент, что уже есть в `src/providers/` для других моделей). URL/ключ — из env, **не хардкодить endpoint из головы**. Если в репо уже есть glm/zhipu/openrouter helper — использовать; если нет — тонкий клиент в `src/providers/`, не новый оркестратор.
3. Grey zone **только** score ∈ **[0.45, 0.70]** идёт на второй модели. Заказчик сказал Grok Vision — включить `allow_xai` **только** для этой зоны, не для всех. Пока xAI ключа нет — grey идёт на GLM-secondary **или** reject в empty; **не** молча gemini-arbiter на всё.
4. `arbiter_max_calls` снизить (разумный потолок ≤3 на ролик, не 8). Точное число — config + тест.

Поля API GLM/Grok **не подтверждено** субагентом — не выдумывать JSON schema провайдера сверх того, что уже есть для Gemini в коде (повторить паттерн существующего vision call).

**Можно:** judge.py, providers, config, cost_report, тесты.  
**Нельзя:** vision до cheap; Grok на каждый evidence.

**Тест + CLI.** Пул 20 мусорных + 4 годных: cheap kill ≥10. Grey-only: score 0.40 и 0.80 не зовут Grok/xAI. Score 0.55 зовёт второй уровень **не больше** 1 раза на клип. Без ключа — нет exception crash, слот empty + report.

**Приёмка.** Метрики MUST-020 показывают cheap_kill_rate≥0.5 на мусорной фикстуре. Grok/xAI calls = 0 вне grey.

---

### MUST-020 — M-CRITIC — не арбитраж всех evidence/twist; метрики build_report

**S/M/L:** M  
**Жалоба:** 5  
**Зависимости:** MUST-019 (логика grey)

**Проблема.** Код арбитражит **все** evidence/twist. Нет сводки: кандидаты/слот, kill по стадиям, счётчики GLM/Grok/Magnific, gen share, стоимость критика.

**Корень.** `judge.py` ветка evidence/twist; writer `build_report`.

**Изменение.** Evidence/twist не auto-arbitrate. Те же пороги, что обычный слот. В `build_report` (и `cost_report` если cost уже там):  
`candidates_per_slot`, `killed_stage1`, `killed_cheap`, `killed_glm`, `grok_calls`, `gemini_calls`, `magnific_calls`, `gen_share`, `critic_cost`. Имена ключей стабильные — тесты на наличие.

**Можно:** judge.py, report writers, тесты.  
**Нельзя:** новый дашборд-сервис.

**Тест + CLI.** Mock evidence slot не инкрементит grok_calls при score вне grey. `build_report` JSON schema test. CLI mock run 0042: ключи на месте.

**Приёмка.** Нет «обязательного» второго vision на evidence. Отчёт читается без раскопок логов.

---

### MUST-021 — M-CARDS — QC чужого hue; cyan=tech; VFX cap = instruction

**S/M/L:** M  
**Жалоба:** 7  
**Зависимости:** MUST-013 (часть жёлтых шаблонов уйдёт)

**Проблема.** 876 off-brand hex, 439 в `templates.py`. Changelog instruction уже фиксировал leftover yellow/mint/GitHub-dark. QC-30 accent share **non-blocking**. Instruction §1.10: VFX ≤**2×** по **2–5 с**; config: `bg_vfx_per_video: 6`, `bg_vfx_sec: [1.5, 8]`. Cyan `#36EFFF` — tech, не «любой акцент вместо красного».

**Корень.** `templates.py` / CSS literals; `qc.py` QC-30; `config.yaml` bg_vfx_*; instruction §1.10.

**Изменение.**
1. QC blocking: overlay/template fill не из палитры brandbook (допуск ΔE или hex allowlist = brandbook ± белый/ink). Урок 0047 pink — тест-цвет, который обязан падать.
2. Cyan только если слот/тема tech/AI-tool; иначе accent `#C8453D` или ink/paper.
3. Выровнять VFX: **одно** число. Истина заказчика/instruction §1.10 → config и QC привести к ≤2 клипам, длительность ∈ [2, 5] с (не 6 и не 1.5). Если в brandbook другое — brandbook побеждает только для цвета, не для «6 VFX».

`templates.py` целиком **не прочитан** — не рефакторить 14k в этом тикете. QC + вычистить **известные** leftover, попавшие в DELETE/brand_ok=false.

**Можно:** qc.py, config, instruction §1.10 сверка, точечные hex в шаблонах, которые трогает DELETE/taxonomy.  
**Нельзя:** переписать все 14k «заодно».

**Тест + CLI.** Overlay fill `#FF00AA` или yellow leftover → QC fail. Tech card cyan pass; medicine card cyan fail. Plan с 3 VFX → fail. pytest QC.

**Приёмка.** Config VFX = instruction. Чужой hue блокирует выдачу. 0047-pink класс падает.

---

### MUST-022 — M-SOUND — карта → SFX role; кровать не из соседнего ролика

**S/M/L:** M  
**Жалоба:** 9  
**Зависимости:** MUST-015 (appear timing)

**Проблема.** Density ≤1/2 с может выкинуть `card_appear`. Кровати: hash+tags+`used_in` rank, **нет** запрета «не играла в предыдущем ролике канала». Лимиты: кровати ≤15, SFX ≤20, без синтеза (`rejected_patterns.md`).

**Корень.** `src/p10_audio/audio_build.py` `pick_bed`, density collapse; `src/lib/sfx_library.py`.

**Изменение.** Мапа тип карты → SFX intent обязательна. Если файла нет: skip + `build_report` (MUST-015). Density не имеет права удалять **первый** `card_appear` слота — режет другие. `pick_bed`: исключить bed id, который стоит в `used_in` последнего собранного ролика (adjacent). Каталог: не больше 15 beds / 20 sfx в выборе; не добавлять synth в library этим тикетом.

**Можно:** audio_build.py, sfx_library.py, тесты P10.  
**Нельзя:** генерировать музыку/SFX нейросетью в assets.

**Тест + CLI.** Две подряд сборки: bed_id_1 ≠ bed_id_2 при ≥2 кроватях в пуле. Density-фикстура с картой: `card_appear` остаётся. Отсутствие файла → skipped[] + нет crash.

**Приёмка.** Соседние ролики (по `used_in` / output index, не по скану `output/` целиком) не делят кровать. Card SFX не съедается первым.

---

### MUST-023 — M-ARTICLE — ARTICLE_URL / TOPIC на существующем P0–P12

**S/M/L:** L  
**Жалоба:** 5 (контент-вход)  
**Зависимости:** MUST-005, MUST-027 (доноры не выдуманы)

**Проблема.** `auto_topic_search: false`. Нет рабочего режима «вот URL статьи» / «вот тема» поверх текущего валидатора. Заказчик хочет **фичу**, не новый пайплайн.

**Корень.** CLI / P0 вход; `config.yaml` `auto_topic_search`; `config/sources.yaml`.

**Изменение.** Два флага/режима CLI на существующей цепочке:
- `ARTICLE_URL`: загрузка primary source → заполнение `sources[]` + черновик блоков **или** отказ. Если primary не извлекается — **стоп**, не писать VO «из головы».
- `TOPIC`: поиск **только** по уже прописанным донорам `sources.yaml` (после MUST-027). 0 доноров / 0 hits — стоп.
Не включать `auto_topic_search: true` по умолчанию. Не генерировать сценарий без `sources[]`.

Детали HTML parser / RSS client: использовать то, что уже есть для Nature/arXiv; не обещать Firecrawl. Если парсера URL нет — минимальный fetch + title/canonical в `sources[]`, VO всё равно из модели по **процитированным** фактам с обязательным P0 `NO_SOURCE` fail при пустом.

**Можно:** CLI, тонкий ingest, P0, config flag default false, тесты.  
**Нельзя:** P13, отдельный «research agent» сервис.

**Тест + CLI.** URL-заглушка без title → stop, exit≠0. Фикстура с sources[] → P0 pass. TOPIC при пустом yaml hits → stop. `--help` показывает режимы.

**Приёмка.** Без primary source сценарий не validate-ok. Default pipeline JSON-скрипта не сломан.

---

### MUST-024 — M-QC — semantic fail ≠ success; выровнять цифры docs↔config↔QC

**S/M/L:** M  
**Жалоба:** 1–10 (обход hard-rule)  
**Зависимости:** MUST-001, 006, 007, 021 (конкретные цифры)

**Проблема.** QC зелёный, глаз видит мусор: loop warn, §11.2 non-block, QC-17 мёртв, QC-21 слеп к need-less, QC-3 считает timer KB событием, skip_live pass. Instruction и config врут друг другу (gen 40/35/10, VFX 2 vs 6, hook 3 vs 5).

**Корень.** `qc.py`, `vision_qc.py`, `instruction.md` лимиты, `config.yaml`.

**Изменение.** Чеклист в одном diff **после** зависимых тикетов или сразу таблицей констант:
| величина | истина |
|---|---|
| hook max | 3.0 с blocking |
| gen share | 0.10 |
| VFX count | 2 |
| VFX duration | [2, 5] с |
| mismatch | 0.10 blocking |
| download | 1080 short side |
| surplus | 1.3× |
| accent | ≤0.12, QC-30 **blocking** если >12% |

`skip_live` не пишет `qc: pass` по семантике. Итог пайплайна `success` только если blocking QC (включая новые) зелёные.

**Можно:** qc aggregator, config, instruction сверка §5.9 §1.10 §11, тесты «константы совпали».  
**Нельзя:** отключать QC-19.

**Тест + CLI.** Тест читает config и instruction-числа (или единый `limits`) и сравнивает с QC thresholds. skip_live fixture: final status ≠ shipped success если semantic skipped.

**Приёмка.** Нет трёх разных чисел одной величины. Success = все S0 blocking green.

---

### MUST-025 — M-QC — safe-zone HyperFrames пишется; QC-7 ловит

**S/M/L:** M  
**Жалоба:** 3, 7  
**Зависимости:** MUST-009

**Проблема.** QC-7 смотрит overlay bboxes. HyperFrames path может не наполнять `safe_zone_violations`. Капшн/plaque/face живут в HF и проходят мимо.

**Корень.** `src/lib/render/hyperframes/composition.py` (и связанные layout); `qc.py` QC-7. **Полный проход всех renderer’ов не делался.**

**Изменение.** Каждый HF overlay, который рисуется, эмитит bbox в тот же список, что QC-7. Нет «внутреннего» слоя без учёта. Если путь ffmpeg compositor отдельный — **не подтверждено** покрытие: добавить эмит или явно пометить путь как must-fail QC если bboxes пусты при ненулевых overlay.

**Можно:** composition.py, qc.py, тесты bbox.  
**Нельзя:** отключить QC-7.

**Тест + CLI.** Сборка с plaque + captions: `safe_zone_violations` структура не пустая (список проверок ≥1). Намеренный сдвиг в bottom 400 → QC-7 fail. Если compositor path не вызывается в unit — отдельный тест render dry.

**Приёмка.** Пустой violations при наличии оверлеев = QC fail («не мерили»), не pass.

---

### MUST-026 — M-QC — subtitle drift реально меряется; QC-11 честный

**S/M/L:** S  
**Жалоба:** 2, 3  
**Зависимости:** —

**Проблема.** `_subtitle_drift` почти не измеряет. QC-11 — offset клипа vs timeline, но читается как lip-sync.

**Корень.** `src/p12_render_qc/qc.py` → `_subtitle_drift`, QC-11.

**Изменение.** Drift: сравнить word SRT timings с speech timeline (после P3 remap). Порог из instruction/QC docs если есть; иначе fail при |Δ| > **450 мс** на слове (верх SRT окна P4) — не выдумывать 50 мс киноточности. QC-11 переименовать смысл в отчёте: `avatar_clip_offset`, не `lipsync`. Сообщение fail не содержит «губы».

**Можно:** qc.py, тексты отчёта, тесты.  
**Нельзя:** обещать mouth-tracking (LATER-003).

**Тест + CLI.** SRT сдвинутый на 1 с → drift fail. Синхронный → pass. Snapshot текста QC-11 без слова lip/lips.

**Приёмка.** Drift ловит 1 с рассинхрон. Отчёт не врёт про губы.

---

### MUST-027 — M-SOURCES — доноры только с проверенной лицензией

**S/M/L:** M  
**Жалоба:** 5  
**Зависимости:** —

**Проблема.** Нет RSS genetics/medicine. ESA в yaml, клиента нет. Mixkit в live = MockStock. Внешний аудит лицензий **не подтверждено**. Нельзя вписывать URL «из памяти».

**Корень.** `config/sources.yaml`, `config/stock_sources.yaml`, `src` stock providers.

**Изменение.** Тикет = **research + yaml + тест**, не список выдуманных фидов.
1. Для каждого нового донора: поле `license`, `attribution`, `url` только после открытия robots/terms **в diff-комментарии/доке с датой**; если не открыли — запись `status: unconfirmed` и **не** включать в live routing.
2. ESA: либо клиент как у NASA, либо yaml `enabled: false` + SHOULD-004.
3. Mixkit: либо не live, либо настоящий клиент после лицензии (SHOULD-003). До подтверждения — не качать mixkit как «реальный сток».
4. Генетика/медицина: **0 новых URL в этом тикете**, если верификации нет. Тогда явный `gaps.md`/секция instruction «дырка канала» + MUST-023 TOPIC не ищет по пустому.

**Можно:** yaml, provider enable flags, instruction sources, тесты «disabled не зовётся».  
**Нельзя:** выдумать Nature-clone RSS.

**Тест + CLI.** Mixkit в live-режиме не ходит во внешний HTTP (остаётся mock) **или** тест лицензионного флага. ESA disabled → 0 calls. pytest providers.

**Приёмка.** Live routing ∩ `unconfirmed` = ∅. В ТЗ/instruction список дыр честный.

---

### MUST-028 — M-AVATAR — не хардкод redshift_0042 / «кубит»

**S/M/L:** S  
**Жалоба:** 3  
**Зависимости:** MUST-009 (геометрия plaque)

**Проблема.** CTA Subscribe скрыт только для `redshift_0042`. Gaze plaque — regex на «кубит». Это не система, а штопка одного ролика.

**Корень.** `src/p11_assemble/assemble.py` (ветки `redshift_0042`, regex кубит).

**Изменение.** Правила по **ролям/категории/флагам сценария**, не по id. Gaze: если в сценарии есть gaze/look-at поле или роль evidence card — общая plaque. CTA hide — только явный `meta.cta: false` / playbook правило для всех id.

**Можно:** assemble.py, schema meta.cta если нужно, тесты на 0042 и 0047.  
**Нельзя:** `if script_id == ...`.

**Тест + CLI.** Переименовать id 0042 в тесте → поведение CTA/gaze сохраняется от meta, не от имени. 0047 не ловит кубит-regex. `rg redshift_0042` в `src/` — 0 (кроме фикстур/скриптов).

**Приёмка.** Нет id-gated вёрстки в assemble.

---

## 4. SHOULD

Не закрывают жалобы 1–10 в одиночку. Не начинать, пока связанный MUST не зелёный.

### SHOULD-001 — обязательный `meta.hook`

Сейчас `meta.hook` только у 0042. Схема: поле обязательно (текст вопроса хука). P0 сверяет с первым блоком. **После** MUST-001. Файлы: schema, validator, скрипты канала (правка JSON скриптов — да, это контент, не пайплайн-архитектура).

### SHOULD-002 — Ken Burns / push_in к punch-словам

Сейчас `kenburns_restart` / `push_in` по таймеру 2.5 с. Привязать к `accent` / punch words из P4, не чаще playbook. QC-3 не считать таймерный KB «осмысленным событием», если нет word lock. **После** MUST-014. LATER-004 если не влезет.

### SHOULD-003 — Mixkit live vs mock

Факт: Mixkit = MockStock в live. Лицензия **не подтверждено**. Либо выкинуть из live routing, либо клиент после MUST-027. Не оставлять «кажется сток».

### SHOULD-004 — ESA live provider

Yaml обещает ESA. `stock.py` live-клиента нет. Реализовать по паттерну NASA **или** `enabled: false`. Лицензия/API **не подтверждено** — не выдумывать endpoint.

### SHOULD-005 — RSS genetics/medicine

Только после верификации URL (MUST-027). Пока **не подтверждено** — не заполнять yaml «известными» журналами из головы.

### SHOULD-006 — категории schema

`CATEGORIES` без physics/genetics/molecular. Либо enum расширить, либо явная карта `physics→science` в instruction + P0. Не ломать 0042–0047 без миграции.

### SHOULD-007 — FrequencyBudget не saturates signature на 80% после 4 пиков

Variant/rare должны реально выпадать. Тикет после MUST-012. Тест: 10 mock picks → не все signature.

### SHOULD-008 — SCREEN_TEMPLATES vs assemble

Схема знает `notepad`, `patent_card`, `chat_ai`; assemble — `browser, search, chat, paper, arxiv`. Согласовать имена, мёртвые — удалить из схемы.

---

## 5. LATER

### LATER-001 — жесты HeyGen / look-at / руки

В `providers/avatar.py` полей нет. Список API **не подтверждено**. Запрещено «добавить `gesture: wave` наугад». Сначала прочитать актуальный HeyGen API (вне этой сессии). Жалоба 8 частично остаётся, пока нет факта.

### LATER-002 — смена голоса / клонов

`voice_pool` два клона. Без отдельного тикета заказчика не трогать `voice_id`, stability/style только если отдельный звуковой тикет.

### LATER-003 — mouth vs audio lip-sync

QC-11 этого не умеет. Нужен сигнал viseme/landmarks, которого в пайплайне нет.

### LATER-004 — полное word-lock всех внутренних событий

После SHOULD-002. Не блокирует S0.

### LATER-005 — новые оркестраторы / P13 / «переписать compositor»

Конституция запрещает. Если всплывёт в diff — reject.

### LATER-006 — внешний бенчмарк Shorts / лицензионные URL субагентов

Payload субагентов **не подтверждено**. Не вносить цифры просмотров, «как у Veritasium», списки сайтов.

---

## 6. Порядок для Grok

Один тикет = один diff. pytest + `validate` 0042 и 0047 после каждого.

1. **Измерители / QC-ворота**  
   MUST-001 → MUST-003 → MUST-008 → MUST-007 → MUST-026 → MUST-006 → MUST-024  
   (хук/луп/late/gen/drift/semantic/константы)
2. **Поиск и критик (деньги)**  
   MUST-016 → MUST-018 → MUST-017 → MUST-019 → MUST-020 → MUST-027
3. **DELETE + таксономия**  
   MUST-013 → MUST-010 → MUST-011 → MUST-012 → MUST-014
4. **Карты / бренд / звук карт**  
   MUST-004 → MUST-005 → MUST-015 → MUST-021 → MUST-022 → MUST-028 → MUST-009 → MUST-025
5. **Статья / топик**  
   MUST-023 (+ SHOULD-001, SHOULD-005 по мере фактов)
6. **Живость аватара сверх геометрии**  
   LATER-001 только после подтверждённого API

Не начинать шаблоны до QC-ворот: иначе «красивый» picker всё равно уедет в success с хуком 7 с.

---

## 7. Команды

Рабочая директория репо. Зависимости как в `requirements.txt` / README. Не запускать полный live-render «проверить ТЗ».

```bash
# схема + P0
python -m src.cli validate scripts/redshift_0042.json
python -m src.cli validate scripts/redshift_0047.json

# точечные тесты (имена пакетов как в репо)
pytest tests/test_p0_validate.py tests/test_template_picker.py tests/test_meaning.py tests/test_footage_pipeline.py

# после тикета — пакет шага, не «весь мир», если долго
pytest tests/ -q --tb=short -k '<marker>'
```

Смотреть после mock-прогона (когда Grok его делает **в своём** тикете, не здесь):

| Артефакт | Зачем |
|---|---|
| `build_report` | surplus, kill stages, grok_calls, gen_share, sfx_skipped, semantic |
| `edit_plan` | первый слот ≠ avatar, A/B template ids, enter 200–280 мс, VFX count |
| SRT | drift vs punch_hold remap |
| `assets_manifest` | download ≤1080, mixkit mock, gen share |
| `cost_report` | critic_cost, Magnific, Gemini |

Конфиг-якоря (не менять без тикета, кроме MUST, которые явно велят):

- `limits.ai_footage_share_max` → 0.10 (MUST-007)
- `max_download_height: 1080`
- `queries_per_slot` → ≤5 (MUST-016)
- `vision.arbiter_max_calls` → ≤3 (MUST-019)
- `features.vision_qc: true`
- `auto_topic_search: false` пока MUST-023
- `heygen.compose_zoom` — только с bbox-тестом (MUST-009)
- `speech.punch_hold_ms: 320`
- `limits.hook_sec: 3.0`

Эталонные скрипты для регрессии: `scripts/redshift_0042.json` … `0047.json`. 0047 **должен** краснеть на P0 после MUST-001/005, пока контент не починен отдельным контент-тикетом.

---

## 8. Ссылки и дыры чтения

Прочитано и использовано как факт: `instruction.md`, `script_playbook.md`, `rejected_patterns.md`, `config.yaml`, `config/brandbook.json`, `config/stock_sources.yaml`, `config/sources.yaml`, P0–P12 перечисленные в §1, `providers/avatar.py`, picker/QC тесты (прогон: **206 passed, 3 skipped** на `test_p0_validate`, `test_template_picker`, `test_meaning`, `test_footage_pipeline` — снимок сессии автора ТЗ).

**Не прочитано целиком (не опираться как на полный аудит):**

- `src/lib/render/hyperframes/templates.py` (~14723)
- большинство HF renderer’ов
- ffmpeg-путь `compositor.py`
- полный `generation.py` / Magnific prompts
- `docs/` (vNEXT старше; Q2 частично уже в коде: FrequencyBudget, word numbers, parallax dispatch, hook picker, skip_vision)

**Не существует:** `template_scenarios.index.json` (старые docs врут).

**Не сканировалось:** `assets/`, `cache/`, `output/`.

**Субагенты (лицензии, Shorts benchmark, HeyGen/EL/GLM fields): не подтверждено.**  
Не вставлять URL, цифры каналов, имена полей API из памяти модели.

---

## 9. DELETE LIST

Grok **удаляет файлы + JSON index**, не comment-out. Нет 20-роличного «вдруг пригодится».

### 9.1 Уже retired в манифесте — добить файлы и intents

Если файл/intent ещё на диске:

- `browser-ui/app-showcase`
- `blue-sweater-intro-video`
- `macos-notification`
- `notification-cascade`
- `spotify-card`
- `vpn-youtube-spot`
- `lower-thirds/instagram-follow`
- `lower-thirds/tiktok-follow`
- `text-fullscreen/split-flap-board`

### 9.2 Активные нише-чужие — DELETE или rarity=rare + requires[] entity (предпочтение DELETE, если нет 20 роликов канала с этой сущностью)

- `data-viz/north-korea-locked-down` + intent `geo-north-korea` (kw `закрыт`/`изоляц`)
- `nyc-paris-flight`
- `spain-map`
- `us-map*`
- `world-map` (kw `миров`)
- `apple-money-count` (kw `доллар`)
- `star-rating-fill`
- `mk-progress-stat`
- `browser-ui/chatgpt-exchange`
- `claude-exchange`
- `ai-chat-reveal` (fires на `нейросет`) — оставить **только** с requires[] конкретной модели/UI, иначе DELETE
- `message-thread-reveal`
- `reddit-post`
- `x-post`
- `lower-thirds/yt-lower-third`
- `text-fullscreen/beat-freeze-cut` (fires на `бит`)
- `news-ticker` (gated — закрыть окончательно или DELETE)
- `geo-generic` catch-all

`geo-generic` weight 2 не имеет права тащить NK/Spain/US без entity.

### 9.3 Не плодить «на всякий случай». Новые шаблоны — только дыра ниши

Каждый: trigger, rarity, ink/white/red/cyan, SFX role, `brand_ok`, `requires[]`. Без этого — не добавлять.

| Кандидат | Зачем | Не делать если |
|---|---|---|
| Science paper card (domain+title+press frame) | жалобы 2, 6; arxiv/nature | копирует жёлтый «CNN ticker» |
| Terminal/code AI-pipelines | ИИ как инструмент | галлюцинации Willow (MUST-004) |
| Chart / molecule schematic | физика/молекулярка | декоративный «научный шум» |
| Side anchor words | хук без talking head | дубль FS, который уже есть |
| Branded footage plate | источник на стоке | второй YouTube lower-third |

Не добавлять шаблон, пока DELETE 9.1–9.2 не сделан (MUST-013).

---

## 10. Не делать

Из `rejected_patterns.md` + это ТЗ:

- crossfade как основной переход
- zoompan Ken Burns «на весь клип вместо смысла»
- stretch to 9:16
- speaker / аватар как full-anchor весь ролик
- clickbait, ALL CAPS, жёлтый YouTube, mint leftover, GitHub-dark как тема
- meme aggregators; мемы в медицине (существующий запрет)
- генерировать **весь** фильм / аватар вместо стока сверх 10%
- vision / Gemini / Grok / Magnific **до** cheap filter
- новые оркестраторы, P13, параллельный compositor «с нуля»
- 4K downloads
- сырые клипы на Gemini/Grok/Magnific
- synth SFX/music в библиотеку
- `if script_id == redshift_0042`
- выдуманный on-screen код/терминал
- always-fire шаблоны с пустым trigger
- geo/finance/social без entity
- менять voice_id без тикета
- жесты HeyGen без подтверждённого API
- URL доноров из головы
- сканировать output/assets «найти вдохновение»
- закрывать жалобы 1–10 SHOULD-тикетами
- Build/CI зелёный как замена приёмке тикета
- три разных числа одной величины в docs/config/QC

---

## Самопроверка автора ТЗ

- Каждый MUST привязан к прочитанному файлу/символу **или** явному правилу заказчика (10%, 1080p, +30%, Grok grey, GLM).
- Нет «сделать умнее» без числа и теста.
- Жалобы 1–10 имеют MUST, не только SHOULD.
- 10% / 1080p / +30% / Grok-only-grey — в MUST-007, 018, 017, 019.
- Rare шаблоны требуют entity (MUST-011) или DELETE.
- Дыры чтения названы в §8.
- Внешние факты субагентов: **не подтверждено**.

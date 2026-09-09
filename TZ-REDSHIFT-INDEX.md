# TZ-REDSHIFT-INDEX

Индекс к `TZ-REDSHIFT-GROK.md`. Исполнителю (Grok): один тикет = один diff. Код пайплайна в этом коммите не менялся.

**Канал:** физика / космос / астрофизика / медицина / генетика / молекулярка / ИИ как научный инструмент.  
**Продукт:** JSON-сценарий → Short 1080×1920, 35–70 с, A/B, аватар, стоки + Ken Burns + HyperFrames, QC-19.  
**Тон:** quiet awe, без кликбейта. Истина цвета — `config/brandbook.json`.

## Счётчики

| Класс | Кол-во | ID |
|---|---|---|
| MUST | 28 | MUST-001 … MUST-028 |
| SHOULD | 8 | SHOULD-001 … SHOULD-008 |
| LATER | 6 | LATER-001 … LATER-006 |
| DELETE (файлы шаблонов + intents) | 9 уже retired + 16 активных к выпилу/гейту | §9 GROK |
| Новые шаблоны (только дыра ниши) | 5 кандидатов, не «на всякий случай» | §9 GROK |

Жалобы заказчика 1–10 закрываются **MUST**, не SHOULD.

Правила заказчика, которых нет в текущем коде как истины:

- генерация футажа **≤10%** (сейчас `limits.ai_footage_share_max: 0.35`, instruction §5.9 = 40%);
- скачивание **≤1080p** (в `config.yaml` уже `max_download_height: 1080` — закрепить тестом);
- **+30%** запас кандидатов **до** платной критики;
- Grok Vision **только серая зона**; дешёвый критик — **GLM**.

## С чего начинает Grok

Порядок §6 GROK, не «что красивее».

1. **Измерители и QC-ворота** — MUST-001, 002, 003, 007, 026, 027 (хук/луп блокируют; vision_qc блокирует; gen ≤10%; цифры instruction↔config↔QC).
2. **Поиск и критик (деньги)** — MUST-016 … MUST-020.
3. **DELETE + таксономия** — MUST-010 … MUST-014 + §9.
4. **Карты / бренд / SFX карт** — MUST-015, 021, 022, 024.
5. **Статья / топик** — MUST-023, SHOULD-005.
6. **Живость аватара** — MUST-008, 009; жесты HeyGen — LATER-001 (**не подтверждено** API).

После каждого тикета: `pytest` затронутого пакета + `python -m src.cli validate` на `scripts/redshift_0042.json` и `scripts/redshift_0047.json`.

## MUST (исполнителю)

| ID | Кластер | Суть | S/M/L | Жалоба |
|---|---|---|---|---|
| MUST-001 | M-HOOK | `HOOK_MAX_SEC` 5.0 → 3.0; `HOOK_TOO_LONG` блокирует P0 | S | 1 |
| MUST-002 | M-HOOK | Первая секунда не talking head; QC-29 + P5 | M | 1, 3 |
| MUST-003 | M-HOOK | Loop / payoff-too-early / late first avatar — блок выдачи | M | 1, 3 |
| MUST-004 | M-SYNC | Запрет галлюцинаций `_rich_terminal_copy`; overlay ⊆ script/source | M | 2 |
| MUST-005 | M-SYNC | `source_ref` ⇒ `sources[]`; `NO_SOURCE` и для `science` | S | 2 |
| MUST-006 | M-SYNC | `vision_qc` §11.2 **blocking** при mismatch_share > 10% | M | 2 |
| MUST-007 | M-GEN | Gen cap **10%**: instruction §5.9 + `config.yaml` + QC-14 + тесты | S | 10 |
| MUST-008 | M-AVATAR | `AVATAR_FIRST_APPEARANCE_LATE` блокирует выдачу | S | 3 |
| MUST-009 | M-AVATAR | `compose_zoom: 2.7` vs face_band/captions; gaze не regex «кубит» | M | 3 |
| MUST-010 | M-TEMPLATES | Пустые `needs`+`signals` не always-fire | M | 6 |
| MUST-011 | M-TEMPLATES | Rare geo/finance/social weight 0 без entity в сценарии | M | 6 |
| MUST-012 | M-TEMPLATES | Таксономия: rarity / topics / requires / forbids / cooldown / brand_ok | L | 6 |
| MUST-013 | M-TEMPLATES | DELETE LIST: файлы + JSON, не comment-out | M | 6, 7 |
| MUST-014 | M-TEMPLATES | A/B из разных пулов hook/hero/cta; QC-17 реально падает | M | 4, 6 |
| MUST-015 | M-CARDS | Копирайт карт только из script/source; enter 200–280 мс + SFX | M | 2, 7, 9 |
| MUST-016 | M-SEARCH | Смысловые EN-запросы 3–5 + entities + negatives | M | 5 |
| MUST-017 | M-SEARCH | **+30% surplus** кандидатов до Gemini/Grok/Magnific | M | 5 |
| MUST-018 | M-SEARCH | Stage1-мертвые клипы не на vision; 1080p — тест регрессии | S | 5 |
| MUST-019 | M-CRITIC | Cheap filter убивает ≥50% пула; GLM mid; Grok **только** 0.45–0.70 | L | 5 |
| MUST-020 | M-CRITIC | Снять auto-arbitrate всех evidence/twist; метрики в `build_report` | M | 5 |
| MUST-021 | M-CARDS | QC чужого hue в HyperFrames; cyan=tech; VFX cap = instruction | M | 7 |
| MUST-022 | M-SOUND | Тип карты → SFX role; skip+report если нет файла; кровати не из соседнего ролика | M | 9 |
| MUST-023 | M-ARTICLE | ARTICLE_URL / TOPIC как флаги на существующем P0–P12; стоп без primary source | L | 5 |
| MUST-024 | M-QC | Semantic fail не уходит как success; выровнять цифры docs↔config↔QC | M | 1–10 |
| MUST-025 | M-QC | Safe-zone HyperFrames реально пишется; QC-7 ловит | M | 3, 7 |
| MUST-026 | M-QC | `_subtitle_drift` измеряет сдвиг; QC-11 не притворяется lip-sync | S | 2, 3 |
| MUST-027 | M-SOURCES | Доноры фактов/стоков только с **проверенной** лицензией; иначе research-only | M | 5 |
| MUST-028 | M-AVATAR | CTA Subscribe / gaze plaque не хардкод `redshift_0042` | S | 3 |

## SHOULD

| ID | Суть |
|---|---|
| SHOULD-001 | `meta.hook` обязателен в схеме (сейчас только 0042) |
| SHOULD-002 | Ken Burns / push_in привязка к punch-словам, не только таймер 2.5 с |
| SHOULD-003 | Mixkit: либо живой провайдер, либо убрать из live-роутинга (сейчас MockStock даже в live) |
| SHOULD-004 | ESA: yaml есть, live-провайдера в `stock.py` нет |
| SHOULD-005 | RSS генетики/медицины — **после** MUST-027, URL не выдумывать |
| SHOULD-006 | Категории schema: physics / genetics / molecular **или** явная карта на `science` |
| SHOULD-007 | FrequencyBudget: signature не saturates на 80% после 4 пиков так, что variant/rare не живут |
| SHOULD-008 | Screen-templates schema (`notepad`, `patent_card`) согласовать с assemble mapping |

## LATER

| ID | Почему LATER |
|---|---|
| LATER-001 | Жесты / look-at / руки HeyGen — поля API **не подтверждено** |
| LATER-002 | Смена voice_id / клонов без отдельного тикета запрещена |
| LATER-003 | Полноценный mouth-vs-audio lip-sync (нет сигнала в текущем QC) |
| LATER-004 | Word-locked внутренние события на всех KB (после SHOULD-002) |
| LATER-005 | Новые оркестраторы / новый пайплайн — запрещено конституцией |
| LATER-006 | Бенчмарк чужих Shorts / внешние лицензионные URL — субагент **не подтверждено** |

## Топ дыр (честно, код не перечитывался повторно)

1. `src/lib/render/hyperframes/templates.py` ~14k строк — не прочитан целиком; 439 off-brand hex из 876.
2. Большинство renderer’ов HyperFrames и `compositor.py` (ffmpeg-путь) — не разобраны покадрово.
3. `src/p9_generate` / generation provider — не полный аудит промптов.
4. ESA в `stock_sources.yaml`, live-клиента нет — поведение на проде **частично** известно.
5. Mixkit = MockStock в live — факт кода; лицензия Mixkit **не подтверждено** внешним субагентом.
6. Жесты HeyGen / EL v3 gesture fields — **не подтверждено**.
7. Каталог GLM / Grok Vision field list — **не подтверждено** (в коде `allow_xai: false`, primary/arbiter = gemini).
8. `template_scenarios.index.json` в репо **нет** (упоминается в старых docs).
9. `assets/`, `cache/`, `output/` не сканировались (запрет сессии).
10. `docs/` (vNEXT) отстаёт от `instruction.md`; часть Q2 уже в коде (FrequencyBudget, hook picker, skip_vision).

## Кластеры → тикеты

- **M-HOOK** MUST-001…003, SHOULD-001
- **M-SYNC** MUST-004…006, MUST-026
- **M-AVATAR** MUST-008, 009, 028
- **M-TEMPLATES** MUST-010…014, SHOULD-007, §9
- **M-CARDS** MUST-015, 021
- **M-SEARCH** MUST-016…018, SHOULD-003, 004
- **M-CRITIC** MUST-019, 020
- **M-GEN** MUST-007
- **M-SOURCES** MUST-027, SHOULD-005
- **M-ARTICLE** MUST-023
- **M-SOUND** MUST-022
- **M-QC** MUST-024…026

Полные карточки, таблица gaps, DELETE LIST, команды и «не делать» — в `TZ-REDSHIFT-GROK.md`.

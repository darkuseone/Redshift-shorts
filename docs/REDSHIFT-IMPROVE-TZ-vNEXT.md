---
model: claude-opus-5
date: 2026-09-08
locale: Europe/Chisinau
status: DRAFT — awaiting Markus OK → исполняется ПОСЛЕ P0 (MEGA-TZ)
builds_on: REDSHIFT-MEGA-TZ
does_not_supersede: REDSHIFT-MEGA-TZ (P0a/P0b остаются в силе; P1/P2 частично поглощены)
repo: /workspace/repos/Redshift-shorts
branch: fix/quality-overhaul-0042b
tip_sha: 6e7719dcdda0a67da9cb75e7e00f8fbd68ba3182
mega_baseline_sha: 913d891
phases: Q1 / Q2 / Q3 — quality wave, post-MEGA
tests_at_scan: 1495 collected
reference_run: gh-artifacts/34172909306 (redshift_0042, A+B, 44.511 s)
inputs:
  - /workspace/tz/REDSHIFT-MEGA-TZ.md (§§0, A, A+, B, C, F, G, I, J, K.3, K.4, K+, K++)
  - /workspace/tz/OPUS-CRITICS-SYNTHESIS.md (D-1 … D-11)
  - /workspace/tz/FIX-0042B-STATUS.md
  - /workspace/tz/MASTER-BRIEF.md
  - /workspace/tz/video-critiques/redshift_0042-B-gemini.md
  - /workspace/tz/CRITICS-SYNTHESIS.md
  - /workspace/research/grok-shorts-deep-research.md
  - /workspace/research/gemini-yt-shorts-trends.md
  - /workspace/research/magnific-survey/FINDINGS.md
  - /workspace/opus-redshift-quality-plan.md
  - /workspace/redshift-quality-overhaul-brief.md
money_locks: elevenlabs=0 · heygen_create=0 · magnific_api=0 · xai=0 (vision и image)
session_models: Claude=Opus 5 (ultrathink) · Grok=max (исполнение) · Gemini=3.8 Flash High (vision)
---

# Redshift IMPROVE ТЗ vNEXT — волна качества после P0

> Русский текст — для Маркуса. Пути, id шаблонов, имена функций, ключи, имена
> файлов — английские.
> Это **не** переписывание MEGA-TZ. Это следующая волна: **удержание, хуки,
> визуальный язык**. Всё, что уже закрыто в P0 (`913d891 → 6e7719d`), здесь
> отмечено как landed и **не переспецифицируется**.
> Каждое утверждение ниже снято исполнением на живом репозитории и на
> артефактах прогона `34172909306`, а не чтением git log.

---

## 2. Executive summary

**Что случилось на эталоне.** Ролик `redshift_0042` вариант B прошёл **все 19
блокирующих QC** (`build_report.json` → `qc_passed: true` на обоих вариантах),
а Gemini-рецензия поставила `visual 2/10`, `broll 2/10`, `retention 2/10`.
Это не спор о вкусе. Это доказательство, что **сегодняшние гейты измеряют план,
а не кадр**.

**Единственная корневая причина.** Лог P8 того же прогона:
`judged: 23, accepted: 3, fill_rate: 0.1765, unfilled: 14`.
Четырнадцать слотов из двадцати остались без материала. У сборщика на такой
случай ровно **две** ветки (`src/p11_assemble/assemble.py:2601-2670`):
полноэкранный текст или голая плита. Он выбрал текст четырнадцать раз — отсюда
«хаотичное слайд-шоу из текста», которое назвал критик. Патч P0 `b6ca72b`
опустил потолок до четырёх — и **десять кадров из четырнадцати станут голой
плитой**. Шума меньше, удержания не прибавится. Это и есть дыра, которую
закрывает Q1.

**Что делает эта волна.**
1. **Лестница закрытия кадра** вместо развилки из двух веток: карточка → data-viz
   → браузер/устройство → параллакс → полноэкранный текст → плита (последняя,
   ≤ 2 на ролик).
2. **Хуки 0–5 с как система**: категория `intro-hooks` (8 шаблонов) сегодня
   **недостижима** — `picker.pick("intro-hooks", …)` не вызывается нигде;
   `plan.hook_window` пишется в `replanner.py:1027` и **не читается ни одной
   строкой кода**. Все восемь шаблонов используют **уже существующие** рендереры,
   новый рендерер писать не нужно.
3. **Cyan становится цветом кадра, а не токеном в JSON**: `emphasis_family`
   живёт в `schema.py:78` и **не читается ни одним модулем**; классы
   `.word.emphasis.cyan` и `.accent-cyan` объявлены и **никем не выводятся**;
   акцент субтитра жёстко прибит к красному (`captions.py:351`, `:403`).
4. **Возврат мёртвого каталога**: **73 шаблона из 204 не использованы ни разу** —
   `data-viz` 28/28, `intro-hooks` 8/8, `parallax` 4/4, `lower-thirds` 11/14.
5. **Сток**: слепой пад запросов жив **в двух местах** (`query.py` шаг 5 и
   `search.py:219`), `topical_match_score` не существует, библиотека футажа —
   **21 видео на весь канал**, а `fill-libraries.yml` умеет доливать что угодно,
   **кроме footage**.

**Чего НЕ переделываем.** Cyan-токены, `card_appear ≠ avatar_in`, fail-closed
Gemini, `frequency` в манифесте, `fit_size(role=)`, Kling 720p, потолок FS,
мьют субтитров под карточкой, deny фиолетовых частиц, музыка −24…−26 LUFS —
**всё landed**, см. §3.

**Денежные замки — без изменений.** Ноль ElevenLabs, ноль HeyGen-create, ноль
Magnific **API**, ноль xAI. Одна поправка со знаком плюс: `skip_vision=true` на
пересборке 0042 **стоил нам ролика**, а не денег — 23 кандидата × 3 кадра по
`$0.0004` = **$0.03**. Gemini разрешён, ключ есть, бюджет 6 USD. Полировка
идёт с живым Gemini-vision, без изменения остальных замков (§9.4).

**Метрика успеха для Маркуса — одна.** Пересобранный B: **≤ 4 полноэкранных
текста, ≤ 2 голых плиты, ≥ 6 кадров с неповторяющимся визуальным приёмом,
хук на экране к 1.0 с, fill_rate ≥ 0.70** — и вердикт Gemini `visual ≥ 6/10`,
`retention ≥ 6/10`. Пока эти семь чисел не сойдутся, 0043 не запускается.

---

## 3. Дельта против MEGA-TZ

### 3.1 MEGA P0 — landed (НЕ переспецифицируем)

Проверено на tip `6e7719d`.

| Пункт MEGA | Статус | Доказательство на живом репозитории |
|---|---|---|
| Cyan first-class токены | **landed** | `config/brandbook.json` → `cyan #36EFFF`, `cyan_soft #7AF0FF`, `cyan_deep #0BB8C9`; `color_rules.accent_tokens: ["accent","cyan"]` |
| `tests/test_brandbook_palette.py` | **landed** | файл есть |
| `card_appear ≠ avatar_in` | **landed** | `sfx_library.py:93` `card_appear: ("click","snap")` vs `:87` `avatar_in: ("hat","bright")` |
| Vision fail-closed, Gemini-only | **landed** | `config.yaml:18 allow_xai: false`; гейт `vision.py:490-498`; `build-video.yml:149-150` не экспортирует `XAI_API_KEY` |
| Честная оценка при `skip_live` (нет фиктивной 0.72) | **landed** | `judge.py:102-112` `skip_live_verdict` → `skip_live_unverified` |
| `frequency` в манифесте + dataclass | **landed** | `Template.frequency` (`templates.py:104`); манифест: signature 52 / variant 122 / rare 30 |
| `gen_templates` preserve | **landed** | сохраняются `status/retired_reason/frequency` |
| Kling ∞ = 720p + SOP | **landed** | `magnific_models.json` блок `web_unlimited` (`resolution: "720p"`, `unlimited_applies_to_api: false`); `tools/magnific_browser_sop.md` есть |
| `fit_size(role=)` / work_area | **landed** | остаточные вызовы закрыты в `0bd5f78` |
| Потолок уникальных FS, мьют пересекающихся субтитров, fit `label-strip` | **landed** | `b6ca72b`; `assemble.py:373 _fullscreen_cap`, `:2540 _claim_screen_phrase` |
| Deny фиолетовых частиц и сетки | **landed** | `1074bf1`; `footage_pins.json` deny 8 id, `footage_index.json` 7 `quarantined` |
| Музыкальный бед −24…−26 LUFS | **landed** | `6e7719d`; `config.yaml music_lufs: [-26,-24]` |
| `emphasis_family` в схеме | **landed (частично)** | поле есть в `schema.py:78` — **но не читается ни одним модулем**, см. §7.1 |
| `pick_bed` учитывает `last_used` | **landed** (MEGA K.3 п.8 закрыт) | `music_library.py:348-356` ранжирует `stale` + `len(used_in)` |
| Backdrop semantic picker | **landed** (файлов не хватает) | `backdrop.py` `SCENES` 5 шт., `PLATES` 3 записи, файлов на диске — **2** |

**Вывод:** ничего из списка выше в Q1–Q3 не переделывается. Где остался хвост
(`emphasis_family`, плиты подложек) — это отмечено отдельной строкой и идёт как
**достройка**, а не как повтор.

### 3.2 MEGA P1/P2 — всё ещё открыто, поглощается этой волной

| Пункт MEGA | Куда переезжает | Почему сюда |
|---|---|---|
| `topical_match_score` (K.3 п.1) | **Q2 / §9.2** | это не «предохранитель стока», это причина `broll 2/10` |
| Слепой пад запросов (K.3 п.2) | **Q2 / §9.1** | жив в двух местах, а не в одном |
| `CONCEPTS["процессор"]` (K.3 п.3) | **Q2 / §9.3** | вместе с ревизией всего словаря |
| `PickTrace` в `build_report` (K.3 п.4) | **Q2 / §10.5** | без него QC-25/26 нечем измерить |
| QC-20 (work_area) / QC-21 (`ungrounded`) / QC-22 (`picked ∈ allow`) | **Q1 / §12.1** — id **зарезервированы за MEGA**, новые начинаются с QC-23 | не создаём коллизию номеров |
| `tools/lint_composition.py` work_area (K.3 п.5) | **Q1 / §12.4** | дешёвый предрендерный гейт |
| `tests/test_no_junk_regressions.py` (K.3 п.6) | **Q1 / §12.5** | расширяется до retention-регрессий |
| 2–4 плиты подложек + `backdrop_pins.json` (K.3 п.7) | **Q3 / §7.6** | закрывает «голую плиту» из лестницы |
| `pick_bed` last_used (K.3 п.8) | **закрыто, снято** | см. 3.1 |
| `config/glossary.json` (K.4 п.1) | **Q3 / §11.3** | критик прямо назвал `(квантовый бит)` в карточках |
| Русский `snippet` обязателен (K.4 п.2) | **Q3 / §7.4** | карточка источника |
| `script_playbook.md` язык (K.4 п.3) | **Q3 / §11.3** | |
| Magnific UI-селекторы (K.4 п.4) | **Q3 / §14.3** | после первого живого прогона Grok Bot |
| wire `intro-hooks` / `parallax` (K.4 п.5, «опционально») | **Q1 / §5 и §8.3 — ГЛАВНЫЙ пункт волны** | в MEGA это было «опционально»; замер показал, что это 12 шаблонов и весь механизм хука |
| Гейт 0043 (K.4 п.6 / §J.1) | **§14** | дополнен визуальными числами |
| Ротатор концовок `CTA_TYPES` → 8 (D-7) | **Q3 / §6.4** | сегодня `CTA_TYPES` = 3, все шесть сценариев используют `question` |
| A/B-пулы `text-fullscreen` схлопнулись (F.6) | **Q2 / §8.4** | проверено: наборы **идентичны**, отличается только порядок |

### 3.3 НОВОЕ — чего нет ни в MEGA, ни в критиках

| # | Находка | Улика | Раздел |
|---|---|---|---|
| N-1 | Лестница закрытия кадра из **двух** веток; 14/20 кадров закрыты текстом | `assemble.py:2601-2670`; `edit_plan_B.json`: 14 shots с `gap_reason: "материал не найден: кадр закрыт словом блока"` | §7.2 |
| N-2 | QC читает статистику **плана**, а не смонтированного кадра: `stats.fullscreen_text_count = 2` при 14 FS-кадрах в ролике | `qc.py:24 stats = cut_plan.get("stats")`; `replanner.py:970` считает слоты, `assemble.py:2661` создаёт новые | §12.2 |
| N-3 | `plan.hook_window` записывается и **не читается** | `replanner.py:1027` — единственное вхождение в `src/` | §5.2 |
| N-4 | `emphasis_family` объявлен в схеме и **не читается ни одним модулем**; cyan физически не может попасть в кадр как акцент | grep `emphasis_family` по `src/` → одна строка, `schema.py:78`; `captions.py:351,403` жёстко `var(--color-accent)` | §7.1 |
| N-5 | `MOTION["parallax"]` зарегистрирован, но `render_motion` вызывается **только** со строкой `"kenburns"`; `r_parallax` целится в `#behind-NN`, который создаётся лишь для `text_behind_head` на альфа-слотах | `templates.py:2024-2027`, `:2121`; `composition.py:460`, `:533` | §8.3 |
| N-6 | `data-viz` мёртв де-факто: `_stats_from_text` ловит только арабские цифры, а сценарии пишут числа словами. На шести сценариях канала — **один** блок годен | `assemble.py:1826`, `:2207-2214`; `meaning.py` док-строка: цифры в 6 % блоков, словами — 25 % | §8.2 |
| N-7 | **73 шаблона из 204 не использованы ни разу**; целиком мертвы `data-viz` 28, `intro-hooks` 8, `parallax` 4 | `templates/manifest.json` → `last_used_in` пуст у 73 | §8.1 |
| N-8 | `frequency` работает как **жёсткий ключ сортировки**, а не как доля: `signature` побеждает `grounded`. Итог — `blur-out-up` трижды в одном ролике при шести signature-шаблонах FS | `templates.py:296-301` ранг `(explicit, freq, grounded, used_recently, usage, id)`; `_FS_SIGNATURE` = 6 шт. | §8.5 |
| N-9 | Слепой пад запросов **в двух местах**, не в одном | `query.py` шаг 5 и `search.py:219-221` («Aggressive pad») | §9.1 |
| N-10 | `fill-libraries.yml` не умеет `footage` — библиотека футажа не пополняется вне сборки ролика | workflow `options: [sfx, music, memes, all]`; при этом `config.yaml libraries.footage` существует | §9.5 |
| N-11 | `render_stats.accent_share_max = 0.0` на обоих вариантах — бюджет акцента `0.12` **не измеряется** на пути HyperFrames | `build_report.json` обоих вариантов | §7.5, §12.3 |
| N-12 | `costs.by_service` есть в коде и **не доходит до `build_report`** — денежный DoD §0.4 MEGA нечем проверить из отчёта | `costs.py:49`; `render.py:430-441` кладёт только `cost_usd` | §12.6 |
| N-13 | Интент `lowerthird-metric-badge` мёртв: требует сигнал `numbers`, а оба вызова `lower-thirds` сигналов не передают | `template_scenarios.json`; `assemble.py:2057`, `:2096` | §8.6 |
| N-14 | Два несовместимых словаря условий: интенты требуют `numbers` (сигнал), манифест — `number` (признак `meaning.py`) | `template_scenarios.json` needs: `numbers ×7`; манифест needs: `number ×26` | §8.6 |
| N-15 | `skip_vision=true` на полировке — не экономия, а причина `fill_rate 0.1765`. Живой Gemini на этот прогон стоит **$0.03** | `pipeline.log` того же прогона; `budget.price.gemini_per_image: 0.0004` | §9.4 |

---

## 4. Цели, анти-цели и DoD волны качества

### 4.1 Цель

Поднять потолок **интересности** ролика: чтобы кадр, у которого нет стокового
материала, закрывался **приёмом**, а не стеной текста и не пустой плитой; чтобы
первые 5 секунд собирались системой, а не случайностью; чтобы четыре цвета
брендбука работали в кадре, а не лежали в JSON.

### 4.2 Анти-цели (явно НЕ делаем)

* Не переписываем VO и клипы аватара 0042 — заморожены.
* Не вызываем ElevenLabs / HeyGen-create / Magnific **API** gen / xAI.
* Не пишем **ни одного нового рендерера** для хуков: все восемь `intro-hooks`
  используют существующие (`fullscreen_text ×4`, `footage`, `split`,
  `source_card`, `avatar`). Проверено по манифесту.
* Не удаляем строки из `templates/manifest.json` и `cache/footage_index.json` —
  только `status` / `quarantined`.
* Не делаем `escaped` блокирующим — решение MEGA D-11 в силе.
* Не занимаем номера **QC-20 / QC-21 / QC-22** — они зарезервированы за MEGA P1.
* Не переписываем `template_scenarios.json` целиком: он уже содержит 105
  интентов, включая 7 хуковых и 2 параллаксных. Правим точечно.
* Не гоняемся за токенами внутри пайплайна: измеренная стоимость прогона —
  **$0.03**. Экономить надо контекст агентов, а не Gemini (§11).

### 4.3 DoD — кадровый, измеримый, по пересобранному B

Каждая строка — число из артефакта, а не впечатление. В скобках — значение на
эталонном прогоне `34172909306`.

| # | Проверка | Источник числа | Порог | Сегодня |
|---|---|---|---|---|
| V-1 | полноэкранных текстовых кадров в **смонтированном** ролике | `count(edit_plan.shots.kind == "fullscreen_text")` | **≤ 4** | **14** ❌ |
| V-2 | голых плит без текста и без ассета | `count(shots где gap_reason содержит "plate without text")` | **≤ 2** | 0 сейчас, **≈10 после патча P0** ❌ |
| V-3 | заполнение слотов материалом | `p8.fill_rate` | **≥ 0.70** | **0.1765** ❌ |
| V-4 | ни один шаблон не повторяется больше двух раз | `max(Counter(templates_used).values())` | **≤ 2** | **3** (`blur-out-up`) ❌ |
| V-5 | различных шаблонов на ролик | `len(set(templates_used))` | **≥ 14** | 23 ✅ |
| V-6 | кадров с «неплоским» приёмом: `frames-cards` / `data-viz` / `parallax` / `browser-ui` / `hero-devices` | по `shots` + `overlays` | **≥ 3** | **1** (browser-scroll) ❌ |
| V-7 | экранный хук на кадре | первый шот с текстом | **начало ≤ 1.0 с, 3–7 слов** | 0.47 с, но фраза выбрана `gap_phrase`, а не хуком ⚠ |
| V-8 | доля акцентного цвета в кадре (red+cyan суммарно) | `render_stats.accent_share_max` | **0.02 ≤ x ≤ 0.12** | **0.0** (не измеряется) ❌ |
| V-9 | cyan присутствует, когда в сценарии есть `emphasis_family ∈ {tech, number, source}` | HTML-класс `.is-accent.cyan` | **≥ 1 бит** | **невозможно** ❌ |
| V-10 | доля аватара | `stats.avatar_share` | 0.35–0.60 | 0.476 ✅ |
| V-11 | макс. интервал без визуального события | `stats.max_event_gap_sec` | ≤ 2.5 | 2.373 ✅ |
| V-12 | медиана длительности кадра | по `shots` | **1.5–3.0 с** | 2.52 ✅ |
| V-13 | у ролика с `cta.type = visual_loop_seam` шов сходится | dHash(кадр 0, последний кадр) | **≤ 12 бит** | тип не существует ❌ |
| V-14 | вердикт Gemini по пересобранному B | `video-critiques/*.md` | `visual ≥ 6`, `broll ≥ 6`, `retention ≥ 6` | 2 / 2 / 2 ❌ |

### 4.4 DoD — системный

```
pytest                        зелёный целиком (база: 1495 тестов)
costs.elevenlabs   == 0
costs.heygen       == 0        (heygen_source=prepared)
costs.magnific     == 0        (generation.skip=true)
costs.grok         == 0        (провайдер не собирается)
costs.gemini       <= 0.10     (разрешено: vision на полировке, §9.4)
build_report.costs             присутствует посервисно (сегодня — только cost_usd)
build_report.pick_traces       присутствует (allow_size, escaped, fired)
```

### 4.5 Что критерием **не** является

«Коммит существует», «тест зелёный», «шаблон добавлен в манифест»,
«категория стала достижимой в теории». Достижимость доказывается **строкой в
`templates_used` пересобранного ролика**, а не в конфиге.

---

## 5. Система хуков 0–5 с

### 5.1 Диагноз

Три независимых улики:

1. **`picker.pick("intro-hooks", …)` не вызывается нигде.** Все десять
   вызовов `picker.pick` в `assemble.py` (строки 1401, 1932, 2057, 2096, 2163,
   2269, 2561, 2635, 2686, 2703) передают первым аргументом одну из десяти
   категорий; `intro-hooks` и `parallax` в этот список не входят. Конфиг
   честно это признаёт:
   ```json
   "unreachable_categories": ["intro-hooks", "parallax"],
   "reason": "Категории intro-hooks (8 шаблонов, 7 интентов) и parallax
              (4 шаблона, 2 интента) не выбираются из каталога нигде в src/"
   ```
2. **`plan.hook_window` мёртв.** `replanner.py:1027` пишет
   `"hook_window": [0.0, limits.hook_sec]` — и это **единственное** вхождение
   строки `hook_window` во всём `src/`.
3. **Хук на 0042 собрался случайно.** Кадр 0 — 0.47 с футажа, кадры 1 и 2 —
   два полноэкранных текста подряд («ЭТОТ ОТВЕТ НЕВОЗМОЖНО ПРОВЕРИТЬ»,
   «ВООБЩЕ НИЧЕМ»). Обе фразы выбраны функцией `gap_phrase`
   (`assemble.py:1172`), то есть «что вынести на экран, когда материала нет».
   Хука как решения не было — был отказ материала.

При этом **вся оснастка уже лежит в репозитории**:

| Что есть | Где | Готовность |
|---|---|---|
| 8 шаблонов хука | `templates/intro-hooks/*.json` | 100 % |
| Рендереры под них | `fullscreen_text` ×4, `footage`, `split`, `source_card`, `avatar` — **все существуют** | 100 % |
| 7 сценарных интентов | `config/template_scenarios.json` (`hook-question`, `hook-number`, `hook-dark`, `hook-cold-open`, `hook-split`, `hook-typing`, `hook-avatar`) | 100 % |
| Окно хука | `plan.hook_window` | пишется, не читается |
| Скриптовая валидация петли | `p0_validate/validator.py`: `HOOK_TOO_LONG` (5.0 с), `HOOK_UNANSWERED`, `PAYOFF_TOO_EARLY/LATE`, `CTA_CLOSES_EVERYTHING` | 100 % |

Не хватает **одного вызова picker'а и трёх полей схемы**.

### 5.2 Что делаем

**H-1. Новая точка выбора в `assemble.py`.**
Перед общей веткой слотов добавляется приоритетный разбор окна хука:

```python
# src/p11_assemble/assemble.py — новая функция, вызывается первой в build_shots
def _pick_hook_shot(slot, block, plan, picker, *, variant, seed,
                    recent_videos, used_templates, assets):
    """Кадр внутри hook_window: сначала intro-hooks, потом общая лестница."""
    hook_hi = float((plan.get("hook_window") or [0.0, 3.0])[1])
    if float(slot["start"]) >= hook_hi or slot.get("role") != "hook":
        return None
    spec = (plan.get("hook") or {})            # из meta.hook, см. H-2
    traits = block_traits(str(block.get("text") or ""))
    head = [spec["template_hint"]] if spec.get("template_hint") else []
    template, trace = picker.pick(
        "intro-hooks",
        blob=" ".join([spec.get("on_screen", ""), block.get("text", "")]),
        signals=_hook_signals(spec, traits, assets),   # {"number","question","footage",…}
        traits=traits,
        variant=variant,
        duration=float(slot["duration"]),
        recent_videos=recent_videos,
        exclude=used_templates,
        prefer_head=head,
        seed=seed,
    )
    return template, trace
```

**H-2. Поля сценария (правка `src/lib/schema.py`).**
`additionalProperties: false` стоит на всех уровнях — без правки схемы P0
упадёт. Добавляем в `meta`:

```python
"hook": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # 3–7 слов, попадают на кадр к 0.5–1.0 с. Это OCR-семя для алгоритма.
        "on_screen":     {"type": "string", "minLength": 3, "maxLength": 64},
        "style":         {"enum": list(HOOK_STYLES)},
        # запрос под холодное открытие: кадр до первого слова
        "cold_open_query": {"type": "string"},
        "template_hint": {"type": "string"},
    },
},
```

и рядом с `CTA_TYPES`:

```python
HOOK_STYLES = ("number_slam", "question_flash", "blackout_word",
               "cold_open", "split_reveal", "typing_search", "avatar_direct")
```

Соответствие `style → template` — один словарь в `assemble.py`, ровно как
`_source_card_category`. Без `style` работает обычный picker по интентам.

**H-3. Согласовать два словаря условий (N-14).**
Интент `hook-number` требует `needs: ["numbers"]` — это **сигнал**, который
`assemble.py` формирует только на пути `hero-devices` (`:1399`) и `data-viz`
(`:2255`). Шаблон `intro-hooks/hook-number-slam` требует `needs: ["number"]` —
это **признак** из `meaning.py`. На пути хука сигналов нет, интент не сработает
никогда.
Решение: `_hook_signals()` кладёт в сигналы **и** признаки блока
(`number`, `question`, `comparison`, `superlative`, `negation`), и структурные
(`footage` — если у слота есть ассет). Тогда оба словаря сходятся, и правка
`template_scenarios.json` сводится к одному месту: `hook-number.needs` →
`["number"]`.

**H-4. Снять запись о недостижимости.**
`config/template_scenarios.json` → `unreachable_categories: ["parallax"]`
(после §8.3 — пустой список). `tests/test_template_picker.py:572` ассертит
множество `{"intro-hooks","parallax"}` — правится **в том же PR**, иначе CI красный.

**H-5. Запреты на входе (P0), а не на выходе.**
В `p0_validate/validator.py` — два новых предупреждения и один блокер:

| Код | Условие | Тип |
|---|---|---|
| `HOOK_GREETING` | первый блок начинается с «привет», «всем привет», «с вами», «в этом видео», «сегодня разберём» | **блокирующий** |
| `HOOK_NO_ON_SCREEN` | `meta.hook.on_screen` пуст **и** у хук-блока нет `overlay.content` | предупреждение |
| `HOOK_ON_SCREEN_TOO_LONG` | `on_screen` > 7 слов | предупреждение |

`HOOK_TOO_LONG` (5.0 с) и `HOOK_UNANSWERED` уже есть — не трогаем.

**H-6. Холодное открытие.**
`intro-hooks/hook-footage-cold-open` (`renderer: footage`, 1.0–3.0 с) требует
кадра **до первого слова**. Сегодня P7 ищет материал по слотам речи, окно 0–0.5 с
собственного запроса не имеет. Добавляется псевдослот `hook_cold_open` в
`p5_replan`, чей запрос берётся из `meta.hook.cold_open_query`, иначе из
`_concepts_from_text(meta.topic)`. Приоритет в P7 — **высший**: этот кадр видят
все, кто пролистает дальше.

### 5.3 Тесты (Q1)

`tests/test_hooks.py` — новый файл:

1. `test_hook_window_is_read` — план с `hook_window: [0,3]` и слотом
   `role="hook"` даёт шот с `template.startswith("intro-hooks/")`.
2. `test_hook_style_maps_to_template` — шесть стилей → шесть разных id.
3. `test_number_hook_fires_on_word_numerals` — блок «сто пять кубитов»
   (без цифр) выбирает `hook-number-slam`.
4. `test_cold_open_has_own_query` — при `cold_open_query` в P7 уходит
   отдельный запрос, и он первый в списке.
5. `test_greeting_is_blocking` — «Привет, с вами Redshift» → `HOOK_GREETING`.
6. `test_on_screen_text_lands_before_1s` — в edit-плане первый текстовый узел
   имеет `start ≤ 1.0`.
7. `test_no_intro_hooks_regression` — категория больше не числится в
   `unreachable_categories`.

### 5.4 Банк русских хуков (готов к использованию)

Из research'а (Grok Приложение A + Gemini §2) и под уже написанные сценарии.
Устный ≤ 8–12 слов / ≤ 2 с; экранный 3–7 слов.

| Стиль | Устный хук | Экранный (OCR-семя) |
|---|---|---|
| `blackout_word` | «Этот ответ невозможно проверить. Вообще ничем.» | `НЕВОЗМОЖНО ПРОВЕРИТЬ` |
| `number_slam` | «Сто пять кубитов. И ни один не считает как бит.» | `105 КУБИТОВ` |
| `question_flash` | «Почему компьютер, которому мы верим, никто не проверял?» | `КТО ЭТО ПРОВЕРИЛ?` |
| `cold_open` | *(без слов 1.2 с: криостат крупно)* → «Это не двигатель.» | `ЭТО НЕ ДВИГАТЕЛЬ` |
| `split_reveal` | «В школе врали про чёрные дыры.» | `МИФ ↔ ИЗМЕРЕНИЕ` |
| `typing_search` | «Мы загуглили то, что физики уже посчитали.» | `ЗАПРОС: 10^25 ЛЕТ` |
| `avatar_direct` | «Стоп. Найди ошибку на этом кадре.» | `НАЙДИ ОШИБКУ` |
| `number_slam` | «Двенадцать километров — и бурить перестали.» | `12 КМ. ХВАТИТ` |
| `question_flash` | «Планета пережила смерть своей звезды. Как?» | `ПЕРЕЖИЛА ЗВЕЗДУ` |
| `blackout_word` | «Твой телефон заряжается медленнее нарочно.» | `НАРОЧНО МЕДЛЕННЕЕ` |

**Запрещено (в `rejected_patterns.md`):** «привет», «с вами», логотип-заставка,
мягкая подложка без голоса, английская жаргонная стена, статичная карточка
дольше 2 с без движения.

---

## 6. Архитектура удержания

MEGA §I задал ритм (событие каждые 1.5–3 с, доля аватара 35–60 %, punch-in
10–20 %) и это **landed и проходит** (`max_event_gap 2.373`, `avatar_share 0.476`,
`cut_share 0.8`). Ролик при этом получил `retention 2/10`. Значит ритм — не всё.
Здесь достраивается то, чего ритм не покрывает.

### 6.1 Карта битов — из плана в edit-план

`script_playbook.md` §3 уже описывает пять битов (Удар / Вопрос / Затяжка /
Ответ / Осадок+CTA) и P0 их валидирует
(`PAYOFF_EARLIEST_SHARE = 0.40`, `PAYOFF_LATEST_SHARE = 0.88`,
`PAYOFF_RESTATES_SETUP`). Но **до монтажа эта карта не доезжает**: в
`edit_plan` нет поля `beat`.

**R-1.** `p5_replan` кладёт в каждый слот `beat ∈ {hit, question, stretch,
payoff, residue}` — вычисляется из `role` + `answers_hook` + доли времени.
`assemble` использует `beat` там, где сегодня использует `role`:

| Бит | Что обязано быть в кадре | Что запрещено |
|---|---|---|
| `hit` | смена плана + звук + экранный хук ≤ 1.0 с | заставка, статичная голова |
| `question` | приём, оставляющий вопрос: `split_reveal`, `question-flash`, таймер | ответ на экране |
| `stretch` | новый визуальный факт каждые 1.5–3 с; **эскалация** — приём не повторяет предыдущий бит | третий подряд полноэкранный текст |
| `payoff` | самый сильный приём ролика: data-viz, карточка-число, параллакс-наезд | голая плита |
| `residue` | 1–2 с без графики, затем CTA | CTA поверх субтитра (это уже было на 0042, 00:43) |

**R-2. Эскалация как правило picker'а.** Внутри `stretch` два соседних кадра
не могут иметь одинаковый `renderer`. Реализуется одной строкой в `exclude`:
`exclude = used_templates + [prev_shot_template_id]` уже частично есть;
добавляется `exclude_renderers={prev.renderer}` в `TemplatePicker.pick`.

### 6.2 Каденция — уточнение, а не переизобретение

Сегодняшний потолок `max_event_gap_sec: 2.5` — это **верхняя** граница.
Нижней нет, и на 0042 два кадра ушли в 0.30 и 0.47 с — это мигание, а не бит.

**R-3.** Добавляется `limits.min_visual_beat_sec: 0.8` и правило: кадр короче
порога **сливается** с соседним, а не рисуется отдельным приёмом. Исключение —
`transitions` и `avatar-entry` (у них `duration_range` от 0.14 с — так и задумано).
Проверка: `QC-23` (§12.2).

### 6.3 Луп и пересматриваемость

Research сходится: шов между последним и первым кадром даёт всплеск
эффективного просмотра > 100 %. Сегодня механизма нет.

**R-4. `visual_loop_seam` как измеримый тип концовки.**
Когда `cta.type == "visual_loop_seam"`:
* `assemble` обязан положить в последний кадр ту же композицию, что в кадр 0:
  тот же `bg_file` (или тот же `backdrop scene`), тот же `kenburns` в обратную
  сторону, тот же экранный глиф.
* `outro-cta/loop-back` (`renderer: footage`) — шаблон под это уже есть,
  `last_used_in` пуст.
* Проверка **числом**: `dHash` кадра `0.0 s` и кадра `duration − 0.1 s`
  различаются ≤ 12 бит из 64. Гейт `QC-27`, блокирующий **только** для этого
  типа концовки.

**R-5. Нарративный шов.** Для `part2_cliff` и `open_question` шов держит текст:
последняя реплика не завершена без первой. Это правило сценария, проверяется
на P0 предупреждением `LOOP_TEXT_SEAM_MISSING` (не блокирует).

### 6.4 Ротатор концовок — достраиваем хранение MEGA D-7

Сегодня: `schema.py:19` `CTA_TYPES = ("question", "loop", "statement")`, и
**все шесть** сценариев `redshift_0042…0047` используют `question`. Канал
заканчивается одинаково шесть раз подряд.

Правка ровно по MEGA D-7, без новых объектов:

```python
CTA_TYPES = ("open_question", "binary_vote", "part2_cliff", "soft_subscribe",
             "share_prompt", "save_prompt", "visual_loop_seam", "source_tease")
_CTA_LEGACY = {"question": "open_question", "loop": "visual_loop_seam",
               "statement": "soft_subscribe"}   # маппинг в p0_validate
```

Память ротации — `config/editing_preferences.json` (файл существует,
структура `defaults` + `situation_weights` уже есть):

```json
"ending_last_type": "open_question",
"ending_ring": ["open_question", "binary_vote", "part2_cliff"]
```

Правила: тот же тип не два ролика подряд; `soft_subscribe` ≤ 1 из 3;
`visual_loop_seam` требует прохождения `QC-27`.

### 6.5 Эмоциональная дуга

Из research'а: удивление → замешательство → разрешение. Механически это
означает **одно**: приём на `payoff` обязан отличаться от приёмов `stretch`
не только id, но и **классом**. Правило:

```
renderer(payoff) ∉ {renderer(s) for s in stretch_shots}
```

Проверка — `QC-25` (§12.2). На 0042 `payoff`-кадр был
`text-fullscreen/blur-out-up` — тот же приём, что и два кадра до него.

---

## 7. Визуальный язык

### 7.1 Cyan: из токена в кадр (главная правка §7)

**Улика.** Три независимых обрыва цепочки:

1. `emphasis_family` объявлен в `src/lib/schema.py:78`. Grep по всему `src/`
   даёт **одну** строку — это объявление. Ни один модуль поле не читает.
2. Классы существуют и никем не выводятся:
   `brand_css.py:249` `.word.emphasis.cyan{color:var(--color-cyan)}`,
   `brand_css.py:295` `.fullscreen-text .accent-cyan{color:var(--color-cyan)}`.
3. Акцент субтитра прибит к красному жёстко:
   `captions.py:351` `.cf-word.is-accent{color:var(--color-accent)}`,
   `captions.py:403` `.bd-word.is-accent{color:var(--color-accent)}`.

Единственный cyan, который физически доезжает до кадра, — декоративный клон
хроматического сдвига `sb-clone-cyan` (`templates.py:9693`, CSS `:13466`) в
одном FS-шаблоне. То есть у канала «четыре цвета» ровно на бумаге.

**Правка (Q1, дёшево, без нового кода рендера).**

| Файл | Что |
|---|---|
| `src/p11_assemble/assemble.py` | читать `block.emphasis_family`; класть на шот и на слово субтитра `accent_family ∈ {red, cyan}` по правилу MEGA D-9: `myth\|emotion → red`, `tech\|number\|source → cyan`, иначе `red` |
| `src/lib/render/hyperframes/captions.py` | `_accent_index` уже находит слово; добавить второй класс: `is-accent` + `cyan` при `word["accent_family"] == "cyan"` — три места (`:486`, `:942`, gradient-путь) |
| `src/lib/render/hyperframes/captions.py` (CSS) | `.cf-word.is-accent.cyan{color:var(--color-cyan)}`, `.bd-word.is-accent.cyan{…}`, `.gf-accent.cyan{…}` |
| `src/lib/render/hyperframes/templates.py:83` | `<span class="accent">` → `accent` либо `accent-cyan` по `params["accent_family"]` (класс `.accent-cyan` уже в CSS) |
| `src/lib/schema.py` | без правок — поле уже есть |
| `scripts/redshift_0042.json` | проставить `emphasis_family` шести блокам. **Только экранные поля, VO заморожен.** |

Разметка для 0042 (VO не меняется):

| Блок | `emphasis_word` | `emphasis_family` | Цвет |
|---|---|---|---|
| b1 hook | невозможно | `emotion` | red |
| b2 setup | кубитов | `tech` | **cyan** |
| b3 evidence | Nature | `source` | **cyan** |
| b4 develop | вдвое | `number` | **cyan** |
| b5 twist | верим | `myth` | red |
| b6 cta | доверил | `emotion` | red |

**Правила кадра (MEGA A+.4 — переносим без изменений, добавляем проверку):**
одновременно ≤ 3 «громких» из четырёх; red и cyan **не красят одну фразу**;
один акцент-токен на бит; суммарная доля акцента ≤ 0.12 (§7.5).

### 7.2 Лестница закрытия кадра (сердце волны)

**Улика.** `assemble.py:2601-2670`, ветка «нет ассета»:

```
prep is None or asset is None
 ├─ fs_count < fs_cap  и есть уникальная фраза → text-fullscreen
 └─ иначе                                      → footage-плита без текста
```

Две ветки. Больше ничего. `edit_plan_B.json`: **14 из 20 кадров** несут
`gap_reason: "материал не найден: кадр закрыт словом блока"`. После патча
`b6ca72b` (`fs_cap = 4`) десять из них станут плитами.

**Правка. Шесть ступеней вместо двух.** Новая функция
`_close_empty_slot(slot, block, traits, budget, picker, …)`, вызывается на месте
текущей развилки. Порядок — от самого содержательного к самому дешёвому:

| # | Ступень | Условие | Категория picker'а | Бюджет на ролик |
|---|---|---|---|---|
| 1 | **Карточка-ключ** — одно акцентное слово + inset-медиа | у блока есть `emphasis_word` **и** любой доступный still (пин, backdrop, NASA-фото из индекса) | `frames-cards` | ≤ 4 |
| 2 | **Данные** | `number` в признаках блока (после §8.2) | `data-viz` | ≤ 2 |
| 3 | **Источник / устройство** | `quote`/`brand`/`device` в признаках | `browser-ui`, `hero-devices` | ≤ 3 |
| 4 | **Параллакс-плита** | есть still + слот ≥ 1.5 с (после §8.3) | `parallax` | ≤ 3 |
| 5 | **Полноэкранный текст** | уникальная фраза и `fs_count < fs_cap` | `text-fullscreen` | ≤ 4 (как сейчас) |
| 6 | **Голая плита** | всё выше не сработало | — | **≤ 2, дальше QC-23 роняет сборку** |

Бюджет держит новый объект:

```python
@dataclass
class VisualBudget:
    """Сколько раз ролик уже закрыл кадр каждым способом.

    Потолок FS уже был (fs_cap). Без остальных потолков лестница просто
    сползла бы на первую подходящую ступень: на 0042 это дало бы четырнадцать
    карточек вместо четырнадцати надписей — то же слайд-шоу, другим шрифтом.
    """
    card: int = 0
    dataviz: int = 0
    source: int = 0
    parallax: int = 0
    fullscreen: int = 0
    plate: int = 0
```

**Почему это лечит именно то, на что жаловался критик.** Из его списка BLOCKING:
«14 полноэкранных при норме 2–4», «грубое дублирование карточек»,
«стены текста» — все три следствия одной развилки. Уникальность фразы уже
закрыта `_claim_screen_phrase` (P0); лестница закрывает остальное.

### 7.3 UX карточки — правило, а не пожелание

Из обоих research-файлов и жалобы №2 Маркуса: карточка = **одно акцентное
слово + опциональная подпись ≤ 6 слов + медиа-слот**.

| Уровень | Что | Ограничение |
|---|---|---|
| A | акцентное слово | 1 слово, red **или** cyan по `emphasis_family` |
| B | подпись | ≤ 6 слов, белая |
| C | мелкий лейбл | домен источника / «упрощение» / NASA, ≤ 3 слова |
| media | still или петля 1–2 с | **буквально** иллюстрирует слово A |

Запрещено на карточке: скобочные глоссы («(квантовый бит)» — прямая цитата
критика), английские служебные лейблы, второй текстовый слой поверх, пустое
стекло без медиа. Глоссы уходят в `config/glossary.json` и в **устный** текст
(§11.3), на карточку — никогда.

### 7.4 Бюджет полноэкранного текста

`limits.fullscreen_text_per_video: [2, 4]` — уже в конфиге. Проблема не в
числе, а в том, что **его никто не измеряет на смонтированном ролике** (N-2).
Закрывается `QC-23` (§12.2): считаем `shots`, а не слоты плана.

Дополнительно: **ни один FS-шаблон не повторяется в ролике**. Сегодня
`blur-out-up` встречается трижды (V-4). Реализуется одной строкой:
`exclude=used_templates` уже передаётся, но `used_templates` растёт **через**
`prefer_head`, который перебивает `exclude`. Чиним приоритет в
`TemplatePicker.pick`: `prefer_head` не может вернуть id, который уже в
`exclude`, если в allow есть хоть один свободный.

### 7.5 Измерить акцент

`render_stats.accent_share_max = 0.0` на обоих вариантах — доля акцентного
цвета на пути HyperFrames не считается вовсе, при том что
`color_rules.accent_max_frame_share = 0.12` объявлена.

**Правка.** В `p12_render_qc/render.py` при съёме `render_stats` добавляется
подсчёт доли пикселей в двух коридорах HSV (красный `#C8453D ±`, cyan
`#36EFFF ±`) на тех же 6 сэмплах, что уже извлекаются для `vision_qc`
(`vision_qc.py:94-97`) — **новых извлечений кадров не делаем**, переиспользуем.
Гейт `QC-24` (§12.3).

### 7.6 Подложки и рисунки

Сегодня: `backdrop.py` знает 5 сцен (`horizon`, `depth`, `space`, `room`, …),
`PLATES` мапит 3, файлов на диске — **2** (`grid.jpg`, `horizon.jpg`), причём
`space` — алиас на `horizon.jpg` с комментарием «No dedicated space still».

**Правка (Q3, money-safe):** 4 новые плиты через **браузер** Magnific
(Nano Banana 2, ∞ по подписке, §K++ MEGA) — `depth`, `space`, `room`, `data`.
Плюс `config/backdrop_pins.json`, чтобы Маркус мог прибить конкретную плиту к
рубрике. Ни одного вызова Magnific **API**.

Промпт-строка (единая, из MEGA I.3 + палитра):

> vertical 9:16, dark cinematic plate, **black / white / red #C8453D / cyan
> #36EFFF only**, no text, no logos, no people, subtle grain, Netflix-investigation
> energy, negative space in the centre for a talking head

### 7.7 Диаграммы как приём, а не как data-viz

`data-viz` завязан на числа. Но половина «рисунков», которых просит Маркус, —
это **схемы без чисел**: барьер и частица, две ветки, стрелка «раньше → теперь».
Под них в каталоге уже есть `data-viz/flowchart`, `data-viz/flowchart-vertical`
(интент `logic-flowchart` существует, `last_used_in` пуст).

**Правка (Q2):** признак `mechanism` в `meaning.py` — «потому что», «из-за»,
«приводит к», «в результате», «сначала… потом». По нему открывается ступень 2
лестницы даже без чисел. Один регэксп, ноль нового рендера.

---

## 8. Шаблоны и сценарии

### 8.1 Перепись мёртвого каталога

Считано по `templates/manifest.json`, поле `last_used_in`:

```
использовано хотя бы раз : 131 из 204
не использовано ни разу  :  73 из 204  (35.8 %)

не использовано, по категориям:
  data-viz        28 из 28   ← категория мертва целиком
  lower-thirds    11 из 14
  intro-hooks      8 из  8   ← категория недостижима
  browser-ui       7 из 21
  text-fullscreen  6 из 34
  hero-devices     5 из 25
  parallax         4 из  4   ← категория недостижима, рендерер не диспатчится
  outro-cta        4 из  6
```

Это не «лишние шаблоны». Это **40 приёмов в трёх категориях**, которые могли бы
закрывать те самые 14 пустых кадров.

### 8.2 Оживить `data-viz` (28 шаблонов)

**Улика.** `assemble.py:2207-2214`:

```python
if slot.get("role") not in ("evidence", "develop"): continue
if slot["kind"] not in ("footage", "meme", "avatar"): continue
nums = _stats_from_text(blocks[...]["text"])
if not nums: continue
```

`_stats_from_text` (`:1826`) ловит только арабские цифры. А `meaning.py` в
собственной док-строке фиксирует обратное:

> «Числа пишутся словами. […] Регулярка на `\d` находила признак в 6 % блоков,
> со словами-числительными — в 25 %.»

Замер по всем шести сценариям канала:

| Сценарий | блоков с цифрами | из них годных для data-viz (`evidence`/`develop`) |
|---|---|---|
| 0042 | 1 (`105` в блоке `setup`) | **0** |
| 0043 | 0 | 0 |
| 0044 | 0 | 0 |
| 0045 | 0 | 0 |
| 0046 | 1 | **1** |
| 0047 | 0 | 0 |

Один пригодный блок на шесть роликов. 28 шаблонов (14 % каталога) не имеют
шанса.

**Правка (Q2), три строки логики:**

1. `_stats_from_text` учит числительные словами — регэксп `_NUMBER_WORDS`
   **уже написан** в `meaning.py:26-33`, импортируется как есть, плюс таблица
   `слово → значение` для двадцати частотных («сто», «тысяча», «вдвое», «треть»).
2. Роли расширяются до `("setup", "evidence", "develop", "twist")` — на 0042
   число живёт в `setup`.
3. Потолок `1 на ролик` → `2 на ролик` (бюджет `VisualBudget.dataviz`).

Ожидаемый эффект на 0042: блок b2 («сто пять кубитов») → `stat-countup-card`;
блок b4 («ошибка падает вдвое») → `compare-bars`. Два текстовых кадра
превращаются в два приёма.

### 8.3 Оживить `parallax` (4 шаблона + мёртвый рендерер)

**Улика — две поломки подряд:**

1. `MOTION` содержит `{"kenburns": r_kenburns, "parallax": r_parallax}`
   (`templates.py:2024-2027`), но `render_motion` вызывается ровно один раз и
   **с литералом**: `composition.py:460` `render_motion("kenburns", …)`.
   Ветка `parallax` недостижима из любого плана.
2. Даже при диспатче `r_parallax` целится в `#behind-{index:02d}`
   (`templates.py:2019`), а такой узел создаётся **только** для шотов с
   `text_behind_head` на альфа-слотах аватара (`composition.py:529-536`).
   На кадре без аватара tween уходит в пустоту — GSAP молча ничего не делает.

**Правка (Q2):**

* `composition.py`: `_add_kenburns` → `_add_motion`, имя приёма берётся из
  `shot["motion"]["renderer"]` (по умолчанию `"kenburns"` — обратная
  совместимость сохранена).
* `r_parallax` получает **собственный** задний узел `#par-{index:02d}`,
  который `composition.py` создаёт при `shot["motion"]["renderer"] == "parallax"`:
  тот же `bg_file`, масштаб 1.12, z-index под основным клипом.
* `assemble.py` кладёт `motion` на ступени 4 лестницы (§7.2).
* `unreachable_categories` → `[]`; тест `test_template_picker.py:572` правится
  в том же PR.

Стоимость: ~60 строк, ноль новых зависимостей, ноль кредитов.

### 8.4 Развести A/B-пулы (MEGA F.6 — подтверждено на tip)

Проверено на `6e7719d`: пулы `text-fullscreen-default-a` и
`text-fullscreen-default-b` — **одно и то же множество из десяти шаблонов**,
различается только порядок в JSON. Всё различие вариантов держит
`_force_ab_difference` (`assemble.py:2907`, `limits.ab_min_template_diff: 3`).

**Правка (Q2):** развести по смыслу, а не по порядку.

```
default-a («спокойный»): stack-3lines · fact-card · per-word-crossfade ·
                         blur-out-up · date-marker · label-strip
default-b («ударный»):   bigtext-mask-footage · quote-frame · bottom-up-letters ·
                         kinetic-type-swap · impact-01 · scramble-reveal
```

`_force_ab_difference` остаётся страховкой, а не единственным механизмом.
Тест: на десяти сидах `len(set(A) & set(B)) ≤ 2`.

### 8.5 `frequency` — доля, а не ключ сортировки

**Улика.** `templates.py:296-301`, ранг кандидата:

```python
return (explicit, freq, grounded, used_recently, usage, template.id)
```

`freq` стоит **раньше** `grounded`: signature-шаблон, не совпавший с признаками
блока, выигрывает у variant-шаблона, который совпал. И раньше `used_recently`:
LRU разводит только внутри одного уровня частоты. Множество
`_FS_SIGNATURE` (`templates.py:31-34`) — **шесть** шаблонов; при четырнадцати
FS-кадрах эти шесть неизбежно повторяются. Факт: `blur-out-up` ×3,
`bigtext-mask-footage` ×2 на 0042.

MEGA F.2 задавала не сортировку, а **доли**: signature 60–80 %, variant 15–25 %,
rare ≤ 5–10 %. Реализована сортировка. Это и надо исправить.

**Правка (Q2):** `FrequencyBudget` на ролик — счётчик выданных пиков по
уровням. Пока доля signature ниже нижней границы — `freq` работает как сейчас.
Как только доля signature достигла верхней (0.80) — уровень `signature`
**временно исключается** из allow, и picker честно уходит в `variant`.
`rare` открывается только при совпадении `needs` (правило MEGA не меняется).

Инвариант теста: на ролике из 20 кадров доли лежат в
`signature ∈ [0.55, 0.80]`, `variant ∈ [0.15, 0.35]`, `rare ≤ 0.10`, и
`max(Counter(ids)) ≤ 2`.

### 8.6 Починить словари условий

* **N-14.** Интенты используют сигнал `numbers` (7 штук), манифест — признак
  `number` (26 штук). Приводим интенты к словарю `meaning.py`
  (`number`, `question`, `quote`, `comparison`, `device`, `place`, …), а
  структурные сигналы (`plate`, `icons`, `alpha`, `lines_ge_7`) оставляем как
  есть — они про наличие данных, а не про смысл.
* **N-13.** `lowerthird-metric-badge` требует `numbers`, а оба вызова
  `lower-thirds` (`assemble.py:2057`, `:2096`) сигналов не передают вовсе →
  интент мёртв. Передаём `signals=set(block_traits(...))` на обоих вызовах.

### 8.7 Что переводим в `candidate` и `retired`

Ничего **не удаляем** (анти-цель MEGA). После Q2 прогоняется отчёт «кто не
выбирался ни разу за 5 роликов» и спорные строки уходят в `status: candidate`
списком в описании PR — **подтверждает человек**, не автомат (правило MEGA F.4).

---

## 9. Сток и семантическое соответствие

### 9.1 Убить слепой пад — он живёт в двух местах

MEGA C.3 нашла один. Их два, и второй агрессивнее первого.

**Место 1** — `src/lib/query.py`, шаг 5 функции `build_queries`:

```python
# 5. Bonus space/news plates — keep avatar BGs and templates interesting
out.extend(["deep space stars", "galaxy nebula", "earth orbit view",
            "newsroom broadcast desk", "breaking news screen"])
```

**Место 2** — `src/p7_broll_search/search.py:219-221`:

```python
# Aggressive pad: space/news always in the ladder so avatar BGs get plates.
for extra in ("deep space stars", "galaxy nebula", "earth orbit view",
              "newsroom broadcast desk", "breaking news screen"):
```

Пять универсальных запросов подмешиваются **в каждый слот каждого ролика**
независимо от темы. Ролик про квантовый чип честно получает галактику и
студию новостей — и критик пишет «пастельные кубики про LLM», «фиолетовые
бактерии», «ядовитая жёлто-зелёная сетка».

**Правка (Q2):**
* Пад **не удаляется**, а гейтится: он допустим, только если
  `classify_intent(slot) ∈ {"space", "news"}` **или** у слота нет ни одного
  предметного концепта из `CONCEPTS`.
* В обоих местах — один и тот же гейт, вынесенный в `query.py::allow_generic_pad()`.
* Тест: на `redshift_0042` (`category: ai`, тема — квантовый чип) ни один слот
  не получает `galaxy nebula`.

### 9.2 `topical_match_score` — на трёх точках

Функции в репозитории нет (grep пуст). Пишем ровно как в MEGA C.3, с одним
уточнением: она нужна не только для отбраковки, а как **вход в лестницу
закрытия кадра** (§7.2) — если материал есть, но не про то, честнее закрыть
кадр приёмом, чем поставить чужую картинку.

```python
def topical_match_score(candidate_tags: set[str], block_text: str,
                        category: str) -> float:
    """0..1: насколько материал про то, о чём реплика.

    Не заменяет vision. Vision отвечает «что изображено», эта функция —
    «относится ли изображённое к тому, что сейчас звучит». На 0042 vision
    честно написал бы «светящиеся фиолетовые сферы» — и был бы прав;
    отбраковать клип должен именно тематический счёт.
    """
```

Три точки применения (как в MEGA):
1. `search.py` — ранжирование кандидатов до скачивания.
2. `judge.py` — множитель к `score`, порог `0.35` на приём.
3. `assemble.py` — вход в лестницу: `< 0.35` → слот считается пустым.

### 9.3 Словарь `CONCEPTS` — ревизия

`query.py:19-58` — 37 триггеров. Дыры, видные глазом:

| Триггер | Сейчас | Должно быть |
|---|---|---|
| `процессор` | `processor macro shot`, `silicon chip`, `computer hardware closeup` | `cpu die macro`, `silicon wafer closeup`, `circuit board macro` (MEGA K.3 п.3) |
| `квант` | `quantum processor`, `quantum computer`, `cryostat laboratory` | + `dilution refrigerator gold`, `superconducting qubit chip` |
| `ошибк` | `error warning screen`, `glitch abstract` | + `error correction diagram`, `signal noise oscilloscope` |
| `вселен` | `universe deep space`, `cosmic web visualization` | оставить, но **запретить** как пад |

Плюс: у 0042 в кадре 0 стоял `pexels_v18069803` — пастельные кубики про LLM,
с вшитой подписью `PEXELS / GOOGLE DEEPMIND`. Это в `prefer`-пинах Маркуса,
поэтому движок его не тронет. Нужен **отдельный гейт на вшитые титры**:
`has_text`/`watermark` из vision-вердикта уже возвращаются
(`vision.py:79-80`) и **никак не используются в отборе**. Правка: `watermark == true`
→ жёсткий reject, даже для `prefer`-пина, с записью в лог, чтобы Маркус видел,
какой его пин отклонён и почему.

### 9.4 Прекратить `skip_vision` на полировке (деньги — в нашу пользу)

**Улика.** Лог эталонного прогона:

```
{"logger":"redshift.p8","msg":"оценка футажей завершена",
 "judged":23,"accepted":3,"fill_rate":0.1765,"arbiter_calls":0,
 "reused":8,"unfilled":14,"rejected_by_palette":0,"rejected_by_dark":0}
```

Прогон шёл с `skip_vision=true` → `vision.skip_live` → `judge.py` честно
выдаёт `skip_live_unverified` и **не закрывает слот** (это правильный
fail-closed из P0). Итог: 14 пустых слотов → 14 текстовых кадров.

**Арифметика.** 23 кандидата × 3 пробных кадра (`stock.video_probe_frames`)
× `budget.price.gemini_per_image = 0.0004` ≈ **$0.028**. Плюс смысловой QC:
6 сэмплов × 2 варианта × $0.0004 = **$0.005**. Итого **≈ $0.03** при лимите
`budget.max_cost_per_video_usd: 6.00`.

**Решение.** Денежные замки не трогаем: `elevenlabs=0`, `heygen=prepared`,
`generation.skip=true`, `allow_xai=false`. А `skip_vision` на пересборке
**снимаем**. Команда пересборки:

```bash
gh workflow run build-video.yml --ref fix/quality-overhaul-0042b \
  -f script=scripts/redshift_0042.json \
  -f providers_mode=auto -f from_step=P7 -f force=true \
  -f skip_vision=false \
  -f skip_generate=true \
  -f heygen_source=prepared
```

`force=true` обязателен: на эталонном прогоне P7 отработал «шаг из кэша», и
пул кандидатов не рос вовсе.

### 9.5 Пополнять библиотеку футажа **вне** сборки ролика

**Улика.** `cache/footage_index.json`: 65 записей на весь канал, из них
**видео — 21**, фото NASA — 44, `quarantined` — 7. Для 0042 в `deny` восемь id.
То есть на ролик доступно порядка десяти клипов. При `stock.target_pool_size:
[50, 100]`.

При этом `.github/workflows/fill-libraries.yml` умеет доливать
`options: [sfx, music, memes, all]` — **footage там нет**, хотя
`config.yaml` содержит `libraries.footage: {max_items: null, eviction: lru}`.

**Правка (Q2):**
* `src/lib/library_filler.py` + `src/cli.py` получают `--kind footage`
  и `--topic "<тема>"`.
* `fill-libraries.yml` — новая опция `footage` и текстовый вход `topic`.
* Режим: только Pexels / Pixabay / NASA / Internet Archive (анонимно или по
  бесплатным ключам), **без** Magnific API. Скачивание из каталога Freepik по
  подписке Magnific кредитов не стоит (`config.yaml` это фиксирует) — разрешено.
* Цель: **60+ видеоклипов** в индексе до пересборки 0042, помеченных тегами
  тем канала (`quantum`, `chip`, `space`, `lab`, `brain`, `genome`).

Это единственный способ поднять `fill_rate` с 0.18 до 0.70, не рисуя ничего.

### 9.6 Генерация — только когда сток честно исчерпан

Порядок MEGA §K++ не меняется. Уточнение одно: **генерация вызывается
после того, как лестница §7.2 дошла до ступени 6**. То есть кадр, который
удалось закрыть карточкой или диаграммой, генерации не требует.
Kling 2.5 ∞ = **720p**, браузер, Nano Banana 2 / Seedream 5 Pro для stills.
На полировке 0042 — `skip_generate=true`, ноль вызовов.

---

## 10. Звук: следующая волна

P0 развёл `card_appear` и `avatar_in` (`sfx_library.py:87` vs `:93`) — это
landed, не повторяем. `pick_bed` уже учитывает `used_in` и общий счётчик
(`music_library.py:348-356`) — MEGA K.3 п.8 закрыт, снимаем с плана.

Что остаётся.

### 10.1 Ротация «сценария звука», а не файлов

Библиотека заморожена (`libraries.sfx.max_items: 20`, сейчас 18 записей,
`frozen_when_full: true`). Новые записи — **только после визуального OK**
(правило MEGA G.7). Уникальность даёт **отображение**, а не файлы.

`SFX_SCENARIOS` — три-четыре именованные раскладки `event → intent`:

| Сценарий | `card_appear` | `avatar_in` | `transition` | `reveal_fullscreen` | Когда |
|---|---|---|---|---|---|
| `glass` (signature) | `click/snap` | `hat/bright` | `whoosh/swipe` | `reveal/hat` | по умолчанию |
| `impact` | `hit/punch` | `whoosh/wide` | `hit/thud` | `hit/punch` | `twist`-тяжёлые ролики, `binary_vote` |
| `soft` | `chime/kalimba` | `whoosh/soft` | `whoosh/soft` | `chime/kalimba` | medicine, `open_question` |

Выбор — по `video_id` + рубрике + кольцу последних двух (та же механика, что
у `pick_bed`). Ноль новых файлов, ноль кредитов.

### 10.2 Антиповтор внутри ролика

`limits.sfx_min_gap_sec: 2.0` есть. Нет потолка на **повтор одного файла**.
Добавляем `limits.sfx_same_file_max: 3` — тот же wav не звучит больше трёх раз
за ролик (правило из research §5.3). Проверка — расширение существующего
`tests/test_sfx_event_matrix.py`.

### 10.3 Беды: кольцо, а не только счётчик

`pick_bed` ранжирует по `used_in`, но кольца последних N в
`editing_preferences.json` нет. Добавляем `bed_ring` (последние 3) рядом с
`ending_ring` — один и тот же файл конфига, одна и та же механика.

### 10.4 Плотность первых трёх секунд

Research: в первые 3 с не должно быть мёртвой паузы > ~200 мс между звуковыми
событиями. Сегодня это нигде не проверяется. `QC-28` (§12.2), предупреждающий.

### 10.5 Новые записи — после OK

2–4 курируемых wav (`glass-pop`, `avatar-riser`, `myth-flip reverse`) —
**только** после того, как Маркус принял визуал. До этого библиотека заморожена.

---

## 11. Токены и стоимость: где резать, а где не трогать

### 11.1 Честная картина: пайплайн уже дёшев

Измерено на эталонном прогоне: `cost_report.json` → `total_usd: 0`,
`by_service: {}`. С включённым vision (§9.4) прогон стоит **≈ $0.03**.
Промпты vision компактны: `PROMPT` ~1.1 КБ, `FINAL_FRAME_PROMPT` ~1.7 КБ
(`vision.py:69-115`), кадров на кандидата — 3.

**Вывод: экономить внутри пайплайна нечего.** Любая «оптимизация токенов
Gemini» здесь даст доли цента и заберёт качество. Резать надо там, где реально
горит: **контекст агентов**.

### 11.2 Что действительно дорого — контекст агента

Измерено на диске:

| Файл | Размер | Кто его читает целиком | Что делать |
|---|---|---|---|
| `src/lib/render/hyperframes/templates.py` | **702 КБ** | агент, ищущий один рендерер | **никогда не читать целиком**; `grep -n "def r_<name>"` + `sed -n 'X,Yp'` |
| `templates/manifest.json` | **135 КБ** | агент, выбирающий шаблон | сгенерировать `templates/manifest.index.json` — `id \| category \| frequency \| needs \| duration_range`, ≈ 12 КБ |
| `config/template_scenarios.json` | **78 КБ** | агент, правящий интенты | `config/template_scenarios.index.json` — `intent_id \| categories \| weight \| templates`, ≈ 8 КБ |
| `instruction.md` | **79 КБ** | все агенты «на всякий случай» | уже есть 16 скиллов в `.claude/skills/` — читать скилл, а не монолит |
| `cache/footage_index.json` | **61 КБ** | агент, анализирующий сток | никогда не пересылать: файл локальный, работать `python3 -c` фильтром |
| `src/p11_assemble/assemble.py` | **156 КБ** | агент, правящий сборку | по функциям через `grep -n "def "` |

**Правило для исполнителя (Grok), в описание каждого PR:**
> Ни один файл > 40 КБ не читается целиком. Читается срез по номерам строк,
> найденный `grep -n`. Индексы (`*.index.json`) генерируются `tools/gen_indexes.py`
> и обновляются тем же хуком, что и манифест.

### 11.3 Безопасные срезы внутри пайплайна

| Что | Сегодня | Правка | Экономия |
|---|---|---|---|
| Смысловой QC | 6 сэмплов × **2 варианта** = 12 вызовов Gemini | считать только по первичному варианту, второй — только при расхождении > 0.15 | −6 вызовов/сборка |
| Повторный суд над тем же ассетом | `reused: 8` из 23 — кэш работает | оставить как есть, **не трогать** | — |
| P7 | `шаг из кэша` целиком, пул не растёт | кэшировать по паре `(query, source)` с TTL, а не шаг целиком | пул растёт, стоимость та же (сток бесплатен) |
| Промпты vision | 1.1 / 1.7 КБ | **не трогать** — уже минимальны и точны | — |
| Арбитр | `arbiter_max_calls: 8`, фактически 0 | **не трогать** | — |

### 11.4 Чего НЕ делать

Не пытаться заменить Gemini на «локальную эвристику ради экономии»: это
попытка, которую MEGA D-3 уже разобрала — провайдера `local_heuristics` не
существует, а fail-closed без vision даёт ровно то, что мы получили —
`fill_rate 0.1765`.

---

## 12. CI и QC-гейты удержания

### 12.1 Номера: что за кем закреплено

* **QC-1 … QC-19** — существуют (`p12_render_qc/qc.py`), не трогаем.
* **QC-20 / QC-21 / QC-22** — **зарезервированы за MEGA P1**
  (текст за work_area; `ungrounded ≤ 0.30`; `picked ∈ allow`).
  Реализуются в Q1 **в формулировке MEGA**, без изменений.
* **QC-23 … QC-29** — новые, этой волны.

### 12.2 Новые гейты

| id | Что проверяет | Источник | Порог | Тип |
|---|---|---|---|---|
| **QC-23** | полноэкранных текстов **в смонтированном ролике** (а не в плане) | `count(edit_plan.shots.kind=="fullscreen_text")` | ≤ `limits.fullscreen_text_per_video[1]` | **блокирующий** |
| **QC-24** | голых плит без текста и ассета | `gap_reason` содержит `plate without text` | ≤ 2 | **блокирующий** |
| **QC-25** | визуальное разнообразие: ни один шаблон больше двух раз; приём `payoff` не повторяет приёмы `stretch` | `templates_used`, `shots[].beat` | `max_count ≤ 2` и `renderer(payoff) ∉ renderers(stretch)` | **блокирующий** |
| **QC-26** | заполнение слотов материалом | `p8.fill_rate` из отчёта P8 | ≥ 0.70 при живом vision; предупреждение при `skip_live` | блокирующий/предупр. |
| **QC-27** | шов лупа | dHash кадра 0 vs последнего | ≤ 12 бит; **только** при `cta.type == visual_loop_seam` | условно блокирующий |
| **QC-28** | плотность первых 3 с: нет паузы > 200 мс между звуковыми событиями | `sfx_map` + VO | предупреждение | предупр. |
| **QC-29** | экранный хук: текст на кадре к ≤ 1.0 с, 3–7 слов, не из стоп-листа | первый текстовый узел `edit_plan` | блокирующий | **блокирующий** |

Плюс **QC-30 (акцент)** — вынесен отдельно, потому что зависит от §7.5:
доля red+cyan в кадре ∈ [0.02, 0.12], измеряется на тех же 6 сэмплах.

### 12.3 Измерение акцента без лишних кадров

`vision_qc.py:94-97` уже извлекает 6 кадров шириной 540. Подсчёт долей HSV
делается на них же, в том же цикле, до отправки в Gemini. Ноль новых
`ffmpeg`-вызовов, ноль новых API-вызовов.

### 12.4 Предрендерный линт

`tools/lint_composition.py` получает проверку выхода за `work_area` (740 px) —
это MEGA K.3 п.5, переносим как есть. Запускается **до** финального рендера в
`ci.yml` и в `build-video.yml`: ошибка композиции стоит секунды линта вместо
минут рендера.

### 12.5 Регрессионные тесты

`tests/test_no_junk_regressions.py` (MEGA K.3 п.6) расширяется до
retention-регрессий:

1. `app-showcase` не выбирается ни на одном сиде.
2. Матрица A/B × длительность: `picked ∈ allow` на 252 комбинациях.
3. Три карантинных id не проходят P7/P8 при `skip_live`.
4. AST: каждый вызов `fit_size` имеет `role=`.
5. Edit-план не содержит `_FS_DEMO_WORDS`.
6. Субтитр не пересекает bbox карточки.
7. **NEW** — при 14 пустых слотах и нулевом стоке план содержит ≤ 4
   `fullscreen_text` и ≤ 2 плиты (лестница §7.2).
8. **NEW** — `galaxy nebula` не появляется в запросах для `category: ai`.
9. **NEW** — `intro-hooks` присутствует в `templates_used` при `role="hook"`.
10. **NEW** — сценарий с `emphasis_family: tech` даёт cyan-класс в HTML.

### 12.6 Отчёт: чтобы DoD было чем проверять

`p12_render_qc/render.py:430-441` кладёт в `build_report` только
`cost_usd: ctx.costs.total_usd`. Добавляем два поля:

```python
"costs": ctx.costs.to_dict(),          # by_service уже есть в costs.py:49
"pick_traces": pick_traces,            # allow_size, escaped, fired, won_at
```

`PickTrace` возвращается **всеми десятью** вызовами `picker.pick` и **везде
выбрасывается** в `_`. Собираем в список и печатаем. Без этого QC-25 и денежный
DoD §4.4 нечем закрыть.

### 12.7 CI

`ci.yml` не меняется структурно (`pytest -q --maxfail=1` + сквозной mock-прогон).
Добавляется шаг после mock-прогона:

```yaml
- name: Retention-гейты на mock-ролике
  run: python -m src.cli qc-report --check QC-23,QC-24,QC-25,QC-29 \
       --input output/redshift_mock/edit_plan_B.json
```

Mock-прогон не требует ключей и не тратит ни цента — а именно он ловит
регресс лестницы.

---

## 13. Фазы Q1 / Q2 / Q3

Все три фазы **после** MEGA P0b. Money-safe на всех: `heygen_source=prepared`,
`generation.skip=true`, `allow_xai=false`, ноль ElevenLabs. Единственное
изменение — `skip_vision=false` (§9.4), стоимость ≈ $0.03.

### Q1 — кадр перестаёт быть текстом (2–3 дня)

| # | Шаг | Файлы | Тест | DoD |
|---|---|---|---|---|
| Q1.1 | Лестница закрытия кадра, `VisualBudget` | `src/p11_assemble/assemble.py` (замена ветки `:2601-2670`) | `tests/test_gap_ladder.py` | при 14 пустых слотах: FS ≤ 4, плит ≤ 2, приёмов ≥ 6 |
| Q1.2 | Хук: вызов `intro-hooks`, `meta.hook`, `HOOK_STYLES` | `assemble.py`, `src/lib/schema.py`, `src/p0_validate/validator.py`, `config/template_scenarios.json`, `tests/test_template_picker.py:572` | `tests/test_hooks.py` (7 кейсов) | `intro-hooks/*` в `templates_used`; текст на кадре ≤ 1.0 с |
| Q1.3 | Cyan в кадре: чтение `emphasis_family`, классы, CSS | `assemble.py`, `captions.py`, `templates.py:83`, `scripts/redshift_0042.json` | `tests/test_accent_family.py` | cyan ≥ 1 бит; red и cyan не на одной фразе |
| Q1.4 | Измерение акцента + QC-30 | `p12_render_qc/render.py`, `vision_qc.py` | `tests/test_palette.py` (расширение) | `accent_share_max ∈ [0.02, 0.12]` |
| Q1.5 | QC-23/24/25/29 + `pick_traces` и `costs` в отчёт | `p12_render_qc/qc.py`, `render.py`, `assemble.py` (10 мест `_` → сбор) | `tests/test_no_junk_regressions.py` (+4 кейса) | 4 новых гейта в `build_report.qc` |
| Q1.6 | MEGA P1 хвост: QC-20/21/22 + `lint_composition` work_area | `qc.py`, `tools/lint_composition.py` | существующие + `test_render.py` | номера MEGA заняты в формулировке MEGA |
| Q1.7 | Полный `pytest` → push → **пересборка с `skip_vision=false`, `force=true`** | — | 1495+ | Маркус смотрит B |

**Гейт Q1 → Q2:** V-1, V-2, V-6, V-7, V-8, V-9 из §4.3 — зелёные.
Без этого Q2 не начинается: смысла тюнить сток, пока кадр не умеет им
пользоваться, нет.

### Q2 — система перестаёт голодать (3–4 дня)

| # | Шаг | Файлы | Тест | DoD |
|---|---|---|---|---|
| Q2.1 | `--kind footage` в доливке библиотек + workflow | `src/lib/library_filler.py`, `src/cli.py`, `.github/workflows/fill-libraries.yml` | `tests/test_footage_pipeline.py` (+) | в индексе **≥ 60 видео** |
| Q2.2 | Гейт слепого пада в обоих местах | `src/lib/query.py`, `src/p7_broll_search/search.py:219` | `tests/test_footage_seed.py` (+) | `galaxy nebula` не уходит на `category: ai` |
| Q2.3 | `topical_match_score` на трёх точках | `src/lib/query.py`, `search.py`, `judge.py`, `assemble.py` | `tests/test_broll_topical.py` | off-topic отклоняется до скачивания |
| Q2.4 | Ревизия `CONCEPTS` + жёсткий reject по `watermark` | `src/lib/query.py`, `src/p8_broll_judge/judge.py` | `tests/test_footage_pipeline.py` | клип с вшитым `PEXELS` не попадает в кадр даже из `prefer` |
| Q2.5 | Оживить `data-viz`: числительные словами + роли + бюджет 2 | `assemble.py:1826`, `:2207`, `src/lib/meaning.py` (экспорт `_NUMBER_WORDS`) | `tests/test_meaning.py` (+), `tests/test_dataviz_reach.py` | на 0042 ≥ 1 `data-viz/*` в `templates_used` |
| Q2.6 | Оживить `parallax`: диспатч `render_motion` + свой задний слой | `composition.py:453-463`, `:529`, `templates.py:2010-2027`, `assemble.py` | `tests/test_hyperframes_templates.py` (+) | `parallax/*` в `templates_used`; `unreachable_categories == []` |
| Q2.7 | `FrequencyBudget` — доля вместо ключа сортировки | `src/lib/templates.py:296`, `src/lib/template_picker.py` | `tests/test_template_picker.py` (+) | signature ∈ [0.55,0.80]; `max_count ≤ 2` |
| Q2.8 | Развести A/B-пулы | `config/template_scenarios.json` | `tests/test_template_picker.py` (+) | пересечение ≤ 2 на 10 сидах |
| Q2.9 | Словари условий: `numbers → number`, сигналы на `lower-thirds` | `config/template_scenarios.json`, `assemble.py:2057,2096` | `tests/test_template_picker.py` (+) | `lowerthird-metric-badge` достижим |
| Q2.10 | Признак `mechanism` (схемы без чисел) | `src/lib/meaning.py` | `tests/test_meaning.py` | `flowchart` достижим |
| Q2.11 | Индексы для агентов + правило «не читать > 40 КБ» | `tools/gen_indexes.py`, `templates/manifest.index.json`, `config/template_scenarios.index.json` | `tests/test_learning_and_ops.py` (+) | индексы генерируются и совпадают с источником |

**Гейт Q2 → Q3:** V-3 (`fill_rate ≥ 0.70`), V-4, V-5 — зелёные;
`templates_used` содержит ≥ 1 `data-viz` и ≥ 1 `parallax`.

### Q3 — язык, концовки, атмосфера (2–3 дня)

| # | Шаг | Файлы | Тест | DoD |
|---|---|---|---|---|
| Q3.1 | `CTA_TYPES` → 8 + `ending_ring` + маппинг legacy | `src/lib/schema.py:19`, `src/p0_validate/validator.py`, `config/editing_preferences.json` | `tests/test_p0_validate.py` (+) | 0043 не повторяет тип концовки 0042 |
| Q3.2 | `visual_loop_seam` + QC-27 (dHash) | `assemble.py`, `p12_render_qc/qc.py` | `tests/test_loop_seam.py` | шов ≤ 12 бит |
| Q3.3 | Карта битов `beat` в слотах + правило эскалации | `src/p5_replan/replanner.py`, `assemble.py`, `template_picker.py` | `tests/test_replan_beats.py` | `renderer(payoff) ∉ renderers(stretch)` |
| Q3.4 | `config/glossary.json` + `soften_on_screen_copy` **только для VO**, не для карточек | `src/lib/text.py`, `config/glossary.json` | `tests/test_press_material.py` (+) | «(квантовый бит)» не появляется ни на одной карточке |
| Q3.5 | Русский `snippet` обязателен на карточке источника | `src/lib/schema.py`, `assemble.py` | `tests/test_press_material.py` | англ. заголовок только мелко/доменом |
| Q3.6 | 4 плиты подложек (браузер Magnific, ∞) + `config/backdrop_pins.json` | `assets/backdrops/*`, `src/lib/backdrop.py:83` | `tests/test_render.py` (+) | `PLATES` покрывает 5 сцен без алиасов |
| Q3.7 | `SFX_SCENARIOS` + `sfx_same_file_max` + `bed_ring` + QC-28 | `src/lib/sfx_library.py`, `src/p10_audio/audio_build.py`, `config/editing_preferences.json` | `tests/test_sfx_event_matrix.py` (+) | два соседних ролика звучат разными раскладками |
| Q3.8 | `script_playbook.md` — разделы «Хук как система» и «Язык для всех» | `script_playbook.md`, `rejected_patterns.md` | — | банк хуков §5.4 в репозитории |
| Q3.9 | Magnific UI-селекторы после первого живого прогона Grok Bot | `tools/magnific_browser_sop.md` | — | SOP воспроизводим вторым агентом |
| Q3.10 | Дедуп смыслового QC по вариантам | `p12_render_qc/render.py` | `tests/test_skip_vision_gen.py` (+) | −6 вызовов Gemini на сборку |

---

## 14. Гейт 0043+

0043 (и любой платный прогон) запускается **только** при всех условиях:

1. **Визуальный DoD §4.3** — все четырнадцать строк зелёные на пересобранном
   0042 B, и Маркус написал «ок» словами.
2. **Вердикт Gemini** по пересобранному B: `visual ≥ 6`, `broll ≥ 6`,
   `retention ≥ 6`, `SEND_TO_MARKUS: YES`.
3. `pytest` зелёный целиком.
4. `build_report.costs` посервисно: `elevenlabs 0`, `heygen 0`, `magnific 0`,
   `grok 0`, `gemini ≤ 0.10`.
5. Тип концовки 0043 выбран ротатором и **не** повторяет 0042.
6. Сухой прогон P11 на сценарии 0043 **до** живого рендера:
   `picked ∈ allow` на всех слотах, `ungrounded ≤ 0.30`,
   FS ≤ 4, плит ≤ 2 — это дешевле рендера.
7. Библиотека футажа ≥ 60 видео (Q2.1), иначе 0043 повторит историю 0042.

Только после этого — то, что MEGA §J отложила:

| Что | Условие |
|---|---|
| Экспрессивный TTS (расширение `voice_settings`) | первый платный прогон после OK |
| Нативный 9:16 HeyGen Avatar V | тот же прогон |
| Тема GPT-6 Astra | после приёмки 0042 |

---

## 15. Риски и не-цели

| Риск | Вероятность | Что делаем |
|---|---|---|
| Лестница §7.2 «сползёт» на первую ступень и даст 14 карточек вместо 14 надписей | **высокая** без бюджета | `VisualBudget` с потолком на каждую ступень + QC-25 (`max_count ≤ 2`) |
| `fill_rate ≥ 0.70` недостижим на текущей библиотеке | **высокая** | Q2.1 (доливка ≥ 60 клипов) — **предусловие**, а не следствие |
| Wire `parallax` даст пустые tween'ы (узел `#behind-NN` не создан) | **средняя** | собственный узел `#par-NN`, тест на присутствие узла в HTML |
| Cyan «расползётся» и убьёт красный акцент | средняя | правило «один акцент-токен на бит» + QC-30 (суммарно ≤ 0.12) |
| `FrequencyBudget` уронит узнаваемость канала | средняя | нижняя граница signature 0.55 — жёсткая |
| Хук с `cold_open` не найдёт кадра и вернёт чёрное | средняя | ступень 6 лестницы (плита) допустима **только** здесь; иначе `hook_style` падает на `blackout_word` |
| Смена `CTA_TYPES` сломает старые сценарии | низкая | маппинг legacy в `p0_validate`, тест на все шесть скриптов |
| Гонка за токенами испортит vision | низкая | §11.4 — промпты не трогаем |
| Снятие `skip_vision` воспримется как «разрешили тратить» | низкая | явная строка в §9.4 и в описании PR: разрешён **только** Gemini, потолок $0.10 |

**Не-цели этой волны:** новый рендерер под хуки; переписывание
`template_scenarios.json` целиком; удаление шаблонов; блокирующий `escaped`;
новые SFX-записи до визуального OK; экспрессивный TTS; нативный 9:16;
оптимизация промптов Gemini; смена палитры (red остаётся `#C8453D`,
cyan `#36EFFF` до скринов Маркуса).

---

## 16. Приложение: улики скана

Всё ниже снято на `/workspace/repos/Redshift-shorts`, ветка
`fix/quality-overhaul-0042b`, tip `6e7719dcdda0a67da9cb75e7e00f8fbd68ba3182`,
2026-09-08.

### A. Каталог шаблонов

```
всего                    204
по категориям  transitions 41 · text-fullscreen 34 · data-viz 28 ·
               hero-devices 25 · browser-ui 21 · lower-thirds 14 ·
               kenburns 10 · intro-hooks 8 · frames-cards 7 ·
               avatar-entry 6 · outro-cta 6 · parallax 4
status         active 193 (поле отсутствует) · retired 9 · gated 2
frequency      variant 122 · signature 52 · rare 30      ← P0 landed

использовано хотя бы раз                131
НЕ использовано ни разу                  73   (35.8 %)
  data-viz 28/28 · lower-thirds 11/14 · intro-hooks 8/8 · browser-ui 7/21 ·
  text-fullscreen 6/34 · hero-devices 5/25 · parallax 4/4 · outro-cta 4/6
```

### B. Категории, которые вызывает `assemble.py`

Десять вызовов `picker.pick`, первый аргумент:

```
:1401  hero-devices        :2163  outro-cta        :2686  kenburns
:1932  browser-ui | frames-cards (по форме источника)
:2057  lower-thirds        :2269  data-viz         :2703  avatar-entry | transitions
:2096  lower-thirds        :2561  text-fullscreen
                           :2635  text-fullscreen
```

`intro-hooks` и `parallax` — **ни разу**. `PickTrace` во всех десяти местах
уходит в `_`.

### C. Эталонный прогон 34172909306 (`redshift_0042`, 44.511 с)

```
P8 :  judged 23 · accepted 3 · fill_rate 0.1765 · reused 8 · unfilled 14
      arbiter_calls 0 · rejected_by_palette 0 · rejected_by_dark 0

edit_plan_B.shots = 20
  kind:  fullscreen_text 14 · footage 3 · avatar 3
  gap_reason «материал не найден: кадр закрыт словом блока» : 14
  ассеты в кадре: pexels_v18069803, pexels_v34912823, pixabay_v113379  (три)
                  два из трёх — те, что критик назвал браком

stats (из плана, не из кадра):
  avatar_share 0.476 · max_event_gap 2.373 · cut_share 0.80
  fullscreen_text_count 2      ← план говорит 2, в ролике 14
  first_event_sec 0.0 · max_shot_sec 4.373 · min shot 0.30

render_stats (оба варианта):
  accent_share_max 0.0         ← бюджет акцента 0.12 не измеряется
  safe_zone_violations []

cost_report: total_usd 0 · by_service {}   ← money-safe подтверждён
qc: passed на A и B                        ← 19 из 19, при visual 2/10
templates_used 26 записей, 23 различных, blur-out-up ×3, bigtext-mask-footage ×2
категории в кадре (shots): text-fullscreen, kenburns, avatar-entry, transitions
```

### D. Библиотеки

```
cache/footage_index.json : 65 записей — video 21, photo 44 (nasa 44, pexels 17, pixabay 4)
                           quarantined 7
config/footage_pins.json : redshift_0042 → prefer 5, deny 8
assets/backdrops/        : grid.jpg, horizon.jpg  (2 файла на 5 сцен;
                           PLATES["space"] = "horizon.jpg" — алиас)
assets/sfx/              : 19 wav + манифест, max_items 20, count 18
assets/music/            : 9 бедов + манифест, max_items 15
stock.target_pool_size   : [50, 100]        ← при 21 доступном видео
fill-libraries.yml kinds : sfx | music | memes | all   ← footage отсутствует
```

### E. Цепочки, оборванные на полпути

| Что | Где создаётся | Где потребляется |
|---|---|---|
| `plan.hook_window` | `replanner.py:1027` | **нигде** |
| `emphasis_family` | `schema.py:78` | **нигде** |
| `MOTION["parallax"]` | `templates.py:2026` | `render_motion` зовут только с `"kenburns"` (`composition.py:460`) |
| `.word.emphasis.cyan` | `brand_css.py:249` | класс не выводится ни одним модулем |
| `.fullscreen-text .accent-cyan` | `brand_css.py:295` | то же |
| `PickTrace` | `template_picker.py:529-538` | все 10 вызовов пишут в `_` |
| `Costs.by_service()` | `costs.py:49` | в `build_report` не попадает (`render.py:430-441`) |
| `libraries.footage` | `config.yaml` | `fill-libraries` не умеет |

### F. Слепой пад — обе точки

```
src/lib/query.py, build_queries, шаг 5:
    out.extend(["deep space stars", "galaxy nebula", "earth orbit view",
                "newsroom broadcast desk", "breaking news screen"])

src/p7_broll_search/search.py:219-221:
    # Aggressive pad: space/news always in the ladder so avatar BGs get plates.
    for extra in ("deep space stars", "galaxy nebula", "earth orbit view",
                  "newsroom broadcast desk", "breaking news screen"):
```

### G. Числа в сценариях канала (почему `data-viz` мёртв)

| Сценарий | блоков с арабскими цифрами | годных для `data-viz` (роль `evidence`/`develop`) |
|---|---|---|
| 0042 | 1 (`105`, роль `setup`) | 0 |
| 0043 | 0 | 0 |
| 0044 | 0 | 0 |
| 0045 | 0 | 0 |
| 0046 | 1 (`87`, роль `evidence`) | 1 |
| 0047 | 0 | 0 |

Все шесть сценариев используют `cta.type: "question"` (0047 — тип не задан).

### H. Вес контекста для агентов

```
src/lib/render/hyperframes/templates.py   702 КБ
src/p11_assemble/assemble.py              156 КБ
templates/manifest.json                   135 КБ
instruction.md                             79 КБ
config/template_scenarios.json             78 КБ
cache/footage_index.json                   61 КБ
config/config.yaml                         23 КБ
script_playbook.md                         20 КБ
tests                                    1495 собранных
```

### I. Что уже проверяет P0 на уровне сценария (не дублировать)

`src/p0_validate/validator.py`: `HOOK_TOO_LONG` (`HOOK_MAX_SEC = 5.0`),
`HOOK_UNANSWERED`, `HOOK_NOT_FIRST`, `MISSING_HOOK`,
`LOOP_NO_PAYOFF_BLOCK`, `PAYOFF_TOO_EARLY` (`< 0.40`), `PAYOFF_TOO_LATE`
(`> 0.88`), `PAYOFF_RESTATES_SETUP`, `CTA_CLOSES_EVERYTHING`,
`DUPLICATE_BLOCK_ID`, `TARGET_DURATION_MISMATCH`, `FILLER_WORDS`,
`MEME_IN_MEDICINE`.

Петля удержания **на уровне текста** уже закрыта. Эта волна закрывает её
**на уровне кадра**.

---

## Как Маркус открывает этот файл

Публичной share-ссылки на сессию нет: прогон шёл в неинтерактивном
SDK-режиме Claude Code, где ссылка не выпускается. Локальные координаты:

* сессия: `bbc789cd-67db-45e1-bdae-b1e7865c50e9`
* транскрипт: `/home/box/.claude/projects/-workspace-repos-Redshift-shorts/bbc789cd-67db-45e1-bdae-b1e7865c50e9.jsonl`

Открыть документ:

```bash
cd /workspace/repos/Redshift-shorts && claude
> прочитай /workspace/tz/REDSHIFT-IMPROVE-TZ-vNEXT.md и начни с Q1.1
```

Или без запуска агента:

```bash
less /workspace/tz/REDSHIFT-IMPROVE-TZ-vNEXT.md
```

Статус исполнения и координаты — `/workspace/tz/OPUS-IMPROVE-STATUS.md`.

---

## Статус

**DRAFT — ждём «ок» Маркуса.** Кода по этому ТЗ **не написано ни строки**:
это документ. После одобрения исполняется Q1 (семь шагов) → пересборка 0042 B
с `skip_vision=false`, `force=true`, `heygen_source=prepared` → визуальная
приёмка → Q2 → Q3 → гейт 0043.

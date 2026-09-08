# OPUS-IMPROVE-STATUS

**Дата:** 2026-09-08 · **Модель:** `claude-opus-5` (ultrathink) · **Локаль:** Europe/Chisinau

## Что написано

| Артефакт | Абсолютный путь |
|---|---|
| Основное ТЗ (волна качества, post-MEGA) | `/workspace/tz/REDSHIFT-IMPROVE-TZ-vNEXT.md` |
| Этот статус | `/workspace/tz/OPUS-IMPROVE-STATUS.md` |
| Заметка о сессии | `/workspace/tz/OPUS-IMPROVE-SESSION.txt` |

Кода **не менялось**: `git status` на `/workspace/repos/Redshift-shorts` чист,
ни один файл репозитория не тронут. ТЗ ждёт одобрения Маркуса.

## Координаты скана

```
repo        /workspace/repos/Redshift-shorts
branch      fix/quality-overhaul-0042b
tip SHA     6e7719dcdda0a67da9cb75e7e00f8fbd68ba3182
MEGA base   913d891
builds_on   REDSHIFT-MEGA-TZ  (P0a/P0b не переспецифицируются)
tests       1495 collected
эталон      gh-artifacts/34172909306 → redshift_0042 A+B, 44.511 s
```

## Ссылка на сессию / share URL

**Share URL получить не удалось.** Прогон шёл в неинтерактивном SDK-режиме
Claude Code (`CLAUDE_CODE_ENTRYPOINT=sdk-cli`, `CLAUDE_CODE_CHILD_SESSION=1`);
в этом режиме публичная ссылка на разговор не выпускается, и создать её
командой из сессии нельзя.

Локальные координаты вместо ссылки:

```
session id  bbc789cd-67db-45e1-bdae-b1e7865c50e9
transcript  /home/box/.claude/projects/-workspace-repos-Redshift-shorts/bbc789cd-67db-45e1-bdae-b1e7865c50e9.jsonl
```

Как открыть ТЗ — см. `/workspace/tz/OPUS-IMPROVE-SESSION.txt`.

## Что внутри ТЗ (коротко)

Волна называется **Q1 / Q2 / Q3**, идёт **после** MEGA P0 и не повторяет его.

* **Корневая причина плохого 0042 B найдена числом:** P8 дал
  `fill_rate 0.1765` (`judged 23 · accepted 3 · unfilled 14`), а у сборщика на
  пустой слот ровно две ветки — полноэкранный текст или голая плита
  (`assemble.py:2601-2670`). Отсюда 14 текстовых кадров из 20 и `visual 2/10`
  при **19 из 19 пройденных QC**.
* **Q1** — лестница закрытия кадра из шести ступеней вместо двух; система
  хуков 0–5 с (категория `intro-hooks` сегодня недостижима, `hook_window`
  пишется и не читается); cyan из токена в кадр (`emphasis_family` не читается
  ни одним модулем, акцент субтитра прибит к красному); измерение доли акцента;
  QC-23/24/25/29 + MEGA-хвост QC-20/21/22.
* **Q2** — доливка библиотеки футажа (`fill-libraries` не умеет `footage`);
  слепой пад запросов убит в **двух** местах; `topical_match_score`; оживление
  `data-viz` (28 шаблонов, мертвы из-за чисел словами) и `parallax`
  (рендерер зарегистрирован, но не диспатчится); `frequency` как доля, а не
  ключ сортировки; развод A/B-пулов; индексы для экономии контекста агентов.
* **Q3** — ротатор концовок (`CTA_TYPES` = 3, все 6 сценариев используют
  `question`); измеримый шов лупа; карта битов; глоссарий; плиты подложек;
  ротация звуковых раскладок; SOP Magnific.

## Денежные замки — без изменений, кроме одного плюса

```
elevenlabs   0
heygen       0    (heygen_source=prepared)
magnific API 0    (generation.skip=true)
xai          0    (providers.allow_xai=false — landed в P0)
gemini      <= 0.10 USD
```

Единственная поправка: **`skip_vision=true` снимается** на пересборке.
Он экономил не деньги, а качество: именно из-за него `fill_rate` упал до 0.18.
Замер: 23 кандидата × 3 кадра × `$0.0004` ≈ **$0.03** при лимите 6 USD.

Команда пересборки (после одобрения Q1):

```bash
gh workflow run build-video.yml --ref fix/quality-overhaul-0042b \
  -f script=scripts/redshift_0042.json \
  -f providers_mode=auto -f from_step=P7 -f force=true \
  -f skip_vision=false -f skip_generate=true -f heygen_source=prepared
```

`force=true` обязателен: на эталонном прогоне P7 отработал «шаг из кэша»,
и пул кандидатов не рос вовсе.

## Метрика успеха для Маркуса (семь чисел + вердикт)

| Проверка | Порог | Сегодня |
|---|---|---|
| полноэкранных текстов в ролике | ≤ 4 | **14** |
| голых плит без текста | ≤ 2 | ≈10 после патча P0 |
| `fill_rate` | ≥ 0.70 | **0.1765** |
| повтор одного шаблона | ≤ 2 | 3 (`blur-out-up`) |
| кадров с «неплоским» приёмом | ≥ 3 | 1 |
| экранный хук на кадре | ≤ 1.0 с, 3–7 слов | собран случайно |
| доля акцента red+cyan | 0.02–0.12 | **0.0** (не измеряется) |
| вердикт Gemini по B | visual/broll/retention ≥ 6 | 2 / 2 / 2 |

## Следующий шаг

Маркус читает `/workspace/tz/REDSHIFT-IMPROVE-TZ-vNEXT.md` и говорит «ок» →
Grok max исполняет **Q1** (семь шагов) → полный `pytest` → пересборка 0042 B →
визуальная приёмка → Q2 → Q3 → гейт 0043.

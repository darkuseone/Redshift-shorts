# Каталог приёмов для режиссёра

> Производный файл: `python tools/gen_director_catalog.py`. Руками не править.
> Как ставить приём в ролик — `docs/director/TIMELINE.md`.

Колонка **куда** — поле таймлайна. **params** — ключи, которые рендерер
реально читает (вынуты из исходника); значения по умолчанию — в
`templates/manifest.json`. Текст на экране — капсом, 1–4 слова.

## avatar-entry — 6

Куда: `shot.transition (вход ведущего)`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `avatar-entry/circle-mask-grow` | Круг раскрывается | mask_wipe | 0.24–0.4 | shape |
| `avatar-entry/flash-cut-in` | Вход через вспышку | white_flash | 0.14–0.24 | peak |
| `avatar-entry/hero-zoom-in` | Вход зумом на аватар | zoom_punch | 0.2–0.4 | from_scale, overshoot |
| `avatar-entry/scale-pop` | Пружинистое появление | zoom_punch | 0.2–0.34 | from_scale, overshoot |
| `avatar-entry/slide-from-bottom` | Выезд снизу | paper_slide | 0.22–0.36 | axis, direction |
| `avatar-entry/split-slide-up` | Половина кадра уезжает вверх | paper_slide | 0.24–0.4 | axis, direction |

## browser-ui — 9

Куда: `overlay`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `browser-ui/article-highlight` | Статья в браузере со скроллом и вырезом цитаты | article_scroll | 2.0–4.5 | domain, title, snippet, highlight_line, theme, dark, background, tone |
| `browser-ui/browser-scroll` | Скролл статьи с подсветкой строки | article_scroll | 2.0–4.5 | domain, title, snippet, highlight_line, theme, dark, background, tone |
| `browser-ui/chat-ai-typing` | Запрос в нейросеть с курсором | chat_thread | 1.5–3.5 | prompt, title, snippet, reply, lines, app |
| `browser-ui/chat-thread` | Окно чата: запрос слева, ответ справа | chat_thread | 1.5–4.0 | prompt, title, snippet, reply, lines, app |
| `browser-ui/google-typing` | Печать в поисковой строке | source_card | 1.5–3.5 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `browser-ui/notepad-typing` | Печать в блокноте | source_card | 1.5–3.5 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `browser-ui/notes-reveal` | Apple Notes: печать строк заметки, скролл и карточка с маркером — notes-reveal | notes_reveal | 3.0–24.9 | titleL1, title, noteLine4, snippet, brandDomain, domain, titleL2, noteLine1, noteLine2, noteLine3 |
| `browser-ui/phone-notification` | Уведомление на телефоне | plaque | 1.2–2.5 | — |
| `browser-ui/terminal-lines` | Строки терминала | source_card | 1.5–3.5 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |

## data-viz — 17

Куда: `overlay`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `data-viz/animated-bar-chart` | Карточка: столбики растут снизу (scaleY), KPI +42%. | dataviz | 2.0–4.0 | title, subtitle, kpi, callout, labels |
| `data-viz/bar-chart-race` | Гонка столбиков: ряды меняются местами, лидер красный — bar-chart-race | dataviz | 2.0–8.0 | bar_count, barCount, value_prefix, valuePrefix, value_suffix, valueSuffix, value_decimals, valueDecimals, title, subtitle |
| `data-viz/bar-race-mini` | Мини-гонка столбиков | dataviz | 2.0–4.0 | format, labels |
| `data-viz/chart-story` | Столбики растут по очереди, акцент и коллаут на последнем значении — chart-story | dataviz | 2.0–5.0 | unit, emphasize, accent, data, labels |
| `data-viz/compare-bars` | Сравнение двух столбиков | dataviz | 1.5–3.0 | format, labels |
| `data-viz/conic-progress-ring` | Кольцо заполняется от 12 часов, центр считает в такт — conic-progress-ring | dataviz | 1.2–4.0 | progress, value, values, label, suffix, thickness |
| `data-viz/counter-roll` | Цифра прокручивается | dataviz | 1.0–2.5 | value, steps, suffix |
| `data-viz/decline-chart` | Линия падает вниз, число считает вниз, фон темнеет — decline-chart | dataviz | 1.2–4.0 | unit, subtitle, source, x_labels, xLabels, values, start_value, end_value, value, label |
| `data-viz/donut-fill` | Кольцо заполняется | dataviz | 1.5–3.0 | value |
| `data-viz/flowchart` | Блок-схема с узлами и связями — flowchart | dataviz | 2.0–12.0 | nodes |
| `data-viz/flowchart-vertical` | Вертикальная блок-схема с узлами, связями и выбором — flowchart-vertical | dataviz | 2.0–12.0 | root, title, branches, leaves |
| `data-viz/line-rise` | Линия идёт вверх | dataviz | 1.5–3.5 | format, labels |
| `data-viz/mk-line-graph` | Две линии рисуются слева направо, точки и числа на фронте — mk-line-graph | dataviz | 1.5–7.0 | series, values, values_b, label, name, color, color_b, xLabels, labels, showValues |
| `data-viz/oscilloscope-trace` | Осциллограф: линия рисует форму волны — oscilloscope-trace | dataviz | 2.0–10.0 | — |
| `data-viz/stat-countup-card` | Набегающая метрика на карточке | dataviz | 1.2–3.0 | label, value, steps, suffix, theme, dark, background, tone |
| `data-viz/timeline-dots` | Точки на таймлайне | dataviz | 1.5–3.5 | labels |
| `data-viz/weight-wave` | Волна весов (weight-wave) — weight-wave | dataviz | 2.0–10.0 | — |

## frames-cards — 7

Куда: `overlay`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `frames-cards/article-card` | Карточка статьи | source_card | 1.5–4.0 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `frames-cards/arxiv-card` | Карточка arXiv | paper_reveal | 1.5–4.0 | domain, title, snippet, highlight_line, lines |
| `frames-cards/chart-card` | Карточка с графиком | source_card | 1.5–4.0 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `frames-cards/paper-reveal` | Строки статьи проявляются, одна вспыхивает | paper_reveal | 1.5–4.0 | domain, title, snippet, highlight_line, lines |
| `frames-cards/patent-card` | Карточка патента | source_card | 1.5–4.0 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `frames-cards/product-card` | Карточка продукта | source_card | 1.5–3.5 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |
| `frames-cards/profile-card` | Карточка персоны | source_card | 1.5–3.5 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |

## hero-devices — 23

Куда: `shot.hero`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `hero-devices/brand-pill` | Пилюля с логотипом бренда у плеча | hero-brand-pill | 1.0–3.0 | label, icon, top |
| `hero-devices/card-stack-top` | Карточка с заголовком сверху, ведущий снизу | hero-card-stack | 1.6–4.5 | title, src, height |
| `hero-devices/chat-generate` | Окно нейросети: промпт, отсчёт и готовый кадр | hero-chat-generate | 3.4–9.0 | gen_prompt, src, app, generate_sec, media_sec |
| `hero-devices/chat-typing` | Переписка: запрос набирается, ответ ждёт | hero-chat-typing | 2.4–5.0 | ask, answer, app |
| `hero-devices/exhibit-card` | Экспонат в раме с музейной подписью | hero-exhibit | 2.4–5.5 | title, src, detail, credit, size |
| `hero-devices/figure-swap` | Числа сменяются на одном месте | hero-figure | 2.2–5.0 | figures, top, size |
| `hero-devices/footage-plate-pop` | Футаж в рамке въезжает поверх кадра | hero-plate-pop | 1.4–4.0 | src, width, height, top |
| `hero-devices/headline-behind-head` | Крупный заголовок из-за головы | hero-headline | 1.2–3.4 | kicker, word, size, clear_crown, top, head_top, line_height |
| `hero-devices/headline-over-head` | Заголовок вырастает над головой | hero-headline | 1.2–3.4 | kicker, word, size, clear_crown, top, head_top, line_height |
| `hero-devices/icons-behind-head` | Знаки о предмете речи вспыхивают за головой | hero-icons | 1.4–3.4 | icons, face_cx, face_cy, head_half, size, spread_deg |
| `hero-devices/knockout-negative` | Негатив: слово прорезано в заливке | hero-knockout | 1.2–3.0 | word, fill, margin, size, face_cy, head_top, head_h |
| `hero-devices/oversize-word` | Слово крупнее кадра, края обрезаны | hero-oversize | 1.6–3.2 | word, overflow |
| `hero-devices/phone-mock` | Экран приложения поверх расфокуса | hero-phone-mock | 1.8–4.5 | lines, app |
| `hero-devices/phrase-log` | Список фраз копится слева по ходу речи | hero-log | 2.6–6.0 | entries, top, size, accent |
| `hero-devices/plate-behind-back` | Кадр появляется за спиной ведущего | hero-plate | 1.4–4.0 | src, top |
| `hero-devices/script-stack` | Реплика строками с толстой обводкой | hero-script-stack | 1.6–4.2 | lines, top, size |
| `hero-devices/source-paper` | Страница первоисточника, по строке идёт маркер | hero-paper | 2.4–5.5 | source, quote, size, rows |
| `hero-devices/split-panel-right` | Кадр делится: ведущий слева, слово справа | hero-split | 1.4–4.0 | word, size, subject_shift, subject_zoom |
| `hero-devices/statement-slam` | Плашка с фразой забирает кадр и уходит | hero-slam | 1.4–2.2 | punch, size |
| `hero-devices/text-column-left` | Строки колонкой слева от ведущего | hero-text-column | 1.6–4.5 | lines, accent_lines, top |
| `hero-devices/title-behind-head` | Двухстрочная тема за головой | hero-title-behind | 2.0–5.2 | head, tail, size, clear_crown, top, head_top, line_height |
| `hero-devices/type-slab` | Плита типа слева от ведущего — Srinika × Mercury | hero-type-slab | 1.4–4.0 | lines, accent_lines, size, top |
| `hero-devices/verdict-card` | Светлая плашка: вторая строка темнеет | hero-verdict | 1.8–3.0 | punch, size |

## intro-hooks — 8

Куда: `shot.fullscreen (хук первых 3 с)`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `intro-hooks/hook-avatar-direct` | Аватар говорит в камеру сразу | avatar | 1.5–3.0 | — |
| `intro-hooks/hook-blackout-word` | Одно слово на чёрном | fullscreen_text | 0.6–1.4 | underline, quotes, content, accent_word, invert, size_px |
| `intro-hooks/hook-countdown-3` | Отсчёт 3-2-1 | fullscreen_text | 1.2–2.0 | underline, quotes, content, accent_word, invert, size_px |
| `intro-hooks/hook-footage-cold-open` | Холодный вход футажом без текста | footage | 1.0–3.0 | — |
| `intro-hooks/hook-number-slam` | Цифра-удар с ударным SFX | fullscreen_text | 0.8–1.6 | underline, quotes, content, accent_word, invert, size_px |
| `intro-hooks/hook-question-flash` | Вопрос вспышкой на однотонном фоне | fullscreen_text | 0.8–2.0 | underline, quotes, content, accent_word, invert, size_px |
| `intro-hooks/hook-split-reveal` | Сплит раскрывается сверху | split | 1.2–2.6 | — |
| `intro-hooks/hook-typing-search` | Печать запроса в поисковой строке | source_card | 1.4–3.0 | domain, title, snippet, highlight_line, compact, theme, dark, background, tone |

## kenburns — 9

Куда: `shot.motion`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `kenburns/diag-drift` | Диагональный дрейф | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/micro-parallax` | Микро-параллакс слоёв | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/pan-down` | Панорама вниз | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/pan-left` | Панорама влево | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/pan-right` | Панорама вправо | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/pan-up` | Панорама вверх | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/zoom-in-center` | Наезд в центр | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/zoom-in-subject` | Наезд на субъект | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |
| `kenburns/zoom-out-reveal` | Отъезд с раскрытием | kenburns | 2.5–5.0 | from_scale, to_scale, pan_x, pan_y |

## lower-thirds — 11

Куда: `overlay`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `lower-thirds/accent-underline` | Имя и роль с акцентной чертой | lt_accent_underline | 1.5–4.8 | name, content, text, role, kicker, subtitle, no_red, accent, source_chip |
| `lower-thirds/clean-bar` | Белая плашка с акцентной полоской | lt_clean_bar | 1.5–4.8 | name, content, text, role, kicker, subtitle, no_red, accent, source_chip |
| `lower-thirds/dark-card` | Угольная карточка на светлом футаже | lt_dark_card | 1.5–4.8 | name, content, text, role, kicker, subtitle, no_red, accent, source_chip |
| `lower-thirds/metric-badge` | Значение метрики | plaque | 1.5–3.0 | — |
| `lower-thirds/name-title` | Имя и должность | plaque | 1.5–4.0 | — |
| `lower-thirds/note-pin` | Короткая ремарка | plaque | 1.5–3.0 | — |
| `lower-thirds/progress-step` | Шаг N из M | plaque | 1.5–3.0 | — |
| `lower-thirds/source-domain` | Домен источника | plaque | 1.5–3.0 | — |
| `lower-thirds/tag-chips` | Ряд тегов | plaque | 1.5–3.0 | — |
| `lower-thirds/timestamp-marker` | Отметка времени | plaque | 1.5–2.5 | — |
| `lower-thirds/warning-strip` | Предупреждающая полоса | plaque | 1.5–3.0 | — |

## outro-cta — 6

Куда: `overlay (финал) / shot.fullscreen`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `outro-cta/logo-brand-close` | Вордмарк каскадом и точка бренда — logo-brand-close | logo_brand_close | 1.5–4.5 | invert, tone, exit, no_period, compact, fontScale, subscribe, buttonText, content |
| `outro-cta/logo-stamp` | Штамп логотипа | fullscreen_text | 1.0–2.0 | underline, quotes, content, accent_word, invert, size_px |
| `outro-cta/loop-back` | Замыкание на первый кадр | footage | 1.0–2.0 | — |
| `outro-cta/next-teaser` | Тизер следующего ролика | plaque | 1.5–2.5 | — |
| `outro-cta/question-card` | Вопрос в карточке | plaque | 1.5–2.5 | — |
| `outro-cta/subscribe-pulse` | Пульсирующая кнопка подписки | cta_button | 1.5–2.5 | — |

## parallax — 4

Куда: `shot.motion`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `parallax/depth-push` | Наезд с разной скоростью слоёв | parallax | 1.5–3.5 | back_id, shift_pct |
| `parallax/foreground-sweep` | Передний план проходит по кадру | parallax | 1.0–2.5 | back_id, shift_pct |
| `parallax/text-behind-object` | Текст за объектом переднего плана | parallax | 1.5–3.5 | back_id, shift_pct |
| `parallax/two-layer-drift` | Два слоя расходятся | parallax | 1.5–3.5 | back_id, shift_pct |

## text-fullscreen — 30

Куда: `shot.fullscreen`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `text-fullscreen/apple-terminal-clear-dark` | Terminal.app Clear Dark: набор команды и вывод — apple-terminal-clear-dark | apple_terminal_clear_dark | 2.0–12.0 | code, content, text, frame_w, frame_h, invert, command, prompt, title, output |
| `text-fullscreen/bigtext-mask-footage` | Текст-маска с футажом внутри | fullscreen_text | 1.0–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/blur-out-up` | Слова выходят из размытия и уходят вверх — blur-out-up | blur_out_up | 0.8–3.0 | stagger_ms, content, accent_word, invert, size_px, direction, distance, blur |
| `text-fullscreen/bottom-up-letters` | Буквы поднимаются снизу со стаггером — bottom-up-letters | bottom_up_letters | 0.8–3.0 | unit, direction, travel, stagger_ms, content, accent_word, invert, size_px |
| `text-fullscreen/code-3d-extrude` | Код на скошенной плите, посадка из глубины — code-3d-extrude | code_3d_extrude | 1.5–8.0 | code, content, text, tokens |
| `text-fullscreen/code-diff` | Правка как цветной diff: минус схлопывается, плюс раскрывается — code-diff | code_diff | 1.5–6.0 | tokens_before, tokens_after, filename, invert, code_before, before, code_after, after, code, content |
| `text-fullscreen/code-highlight` | Синтаксическая подсветка строки кода с горизонтальной световой плашкой — code-highlight | code_highlight | 1.5–6.0 | code, content, text, tokens, frame_w, frame_h, filename, line, target_line, focus |
| `text-fullscreen/code-morph` | FLIP-морфинг между состояниями кода — code-morph | code_morph | 1.5–7.0 | tokens_before, tokens_after, content, frame_w, frame_h, filename, code_before, before, code_after, after |
| `text-fullscreen/code-particle-assemble` | Пыль собирается в глифы кода — code-particle-assemble | code_particle_assemble | 1.5–8.0 | code, content, text, tokens, frame_w, frame_h, seed, invert |
| `text-fullscreen/code-scroll` | Камера скроллит файл к целевой строке — code-scroll | code_scroll | 1.5–6.0 | code, content, text, tokens, frame_w, frame_h, visible_lines, filename, invert, line |
| `text-fullscreen/code-typing` | Посимвольный набор с кареткой — code-typing | code_typing | 1.5–5.0 | code, content, text, tokens, frame_w, frame_h, filename, invert |
| `text-fullscreen/dark-plus` | VS Code Dark+: workbench и посимвольный набор — dark-plus | dark_plus | 2.0–11.0 | code, content, text, frame_w, frame_h, invert, filename |
| `text-fullscreen/date-marker` | Дата крупно | fullscreen_text | 0.8–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/fact-card` | Карточка факта | fullscreen_text | 1.2–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/impact-01` | Гигантская цифра | fullscreen_text | 0.8–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/impact-02` | Слово с подчёркиванием accent | fullscreen_text | 0.8–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/kinetic-stack` | Слова входят rise со стаггером — Texture / OBLIST | kinetic_stack | 0.8–3.0 | stagger_ms, content, accent_word, invert, size_px |
| `text-fullscreen/kinetic-type-swap` | Фраза стоит, в маске катится слово — kinetic-type-swap | kinetic_type_swap | 0.8–4.0 | content, invert, exit, prefix, suffix, options, underline, quotes, accent_word, size_px |
| `text-fullscreen/label-strip` | Полоса-ярлык поперёк кадра | fullscreen_text | 0.8–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/line-by-line-slide` | Строки заезжают слева со стаггером — line-by-line-slide | line_by_line_slide | 0.8–3.0 | tone, direction, density, size, stagger_ms, content, accent_word, invert, lines, max_lines |
| `text-fullscreen/number-slam-card` | Цифра-удар на карточке — K3 promo | number_slam | 0.8–3.0 | media, media_src, detail, secondary, content, accent_word, invert, size_px |
| `text-fullscreen/particle-text-dissolve` | Строка собирается из облака пыли — particle-text-dissolve | particle_text_dissolve | 0.8–4.0 | text, content, accent_word, invert, tone, direction, density, exit, frame_w, frame_h |
| `text-fullscreen/per-word-crossfade` | Слова входят из блюра с коротким подъёмом — per-word-crossfade | per_word_crossfade | 0.8–3.0 | tone, stagger_ms, exit, content, accent_word, invert, size_px, direction, distance, blur |
| `text-fullscreen/quote-frame` | Цитата в рамке | fullscreen_text | 1.2–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/scan-band` | Диагональная полоса с RGB-сдвигом по вордмарку — scan-band | scan_band | 0.8–4.0 | band_angle, frame_w, frame_h, content, accent_word, invert |
| `text-fullscreen/scramble-reveal` | Строка собирается из детерминированного шума — scramble-reveal | scramble_reveal | 0.8–4.0 | text, content, accent, style, exit, frame_w, frame_h |
| `text-fullscreen/stack-3lines` | Три строки лесенкой | fullscreen_text | 1.2–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/terminal-simulator` | Окно IDE: скелет строк и команда в терминале — terminal-simulator | terminal_simulator | 1.5–5.0 | code, content, text, title, frame_w, frame_h, invert, command, files |
| `text-fullscreen/vs-compare` | Два значения через VS | fullscreen_text | 1.2–3.0 | underline, quotes, content, accent_word, invert, size_px |
| `text-fullscreen/word-swap` | Слова сменяются на месте | fullscreen_text | 1.0–3.0 | underline, quotes, content, accent_word, invert, size_px |

## transitions — 41

Куда: `shot.transition`

| id | что это | рендерер | сек | params |
|---|---|---|---|---|
| `transitions/blur-dip` | Провал в размытие | blur_dip | 0.18–0.28 | max_blur |
| `transitions/chromatic-radial-split` | Chromatic radial split: радиальный разлёт RGB-каналов — chromatic-radial-split | chromatic_radial_split | 0.22–0.42 | from_scale |
| `transitions/cinematic-zoom` | Cinematic zoom: radial blur и сдвиг каналов — cinematic-zoom | cinematic_zoom | 0.22–0.42 | from_scale |
| `transitions/cross-warp-morph` | Cross-warp morph: шумовое смещение и морфинг склейки — cross-warp-morph | cross_warp_morph | 0.22–0.42 | from_scale |
| `transitions/cut` | Прямая склейка — база ≥70 % | cut | 0.0–0.0 | — |
| `transitions/domain-warp-dissolve` | Domain warp dissolve: каскадный ворп и радужное свечение кромок — domain-warp-dissolve | domain_warp_dissolve | 0.22–0.42 | from_scale |
| `transitions/flash-through-white` | Flash through white: переход через белую вспышку на тёмных сценах — flash-through-white | flash_through_white | 0.22–0.42 | from_scale |
| `transitions/glitch` | Glitch: scan lines, scramble и chroma — glitch | glitch_shader | 0.22–0.42 | seed |
| `transitions/glitch-short` | Короткий глитч | glitch | 0.16–0.26 | bars |
| `transitions/gravitational-lens` | Gravitational lens: колодец, горизонт и chroma — gravitational-lens | gravitational_lens | 0.22–0.42 | from_scale |
| `transitions/light-leak` | Light leak: тёплый засвет, flare и ACES — light-leak | light_leak | 0.22–0.42 | — |
| `transitions/light-sweep` | Световой блик поперёк кадра | light_sweep | 0.24–0.36 | — |
| `transitions/mask-wipe-circle` | Круговая маска | mask_wipe | 0.2–0.32 | shape |
| `transitions/mask-wipe-diagonal` | Диагональная маска | mask_wipe | 0.2–0.32 | shape |
| `transitions/mk-clone-wall-transition` | Clone wall: плитка слов накрывает кадр и инвертируется — mk-clone-wall-transition | mk_clone_wall | 0.22–0.42 | word, fontSize, font_size, spreadX, spread_x, spreadY, spread_y, brickOffset, brick_offset, driftX |
| `transitions/paper-slide` | Сдвиг «листом» | paper_slide | 0.2–0.3 | axis, direction |
| `transitions/ridged-burn` | Ridged burn: пламенный прожиг с искрами и острыми кромками — ridged-burn | ridged_burn | 0.22–0.42 | from_scale |
| `transitions/ripple-waves` | Ripple waves: концентрические волны ряби с противофазой — ripple-waves | ripple_waves | 0.22–0.42 | from_scale |
| `transitions/sdf-iris` | SDF iris: круг из центра и onion rings — sdf-iris | sdf_iris | 0.22–0.42 | — |
| `transitions/swirl-vortex` | Swirl vortex: органическое вихревое вращение и закрутка склейки — swirl-vortex | swirl_vortex | 0.22–0.42 | from_scale |
| `transitions/thermal-distortion` | Thermal distortion: heat shimmer снизу и haze — thermal-distortion | thermal_distortion | 0.22–0.42 | — |
| `transitions/transitions-3d` | 3D card flip: SCENE A схлопывается, SCENE B раскрывается — transitions-3d | transitions_3d | 0.22–0.42 | — |
| `transitions/transitions-blur` | Blur through: SCENE A уходит в размытие, SCENE B выходит из него — transitions-blur | transitions_blur | 0.22–0.42 | — |
| `transitions/transitions-cover` | Cover: staggered blocks накрывают SCENE A и открывают SCENE B — transitions-cover | transitions_cover | 0.22–0.42 | — |
| `transitions/transitions-destruction` | Page burn: SCENE A сгорает кругом, SCENE B проявляется — transitions-destruction | transitions_destruction | 0.22–0.42 | — |
| `transitions/transitions-dissolve` | Dissolve: мягкое растворение SCENE A и проявление SCENE B — transitions-dissolve | transitions_dissolve | 0.22–0.42 | from_scale |
| `transitions/transitions-distortion` | Distortion: глитч и хроматическое расщепление на склейке — transitions-distortion | transitions_distortion | 0.22–0.42 | from_scale |
| `transitions/transitions-grid` | Grid: мозаичный распад на тайлы и каскадное проявление — transitions-grid | transitions_grid | 0.22–0.42 | from_scale |
| `transitions/transitions-light` | Light leak: тёплые блики едут по кадру, SCENE B проявляется — transitions-light | transitions_light | 0.22–0.42 | — |
| `transitions/transitions-mechanical` | Mechanical: индастриал захлопывание шторок со снопом искр на стыке — transitions-mechanical | transitions_mechanical | 0.22–0.42 | from_scale |
| `transitions/transitions-other` | Flash cut: белая вспышка на склейке, SCENE B проявляется — transitions-other | transitions_other | 0.22–0.42 | — |
| `transitions/transitions-push` | Push: направленное выталкивание сцен со слайдом — transitions-push | transitions_push | 0.22–0.42 | from_scale, direction |
| `transitions/transitions-radial` | Radial: круговое диафрагменное раскрытие склейки с кольцом свечения — transitions-radial | transitions_radial | 0.22–0.42 | from_scale |
| `transitions/transitions-scale` | Scale: сквозной наезд через кадр или стягивание в центр — transitions-scale | transitions_scale | 0.22–0.42 | from_scale, mode |
| `transitions/whip-pan` | Whip pan: оба кадра едут вбок с направленным смазом — whip-pan | whip_pan_shader | 0.22–0.42 | — |
| `transitions/whip-pan-l` | Резкий пан влево | whip_pan | 0.16–0.28 | direction, blur |
| `transitions/whip-pan-r` | Резкий пан вправо | whip_pan | 0.16–0.28 | direction, blur |
| `transitions/white-flash` | Вспышка в белое | white_flash | 0.14–0.24 | peak |
| `transitions/zoom-punch-in` | Удар зумом внутрь | zoom_punch | 0.16–0.26 | from_scale, overshoot |
| `transitions/zoom-punch-out` | Удар зумом наружу | zoom_punch | 0.16–0.26 | from_scale, overshoot |
| `transitions/zoom-through` | Наезд в деталь на склейке — жест SpaceX | zoom_through | 0.18–0.3 | from_scale, overshoot |

## Рендеры вне каталога

Зарегистрированы в движке, но без карточки в каталоге. В таймлайн —
через `"renderer": "<имя>"` вместо `template` (оверлей).

| вид | renderer | params |
|---|---|---|
| overlay | `ai_chat_reveal` | userMessage, prompt, title, snippet, botName, app |
| overlay | `app_showcase` | tagline, title, headline, name, user, cta, subtitle, role, goalNum, goalDen |
| overlay | `blue_sweater` | — |
| overlay | `chatgpt_exchange` | prompt, userMessage, title, intro1, intro2, tableHeadUse, tableHeadTool, tableHeadWhy, row1Use, row1Tool |
| overlay | `claude_exchange` | prompt, userMessage, title, answer2, domain, thinking, lead, search, answer1, answer3 |
| overlay | `instagram_follow` | displayName, name, title, handle, domain, followers, buttonText, followingText |
| overlay | `macos_notification` | appName, domain, name, title, heading, body, text, snippet, content, time |
| overlay | `message_thread_reveal` | cardTitle, title, cardDomain, domain, questionMessage, snippet, contactName, teaserMessage, reactionMessage, reactionEmoji |
| overlay | `notification_cascade` | notifTitle, title, message1, snippet, message2, message3, message4, appName, domain, headlineTop |
| overlay | `reddit_post` | subreddit, name, author, domain, title, body, text, snippet, votes, votesActive |
| overlay | `spotify_card` | trackName, title, name, artistName, domain, snippet, brandText |
| overlay | `tiktok_follow` | displayName, name, title, handle, domain, followers, buttonText, followingText |
| overlay | `vpn_youtube_spot` | — |
| overlay | `x_post` | displayName, name, title, handle, domain, text, tweet, snippet, likes, likesActive |
| overlay | `yt_lower_third` | channelName, displayName, name, title, subscriberCount, subscribers, followers, snippet, buttonText, subscribedText |
| dataviz | `apple-money-count` | end_value, value, end, start_value, start, prefix |
| dataviz | `mk-progress-stat` | value, max, suffix, label, caption |
| dataviz | `north-korea-locked-down` | label, title, headline |
| dataviz | `nyc-paris-flight` | origin, from, dest, to, origin_code, dest_code, km, distance |
| dataviz | `spain-map` | regions, values, title, headline, subtitle, source, highlight, highlights |
| dataviz | `star-rating-fill` | rating, value, starCount, star_count, stars, showValue, show_value |
| dataviz | `us-map` | regions, states, values, title, headline, subtitle, source, highlight, highlights |
| dataviz | `us-map-bubble` | title, subtitle |
| dataviz | `us-map-flow` | cities, flows, title, headline, subtitle, source |
| dataviz | `us-map-hex` | title, headline, subtitle, source, legend_low, legend_high, highlight, highlights |
| dataviz | `world-map` | regions, countries, title, headline, subtitle, source, highlight, highlights |
| fullscreen | `beat_freeze_cut` | invert, content, text, accent_word, secondary, topic, eyebrow, kicker, pill |
| fullscreen | `news_ticker` | text, content |
| fullscreen | `shared_axis_z` | text, content, direction, depth, tone, size_px |
| fullscreen | `split_flap_board` | word, content |

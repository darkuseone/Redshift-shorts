# Таксономия шаблона (MUST-012)

Каждый **активный** пресет в `manifest.json` несёт контракт «когда можно».
Picker читает поля JSON, не комментарии. Генератор — `tools/gen_templates.py`.

| поле | смысл |
|---|---|
| `rarity` | `signature` / `variant` / `rare`. То же значение пишется в `frequency` (старое имя). Доли на ролик режет существующий `FrequencyBudget` — **жёстко**, не штрафом в ранге. |
| `topics[]` | Канал/категория, из которой приём. |
| `requires[]` | Признаки блока (`src/lib/meaning.py`), без которых приём пустой. Совпадает с `needs`. Пустой список — catchall/default, не always-fire интента. Непустой `requires` при пустом тексте **не** выбирается (`traits=∅`). |
| `forbids[]` | Признаки, с которыми приём запрещён. Пока пусто у живого каталога. |
| `cooldown_videos` | Не чаще 1 раза в N роликов. Если поле не задано: signature = 3 (`ROTATION_WINDOW`), иначе 1. Это жёсткий вырез при наличии альтернативы, не `used_recently`-штраф. |
| `brand_ok` | Hue проверен по params против brandbook (`ink` / white / red accent / cyan). `false` → picker не берёт. Нет hex в params → `true` (цвета из CSS-переменных брендбука). Чужой hue в рендерере `templates.py` этим тикетом не перекрашивается. |

Ротацию не выносить в отдельный сервис: `FrequencyBudget` + `cooldown_videos` + `last_used_in`.

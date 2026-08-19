"""Провайдеры внешних сервисов.

Каждый сервис из ТЗ (ElevenLabs, HeyGen, Gemini/Grok Vision, Magnific,
Pexels/Pixabay/NASA/Internet Archive) представлен парой реализаций:

* ``live`` — реальный HTTP-клиент с ретраями и таймаутами (§10.5.3);
* ``mock`` — детерминированная локальная реализация.

Режим выбирается ``providers.mode``: ``live`` / ``mock`` / ``auto`` (live, если
в окружении есть ключ, иначе mock с предупреждением в лог). Это даёт три вещи,
которых требует ТЗ: воспроизводимый CI без ключей, честный учёт кредитов и
отсутствие молчаливой деградации — mock всегда помечает себя в манифестах.
"""

from .base import Provider, ProviderMode, resolve_mode  # noqa: F401
from .registry import (  # noqa: F401
    get_avatar_provider, get_generation_provider, get_sfx_provider,
    get_stock_providers, get_tts_provider, get_vision_provider,
)

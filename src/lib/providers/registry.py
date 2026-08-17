"""Фабрики провайдеров.

Импорты внутри функций: каждый провайдер тянет свои зависимости, и шаг, который
работает только со звуком, не должен грузить модуль зрения.
"""

from __future__ import annotations

from typing import Any


def get_tts_provider(cfg, costs=None):
    from .tts import build_tts_provider

    return build_tts_provider(cfg, costs)


def get_avatar_provider(cfg, costs=None):
    from .avatar import build_avatar_provider

    return build_avatar_provider(cfg, costs)


def get_vision_provider(cfg, costs=None, *, role: str = "primary"):
    from .vision import build_vision_provider

    return build_vision_provider(cfg, costs, role=role)


def get_stock_providers(cfg, costs=None) -> dict[str, Any]:
    from .stock import build_stock_providers

    return build_stock_providers(cfg, costs)


def get_generation_provider(cfg, costs=None):
    from .generation import build_generation_provider

    return build_generation_provider(cfg, costs)


def get_sfx_provider(cfg, costs=None):
    from .sfx import build_sfx_provider

    return build_sfx_provider(cfg, costs)

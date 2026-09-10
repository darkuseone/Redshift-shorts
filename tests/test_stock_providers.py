"""Сток в auto без ключа: не подставлять MockStock (lavfi) вместо живого каталога."""

from __future__ import annotations

from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.stock import MockStock, build_stock_providers


def test_auto_without_stock_keys_omits_mock_pexels(monkeypatch):
    for env in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "MAGNIFIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    cfg = load_config(overrides=["providers.mode=auto"])
    providers = build_stock_providers(cfg, CostLedger(video_id="t"))
    assert "pexels" not in providers
    assert "pixabay" not in providers
    assert "freepik" not in providers
    assert "nasa" in providers
    assert "internet_archive" in providers
    assert not isinstance(providers["nasa"], MockStock)
    assert not isinstance(providers["internet_archive"], MockStock)


def test_mock_mode_still_uses_mock_stock():
    cfg = load_config(overrides=["providers.mode=mock"])
    providers = build_stock_providers(cfg, CostLedger(video_id="t"))
    assert isinstance(providers["pexels"], MockStock)
    assert isinstance(providers["nasa"], MockStock)

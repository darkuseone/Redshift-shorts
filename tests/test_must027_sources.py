"""MUST-027: donors only with verified licenses; otherwise research-only."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.lib.providers.stock import ia_license_confirmed, nasa_item_allowed
from src.p7_broll_search.search import (
    _load_routing, _restricted_license_reason, _sources_for, _stage1_reject,
    live_unconfirmed_sources, missing_on_screen_credit,
)
from src.lib.providers.stock import StockCandidate


ROOT = Path(__file__).resolve().parents[1]


def _yaml():
    path = ROOT / "config" / "stock_sources.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _cand(**kwargs) -> StockCandidate:
    base = dict(id="x", source="pexels", kind="video", query="q", width=1080,
                height=1920, duration_sec=5.0, license="Pexels License",
                license_confirmed=True)
    base.update(kwargs)
    return StockCandidate(**base)


def test_esa_yaml_is_not_cc_by_sa_on_esa_int():
    spec = _yaml()["sources"]["esa"]
    lic = str(spec.get("license") or "")
    assert "CC-BY-SA" not in lic.upper()
    assert "ESA Standard" in lic
    assert spec.get("enabled") is False
    assert spec.get("research_only") is True
    notes = str(spec.get("notes") or "")
    assert "CC-BY-SA" in notes or "не CC" in notes.lower() or "НЕ CC" in notes


def test_mixkit_is_not_live_without_per_item_parser():
    spec = _yaml()["sources"]["mixkit"]
    assert spec.get("enabled") is False
    assert spec.get("license_check") == "per_item"
    routing = _yaml().get("routing") or {}
    for names in routing.values():
        assert "mixkit" not in names


def test_mixkit_restricted_is_stage1_fail(cfg):
    routing = _load_routing(cfg)
    cand = _cand(source="mixkit", license="videoRestricted",
                 meta={"data-license": "videoRestricted"})
    reason = _stage1_reject(cand, cfg, 3.0, routing=routing)
    assert reason
    assert "Restricted" in reason
    assert _restricted_license_reason(cand)


def test_mixkit_video_free_reason_is_disabled_source(cfg):
    routing = _load_routing(cfg)
    cand = _cand(source="mixkit", license="videoFree",
                 meta={"data-license": "videoFree"})
    reason = _stage1_reject(cand, cfg, 3.0, routing=routing)
    assert reason
    assert "выключен" in reason or "Restricted" not in reason


def test_live_routing_has_no_unconfirmed_donors():
    routing = _yaml()
    assert live_unconfirmed_sources(routing) == []
    space = _sources_for("space", routing)
    assert "esa" not in space
    assert "mixkit" not in space
    assert "nasa" in space


def test_hubble_webb_eso_yaml_are_cc_by_4_and_need_on_screen_credit():
    sources = _yaml()["sources"]
    for name in ("hubble", "webb", "eso"):
        spec = sources[name]
        assert spec.get("enabled") is False
        assert "CC BY 4.0" in str(spec.get("license"))
        assert spec.get("on_screen_credit") is True
        assert spec.get("attribution_required") is True


def test_hubble_without_credit_is_warned():
    routing = _yaml()
    warn = missing_on_screen_credit({"source": "hubble"}, routing)
    assert warn
    assert "кредит" in warn.lower() or "credit" in warn.lower()
    ok = missing_on_screen_credit(
        {"source": "hubble", "attribution": "ESA/Hubble, NASA"}, routing)
    assert ok is None


def test_ia_whitelist_drops_nc_nd_and_empty():
    assert ia_license_confirmed("https://creativecommons.org/licenses/by/4.0/")
    assert ia_license_confirmed("https://creativecommons.org/licenses/by-sa/4.0/")
    assert ia_license_confirmed("https://creativecommons.org/publicdomain/zero/1.0/")
    assert not ia_license_confirmed("")
    assert not ia_license_confirmed("https://creativecommons.org/licenses/by-nc/4.0/")
    assert not ia_license_confirmed("https://creativecommons.org/licenses/by-nd/4.0/")
    assert not ia_license_confirmed("https://creativecommons.org/licenses/by-nc-sa/4.0/")


def test_nasa_drops_copyright_text_and_meatball():
    assert nasa_item_allowed({"title": "Hubble deep field", "rights": "Public Domain"})
    assert not nasa_item_allowed({"title": "Image copyright STScI", "rights": "Public Domain"})
    assert not nasa_item_allowed({"title": "NASA meatball on the patch", "description": ""})

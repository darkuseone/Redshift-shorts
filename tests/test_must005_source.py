"""MUST-005: source_ref ⇒ sources[]; NO_SOURCE for science."""

from __future__ import annotations

import copy

import pytest

from src.errors import NoSource, ValidationError
from src.lib.jsonio import read_json
from src.lib.schema import estimate_block_duration
from src.p0_validate.validator import HOOK_MAX_SEC, validate_script


_NATURE_SOURCE = {
    "title": "Кольская сверхглубокая: тепловой градиент и вода в коре",
    "domain": "nature.com",
    "url": "https://www.nature.com/articles/placeholder-kola",
    "show_on_screen": True,
    "snippet": "На семи километрах гранит трещиноватый, термометр показал сто восемьдесят.",
    "highlight_line": "сто восемьдесят градусов",
}

_SHORT_HOOK = "Этот ответ невозможно проверить. Совсем никак."
_SHORT_HOOK_0047 = "Скважину закрыли."


def _load_0047(repo_root):
    return copy.deepcopy(read_json(repo_root / "scripts" / "redshift_0047.json"))


def _with_short_hook(script: dict, text: str = _SHORT_HOOK) -> dict:
    hook = next(b for b in script["blocks"] if b.get("role") == "hook")
    hook["text"] = text
    assert estimate_block_duration(hook["text"]) <= HOOK_MAX_SEC
    return script


def test_science_without_sources_is_no_source(sample_script, cfg):
    script = _with_short_hook(sample_script)
    script["meta"]["category"] = "science"
    script["sources"] = []
    with pytest.raises(NoSource) as exc:
        validate_script(script, cfg)
    assert exc.value.code == "NO_SOURCE"


def test_0047_with_short_hook_fails_no_source(cfg, repo_root):
    script = _with_short_hook(_load_0047(repo_root), _SHORT_HOOK_0047)
    script["sources"] = []
    assert script.get("sources") in (None, [])
    with pytest.raises(ValidationError) as exc:
        validate_script(script, cfg)
    assert exc.value.code == "NO_SOURCE"


def test_0047_copy_with_sources_passes(cfg, repo_root):
    script = _with_short_hook(_load_0047(repo_root), _SHORT_HOOK_0047)
    script["sources"] = [dict(_NATURE_SOURCE)]
    result = validate_script(script, cfg)
    assert result["_validation"]["ok"] is True


def test_source_ref_without_sources_is_no_source(sample_script, cfg):
    script = _with_short_hook(sample_script)
    script["meta"]["category"] = "science"
    script["sources"] = []
    script["blocks"][2]["source_ref"] = "nature.com"
    with pytest.raises(NoSource) as exc:
        validate_script(script, cfg)
    assert exc.value.code == "NO_SOURCE"


def test_source_ref_must_match_sources_entry(sample_script, cfg):
    script = _with_short_hook(sample_script)
    script["blocks"][2]["source_ref"] = "nature.com"
    script["sources"] = [{
        "title": "Чужой пресс-релиз",
        "domain": "blog.google",
        "url": "https://blog.google/technology/research/unrelated/",
        "show_on_screen": False,
    }]
    with pytest.raises(NoSource) as exc:
        validate_script(script, cfg)
    assert exc.value.code == "NO_SOURCE"


def test_source_ref_matching_domain_passes(sample_script, cfg):
    script = _with_short_hook(sample_script)
    script["blocks"][2]["source_ref"] = "nature.com"
    assert any(
        "nature.com" in str(s.get("domain") or "")
        for s in script["sources"]
    )
    result = validate_script(script, cfg)
    assert result["_validation"]["ok"] is True

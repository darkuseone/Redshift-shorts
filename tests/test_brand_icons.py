"""Библиотека иконок брендов (§14).

Набор копится по ходу роликов, поэтому главное свойство — «спросить, есть ли
уже»: ради этого библиотека и заведена, чтобы один и тот же логотип не искали
в каждом ролике заново.
"""

from __future__ import annotations

import json

import pytest

from src.lib.brand_icons import BrandIconLibrary, slugify


@pytest.fixture
def library(tmp_path):
    (tmp_path / "brand_icons_manifest.json").write_text(json.dumps({
        "version": 1,
        "policy": {"variants_per_brand": 2, "max_bytes": 1000},
        "brands": [],
    }, ensure_ascii=False), encoding="utf-8")
    return BrandIconLibrary(tmp_path)


@pytest.mark.parametrize("name,expected", [
    ("ChatGPT", "chatgpt"),
    ("Microsoft", "microsoft"),
    ("Яндекс", "yandeks"),   # побуквенная транслитерация, «кс» не схлопывается в «x»
    ("X (Twitter)", "x-twitter"),
    ("  ", "brand"),
])
def test_slug_survives_cyrillic_and_punctuation(name, expected):
    assert slugify(name) == expected


def test_added_icon_is_found_next_time(library):
    assert library.has("ChatGPT") is False
    library.add("ChatGPT", "dark", b"png-bytes", source_url="https://openai.com")
    assert library.has("ChatGPT") is True
    assert library.find("ChatGPT", "dark")[0].file == "chatgpt_dark.png"


def test_two_variants_fill_the_brand(library):
    library.add("Microsoft", "light", b"a")
    library.add("Microsoft", "dark", b"b")
    assert library.variants_left("Microsoft") == 0


def test_limit_refuses_a_new_variant(tmp_path):
    """Лимит вариантов — правило, а не рекомендация."""
    (tmp_path / "brand_icons_manifest.json").write_text(json.dumps({
        "version": 1,
        "policy": {"variants_per_brand": 1, "max_bytes": 1000},
        "brands": [],
    }, ensure_ascii=False), encoding="utf-8")
    lib = BrandIconLibrary(tmp_path)
    lib.add("Microsoft", "light", b"a")
    with pytest.raises(ValueError, match="лимит"):
        lib.add("Microsoft", "dark", b"b")


def test_same_variant_is_not_silently_overwritten(library):
    library.add("Microsoft", "dark", b"a")
    with pytest.raises(ValueError, match="уже есть"):
        library.add("Microsoft", "dark", b"b")


def test_oversized_icon_is_refused(library):
    with pytest.raises(ValueError, match="лимите"):
        library.add("Heavy", "dark", b"x" * 1001)


def test_unknown_variant_is_refused(library):
    with pytest.raises(ValueError, match="light или dark"):
        library.add("ChatGPT", "neon", b"png")


def test_missing_file_is_not_reported_as_present(library):
    library.add("ChatGPT", "dark", b"png")
    (library.root / "chatgpt_dark.png").unlink()
    # Запись в манифесте есть, файла нет — библиотека не должна врать.
    assert library.has("ChatGPT") is False


def test_usage_is_recorded_per_video(library):
    library.add("ChatGPT", "dark", b"png", video_id="redshift_0001")
    library.mark_used("ChatGPT", "redshift_0002")
    saved = json.loads((library.root / "brand_icons_manifest.json").read_text())
    assert saved["brands"][0]["used_in"] == ["redshift_0001", "redshift_0002"]

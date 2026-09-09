"""MUST-023: ARTICLE_URL / TOPIC flags on existing P0–P12. Stop without primary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from src.cli import build_parser, main
from src.errors import NoSource
from src.lib.article_ingest import (
    apply_article_url,
    apply_topic,
    extract_primary,
    parse_rss_items,
    topic_donors,
)
from src.lib.jsonio import read_json, write_json
from src.lib.schema import estimate_block_duration
from src.p0_validate.validator import HOOK_MAX_SEC, validate_script


ROOT = Path(__file__).resolve().parents[1]
_SHORT_HOOK = "Этот ответ невозможно проверить. Совсем никак."
_NATURE_URL = "https://www.nature.com/articles/s41586-024-08449-y"
_OG_HTML = """<!doctype html><html><head>
<meta property="og:title" content="Logical qubit below surface-code threshold">
<meta property="og:url" content="https://www.nature.com/articles/s41586-024-08449-y">
<meta property="og:description" content="A logical qubit lives longer than its physical qubits.">
</head><body></body></html>
"""
_NO_TITLE_HTML = "<html><head></head><body>no primary title</body></html>"
_EMPTY_RSS = "<rss version='2.0'><channel><title>empty</title></channel></rss>"
_HIT_RSS = """<rss version="2.0"><channel>
<item>
  <title>Willow chip below threshold</title>
  <link>https://www.nature.com/articles/s41586-024-08449-y</link>
</item>
</channel></rss>
"""


def _short(script: dict) -> dict:
    hook = next(b for b in script["blocks"] if b.get("role") == "hook")
    hook["text"] = _SHORT_HOOK
    assert estimate_block_duration(hook["text"]) <= HOOK_MAX_SEC
    return script


def _script_copy(tmp_path: Path, script: dict, name: str = "script.json") -> Path:
    path = tmp_path / name
    write_json(path, script)
    return path


def test_help_shows_article_url_and_topic_modes():
    help_text = build_parser().format_help()
    assert "ARTICLE_URL" in help_text
    assert "TOPIC" in help_text
    val_help = build_parser()._subparsers._group_actions[0].choices["validate"].format_help()
    assert "--article-url" in val_help
    assert "--topic" in val_help
    run_help = build_parser()._subparsers._group_actions[0].choices["run"].format_help()
    assert "--article-url" in run_help
    assert "--topic" in run_help


def test_auto_topic_search_stays_false():
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["features"]["auto_topic_search"] is False


def test_extract_primary_none_without_title():
    assert extract_primary(_NO_TITLE_HTML, "https://example.com/x") is None


def test_article_url_without_title_stops(sample_script):
    script = _short(copy.deepcopy(sample_script))
    blocks_before = copy.deepcopy(script["blocks"])
    with pytest.raises(NoSource) as exc:
        apply_article_url(script, "https://example.com/no-title",
                          fetch_html=lambda url: _NO_TITLE_HTML)
    assert exc.value.code == "NO_SOURCE"
    assert script["blocks"] == blocks_before


def test_article_url_og_title_fills_sources_p0_pass(sample_script, cfg):
    script = _short(copy.deepcopy(sample_script))
    script["sources"] = []
    blocks_before = copy.deepcopy(script["blocks"])
    out = apply_article_url(script, _NATURE_URL, fetch_html=lambda url: _OG_HTML)
    assert out["blocks"] == blocks_before
    assert len(out["sources"]) == 1
    assert out["sources"][0]["domain"] == "nature.com"
    assert out["sources"][0]["title"] == "Logical qubit below surface-code threshold"
    assert out["sources"][0]["url"] == _NATURE_URL
    result = validate_script(out, cfg)
    assert result["_validation"]["ok"] is True


def test_topic_empty_yaml_stops(sample_script):
    script = _short(copy.deepcopy(sample_script))
    with pytest.raises(NoSource) as exc:
        apply_topic(script, "space", news_yaml={"rss": []})
    assert exc.value.code == "NO_SOURCE"
    assert "0 доноров" in exc.value.message


def test_topic_donor_empty_rss_stops(sample_script):
    script = _short(copy.deepcopy(sample_script))
    yaml_news = {
        "rss": [{"name": "NASA Breaking News", "url": "https://example.com/rss",
                 "topics": ["space"]}],
    }
    with pytest.raises(NoSource) as exc:
        apply_topic(script, "space", news_yaml=yaml_news,
                    fetch_rss=lambda url: _EMPTY_RSS)
    assert exc.value.code == "NO_SOURCE"
    assert "0 hits" in exc.value.message


def test_topic_hit_fills_sources_no_new_blocks(sample_script, cfg):
    script = _short(copy.deepcopy(sample_script))
    script["sources"] = []
    blocks_before = copy.deepcopy(script["blocks"])
    yaml_news = {
        "rss": [{"name": "Nature News", "url": "https://www.nature.com/nature.rss",
                 "topics": ["science"]}],
    }
    out = apply_topic(script, "science", news_yaml=yaml_news,
                      fetch_rss=lambda url: _HIT_RSS)
    assert out["blocks"] == blocks_before
    assert out["sources"][0]["url"] == _NATURE_URL
    assert validate_script(out, cfg)["_validation"]["ok"] is True


def test_topic_donors_only_listed_yaml():
    assert topic_donors({"rss": []}, "space") == []
    donors = topic_donors({
        "rss": [{"name": "NASA Breaking News", "url": "u", "topics": ["space"]}],
    }, "space")
    assert len(donors) == 1
    assert topic_donors({
        "rss": [{"name": "NASA Breaking News", "url": "u", "topics": ["space"]}],
    }, "genetics") == []


def test_parse_rss_skips_item_without_title_or_link():
    xml = """<rss><channel>
      <item><title></title><link>https://x.example/a</link></item>
      <item><title>ok</title><link></link></item>
      <item><title>hit</title><link>https://www.nature.com/articles/x</link></item>
    </channel></rss>"""
    items = parse_rss_items(xml)
    assert items == [{"title": "hit", "url": "https://www.nature.com/articles/x"}]


def test_cli_article_url_no_title_exits_nonzero(sample_script, tmp_path, monkeypatch, capsys):
    path = _script_copy(tmp_path, _short(copy.deepcopy(sample_script)))
    monkeypatch.setattr("src.lib.article_ingest._default_fetch",
                        lambda url: _NO_TITLE_HTML)
    ret = main(["validate", "--script", str(path), "--article-url", _NATURE_URL])
    assert ret != 0
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == "NO_SOURCE"


def test_cli_article_url_og_title_p0_pass(sample_script, tmp_path, monkeypatch, capsys):
    script = _short(copy.deepcopy(sample_script))
    script["sources"] = []
    path = _script_copy(tmp_path, script)
    monkeypatch.setattr("src.lib.article_ingest._default_fetch",
                        lambda url: _OG_HTML)
    ret = main(["validate", "--script", str(path), "--article-url", _NATURE_URL])
    assert ret == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["blocks"] == len(script["blocks"])


def test_cli_topic_empty_yaml_exits_nonzero(sample_script, tmp_path, monkeypatch, capsys):
    path = _script_copy(tmp_path, _short(copy.deepcopy(sample_script)))
    monkeypatch.setattr("src.lib.article_ingest._load_news_yaml",
                        lambda news_yaml, cfg: {"rss": []})
    ret = main(["validate", "--script", str(path), "--topic", "space"])
    assert ret != 0
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == "NO_SOURCE"


def test_cli_topic_empty_rss_exits_nonzero(sample_script, tmp_path, monkeypatch, capsys):
    path = _script_copy(tmp_path, _short(copy.deepcopy(sample_script)))
    monkeypatch.setattr(
        "src.lib.article_ingest._load_news_yaml",
        lambda news_yaml, cfg: {
            "rss": [{"name": "NASA Breaking News",
                     "url": "https://example.com/rss", "topics": ["space"]}],
        },
    )
    monkeypatch.setattr("src.lib.article_ingest._default_fetch",
                        lambda url: _EMPTY_RSS)
    ret = main(["validate", "--script", str(path), "--topic", "space"])
    assert ret != 0
    assert json.loads(capsys.readouterr().err)["code"] == "NO_SOURCE"


def test_validate_without_flags_unchanged(sample_script, tmp_path, capsys):
    path = _script_copy(tmp_path, _short(copy.deepcopy(sample_script)))
    ret = main(["validate", "--script", str(path)])
    assert ret == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_disk_0042_without_flags_still_validates(capsys):
    ret = main(["validate", "--script", str(ROOT / "scripts" / "redshift_0042.json")])
    assert ret == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_run_article_url_writes_ingested_script(sample_script, tmp_path, monkeypatch, capsys):
    script = _short(copy.deepcopy(sample_script))
    script["sources"] = []
    path = _script_copy(tmp_path, script)
    work = tmp_path / "work"
    out = tmp_path / "output"
    monkeypatch.setattr("src.lib.article_ingest._default_fetch",
                        lambda url: _OG_HTML)
    ret = main([
        "--set", "providers.mode=mock",
        "run", "--script", str(path), "--only", "P0",
        "--work-dir", str(work), "--output-dir", str(out),
        "--article-url", _NATURE_URL, "--no-cache", "--force",
    ])
    assert ret == 0
    ingested = read_json(work / "ingested_script.json")
    assert ingested["sources"][0]["domain"] == "nature.com"
    assert ingested["blocks"] == script["blocks"]
    validated = read_json(work / "validated_script.json")
    assert validated["_validation"]["ok"] is True

from src.lib.owner_visuals_0050 import apply_0050_owner_visuals


def test_0050_owner_visual_pass_rewrites_five_defects():
    plan = {
        "video_id": "redshift_0050",
        "shots": [
            {"content": "7 · $1 000 000 · 25 Y",
             "params": {"content": "7 · $1 000 000 · 25 Y"}},
            {"hero": {"template": "hero-devices/icons-behind-head"}},
            {"hero": {"template": "hero-devices/footage-plate-pop"}},
            {"template": "data-viz/decline-chart",
             "params": {"values": [88, 17], "label": "LEAN"}},
            {"credit": "NASA GODDARD SPACE FLIGHT CENTER | GEOS-5"},
        ],
        "overlays": [
            {"type": "dataviz", "template": "data-viz/decline-chart",
             "params": {"values": [88, 17], "label": "LEAN"}},
            {"type": "dataviz", "template": "data-viz/stat-countup-card",
             "params": {"value": 6}},
        ],
    }
    assert apply_0050_owner_visuals(plan) >= 6
    assert plan["shots"][0]["content"] == "7 TASKS · $1 000 000 · 25 YEARS"
    assert plan["shots"][1]["hero"]["template"] == "hero-devices/headline-over-head"
    assert plan["shots"][2]["hero"]["template"] == "hero-devices/headline-over-head"
    assert plan["shots"][3]["template"] == "data-viz/compare-bars"
    assert plan["shots"][4]["credit"] == "NASA"
    charts = [o for o in plan["overlays"] if o.get("type") == "dataviz"]
    assert len(charts) == 1
    assert charts[0]["template"] == "data-viz/compare-bars"
    assert charts[0]["params"]["labels"] == ["SEARCH", "LEAN"]


def test_0050_gemini_hook_mute_and_plaques():
    plan = {
        "video_id": "redshift_0050",
        "subtitle_style": {"mode": "glow", "baseline_y": 720, "caption": "gradient-fill"},
        "subtitles": [
            {"display": "века", "start": 1.88, "end": 2.13},
            {"display": "Клей", "start": 52.0, "end": 52.4},
        ],
        "shots": [
            {"start": 0.05, "end": 1.2, "role": "hook", "kind": "fullscreen_text",
             "content": "$1 000 000", "file": "vortex.mp4",
             "params": {"content": "$1 000 000", "media": "vortex.mp4"}},
            {"start": 1.2, "end": 3.2, "role": "hook", "kind": "footage",
             "file": "frostscan.mp4"},
        ],
        "overlays": [
            {"template": "lower-thirds/accent-underline",
             "params": {"text": "REJECTED", "content": "REJECTED"}},
            {"template": "lower-thirds/source-domain",
             "params": {"text": "FOLLOWUP", "content": "FOLLOWUP"}},
        ],
    }
    assert apply_0050_owner_visuals(plan) >= 4
    assert all(s["start"] >= 3.2 for s in plan["subtitles"])
    assert plan["subtitles"][0]["display"] == "Clay"
    assert plan["shots"][1]["template"] == "intro-hooks/hook-number-slam"
    assert plan["shots"][1]["content"] == "$1 000 000"
    assert plan["shots"][1]["file"] == "vortex.mp4"
    assert plan["subtitle_style"]["baseline_y"] == 520
    assert all(o["template"] == "lower-thirds/dark-card" for o in plan["overlays"])

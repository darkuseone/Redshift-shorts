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

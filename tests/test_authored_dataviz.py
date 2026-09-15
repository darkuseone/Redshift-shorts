"""Блок сам просит диаграмму: overlay.type=dataviz, а не пустой слот §7.2.

0050 b4 — «Десять тысяч агентов. Восемьдесят восемь часов. Два миллиона
семьсот тысяч сообщений. Семнадцать часов…» — раньше уходил в
``fullscreen_text/fact-card`` и клал все четыре числа на карточку в четыре
строки без единого визуального прочтения самих цифр. Диаграмма из §7.2
собирается только когда материала на слот не нашлось; здесь материал есть
(футаж под числами), и блок явно просит график поверх него.
"""
from src.lib.template_picker import TemplatePicker
from src.lib.templates import TemplateCatalog
from src.p11_assemble.assemble import ScenarioIndex, VisualBudget, _authored_dataviz_overlays


def _picker(ctx):
    catalog = TemplateCatalog.load(ctx.cfg)
    return TemplatePicker(catalog, ScenarioIndex.load(ctx.cfg, catalog=catalog))


def _shots(block_id="b4"):
    return [
        {"index": 10, "block_id": block_id, "start": 31.41, "end": 33.41,
         "kind": "footage"},
        {"index": 11, "block_id": block_id, "start": 33.41, "end": 36.63,
         "kind": "footage"},
    ]


B4_TEXT = ("Десять тысяч агентов. Восемьдесят восемь часов. "
          "Два миллиона семьсот тысяч сообщений. "
          "Семнадцать часов переложили доказательство в Lean.")


def test_a_dataviz_block_gets_a_chart_overlay(cfg):
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget()
    blocks = {"b4": {"id": "b4", "text": B4_TEXT,
                     "overlay": {"type": "dataviz"}}}
    out = _authored_dataviz_overlays(
        _shots(), blocks, picker=picker, budget=budget, variant="A",
        seed=1, recent_videos=[], used_templates=[])
    assert len(out) == 1
    overlay = out[0]
    assert overlay["type"] == "dataviz"
    assert overlay["template"].startswith("data-viz/")
    assert overlay["start"] == 31.41
    assert overlay["end"] == 36.63


def test_mismatched_units_never_share_one_axis(cfg):
    # 10 000 (тыс.), 88 (без суффикса), 2 700 000 (млн), 17 (без суффикса) —
    # только сопоставимая пара часов уходит в params.
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget()
    blocks = {"b4": {"id": "b4", "text": B4_TEXT,
                     "overlay": {"type": "dataviz"}}}
    out = _authored_dataviz_overlays(
        _shots(), blocks, picker=picker, budget=budget, variant="A",
        seed=1, recent_videos=[], used_templates=[])
    params = out[0]["params"]
    values = params.get("values") or [params.get("value")]
    assert 2_700_000 not in values
    assert 10_000 not in values


def test_a_plain_fullscreen_block_gets_no_chart(cfg):
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget()
    blocks = {"b1": {"id": "b1", "text": "Миллион долларов.",
                     "overlay": {"type": "fullscreen_text",
                                "content": "$1 000 000"}}}
    out = _authored_dataviz_overlays(
        [{"index": 0, "block_id": "b1", "start": 0.0, "end": 1.2,
          "kind": "fullscreen_text"}],
        blocks, picker=picker, budget=budget, variant="A", seed=1,
        recent_videos=[], used_templates=[])
    assert out == []


def test_a_block_with_no_numbers_gets_no_chart(cfg):
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget()
    blocks = {"b9": {"id": "b9", "text": "Это не про числа вовсе.",
                     "overlay": {"type": "dataviz"}}}
    out = _authored_dataviz_overlays(
        [{"index": 0, "block_id": "b9", "start": 0.0, "end": 3.0,
          "kind": "footage"}],
        blocks, picker=picker, budget=budget, variant="A", seed=1,
        recent_videos=[], used_templates=[])
    assert out == []


def test_the_dataviz_cap_is_shared_with_the_empty_slot_ladder(cfg):
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget(dataviz=2)  # потолок уже выбран лестницей §7.2
    blocks = {"b4": {"id": "b4", "text": B4_TEXT,
                     "overlay": {"type": "dataviz"}}}
    out = _authored_dataviz_overlays(
        _shots(), blocks, picker=picker, budget=budget, variant="A",
        seed=1, recent_videos=[], used_templates=[])
    assert out == []


def test_a_too_short_window_gets_no_chart(cfg):
    picker = _picker(type("C", (), {"cfg": cfg})())
    budget = VisualBudget()
    blocks = {"b4": {"id": "b4", "text": B4_TEXT,
                     "overlay": {"type": "dataviz"}}}
    out = _authored_dataviz_overlays(
        [{"index": 10, "block_id": "b4", "start": 31.41, "end": 32.1,
          "kind": "footage"}],
        blocks, picker=picker, budget=budget, variant="A", seed=1,
        recent_videos=[], used_templates=[])
    assert out == []

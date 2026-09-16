"""Отпечаток шага меряет тот конфиг, который шаг читает.

0050 r62: заказчик просил ускорить темп. Плотность речи живёт в `speech`
(порог паузы, целевая пауза), но в отпечатке стояли только limits/audio/
render/features — общие для всех шагов. Правка `speech.pause_threshold_ms`
не отменяла ничего: P3 отдавал прежнюю дорожку из кэша, и заказанный темп
молча не менялся.
"""
import pytest

from src.pipeline import Step
from src.steps import build_pipeline


class _Cfg:
    def __init__(self, data):
        self.data = data
        self.repo_root = "."

    def get(self, key, default=None):
        return self.data.get(key, default)


class _Ctx:
    def __init__(self, cfg, tmp_path):
        self.cfg = cfg
        self.work_dir = tmp_path
        self.script_path = tmp_path / "script.json"
        self.script_path.write_text("{}", encoding="utf-8")


def _step(sections):
    return Step("PX", "проба", lambda ctx: None, inputs=(), outputs=(),
                cfg_sections=sections)


def test_a_declared_section_changes_the_fingerprint(tmp_path):
    step = _step(("speech",))
    a = step.fingerprint(_Ctx(_Cfg({"speech": {"pause_threshold_ms": 150}}), tmp_path))
    b = step.fingerprint(_Ctx(_Cfg({"speech": {"pause_threshold_ms": 110}}), tmp_path))
    assert a != b


def test_an_undeclared_section_does_not(tmp_path):
    step = _step(())
    a = step.fingerprint(_Ctx(_Cfg({"speech": {"pause_threshold_ms": 150}}), tmp_path))
    b = step.fingerprint(_Ctx(_Cfg({"speech": {"pause_threshold_ms": 110}}), tmp_path))
    assert a == b


@pytest.mark.parametrize("name,section", [
    ("P2", "elevenlabs"),   # голос: модель, клон, темп
    ("P3", "speech"),       # паузы, вдохи, нормализация
    ("P4", "speech"),       # длительность слова в субтитре
])
def test_the_speech_steps_declare_what_they_read(name, section):
    step = next(s for s in build_pipeline().steps if s.name == name)
    assert section in step.cfg_sections

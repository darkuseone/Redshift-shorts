"""Отпечаток кода шага должен смотреть на код шага.

``Step.fingerprint`` берёт ``code_fingerprint(self.fn.__module__)``. P8 и P11
оборачиваются в ``wrap_p8``/``wrap_p11``, и замыкание объявлено в
``lib/slots_lock.py`` — значит оба шага считали свой код по файлу обёртки.
Правки в ``judge.py`` и ``assemble.py`` кэш не отменяли: прогон 173 взял P8
из кэша, и весь предыдущий круг работы по штампу не выполнился ни разу.
"""
import importlib

from src.lib.cache import _reachable_source_files
from src.steps import build_pipeline

STEPS = {s.name: s for s in build_pipeline().steps}


def test_p8_counts_its_own_module():
    assert STEPS["P8"].fn.__module__ == "src.p8_broll_judge.judge"


def test_p11_counts_its_own_module():
    assert STEPS["P11"].fn.__module__ == "src.p11_assemble.assemble"


def test_the_lock_stays_inside_both_graphs():
    # обёртка выполняется в составе шага — её правка обязана отменять кэш
    for name in ("src.p8_broll_judge.judge", "src.p11_assemble.assemble"):
        files = _reachable_source_files(importlib.import_module(name))
        assert any("slots_lock" in f for f in files), name


def test_every_wrapped_step_reaches_its_own_source():
    for name, step in STEPS.items():
        module = importlib.import_module(step.fn.__module__)
        files = _reachable_source_files(module)
        assert module.__file__ in files, name

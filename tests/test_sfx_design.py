"""Звук должен доходить до зрителя, а зритель смотрит с телефона.

Заказчик услышал «дешёвый звук» на появлении полноэкранного текста. Причина
нашлась замером: удар был чистым синусом на 70 Гц, а динамик телефона ниже
400 Гц почти ничего не отдаёт — в ролике от удара оставался слабый шорох.
Здесь это правило, а не наблюдение.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.lib.audio import phone_speaker_loss_db
from src.lib.sfx_synth import MUSIC_MOODS, SFX_ROLES, SR, synth_music, synth_sfx

# Бюджет потерь на динамике телефона. Прежние удары теряли 16–25 дБ и звучали
# глухо; после переработки худший — sub_drop с 9.2 дБ, и это его роль.
PHONE_LOSS_MAX_DB = 10.0

# Роли, у которых работа — акцент: у них обязана быть слышимая атака.
ACCENTS = ("hit_impact", "boom", "sub_drop", "chime", "subscribe_ping", "reveal")


@pytest.mark.parametrize("role", SFX_ROLES)
def test_every_sfx_survives_a_phone_speaker(role):
    loss = phone_speaker_loss_db(synth_sfx(role), SR)
    assert loss > -PHONE_LOSS_MAX_DB, (
        f"{role}: на телефоне теряется {-loss:.1f} дБ — звук уходит под порог динамика")


@pytest.mark.parametrize("role", ACCENTS)
def test_accent_has_a_transient(role):
    """Без широкополосной атаки акцент читается как гудок, а не как удар."""
    mono = synth_sfx(role)[:, 0].astype(np.float64)
    # Окно в 21 мс: щелчок гаснет за десяток миллисекунд, и на длинном окне
    # его целиком забивает тон, который идёт следом.
    n = min(1 << 10, len(mono))
    head = mono[:n] * np.hanning(n)
    spec = np.abs(np.fft.rfft(head)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    high = spec[freqs > 4000].sum() / (spec.sum() + 1e-20)
    assert high > 0.002, f"{role}: в атаке нет высоких — доля выше 4 кГц {high:.4f}"


@pytest.mark.parametrize("role", SFX_ROLES)
def test_sfx_is_deterministic(role):
    """Один и тот же ролик обязан звучать одинаково при пересборке."""
    assert np.array_equal(synth_sfx(role), synth_sfx(role))


@pytest.mark.parametrize("role", SFX_ROLES)
def test_committed_wav_matches_the_synthesiser(role):
    """Файл в библиотеке обязан быть тем, что выдаёт код сегодня.

    Файлы лежат в git, а рецепт живёт в коде, и разъехаться они могут молча:
    правка синтеза не перезаписывает библиотеку сама. При переработке ударов
    выяснилось, что семь файлов уже разошлись с кодом до неё.
    """
    import subprocess
    from pathlib import Path

    from src.lib.audio import SAMPLE_RATE, normalize_peak

    path = Path("assets/sfx") / f"{role}.wav"
    if not path.exists():
        pytest.skip(f"{path} нет в рабочем дереве")

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-"], capture_output=True, check=True).stdout
    on_disk = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 2) / 32768.0
    fresh = np.asarray(normalize_peak(synth_sfx(role), -12.0), dtype=np.float64)

    assert on_disk.shape == fresh.shape, "длительность файла разошлась с рецептом"
    assert np.max(np.abs(on_disk - fresh)) < 2e-4, (
        f"{role}.wav не совпадает с синтезом — библиотеку надо перегенерировать")


@pytest.mark.parametrize("mood", sorted(MUSIC_MOODS))
def test_music_bed_reaches_a_phone(mood):
    """Подложка «на грани слышимости» — но на телефоне, а не в теории.

    Аккорд стоял на 49–73 Гц и целиком уходил под порог динамика: замер
    показал потерю 19–23 дБ, то есть музыки зритель не слышал вовсе. Верхний
    голос вернул гармонию в рабочую полосу.
    """
    loss = phone_speaker_loss_db(synth_music(mood, duration_sec=6.0), SR)
    assert loss > -16.0, f"{mood}: подложка теряет {-loss:.1f} дБ — её просто нет"


def test_bandwidth_metric_sees_where_the_spectrum_ends():
    """Полоса — единственное, по чему видно, что сервис отдал вместо PCM.

    Формат ответа ElevenLabs не сообщает: на 0047 запрошен был pcm_44100, а
    пришёл mp3 со срезом на 11 кГц. Мерка обязана этот срез показывать.

    Материал — гребёнка тонов с заданным потолком, а не белый шум: у шума
    спектр плоский, и доля 0.999 у него приходится далеко за срез фильтра.
    У речи спектр падает круто, поэтому гребёнка ближе к делу.
    """
    from src.lib.audio import SAMPLE_RATE, speech_bandwidth_hz

    def comb(top_hz: float) -> np.ndarray:
        t = np.arange(SAMPLE_RATE * 3) / SAMPLE_RATE
        tones = np.arange(200.0, top_hz, 200.0)
        return sum(np.sin(2 * np.pi * f * t) / (1 + f / 500.0) for f in tones)

    narrow = speech_bandwidth_hz(comb(11000), SAMPLE_RATE)
    wide = speech_bandwidth_hz(comb(20000), SAMPLE_RATE)
    assert 10000 < narrow < 11500, f"срез на 11 кГц прочитан как {narrow:.0f} Гц"
    assert wide > 18000, f"широкая полоса прочитана как {wide:.0f} Гц"
    assert wide - narrow > 6000, "мерка не различает сжатый источник и несжатый"


def test_sfx_sit_at_the_quiet_end_of_the_corridor():
    """«Еле слышно, но слышно, что дорого» — это уровень, а не только тембр.

    Переработка ударов добавила им около пятнадцати децибел в полосе динамика
    телефона. На прежнем пике −12 dBFS они кричали бы поверх речи, поэтому
    ставятся на тихий край коридора §4.4, а слышимость держит сам звук.
    """
    from src.lib.config import load_config
    from src.p10_audio.audio_build import sfx_peak_corridor, sfx_peak_target

    cfg = load_config()
    lo, hi = sfx_peak_corridor(cfg)
    assert lo < hi, "коридор пиков задом наперёд"
    assert sfx_peak_target(cfg) == lo

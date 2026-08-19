"""Движок рендера на HyperFrames (HTML → MP4).

Кадр описывается разметкой и собирается headless Chrome, звук и нарезку
по-прежнему делает ffmpeg. Точка входа — :class:`HyperFramesCompositor`,
совместимая по интерфейсу с покадровым композитором.
"""

from .compositor import HyperFramesCompositor
from .project import HyperFramesProject

__all__ = ["HyperFramesCompositor", "HyperFramesProject"]

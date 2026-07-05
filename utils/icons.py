"""
utils/icons.py

Lightweight, dependency-free icon generation for InstantBoard.

Rather than shipping a folder of binary image assets, this module
renders simple vector icons on the fly using Qt's QPainter. This keeps
the project self-contained (no missing-asset errors) while still
giving the UI a modern, consistent icon set. Every icon is cached in
memory after first render.
"""

from __future__ import annotations

from typing import Dict, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_ICON_CACHE: Dict[Tuple[str, int, str], QIcon] = {}

ACCENT = "#7c5cff"
WHITE = "#f2f2f7"
GREY = "#9a9aa5"
RED = "#ff5c7a"
GREEN = "#3ddc97"


def _new_pixmap(size: int) -> Tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    return pixmap, painter


def _finish(pixmap: QPixmap, painter: QPainter, key: Tuple[str, int, str]) -> QIcon:
    painter.end()
    icon = QIcon(pixmap)
    _ICON_CACHE[key] = icon
    return icon


def get_icon(name: str, size: int = 20, color: str = WHITE) -> QIcon:
    """Return a cached QIcon for the given logical icon name.

    Supported names: play, pause, download, favorite, favorite_filled,
    search, refresh, settings, speaker, microphone, warning, close,
    soundboard, normal_mic.
    """
    key = (name, size, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    pixmap, painter = _new_pixmap(size)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.08))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    brush_color = QColor(color)

    margin = size * 0.2

    if name == "play":
        path = QPainterPath()
        path.moveTo(size * 0.32, size * 0.2)
        path.lineTo(size * 0.32, size * 0.8)
        path.lineTo(size * 0.85, size * 0.5)
        path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(brush_color)
        painter.drawPath(path)

    elif name == "pause":
        painter.setPen(Qt.NoPen)
        painter.setBrush(brush_color)
        bar_w = size * 0.18
        painter.drawRoundedRect(QRectF(size * 0.28, size * 0.2, bar_w, size * 0.6), 2, 2)
        painter.drawRoundedRect(QRectF(size * 0.56, size * 0.2, bar_w, size * 0.6), 2, 2)

    elif name in ("favorite", "favorite_filled"):
        star = QPainterPath()
        cx, cy, r_out, r_in = size / 2, size / 2, size * 0.42, size * 0.18
        import math
        points = []
        for i in range(10):
            angle = math.pi / 2 + i * math.pi / 5
            r = r_out if i % 2 == 0 else r_in
            points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
        star.moveTo(points[0])
        for p in points[1:]:
            star.lineTo(p)
        star.closeSubpath()
        if name == "favorite_filled":
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ffcf4d"))
        else:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
        painter.drawPath(star)

    elif name == "download":
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(QPointF(size / 2, margin), QPointF(size / 2, size * 0.65))
        painter.drawLine(QPointF(size * 0.3, size * 0.45), QPointF(size / 2, size * 0.68))
        painter.drawLine(QPointF(size * 0.7, size * 0.45), QPointF(size / 2, size * 0.68))
        painter.drawLine(QPointF(size * 0.22, size * 0.82), QPointF(size * 0.78, size * 0.82))

    elif name == "search":
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(size * 0.18, size * 0.18, size * 0.5, size * 0.5))
        painter.drawLine(QPointF(size * 0.62, size * 0.62), QPointF(size * 0.85, size * 0.85))

    elif name == "refresh":
        painter.setBrush(Qt.NoBrush)
        rect = QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6)
        painter.drawArc(rect, 30 * 16, 300 * 16)
        arrow = QPainterPath()
        arrow.moveTo(size * 0.75, size * 0.18)
        arrow.lineTo(size * 0.85, size * 0.32)
        arrow.lineTo(size * 0.68, size * 0.34)
        arrow.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(brush_color)
        painter.drawPath(arrow)

    elif name == "settings":
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(size * 0.3, size * 0.3, size * 0.4, size * 0.4))
        import math
        cx, cy = size / 2, size / 2
        for i in range(8):
            angle = i * math.pi / 4
            x1 = cx + math.cos(angle) * size * 0.32
            y1 = cy + math.sin(angle) * size * 0.32
            x2 = cx + math.cos(angle) * size * 0.44
            y2 = cy + math.sin(angle) * size * 0.44
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    elif name == "speaker":
        painter.setPen(Qt.NoPen)
        painter.setBrush(brush_color)
        body = QPainterPath()
        body.moveTo(size * 0.18, size * 0.38)
        body.lineTo(size * 0.38, size * 0.38)
        body.lineTo(size * 0.58, size * 0.2)
        body.lineTo(size * 0.58, size * 0.8)
        body.lineTo(size * 0.38, size * 0.62)
        body.lineTo(size * 0.18, size * 0.62)
        body.closeSubpath()
        painter.drawPath(body)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(size * 0.6, size * 0.28, size * 0.28, size * 0.44), -60 * 16, 120 * 16)

    elif name == "microphone":
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(size * 0.38, size * 0.15, size * 0.24, size * 0.42), size * 0.12, size * 0.12)
        painter.drawArc(QRectF(size * 0.25, size * 0.32, size * 0.5, size * 0.42), 180 * 16, 180 * 16)
        painter.drawLine(QPointF(size / 2, size * 0.74), QPointF(size / 2, size * 0.88))
        painter.drawLine(QPointF(size * 0.35, size * 0.88), QPointF(size * 0.65, size * 0.88))

    elif name == "warning":
        painter.setBrush(QColor(RED))
        painter.setPen(Qt.NoPen)
        tri = QPainterPath()
        tri.moveTo(size / 2, size * 0.12)
        tri.lineTo(size * 0.9, size * 0.85)
        tri.lineTo(size * 0.1, size * 0.85)
        tri.closeSubpath()
        painter.drawPath(tri)
        painter.setPen(QPen(QColor(WHITE), max(1.4, size * 0.08)))
        painter.drawLine(QPointF(size / 2, size * 0.42), QPointF(size / 2, size * 0.62))
        painter.drawPoint(QPointF(size / 2, size * 0.72))

    elif name == "close":
        painter.drawLine(QPointF(size * 0.25, size * 0.25), QPointF(size * 0.75, size * 0.75))
        painter.drawLine(QPointF(size * 0.75, size * 0.25), QPointF(size * 0.25, size * 0.75))

    elif name == "soundboard":
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(size * 0.15, size * 0.25, size * 0.7, size * 0.5), 4, 4)
        painter.drawLine(QPointF(size * 0.3, size * 0.4), QPointF(size * 0.3, size * 0.6))
        painter.drawLine(QPointF(size * 0.5, size * 0.35), QPointF(size * 0.5, size * 0.65))
        painter.drawLine(QPointF(size * 0.7, size * 0.4), QPointF(size * 0.7, size * 0.6))

    elif name == "normal_mic":
        return get_icon("microphone", size, color)

    else:
        # Unknown icon name: draw a simple placeholder circle so the UI
        # never crashes on a typo, but log-worthy in development.
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))

    return _finish(pixmap, painter, key)

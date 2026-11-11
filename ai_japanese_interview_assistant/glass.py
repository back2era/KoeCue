"""Shared Qt material, typography and motion for the desktop windows."""
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect, QGraphicsScene,
    QLabel, QProxyStyle, QStyle, QVBoxLayout, QWidget,
)


GLASS_STYLE = """
QWidget { color: #f1f3ff; }
QWidget:disabled { color: #8992ab; }
QLabel { background: transparent; }
QLabel#appTitle { font-size: 21px; font-weight: 700; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; }
QLabel#sectionTitle { font-size: 16px; font-weight: 700; }
QLabel#muted, QLabel#captionState { color: #b6c1dc; font-size: 12px; }
QLabel#captionText { font-size: 23px; }
QLabel#answerText { font-size: 17px; }
QLabel#answerTranslation { color: #c5cfe9; font-size: 15px; }
QLabel#listeningBadge {
    color: #d0d9f2; background: rgba(149, 170, 226, 32);
    border: 1px solid rgba(213, 225, 255, 36); border-radius: 13px;
    padding: 5px 11px; font-size: 12px; font-weight: 700;
}
QLabel#listeningBadge[tone="live"] { color: #bafde7; background: rgba(56, 193, 146, 44); }
QLabel#listeningBadge[tone="pending"] { color: #ffe2b2; background: rgba(239, 177, 86, 39); }
QFrame#glassPanel, QFrame#glassBar, QFrame#glassInset {
    background: qlineargradient(x1:0, y1:0, x2:0.8, y2:1,
        stop:0 rgba(202, 218, 255, 32), stop:0.48 rgba(148, 163, 215, 19),
        stop:1 rgba(55, 69, 115, 27));
    border: 1px solid rgba(205, 221, 255, 42);
    border-top-color: rgba(233, 239, 255, 65);
    border-radius: 23px;
}
QFrame#glassBar { border-radius: 22px; }
QFrame#glassInset { border-radius: 16px; }
QFrame#answerCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(144, 165, 255, 35), stop:1 rgba(110, 100, 203, 17));
    border: 1px solid rgba(186, 198, 255, 39); border-radius: 17px;
}
QFrame#captionRule { background: rgba(218, 225, 255, 28); border: none; }
QPushButton, QComboBox, QLineEdit {
    background: rgba(196, 212, 255, 19); color: #edf1ff;
    border: 1px solid rgba(198, 213, 255, 44); border-radius: 12px;
    min-height: 20px; padding: 6px 12px;
}
QPushButton { border-radius: 16px; }
QPushButton:hover, QComboBox:hover { background: rgba(189, 211, 255, 35); }
QPushButton:pressed { background: rgba(156, 182, 255, 54); }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border-color: #98b9ff; }
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled {
    color: #929bb3; background: rgba(192, 206, 245, 8); border-color: rgba(192, 206, 245, 21);
}
QPushButton#primaryAction {
    color: #111e40; font-weight: 700; border-color: #b1c7ff;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c7d9ff, stop:1 #a3baff);
}
QPushButton#primaryAction:hover { background: #dbe6ff; }
QPushButton#primaryAction:pressed { background: #a3baff; }
QPushButton#primaryAction:disabled {
    color: #a6b4d6; background: rgba(136, 167, 255, 31); border-color: rgba(168, 190, 255, 37);
}
QPushButton[nav="true"] { border-color: transparent; background: transparent; color: #c9d3ed; }
QPushButton[nav="true"]:hover { background: rgba(196, 212, 255, 25); }
QPushButton[nav="true"]:checked { background: rgba(177, 198, 255, 49); color: #fff; }
QPushButton[nav="true"]:focus { border-color: #98b9ff; }
QPushButton#vaultAction { padding-right: 23px; }
QPushButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: center right; right: 3px; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; width: 22px; border: none; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView, QMenu {
    background: #263152; color: #edf1ff; border: 1px solid #52618a;
    selection-background-color: #405484; selection-color: #ffffff;
}
QMenu { padding: 5px; border-radius: 10px; }
QMenu::item { padding: 6px 16px; border-radius: 6px; }
QMenu::item:selected { background: #405484; }
QCheckBox { spacing: 8px; min-height: 24px; }
QTableWidget {
    background: rgba(10, 16, 37, 48); alternate-background-color: rgba(170, 189, 245, 10);
    color: #edf1ff; border: 1px solid rgba(198, 213, 255, 33); border-radius: 12px;
    selection-background-color: #415780; selection-color: #fff;
}
QTableWidget::item { padding: 5px 8px; }
QTableWidget::item:selected { background: #415780; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: rgba(170, 192, 255, 29); color: #d6dff6; padding: 8px;
    border: none; border-bottom: 1px solid rgba(207, 224, 255, 38);
}
QTableCornerButton::section { background: #303d62; border: none; }
QScrollArea#captionScroll, QWidget#captionContent { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: rgba(171, 191, 250, 27); border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: rgba(189, 205, 246, 78); border-radius: 3px; min-height: 22px; min-width: 22px; }
QScrollBar::handle:hover { background: rgba(210, 224, 255, 132); }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent; width: 0; height: 0;
}
QProgressBar {
    background: rgba(12, 20, 45, 75); border: 1px solid rgba(198, 213, 255, 39);
    border-radius: 7px; min-height: 12px; max-height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #87a9ff, stop:1 #b3f1eb);
    border-radius: 6px;
}
QToolTip { background: #283653; color: #fff; border: 1px solid #64749d; padding: 5px; }
"""


def _soft_light():
    """Blur only the decorative background once, independently of live widgets."""
    width, height = 480, 320
    source = QPixmap(width, height)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    for x, y, radius, color in (
        (61, 45, 235, "#435caa"), (415, 116, 194, "#514584"),
        (150, 324, 210, "#204d65"),
    ):
        glow = QRadialGradient(QPointF(x, y), radius)
        glow.setColorAt(0, QColor(color))
        glow.setColorAt(0.60, QColor(54, 69, 123, 95))
        glow.setColorAt(1, Qt.GlobalColor.transparent)
        painter.fillRect(source.rect(), glow)
    painter.end()

    bounds = QRectF(source.rect())
    scene = QGraphicsScene(bounds)
    layer = scene.addPixmap(source)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(24)
    blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    layer.setGraphicsEffect(blur)
    backdrop = QPixmap(width, height)
    backdrop.fill(QColor("#0e162c"))
    painter = QPainter(backdrop)
    scene.render(painter, bounds, bounds)
    painter.end()
    return backdrop


class GlassCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.backdrop = _soft_light()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self.backdrop)


class GlassStyle(QProxyStyle):
    def __init__(self):
        super().__init__("Fusion")

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
            return 16
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#9eb7f1" if enabled else "#586683"))
        painter.setBrush(QColor("#a9c2ff" if checked and enabled else "#344363"))
        painter.drawRoundedRect(rect, 4, 4)
        if checked:
            pen = QPen(QColor("#142344" if enabled else "#b7c3dc"))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            check = QPainterPath(QPointF(rect.left() + 3.5, rect.center().y()))
            check.lineTo(rect.left() + 6, rect.center().y() + 2.5)
            check.lineTo(rect.right() - 3, rect.center().y() - 3)
            painter.drawPath(check)
        painter.restore()


class GlassComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#d6e3ff" if self.isEnabled() else "#8896b3"))
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        x, y = self.width() - 16, self.height() / 2
        chevron = QPainterPath(QPointF(x - 3.5, y - 1.5))
        chevron.lineTo(x, y + 2)
        chevron.lineTo(x + 3.5, y - 1.5)
        painter.drawPath(chevron)


class GlassDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        frame = QVBoxLayout(self)
        frame.setContentsMargins(0, 0, 0, 0)
        canvas = GlassCanvas(self)
        frame.addWidget(canvas)
        self.body = QVBoxLayout(canvas)
        self.body.setContentsMargins(22, 20, 22, 20)
        self.body.setSpacing(12)
        self.body.addWidget(plain_label(title, "pageTitle"))


def glass_panel(name="glassPanel"):
    panel = QFrame()
    panel.setObjectName(name)
    return panel


def plain_label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class BrandMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(38, 38)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(235, 243, 255, 120))
        painter.setBrush(QColor(136, 162, 255, 104))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 37, 37), 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#edf4ff"))
        for index, height in enumerate((8, 15, 21, 12, 6)):
            painter.drawRoundedRect(QRectF(9 + index * 4.5, (38 - height) / 2, 2.5, height), 1.25, 1.25)


class PageFade:
    def __init__(self, widget):
        self.widget = widget
        self.effect = QGraphicsOpacityEffect(widget)
        self.effect.setEnabled(False)
        widget.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b"opacity", widget)
        self.animation.setStartValue(0.72)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(lambda: self.effect.setEnabled(False))

    def play(self):
        self.animation.stop()
        self.effect.setEnabled(False)
        duration = self.widget.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration)
        if duration > 0:
            self.animation.setDuration(min(duration, 180))
            self.effect.setOpacity(0.72)
            self.effect.setEnabled(True)
            self.animation.start()

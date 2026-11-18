"""Shared Qt material, typography and motion for the desktop windows."""
from string import Template

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect,
    QGraphicsScene, QLabel, QProxyStyle, QStyle, QVBoxLayout, QWidget,
)

from .themes import DEFAULT_THEME, THEMES, Theme


_STYLE = Template("""
QWidget { color: $text; }
QWidget:disabled { color: $disabled; }
QLabel { background: transparent; }
QLabel#appTitle { font-size: 21px; font-weight: 700; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; }
QLabel#sectionTitle { font-size: 16px; font-weight: 700; }
QLabel#muted, QLabel#captionState { color: $muted; font-size: 12px; }
QLabel#captionText { font-size: 23px; }
QLabel#answerText { font-size: 17px; }
QLabel#answerTranslation { color: $muted; font-size: 15px; }
QLabel#listeningBadge {
    color: $muted; background: $control;
    border: 1px solid $edge; border-radius: 13px;
    padding: 5px 11px; font-size: 12px; font-weight: 700;
}
QLabel#listeningBadge[tone="live"] { color: $live_text; background: $live_surface; }
QLabel#listeningBadge[tone="pending"] { color: $pending_text; background: $pending_surface; }
QFrame#glassPanel, QFrame#glassBar, QFrame#glassInset {
    background: qlineargradient(x1:0, y1:0, x2:0.8, y2:1,
        stop:0 $panel_top, stop:1 $panel_bottom);
    border: 1px solid $edge;
    border-top-color: $edge_top;
    border-radius: 23px;
}
QFrame#glassBar { border-radius: 22px; }
QFrame#glassInset { border-radius: 16px; }
QFrame#answerCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 $answer_top, stop:1 $answer_bottom);
    border: 1px solid $edge; border-radius: 17px;
}
QFrame#captionRule { background: $edge; border: none; }
QPushButton, QComboBox, QLineEdit {
    background: $control; color: $text;
    border: 1px solid $edge; border-radius: 12px;
    min-height: 20px; padding: 6px 12px;
}
QPushButton {
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $control_top, stop:1 $control);
}
QPushButton:hover, QComboBox:hover { background: $control_hover; }
QPushButton:pressed, QPushButton:checked { background: $selection; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border-color: $focus; }
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled {
    color: $disabled; background: $control_disabled; border-color: $edge_soft;
}
QPlainTextEdit {
    color: $text; background: $table; border: 1px solid $edge; border-radius: 12px;
    padding: 8px; selection-background-color: $selection; selection-color: $text;
}
QPlainTextEdit:focus { border-color: $focus; }
QPlainTextEdit:disabled { color: $disabled; border-color: $edge_soft; }
QPushButton#primaryAction {
    color: $action_text; font-weight: 700; border-color: $action_bottom;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $action_top, stop:1 $action_bottom);
}
QPushButton#primaryAction:hover { background: $action_top; }
QPushButton#primaryAction:pressed { background: $action_bottom; }
QPushButton#primaryAction:focus { border: 2px solid $focus; padding: 5px 11px; }
QPushButton#primaryAction:disabled {
    color: $disabled; background: $control_disabled; border-color: $edge_soft;
}
QPushButton[nav="true"] { border-color: transparent; background: transparent; color: $muted; }
QPushButton[nav="true"]:hover { background: $control_top; }
QPushButton[nav="true"]:checked { background: $nav_selected; color: $text; }
QPushButton[nav="true"]:focus { border-color: $focus; }
QPushButton#vaultAction { padding-right: 23px; }
QPushButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: center right; right: 3px; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; width: 22px; border: none; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView, QMenu {
    background: $table; color: $text; border: 1px solid $focus;
    selection-background-color: $selection; selection-color: $text;
}
QMenu { padding: 5px; border-radius: 10px; }
QMenu::item { padding: 6px 16px; border-radius: 6px; }
QMenu::item:selected { background: $selection; }
QCheckBox { spacing: 8px; min-height: 24px; }
QTableWidget {
    background: $table; alternate-background-color: $alternate_row;
    color: $text; border: 1px solid $edge; border-radius: 12px;
    selection-background-color: $selection; selection-color: $text;
}
QTableWidget::item { padding: 5px 8px; }
QTableWidget::item:selected { background: $selection; }
QTableWidget QLineEdit { background: $table; border-radius: 5px; padding: 0 4px; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: $table_header; color: $muted; padding: 8px;
    border: none; border-bottom: 1px solid $edge;
}
QTableCornerButton::section { background: $table_header; border: none; }
QScrollArea#captionScroll, QWidget#captionContent { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: $edge; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $scroll; border-radius: 3px; min-height: 22px; min-width: 22px; }
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent; width: 0; height: 0;
}
QProgressBar {
    background: $table; border: 1px solid $edge;
    border-radius: 7px; min-height: 12px; max-height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $focus, stop:1 $action_top);
    border-radius: 6px;
}
QToolTip { background: $table; color: $text; border: 1px solid $focus; padding: 5px; }
""")


def _translucent(color: str, alpha: int) -> str:
    red, green, blue, _ = QColor(color).getRgb()
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _style(theme: Theme) -> str:
    light = theme.light
    return _STYLE.substitute(
        text=theme.text, muted=theme.muted, disabled=theme.disabled, focus=theme.focus,
        table=theme.table, alternate_row=theme.alternate_row, table_header=theme.table_header,
        selection=theme.selection, action_text=theme.action_text,
        action_top=theme.action_top, action_bottom=theme.action_bottom,
        panel_top=_translucent(theme.surface_tint, 179 if light else 43),
        panel_bottom=_translucent(theme.surface_tint, 92 if light else 13),
        edge=_translucent(theme.border_tint, 49 if light else 38),
        edge_top=_translucent(theme.surface_tint, 218 if light else 62),
        edge_soft=_translucent(theme.border_tint, 31 if light else 24),
        answer_top=_translucent(theme.border_tint, 52 if light else 36),
        answer_bottom=_translucent(theme.border_tint, 28 if light else 18),
        control_top=_translucent(theme.surface_tint, 204 if light else 30),
        control=_translucent(theme.surface_tint, 136 if light else 19),
        control_hover=_translucent(theme.surface_tint, 232 if light else 47),
        control_disabled=_translucent(theme.border_tint, 30 if light else 17),
        nav_selected=_translucent(theme.border_tint, 48),
        scroll=_translucent(theme.border_tint, 98),
        scroll_hover=_translucent(theme.border_tint, 165),
        live_text="#215e4b" if light else "#bafde7",
        live_surface="rgba(83, 165, 130, 45)",
        pending_text="#704313" if light else "#ffe2b2",
        pending_surface="rgba(207, 151, 70, 52)",
    )


GLASS_STYLE = _style(THEMES[DEFAULT_THEME])


def _palette(theme: Theme) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    for key, color in {
        role.Window: theme.backdrop,
        role.WindowText: theme.text,
        role.Base: theme.table,
        role.AlternateBase: theme.alternate_row,
        role.Text: theme.text,
        role.PlaceholderText: theme.muted,
        role.Button: theme.table_header,
        role.ButtonText: theme.text,
        role.Highlight: theme.selection,
        role.HighlightedText: theme.text,
        role.ToolTipBase: theme.table,
        role.ToolTipText: theme.text,
        role.Link: theme.focus,
        role.Accent: theme.focus,
    }.items():
        palette.setColor(key, QColor(color))
    for key in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, key, QColor(theme.disabled))
    return palette


def _active_theme() -> Theme:
    theme_id = QApplication.instance().property("interviewTheme")
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])


def apply_theme(app: QApplication, theme_id: str) -> None:
    """Apply colors to the application and refresh canvases already on screen."""
    if theme_id not in THEMES:
        theme_id = DEFAULT_THEME
    theme = THEMES[theme_id]
    app.setProperty("interviewTheme", theme_id)
    app.styleHints().setColorScheme(Qt.ColorScheme.Light if theme.light else Qt.ColorScheme.Dark)
    app.setPalette(_palette(theme))
    app.setStyleSheet(_style(theme))
    canvases = [widget for widget in app.allWidgets() if isinstance(widget, GlassCanvas)]
    if canvases:
        backdrop = _soft_light(theme)
        for canvas in canvases:
            canvas.backdrop = backdrop
            canvas.update()


def _soft_light(theme: Theme) -> QPixmap:
    """Blur the decorative background independently of live widgets."""
    width, height = 480, 320
    backdrop = QPixmap(width, height)
    backdrop.fill(QColor(theme.backdrop))
    if not theme.glows:
        return backdrop

    source = QPixmap(width, height)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    for (x, y, radius), color in zip(((44, 31, 220), (445, 80, 237), (158, 331, 225)), theme.glows):
        glow = QRadialGradient(QPointF(x, y), radius)
        tint = QColor(color)
        glow.setColorAt(0, tint)
        tint.setAlpha(110)
        glow.setColorAt(0.62, tint)
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
    painter = QPainter(backdrop)
    scene.render(painter, bounds, bounds)
    painter.end()
    return backdrop


class GlassCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.backdrop = _soft_light(_active_theme())

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
        theme = _active_theme()
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(theme.focus if enabled else theme.disabled))
        painter.setBrush(QColor(theme.action_bottom if checked and enabled else theme.table))
        painter.drawRoundedRect(rect, 4, 4)
        if checked:
            pen = QPen(QColor(theme.action_text if enabled else theme.disabled))
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
        theme = _active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.text if self.isEnabled() else theme.disabled))
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


def _paint_waveform_mark(painter, edge, fill, wave):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(QRectF(0.5, 0.5, 37, 37), 12, 12)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(wave)
    for index, height in enumerate((8, 15, 21, 12, 6)):
        painter.drawRoundedRect(QRectF(9 + index * 4.5, (38 - height) / 2, 2.5, height), 1.25, 1.25)


def application_icon():
    """Draw the waveform at native window-icon sizes with transparent corners."""
    icon = QIcon()
    edge, fill, wave = QColor("#909096"), QColor("#5d5e63"), QColor("#f5f5f7")
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.scale(size / 38, size / 38)
        _paint_waveform_mark(painter, edge, fill, wave)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class BrandMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(38, 38)

    def paintEvent(self, event):
        theme = _active_theme()
        painter = QPainter(self)
        edge = QColor(theme.border_tint)
        edge.setAlpha(112)
        fill = QColor(theme.action_bottom)
        fill.setAlpha(131)
        _paint_waveform_mark(painter, edge, fill, QColor(theme.text))


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

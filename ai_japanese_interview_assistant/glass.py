"""Shared Qt controls, palette and motion for the KoeCue desktop."""
import ctypes
from string import Template
import sys

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGraphicsOpacityEffect,
    QLabel, QProxyStyle, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from .themes import (
    CONTROL_RADIUS, DEFAULT_THEME, GAP, GUTTER, INSET, PANEL_RADIUS, TEXT_ANSWER,
    TEXT_BODY, TEXT_CAPTION, TEXT_SMALL, TEXT_TITLE, THEMES, Theme,
)


_STYLE = Template("""
QWidget { color: $text; }
QWidget:disabled { color: $disabled; }
QWidget#appCanvas { background: $backdrop; }
QLabel { background: transparent; }
QLabel#appTitle { font-size: 16px; font-weight: 650; }
QLabel#pageTitle { font-size: ${title}px; font-weight: 600; }
QLabel#sectionTitle { font-size: ${body}px; font-weight: 600; }
QLabel#eyebrow, QLabel#muted, QLabel#captionState { color: $secondary; font-size: ${small}px; }
QLabel#captionState[tone="error"] { color: $danger; }
QLabel#captionText { font-size: ${caption}px; }
QLabel#translatedCaption, QLabel#answerTranslation { color: $secondary; font-size: ${body}px; }
QLabel#compactRescue { font-size: ${body}px; }
QLabel#answerText { font-size: ${answer}px; }
QLabel#answerText[empty="true"] { color: $secondary; }
QLabel#listeningBadge { color: $secondary; font-size: ${small}px; }
QLabel#listeningBadge[tone="live"] { color: $success; }
QLabel#listeningBadge[tone="pending"] { color: $warning; }
QLabel#listeningBadge[tone="error"] { color: $danger; }
QLabel#keyword {
    color: $accent; background: $selection; border-radius: ${control_radius}px;
    font-size: ${small}px; padding: 3px 8px;
}
QFrame#glassPanel {
    background: $surface; border: 1px solid $border; border-radius: ${panel_radius}px;
}
QFrame#toolbar, QFrame#sessionBar { background: $surface; }
QFrame#toolbar { border-bottom: 1px solid $border; }
QFrame#sessionBar { border-top: 1px solid $border; }
QFrame#historyPane { background: $surface; }
QFrame#formFooter { border-top: 1px solid $border; }
QFrame#answerCard, QFrame#glassInset { background: $surface; border-radius: ${panel_radius}px; }
QFrame#captionRule { background: $border; border: none; }
QPushButton, QComboBox, QLineEdit {
    background: $surface; color: $text;
    border: 1px solid $border; border-radius: ${control_radius}px;
    min-height: 18px; padding: 5px 10px;
}
QPushButton:hover, QComboBox:hover { background: $elevated; }
QPushButton:pressed, QPushButton:checked { background: $selection; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus { border-color: $accent; }
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled {
    color: $disabled; background: $backdrop; border-color: $border;
}
QPlainTextEdit {
    color: $text; background: $backdrop; border: 1px solid $border; border-radius: ${control_radius}px;
    padding: 8px; selection-background-color: $selection; selection-color: $text;
}
QPlainTextEdit:focus { border-color: $accent; }
QPlainTextEdit:disabled { color: $disabled; }
QPushButton#primaryAction {
    color: $action_text; background: $action; border-color: $action; font-weight: 600;
}
QPushButton#primaryAction:hover { background: $accent; }
QPushButton#primaryAction:pressed { background: $action; }
QPushButton#primaryAction:focus { border-color: $text; }
QPushButton#primaryAction:disabled {
    color: $disabled; background: $elevated; border-color: $border;
}
QPushButton[nav="true"], QPushButton[quiet="true"] {
    border-color: transparent; background: transparent; color: $secondary;
}
QPushButton[quiet="true"] { padding: 4px 8px; }
QPushButton[nav="true"]:hover, QPushButton[quiet="true"]:hover {
    background: $elevated; color: $text;
}
QPushButton[nav="true"]:checked, QPushButton[quiet="true"]:checked {
    background: $selection; color: $text;
}
QPushButton[nav="true"]:focus, QPushButton[quiet="true"]:focus { border-color: $accent; }
QPushButton[nav="true"]:disabled, QPushButton[quiet="true"]:disabled { color: $disabled; background: transparent; }
QPushButton#iconButton { padding: 0; }
QPushButton#vaultAction { padding-right: 23px; }
QPushButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: center right; right: 3px; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; width: 22px; border: none; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView, QMenu {
    background: $surface; color: $text; border: 1px solid $border;
    selection-background-color: $selection; selection-color: $text;
}
QMenu { padding: 4px; border-radius: ${control_radius}px; }
QMenu::item { padding: 6px 14px; border-radius: 5px; }
QMenu::item:selected { background: $selection; }
QCheckBox { spacing: 8px; min-height: 24px; }
QTableWidget {
    background: $surface; alternate-background-color: $backdrop;
    color: $text; border: 1px solid $border; border-radius: ${control_radius}px;
    selection-background-color: $selection; selection-color: $text;
}
QTableWidget::item { padding: 5px 8px; }
QTableWidget QLineEdit { background: $surface; padding: 0 4px; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: $elevated; color: $secondary; padding: 8px;
    border: none; border-bottom: 1px solid $border;
}
QListWidget#conversationList { background: $surface; border: none; outline: none; }
QScrollArea#captionScroll, QWidget#captionContent { background: transparent; }
QSplitter::handle { background: $border; }
QSplitter::handle:hover { background: $accent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle { background: $border; border-radius: 3px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent; width: 0; height: 0;
}
QProgressBar {
    background: $elevated; border: none; border-radius: 4px; min-height: 8px; max-height: 8px;
}
QProgressBar::chunk { background: $success; border-radius: 4px; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 5px; }
""")


def _style(theme: Theme) -> str:
    return _STYLE.substitute(
        vars(theme), small=TEXT_SMALL, body=TEXT_BODY, caption=TEXT_CAPTION,
        answer=TEXT_ANSWER, title=TEXT_TITLE, control_radius=CONTROL_RADIUS, panel_radius=PANEL_RADIUS,
    )


def _palette(theme: Theme) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    for key, color in {
        role.Window: theme.backdrop, role.WindowText: theme.text, role.Base: theme.surface,
        role.AlternateBase: theme.backdrop, role.Text: theme.text, role.PlaceholderText: theme.secondary,
        role.Button: theme.elevated, role.ButtonText: theme.text, role.Mid: theme.border,
        role.Highlight: theme.selection, role.HighlightedText: theme.text, role.ToolTipBase: theme.surface,
        role.ToolTipText: theme.text, role.Link: theme.accent, role.Accent: theme.accent,
    }.items():
        palette.setColor(key, QColor(color))
    for key in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, key, QColor(theme.disabled))
    return palette


def active_theme() -> Theme:
    theme_id = QApplication.instance().property("interviewTheme")
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])


def apply_theme(app: QApplication, theme_id: str) -> None:
    """Update existing windows and future controls from the same theme."""
    if theme_id not in THEMES:
        theme_id = DEFAULT_THEME
    theme = THEMES[theme_id]
    app.setProperty("interviewTheme", theme_id)
    app.styleHints().setColorScheme(Qt.ColorScheme.Light if theme.light else Qt.ColorScheme.Dark)
    app.setPalette(_palette(theme))
    app.setStyleSheet(_style(theme))


def set_role(widget, name, value):
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class GlassCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("appCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)


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
        theme = active_theme()
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        focus = option.state & QStyle.StateFlag.State_HasFocus
        hovered = option.state & QStyle.StateFlag.State_MouseOver
        rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(theme.accent if enabled and (checked or focus or hovered) else theme.border))
        painter.setBrush(QColor(theme.action if checked and enabled else theme.surface))
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
        theme = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.secondary if self.isEnabled() else theme.disabled))
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        x, y = self.width() - 14, self.height() / 2
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
        self.body.setContentsMargins(GUTTER, GUTTER, GUTTER, INSET)
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


def quiet_button(button):
    button.setProperty("quiet", True)
    return button


def _paint_waveform_mark(painter, edge, fill, wave):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(QRectF(0.5, 0.5, 37, 37), 10, 10)
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
        self.setFixedSize(28, 28)

    def paintEvent(self, event):
        theme = active_theme()
        painter = QPainter(self)
        painter.scale(self.width() / 38, self.height() / 38)
        _paint_waveform_mark(painter, QColor(theme.border), QColor(theme.selection), QColor(theme.accent))


class IconButton(QPushButton):
    """Small, consistently weighted toolbar actions with native focus and tooltips."""

    def __init__(self, kind, name):
        super().__init__()
        self.kind = kind
        self.setObjectName("iconButton")
        self.setFixedSize(32, 32)
        self.setAccessibleName(name)
        self.setToolTip(name)
        quiet_button(self)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(8, 8)
        theme = active_theme()
        ink = theme.accent if self.isChecked() else theme.secondary
        pen = QPen(QColor(ink if self.isEnabled() else theme.disabled))
        pen.setWidthF(1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if self.kind in {"history", "window", "main"}:
            painter.drawRoundedRect(QRectF(1, 2.5, 14, 11), 2, 2)
            if self.kind == "history":
                painter.drawLine(QPointF(10, 3), QPointF(10, 13))
            elif self.kind == "window":
                painter.drawRoundedRect(QRectF(7, 7, 5, 3.5), .7, .7)
        elif self.kind == "pin":
            path = QPainterPath(QPointF(6, 2))
            for x, y in ((12, 2), (10, 5), (10, 8), (12, 10), (4, 10), (6, 8), (6, 5), (4, 2), (6, 2)):
                path.lineTo(x, y)
            painter.drawPath(path)
            painter.drawLine(QPointF(8, 10), QPointF(8, 15))
        elif self.kind == "settings":
            for y, x in ((4, 5), (8, 11), (12, 7)):
                painter.drawLine(QPointF(2, y), QPointF(x - 1.5, y))
                painter.drawLine(QPointF(x + 1.5, y), QPointF(14, y))
                painter.drawEllipse(QPointF(x, y), 1.5, 1.5)


def motion_enabled():
    if sys.platform != "win32":
        return True
    animation = ctypes.c_int()
    success = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animation), 0)
    return not success or bool(animation.value)


class PageFade:
    def __init__(self, widget):
        self.widget = widget
        self.effect = QGraphicsOpacityEffect(widget)
        self.effect.setEnabled(False)
        widget.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b"opacity", widget)
        self.animation.setStartValue(0.8)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(lambda: self.effect.setEnabled(False))

    def play(self):
        self.animation.stop()
        self.effect.setEnabled(False)
        duration = self.widget.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration)
        if duration > 0 and motion_enabled():
            self.animation.setDuration(min(duration, 200))
            self.effect.setOpacity(0.8)
            self.effect.setEnabled(True)
            self.animation.start()

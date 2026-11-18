"""Native compact interview window backed by the existing live session."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from . import APP_NAME
from .glass import GlassCanvas, IconButton, glass_panel, plain_label, set_role
from .interview_ui import AnswerPanel, RescuePhrases, TranscriptionPanel
from .themes import GAP, INSET


COMPACT_SHORTCUT = "Ctrl+Alt+Shift+K"
_HOTKEY_ID = 0x4B43
_WM_HOTKEY = 0x0312
_HOTKEY_MODIFIERS = 0x0001 | 0x0002 | 0x0004 | 0x4000  # Alt, Ctrl, Shift and MOD_NOREPEAT.


class CompactShortcut:
    def __init__(self, window):
        self.handle = None
        if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
            handle = wintypes.HWND(int(window.winId()))
            if ctypes.windll.user32.RegisterHotKey(handle, _HOTKEY_ID, _HOTKEY_MODIFIERS, ord("K")):
                self.handle = handle

    @property
    def registered(self):
        return self.handle is not None

    def matches(self, event_type, message):
        if self.registered and bytes(event_type) == b"windows_generic_MSG":
            event = wintypes.MSG.from_address(int(message))
            return event.message == _WM_HOTKEY and event.wParam == _HOTKEY_ID
        return False

    def release(self):
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(self.handle, _HOTKEY_ID)
            self.handle = None


class CompactWindow(QWidget):
    visibility_changed = Signal(bool)
    main_requested = Signal()

    def __init__(self, cloud, parent):
        flags = (Qt.WindowType.Tool | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint
                 | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(None, flags)
        self.cloud = cloud
        self.main_window = parent
        parent.destroyed.connect(self.close)
        self.positioned = False
        self.setWindowTitle(f"{APP_NAME} · 面试小窗")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(424, 420)
        self.setMinimumSize(352, 336)
        canvas = GlassCanvas()
        window = QVBoxLayout(self)
        window.setContentsMargins(0, 0, 0, 0)
        window.addWidget(canvas)
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = glass_panel("toolbar")
        toolbar.setFixedHeight(41)
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(INSET, 4, GAP, 4)
        tools.setSpacing(GAP)
        self.session = plain_label("", "listeningBadge")
        tools.addWidget(self.session, 1)
        self.pin = IconButton("pin", "切换始终置顶")
        self.pin.setCheckable(True)
        self.pin.setChecked(True)
        self.pin.toggled.connect(self.set_pinned)
        tools.addWidget(self.pin)
        back = IconButton("main", "返回主窗口")
        back.clicked.connect(self.main_requested)
        tools.addWidget(back)
        layout.addWidget(toolbar)

        question = QWidget()
        question_layout = QVBoxLayout(question)
        question_layout.setContentsMargins(INSET, 12, INSET, GAP)
        self.transcription = TranscriptionPanel(compact=True)
        question_layout.addWidget(self.transcription)
        layout.addWidget(question)
        layout.addWidget(self.cloud.rule())

        self.answer = AnswerPanel(compact=True)
        self.answer_scroll = QScrollArea()
        self.answer_scroll.setObjectName("captionScroll")
        self.answer_scroll.setWidgetResizable(True)
        self.answer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.answer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        wrapper = QWidget()
        wrapper.setObjectName("captionContent")
        reading = QVBoxLayout(wrapper)
        reading.setContentsMargins(INSET, GAP, INSET, GAP)
        reading.addWidget(self.answer)
        reading.addStretch()
        self.answer_scroll.setWidget(wrapper)
        layout.addWidget(self.answer_scroll, 1)

        rescue = glass_panel("sessionBar")
        rescue_layout = QVBoxLayout(rescue)
        rescue_layout.setContentsMargins(INSET, 4, INSET, 4)
        rescue_layout.addWidget(RescuePhrases(compact=True))
        layout.addWidget(rescue)
        self.cloud.view_changed.connect(self.refresh)
        QGuiApplication.instance().screenRemoved.connect(self.screen_removed)

    def refresh(self):
        if not self.isVisible():
            return
        key = self.cloud.rendered[-1] if self.cloud.rendered else None
        row = self.cloud.rows.get(key)
        preview = self.cloud.preview_text
        transcription = self.transcription
        transcription.original.set_caption(preview or (row.ja if row else ""), tail=bool(preview))
        status = "识别中" if preview else row.asr if row else ""
        transcription.original_state.setText(status)
        transcription.original_state.setVisible(bool(status))
        zh = row.zh if row and not preview else ""
        transcription.translated.set_caption(zh)
        transcription.translated.setVisible(bool(zh))

        if key != self.answer.row_key:
            self.answer_scroll.verticalScrollBar().setValue(0)
        answer = row.answer if row else None
        self.answer.set_content(
            key, answer, row.answer_status if row else "", self.cloud.answer_placeholder(row),
            prior=bool(preview and answer),
        )
        self.session.setText(self.cloud.listening_badge.text())
        set_role(self.session, "tone", self.cloud.listening_badge.property("tone"))
        self.session.setToolTip(self.cloud.status_detail.text())

    def show_overlay(self):
        target = QGuiApplication.screenAt(QCursor.pos()) or self.main_window.screen()
        if not self.positioned and target is not None:
            area = target.availableGeometry()
            self.move(area.right() - self.width() - 24, area.top() + 72)
            self.positioned = True
        self.show()
        self.keep_on_screen(target)
        self.raise_()

    def set_pinned(self, pinned):
        visible = self.isVisible()
        position = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.move(position)
        if visible:
            self.show_overlay()

    def keep_on_screen(self, fallback=None):
        frame = self.frameGeometry()
        screen = QGuiApplication.screenAt(frame.center()) or fallback or self.main_window.screen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(
                min(self.width(), area.width() - (frame.width() - self.width())),
                min(self.height(), area.height() - (frame.height() - self.height())),
            )
            frame = self.frameGeometry()
            self.move(
                max(area.left(), min(frame.left(), area.right() - frame.width() + 1)),
                max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1)),
            )

    def screen_removed(self, _screen):
        if self.isVisible():
            self.keep_on_screen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.transcription.original.limit_lines(1 if event.size().height() < 370 else 2)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)

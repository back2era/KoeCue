"""Launch the desktop application."""
import sys
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout,
)

from . import APP_NAME
from .cloud_gui import CloudPane
from .compact import COMPACT_SHORTCUT, CompactShortcut, CompactWindow
from .diagnostic import DiagnosticPane
from .glass import (
    DEFAULT_THEME, BrandMark, GlassCanvas, GlassStyle, IconButton, PageFade, application_icon,
    apply_theme, glass_panel, plain_label,
)
from .personal_gui import PersonalPane
from .themes import GAP, INSET, TEXT_BODY, UI_FONTS
from .windows_taskbar import register_process, register_window, unregister_window


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.closing = False
        self.taskbar_handle = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(620, 500)
        default_size = QSize(1120, 740)
        if QApplication.platformName() == "windows":
            available = self.screen().availableGeometry().size()
            default_size = default_size.boundedTo(available - QSize(24, 64))
        self.resize(default_size)
        canvas = GlassCanvas()
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = glass_panel("toolbar")
        header = QHBoxLayout(toolbar)
        header.setContentsMargins(INSET, GAP, INSET, GAP)
        header.setSpacing(GAP)
        header.addWidget(BrandMark())
        header.addWidget(plain_label(APP_NAME, "appTitle"))
        header.addStretch(1)
        self.navigation = QButtonGroup(self)
        for index, title in enumerate(("实时面试", "音频诊断", "个人信息")):
            button = QPushButton(title)
            button.setProperty("nav", True)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            header.addWidget(button)
        header.addStretch(1)
        layout.addWidget(toolbar)
        self.tabs = QStackedWidget()
        self.diagnostic = DiagnosticPane(self)
        self.diagnostic.idle.connect(self.retry_close)
        self.diagnostic.idle.connect(self.sync_audio_controls)
        self.cloud = CloudPane(self)
        self.cloud.theme_changed.connect(lambda theme_id: apply_theme(QApplication.instance(), theme_id))
        self.cloud.idle.connect(self.retry_close)
        self.cloud.idle.connect(self.sync_audio_controls)
        header.addWidget(self.cloud.history_toggle)
        self.compact_button = IconButton("window", "面试小窗")
        self.compact_button.setCheckable(True)
        self.compact_button.clicked.connect(self.toggle_compact)
        header.addWidget(self.compact_button)
        header.addWidget(self.cloud.settings_toggle)
        self.compact = CompactWindow(self.cloud, self)
        self.compact.visibility_changed.connect(self.compact_button.setChecked)
        self.compact.main_requested.connect(self.show_main)
        self.personal = PersonalPane(self.cloud.auto_answer, self.cloud.open_profile, self)
        self.personal.idle.connect(self.retry_close)
        self.personal.authorized.connect(self.cloud.set_approved_personal)
        self.personal.revoked.connect(self.cloud.revoke_profile)
        self.cloud.profile_changed.connect(self.personal.session_state)
        self.personal.session_state(*self.cloud.profile_snapshot)
        self.tabs.addWidget(self.cloud)
        self.tabs.addWidget(self.diagnostic)
        self.tabs.addWidget(self.personal)
        self.navigation.button(0).setChecked(True)
        self.navigation.idClicked.connect(self.tabs.setCurrentIndex)
        for key, step in ((QKeySequence.StandardKey.NextChild, 1), (QKeySequence.StandardKey.PreviousChild, -1)):
            shortcut = QShortcut(key, self)
            shortcut.activated.connect(lambda step=step: self.cycle_page(step))
        self.fade = PageFade(self.tabs)
        self.tabs.currentChanged.connect(self.change_page)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(canvas)
        self.compact_shortcut = CompactShortcut(self)
        shortcut_tip = COMPACT_SHORTCUT
        if not self.compact_shortcut.registered:
            shortcut = QShortcut(QKeySequence(COMPACT_SHORTCUT), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.toggle_compact)
            shortcut_tip += " · KoeCue 内"
        self.compact_button.setToolTip(f"显示或隐藏面试小窗（{shortcut_tip}）")

    def nativeEvent(self, event_type, message):
        shortcut = getattr(self, "compact_shortcut", None)
        if shortcut is not None and shortcut.matches(event_type, message):
            self.toggle_compact()
            return True, 0
        return super().nativeEvent(event_type, message)

    def cycle_page(self, step):
        self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def toggle_compact(self):
        if self.closing or self.cloud.confirmation is not None:
            self.compact_button.setChecked(self.compact.isVisible())
        elif self.compact.isVisible():
            self.compact.hide()
        else:
            self.compact.show_overlay()

    def show_main(self):
        self.compact.hide()
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def change_page(self, index):
        self.navigation.button(index).setChecked(True)
        current = self.tabs.widget(index)
        self.cloud.history_toggle.setEnabled(current is self.cloud)
        if current is not self.cloud:
            self.cloud.settings_toggle.setChecked(False)
        if current is self.diagnostic and self.cloud.state != "idle":
            self.cloud.stop_session()
        if current is not self.diagnostic and self.diagnostic.state != "idle":
            self.diagnostic.stop_capture()
        self.sync_audio_controls()
        self.fade.play()

    def sync_audio_controls(self):
        self.cloud.capture_available = self.diagnostic.worker is None
        self.diagnostic.capture_available = self.cloud.worker is None
        self.cloud.controls()
        self.diagnostic.update_controls()

    def retry_close(self):
        if self.closing:
            self.close()

    def closeEvent(self, event):
        self.closing = True
        self.compact.hide()
        diagnostic_idle = self.diagnostic.shutdown()
        cloud_idle = self.cloud.shutdown()
        personal_idle = self.personal.shutdown()
        if diagnostic_idle and cloud_idle and personal_idle:
            self.compact_shortcut.release()
            if self.taskbar_handle is not None:
                unregister_window(self.taskbar_handle)
                self.taskbar_handle = None
            event.accept()
        else:
            event.ignore()


def configure_application(app):
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(application_icon())
    app.setStyle(GlassStyle())
    fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    for family, file in (("Microsoft YaHei UI", "msyh.ttc"), ("Yu Gothic UI", "YuGothM.ttc")):
        if family not in QFontDatabase.families() and (fonts / file).is_file():
            QFontDatabase.addApplicationFont(str(fonts / file))
    font = app.font()
    font.setFamilies(list(UI_FONTS))
    font.setPixelSize(TEXT_BODY)
    app.setFont(font)
    apply_theme(app, DEFAULT_THEME)


def main():
    register_process()
    app = QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.taskbar_handle = register_window(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

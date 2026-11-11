"""Launch the desktop application."""
import sys
import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout,
)

from .cloud_gui import CloudPane
from .diagnostic import DiagnosticPane
from .glass import (
    DEFAULT_THEME, BrandMark, GlassCanvas, GlassStyle, PageFade, application_icon, apply_theme, glass_panel, plain_label,
)
from .personal_gui import PersonalPane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.closing = False
        self.setWindowTitle("AI 日语面试助手")
        self.resize(1120, 740)
        self.setMinimumSize(620, 540)
        canvas = GlassCanvas()
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(13)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(BrandMark())
        header.addWidget(plain_label("AI 日语面试助手", "appTitle"), 1)
        nav = glass_panel("glassBar")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(4, 4, 4, 4)
        nav_layout.setSpacing(3)
        self.navigation = QButtonGroup(self)
        for index, title in enumerate(("实时面试", "音频诊断", "个人信息")):
            button = QPushButton(title)
            button.setProperty("nav", True)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            nav_layout.addWidget(button)
        header.addWidget(nav)
        layout.addLayout(header)
        self.tabs = QStackedWidget()
        self.diagnostic = DiagnosticPane(self)
        self.diagnostic.idle.connect(self.retry_close)
        self.diagnostic.idle.connect(self.sync_audio_controls)
        self.cloud = CloudPane(self)
        self.cloud.theme_changed.connect(lambda theme_id: apply_theme(QApplication.instance(), theme_id))
        self.cloud.idle.connect(self.retry_close)
        self.cloud.idle.connect(self.sync_audio_controls)
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

    def cycle_page(self, step):
        self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def change_page(self, index):
        self.navigation.button(index).setChecked(True)
        current = self.tabs.widget(index)
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
        diagnostic_idle = self.diagnostic.shutdown()
        cloud_idle = self.cloud.shutdown()
        personal_idle = self.personal.shutdown()
        if diagnostic_idle and cloud_idle and personal_idle:
            event.accept()
        else:
            event.ignore()


def configure_application(app):
    app.setWindowIcon(application_icon())
    app.setStyle(GlassStyle())
    fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    for family, file in (("Microsoft YaHei UI", "msyh.ttc"), ("Yu Gothic UI", "YuGothM.ttc")):
        if family not in QFontDatabase.families() and (fonts / file).is_file():
            QFontDatabase.addApplicationFont(str(fonts / file))
    font = app.font()
    font.setFamilies(["Inter", "Microsoft YaHei UI", "Yu Gothic UI", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)
    apply_theme(app, DEFAULT_THEME)


def main():
    app = QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

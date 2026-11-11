"""Launch the desktop application."""
import sys
import os
from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .cloud_gui import CloudPane
from .diagnostic import DiagnosticPane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.closing = False
        self.setWindowTitle("AI 日语面试助手")
        self.resize(920, 710)
        self.tabs = QTabWidget()
        self.diagnostic = DiagnosticPane(self)
        self.diagnostic.idle.connect(self.retry_close)
        self.diagnostic.idle.connect(self.sync_audio_controls)
        self.cloud = CloudPane(self)
        self.cloud.idle.connect(self.retry_close)
        self.cloud.idle.connect(self.sync_audio_controls)
        self.tabs.addTab(self.cloud, "实时面试辅助")
        self.tabs.addTab(self.diagnostic, "音频诊断")
        self.tabs.currentChanged.connect(self.stop_other_session)
        self.setCentralWidget(self.tabs)

    def stop_other_session(self, index):
        current = self.tabs.widget(index)
        if current is self.diagnostic and self.cloud.state != "idle":
            self.cloud.stop_session()
        elif current is self.cloud and self.diagnostic.state != "idle":
            self.diagnostic.stop_capture()
        self.sync_audio_controls()

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
        if diagnostic_idle and cloud_idle:
            event.accept()
        else:
            event.ignore()


def configure_application(app):
    app.setStyle("Fusion")
    fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    for family, file in (("Microsoft YaHei UI", "msyh.ttc"), ("Yu Gothic UI", "YuGothM.ttc")):
        if family not in QFontDatabase.families() and (fonts / file).is_file():
            QFontDatabase.addApplicationFont(str(fonts / file))
    font = app.font()
    font.setFamilies(["Microsoft YaHei UI", "Yu Gothic UI", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#090a0c",
        QPalette.ColorRole.WindowText: "#ecf2ff",
        QPalette.ColorRole.Base: "#101622",
        QPalette.ColorRole.AlternateBase: "#1a2433",
        QPalette.ColorRole.Text: "#ecf2ff",
        QPalette.ColorRole.PlaceholderText: "#a1adc0",
        QPalette.ColorRole.Button: "#253247",
        QPalette.ColorRole.ButtonText: "#ecf2ff",
        QPalette.ColorRole.Highlight: "#64a9ff",
        QPalette.ColorRole.HighlightedText: "#101622",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#8190a7"))
    app.setPalette(palette)


def main():
    app = QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

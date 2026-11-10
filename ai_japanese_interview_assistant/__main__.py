"""Launch the desktop application."""
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .cloud_gui import CloudPane
from .diagnostic import DiagnosticPane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.closing = False
        self.setWindowTitle("AI Japanese Interview Assistant")
        self.resize(980, 720)
        self.tabs = QTabWidget()
        self.diagnostic = DiagnosticPane(self)
        self.diagnostic.idle.connect(self.retry_close)
        self.cloud = CloudPane(self)
        self.cloud.idle.connect(self.retry_close)
        self.tabs.addTab(self.diagnostic, "本地音频诊断")
        self.tabs.addTab(self.cloud, "实时面试辅助")
        self.tabs.currentChanged.connect(self.stop_other_session)
        self.setCentralWidget(self.tabs)

    def stop_other_session(self, index):
        if index == 0 and self.cloud.state != "idle":
            self.cloud.stop_session()
        elif index == 1 and self.diagnostic.state != "idle":
            self.diagnostic.stop_capture()

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


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#161d29",
        QPalette.ColorRole.WindowText: "#ecf2ff",
        QPalette.ColorRole.Base: "#101622",
        QPalette.ColorRole.Text: "#ecf2ff",
        QPalette.ColorRole.Button: "#253247",
        QPalette.ColorRole.ButtonText: "#ecf2ff",
        QPalette.ColorRole.Highlight: "#64a9ff",
        QPalette.ColorRole.HighlightedText: "#101622",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

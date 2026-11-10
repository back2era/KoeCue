"""Launch the desktop application."""
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow

from .diagnostic import DiagnosticPane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.closing = False
        self.setWindowTitle("AI Japanese Interview Assistant")
        self.resize(840, 540)
        self.diagnostic = DiagnosticPane(self)
        self.diagnostic.idle.connect(self.retry_close)
        self.setCentralWidget(self.diagnostic)

    def retry_close(self):
        if self.closing:
            self.close()

    def closeEvent(self, event):
        self.closing = True
        if self.diagnostic.shutdown():
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

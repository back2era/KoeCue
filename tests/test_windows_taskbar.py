"""Read back the taskbar metadata from a real, hidden Windows window."""
import os
import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("AIJA_TEST_GUI") != "1",
    reason="opt-in native Windows Qt test",
)
def test_windows_shell_receives_waveform_icon_and_separate_application_id(tmp_path):
    script = dedent("""
        import ctypes
        from pathlib import Path
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication, QMainWindow
        from ai_japanese_interview_assistant.__main__ import configure_application
        from ai_japanese_interview_assistant import windows_taskbar as taskbar

        taskbar.register_process()
        query = ctypes.oledll.shell32.GetCurrentProcessExplicitAppUserModelID
        query.argtypes = (ctypes.POINTER(ctypes.c_void_p),)
        app_id = ctypes.c_void_p()
        query(ctypes.byref(app_id))
        try:
            assert ctypes.wstring_at(app_id) == taskbar.APP_ID
        finally:
            ctypes.windll.ole32.CoTaskMemFree(app_id)

        app = QApplication([])
        configure_application(app)
        window = QMainWindow()
        window.setWindowTitle(app.applicationName())
        hwnd = taskbar.register_window(window)
        assert hwnd == int(window.winId()) and not window.isVisible()

        def property_value(property_id):
            with taskbar._property_store(hwnd) as (store, methods):
                get_value = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p,
                    ctypes.POINTER(taskbar._PropertyKey), ctypes.POINTER(taskbar._PropVariant),
                )(methods[5])
                key = taskbar._PropertyKey(taskbar._APP_PROPERTIES, property_id)
                value = taskbar._PropVariant()
                get_value(store, ctypes.byref(key), ctypes.byref(value))
                try:
                    return ctypes.wstring_at(value.data[0]) if value.type == 31 else None
                finally:
                    ctypes.oledll.ole32.PropVariantClear(ctypes.byref(value))

        assert property_value(5) == taskbar.APP_ID
        assert property_value(4) == "KoeCue"
        assert "pythonw.exe" in property_value(2) and "launch.pyw" in property_value(2)
        icon_path, index = property_value(3).rsplit(",", 1)
        assert index == "0" and Path(icon_path).is_file()
        image = QImage(icon_path)
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(image.width() // 2, image.height() // 2).lightness() > 220
        taskbar.unregister_window(hwnd)
        assert all(property_value(i) is None for i in (2, 3, 4, 5))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=dict(os.environ, QT_QPA_PLATFORM="windows", LOCALAPPDATA=str(tmp_path)),
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

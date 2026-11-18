"""Launch KoeCue from a Windows taskbar shortcut or the packaged executable."""
import json
from pathlib import Path
import sys
from time import monotonic, sleep
import traceback

from ai_japanese_interview_assistant import APP_VERSION


def verify_installation(report):
    """Exercise the bundled Qt, WASAPI, and Whisper components without capturing audio."""
    window = None
    try:
        from PySide6.QtWidgets import QApplication
        from ai_japanese_interview_assistant import cloud_gui
        from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application
        from ai_japanese_interview_assistant.audio import list_devices
        from ai_japanese_interview_assistant.local_asr import decoder_model_directory, load_decoder

        app = QApplication([])
        configure_application(app)
        cloud_gui.credential = lambda *args: ""
        window = MainWindow()
        window.show()
        app.processEvents()
        devices = list_devices()
        decode = load_decoder()
        decode(bytes(48000))
        model = decoder_model_directory()
        result = {"version": APP_VERSION, "qt_platform": app.platformName(), "devices": len(devices),
                  "main_window_tabs": window.tabs.count(),
                  "bundled_model": model.is_relative_to(Path(sys.executable).parent),
                  "local_inference": True}
    except Exception:
        result = {"error": traceback.format_exc()}
    finally:
        if window is not None:
            window.close()
            deadline = monotonic() + 10
            while window.isVisible() and monotonic() < deadline:
                app.processEvents()
                sleep(0.02)
            if window.isVisible():
                result = {"error": "KoeCue window did not finish closing."}
    Path(report).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return int("error" in result)


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and len(sys.argv) == 3 and sys.argv[1] == "--verify-installation":
        raise SystemExit(verify_installation(sys.argv[2]))
    from ai_japanese_interview_assistant.__main__ import main

    raise SystemExit(main())

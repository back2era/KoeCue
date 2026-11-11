"""Give the source-launched app its own Windows taskbar identity and icon."""
from contextlib import contextmanager
import ctypes
import logging
from pathlib import Path
from subprocess import list2cmdline
import sys
from uuid import UUID

from PySide6.QtCore import QIODevice, QSaveFile
from PySide6.QtGui import QGuiApplication

from .profiles import ProfileError, app_directory


APP_ID = "AIJapaneseInterviewAssistant.Desktop"
_LOG = logging.getLogger(__name__)
_Guid = ctypes.c_ubyte * 16
_APP_PROPERTIES = _Guid.from_buffer_copy(UUID("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3").bytes_le)
_PROPERTY_STORE_IID = _Guid.from_buffer_copy(UUID("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99").bytes_le)
_RELAUNCH_COMMAND, _RELAUNCH_ICON, _RELAUNCH_NAME, _WINDOW_APP_ID = 2, 3, 4, 5


class _PropertyKey(ctypes.Structure):
    _fields_ = [("format", _Guid), ("id", ctypes.c_uint32)]


class _PropVariant(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint16), ("reserved", ctypes.c_uint16 * 3), ("data", ctypes.c_void_p * 2)]


def register_process():
    if sys.platform != "win32":
        return
    try:
        set_app_id = ctypes.oledll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = (ctypes.c_wchar_p,)
        set_app_id(APP_ID)
    except OSError:
        _LOG.warning("Windows taskbar process identity could not be set.")


@contextmanager
def _property_store(hwnd):
    initialize = ctypes.oledll.ole32.CoInitializeEx
    initialize.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    initialize(None, 2)  # COINIT_APARTMENTTHREADED
    try:
        get_store = ctypes.oledll.shell32.SHGetPropertyStoreForWindow
        get_store.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p))
        store = ctypes.c_void_p()
        get_store(hwnd, ctypes.byref(_PROPERTY_STORE_IID), ctypes.byref(store))
        methods = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        try:
            yield store, methods
        finally:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(methods[2])(store)  # IUnknown::Release
    finally:
        ctypes.windll.ole32.CoUninitialize()


def _set_properties(hwnd, properties):
    with _property_store(hwnd) as (store, methods):
        set_value = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropVariant),
        )(methods[6])  # IPropertyStore::SetValue
        for property_id, text in properties:
            key = _PropertyKey(_APP_PROPERTIES, property_id)
            value = _PropVariant()  # VT_EMPTY clears the property.
            if text is not None:
                # SetValue copies the string before this Python-owned buffer goes out of scope.
                buffer = ctypes.create_unicode_buffer(text)
                value.type = 31  # VT_LPWSTR
                value.data[0] = ctypes.addressof(buffer)
            result = set_value(store, ctypes.byref(key), ctypes.byref(value))
            if result < 0:
                raise OSError(f"IPropertyStore::SetValue failed with HRESULT {result:#x}")


def _save_icon(icon):
    directory = app_directory().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "taskbar-waveform.ico"
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError("Cannot open the taskbar icon file")
    if not icon.pixmap(256, 256).save(file, "ICO"):
        file.cancelWriting()
        raise OSError("Cannot write the waveform ICO")
    if not file.commit():
        raise OSError("Cannot save the waveform ICO")
    return path


def _relaunch_command():
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    launcher = Path(__file__).resolve().parents[1] / "launch.pyw"
    return list2cmdline([str(windowed if windowed.is_file() else executable), str(launcher)])


def register_window(window):
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return None
    hwnd = None
    try:
        icon = _save_icon(window.windowIcon())
        hwnd = int(window.winId())
        # Windows refreshes the taskbar when the window AppUserModelID is set.
        _set_properties(hwnd, (
            (_RELAUNCH_COMMAND, _relaunch_command()),
            (_RELAUNCH_ICON, f"{icon},0"),
            (_RELAUNCH_NAME, window.windowTitle()),
            (_WINDOW_APP_ID, APP_ID),
        ))
        return hwnd
    except (OSError, ProfileError):
        if hwnd is not None:
            unregister_window(hwnd)
        _LOG.warning("Windows taskbar waveform metadata could not be set.")
        return None


def unregister_window(hwnd):
    try:
        _set_properties(hwnd, (
            (_RELAUNCH_COMMAND, None), (_RELAUNCH_ICON, None), (_RELAUNCH_NAME, None), (_WINDOW_APP_ID, None),
        ))
    except OSError:
        _LOG.warning("Windows taskbar waveform metadata could not be cleared.")

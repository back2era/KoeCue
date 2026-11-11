"""Local preferences for the interview panel."""
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from .config import PROVIDERS
from .glass import DEFAULT_THEME, THEMES
from .profiles import ProfileError, app_directory


@dataclass(frozen=True)
class Preferences:
    provider: str = "openai"
    audio_name: str = ""
    audio_loopback: bool = False
    auto_answer: bool = True
    theme: str = DEFAULT_THEME


def _store():
    return QSettings(str(app_directory() / "settings.ini"), QSettings.Format.IniFormat)


def load_preferences():
    store = _store()
    provider = store.value("provider", "openai", type=str)
    theme = store.value("appearance/theme", DEFAULT_THEME, type=str)
    preferences = Preferences(
        provider=provider if provider in PROVIDERS else "openai",
        audio_name=store.value("audio/name", "", type=str),
        audio_loopback=store.value("audio/loopback", False, type=bool),
        auto_answer=store.value("auto_answer", True, type=bool),
        theme=theme if theme in THEMES else DEFAULT_THEME,
    )
    if store.status() != QSettings.Status.NoError:
        raise ProfileError("无法读取上次的设置。")
    return preferences


def save_preferences(preferences):
    store = _store()
    store.setValue("provider", preferences.provider)
    store.setValue("audio/name", preferences.audio_name)
    store.setValue("audio/loopback", preferences.audio_loopback)
    store.setValue("auto_answer", preferences.auto_answer)
    store.setValue("appearance/theme", preferences.theme)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise ProfileError("无法保存面试助手设置。")

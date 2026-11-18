"""Local preferences for the interview panel."""
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from . import APP_NAME
from .answer_format import ANSWER_LEVELS, DEFAULT_ANSWER_LEVEL
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
    answer_level: str = DEFAULT_ANSWER_LEVEL
    model_choices: tuple[tuple[str, str], ...] = ()
    qwen_workspace: str = ""


def _store():
    return QSettings(str(app_directory() / "settings.ini"), QSettings.Format.IniFormat)


def load_preferences():
    store = _store()
    provider = store.value("provider", "openai", type=str)
    theme = store.value("appearance/theme", DEFAULT_THEME, type=str)
    answer_level = store.value("answer/level", DEFAULT_ANSWER_LEVEL, type=str)
    model_choices = tuple(
        (code, model) for code in PROVIDERS
        if (model := store.value(f"api/models/{code}", "", type=str).strip())
    )
    preferences = Preferences(
        provider=provider if provider in PROVIDERS else "openai",
        audio_name=store.value("audio/name", "", type=str),
        audio_loopback=store.value("audio/loopback", False, type=bool),
        auto_answer=store.value("auto_answer", True, type=bool),
        theme=theme if theme in THEMES else DEFAULT_THEME,
        answer_level=answer_level if answer_level in ANSWER_LEVELS else DEFAULT_ANSWER_LEVEL,
        model_choices=model_choices,
        qwen_workspace=store.value("api/qwen_workspace", "", type=str).strip(),
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
    store.setValue("answer/level", preferences.answer_level)
    models = dict(preferences.model_choices)
    for code in PROVIDERS:
        store.setValue(f"api/models/{code}", models.get(code, ""))
    store.setValue("api/qwen_workspace", preferences.qwen_workspace)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise ProfileError(f"无法保存 {APP_NAME} 设置。")

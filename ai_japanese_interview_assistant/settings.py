"""Local preferences for the interview panel."""
from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

from . import APP_NAME
from .answer_format import ANSWER_LEVELS
from .config import PROVIDERS
from .glass import DEFAULT_THEME, THEMES
from .profiles import ProfileError, app_directory
from .spoken_cues import CueOptions, DEFAULT_LEVEL, DEFAULT_MAX_ITEMS, MODES


@dataclass(frozen=True)
class Preferences:
    provider: str = "openai"
    audio_name: str = ""
    audio_loopback: bool = False
    auto_answer: bool = True
    theme: str = DEFAULT_THEME
    answer_level: str = DEFAULT_LEVEL
    model_choices: tuple[tuple[str, str], ...] = ()
    qwen_workspace: str = ""
    cue_options: CueOptions = field(default_factory=CueOptions)
    show_rescue_phrases: bool = True


def _store():
    return QSettings(str(app_directory() / "settings.ini"), QSettings.Format.IniFormat)


def _limit(store, key):
    try:
        value = store.value(key, DEFAULT_MAX_ITEMS, type=int)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITEMS
    return value if value in range(1, DEFAULT_MAX_ITEMS + 1) else DEFAULT_MAX_ITEMS


def load_preferences():
    store = _store()
    provider = store.value("provider", "openai", type=str)
    theme = store.value("appearance/theme", DEFAULT_THEME, type=str)
    answer_level = store.value("answer/level", DEFAULT_LEVEL, type=str)
    answer_mode = store.value("answer/mode", "short", type=str)
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
        answer_level=answer_level if answer_level in ANSWER_LEVELS else DEFAULT_LEVEL,
        model_choices=model_choices,
        qwen_workspace=store.value("api/qwen_workspace", "", type=str).strip(),
        cue_options=CueOptions(
            answer_mode if answer_mode in MODES else "short",
            _limit(store, "answer/max_keywords"), _limit(store, "answer/max_sentences"),
        ),
        show_rescue_phrases=store.value("answer/show_rescue_phrases", True, type=bool),
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
    store.setValue("answer/mode", preferences.cue_options.mode)
    store.setValue("answer/max_keywords", preferences.cue_options.max_keywords)
    store.setValue("answer/max_sentences", preferences.cue_options.max_sentences)
    store.setValue("answer/show_rescue_phrases", preferences.show_rescue_phrases)
    models = dict(preferences.model_choices)
    for code in PROVIDERS:
        store.setValue(f"api/models/{code}", models.get(code, ""))
    store.setValue("api/qwen_workspace", preferences.qwen_workspace)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise ProfileError(f"无法保存 {APP_NAME} 设置。")

"""Local preferences for the interview panel."""
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from . import APP_NAME
from .answer_format import ANSWER_LEVELS, DEFAULT_ANSWER_LEVEL
from .config import (
    DEFAULT_INTERVIEW_LANGUAGE, DEFAULT_TRANSLATION_LANGUAGES, INTERVIEW_LANGUAGES, PROVIDERS,
    TRANSLATION_LANGUAGES,
)
from .glass import DEFAULT_THEME, THEMES
from .profiles import ProfileError, app_directory
from .speech import SPEECH_MODELS


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
    interview_language: str = DEFAULT_INTERVIEW_LANGUAGE
    speech_model: str = ""
    translation_language: str | None = None
    answer_language: str | None = None
    speech_models_dir: str = ""


def _store():
    return QSettings(str(app_directory() / "settings.ini"), QSettings.Format.IniFormat)


def load_preferences():
    store = _store()
    provider = store.value("provider", "openai", type=str)
    theme = store.value("appearance/theme", DEFAULT_THEME, type=str)
    answer_level = store.value("answer/level", DEFAULT_ANSWER_LEVEL, type=str)
    language = store.value("interview/language", DEFAULT_INTERVIEW_LANGUAGE, type=str)
    if language not in INTERVIEW_LANGUAGES:
        language = DEFAULT_INTERVIEW_LANGUAGE
    default_translation = DEFAULT_TRANSLATION_LANGUAGES[language]
    translation = store.value("interview/translation_language", default_translation, type=str)
    answer = store.value("interview/answer_language", language, type=str)
    speech_model = store.value("asr/model", "", type=str)
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
        interview_language=language,
        speech_model=speech_model if speech_model in SPEECH_MODELS else "",
        speech_models_dir=store.value("asr/models_dir", "", type=str),
        translation_language=translation if translation in TRANSLATION_LANGUAGES or translation == "" else default_translation,
        answer_language=answer if answer in INTERVIEW_LANGUAGES else language,
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
    store.setValue("interview/language", preferences.interview_language)
    store.setValue("asr/model", preferences.speech_model)
    store.setValue("asr/models_dir", preferences.speech_models_dir)
    translation = preferences.translation_language
    if translation is None:
        translation = DEFAULT_TRANSLATION_LANGUAGES[preferences.interview_language]
    store.setValue("interview/translation_language", translation)
    store.setValue("interview/answer_language", preferences.answer_language or preferences.interview_language)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise ProfileError(f"无法保存 {APP_NAME} 设置。")

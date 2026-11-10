"""Small rotating log for fixed event names and durations only."""
from enum import StrEnum
import logging
from logging.handlers import RotatingFileHandler
from math import isfinite
from threading import Lock

from .profiles import ProfileError, app_directory


class Event(StrEnum):
    AUDIO_OPEN = "audio_open"
    AUDIO_CLOSE = "audio_close"
    AUDIO_ERROR = "audio_error"
    REALTIME_READY = "realtime_ready"
    REALTIME_END = "realtime_end"
    TRANSLATION_READY = "translation_ready"
    ANSWER_READY = "answer_ready"
    API_ERROR = "api_error"


class SessionLog:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(directory / "assistant.log", maxBytes=128 * 1024,
                                           backupCount=2, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger = logging.Logger("AI Japanese Interview Assistant", logging.INFO)
        self.logger.addHandler(self.handler)

    def record(self, event: Event, elapsed=None):
        if elapsed is not None and isfinite(elapsed):
            self.logger.info("%s elapsed_ms=%d", Event(event), round(elapsed * 1000))
        else:
            self.logger.info("%s", Event(event))

    def close(self):
        self.handler.close()


_lock = Lock()
_log = None


def record(event, elapsed=None):
    global _log
    try:
        with _lock:
            if _log is None:
                _log = SessionLog(app_directory())
        _log.record(event, elapsed)
    except (OSError, ProfileError):
        # A missing or unwritable diagnostics directory must not interrupt listening.
        pass

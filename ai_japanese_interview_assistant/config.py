"""Provider defaults shared by desktop and validation entry points."""
from dataclasses import dataclass


REALTIME_MODEL = "gpt-live-transcribe"
TEXT_MODEL = "gpt-6-luna"
REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"


@dataclass(frozen=True)
class Provider:
    label: str
    key_env: str
    url: str
    model: str


OPENAI = Provider("OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1/responses", TEXT_MODEL)
DEEPSEEK = Provider("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/responses", "deepseek-flash")
ANTHROPIC = Provider("Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages", "claude-haiku-5-5")
PROVIDERS = {"openai": OPENAI, "deepseek": DEEPSEEK, "anthropic": ANTHROPIC}

"""Provider defaults shared by desktop and validation entry points."""
from dataclasses import dataclass
import re


REALTIME_MODEL = "gpt-live-transcribe"
TEXT_MODEL = "gpt-6-luna"
REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"


@dataclass(frozen=True)
class Provider:
    label: str
    key_env: str
    url: str
    model: str
    alternatives: tuple[str, ...] = ()
    chat: bool = False
    models_url: str = ""
    model_pattern: str = ""

    @property
    def models(self):
        return (self.model, *self.alternatives)

    def endpoint(self, workspace=""):
        if self is QWEN and workspace:
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", workspace):
                raise ValueError("百炼工作空间 ID 格式不正确。")
            return f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
        return self.url


OPENAI = Provider(
    "OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1/responses", TEXT_MODEL,
    ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra"),
    models_url="https://api.openai.com/v1/models",
    model_pattern=r"gpt-6(?:\.\d+)?-(?:luna|sol|terra|astra)(?:-\d{4}-\d{2}-\d{2})?",
)
DEEPSEEK = Provider(
    "DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/responses", "deepseek-flash",
    ("deepseek-v4-pro",), models_url="https://api.deepseek.com/models",
    model_pattern=r"deepseek-(?:flash|v4-pro)",
)
ANTHROPIC = Provider(
    "Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages", "claude-haiku-5-5",
    ("claude-opus-5-5",), models_url="https://api.anthropic.com/v1/models", model_pattern=r"claude-[\w.-]+",
)
QWEN = Provider(
    "千问 · 阿里云百炼", "DASHSCOPE_API_KEY",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "qwen3.8-flash", ("qwen3.8-max",), chat=True,
)
KIMI = Provider(
    "Kimi · 月之暗面", "MOONSHOT_API_KEY", "https://api.moonshot.cn/v1/chat/completions",
    "kimi-k3.1-pro", ("kimi-k3.1-pro-highspeed", "kimi-k2.6"),
    chat=True, models_url="https://api.moonshot.cn/v1/models",
    model_pattern=r"(?:kimi-k[\w.-]+|moonshot-v1-[\w.-]+)",
)
GLM = Provider(
    "GLM · 智谱", "ZHIPUAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "glm-5.3", ("glm-5.3-flash",), chat=True,
)
MINIMAX = Provider(
    "MiniMax", "MINIMAX_API_KEY", "https://api.minimax.cn/v1/chat/completions",
    "MiniMax-M3.1-Flash", ("MiniMax-M3",), chat=True,
)
GEMINI = Provider(
    "Google Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "gemini-3.8-flash", chat=True, models_url="https://generativelanguage.googleapis.com/v1beta/openai/models",
    model_pattern=r"gemini-\d+(?:\.\d+)?-(?:flash(?:-lite)?|pro)(?:-(?:preview|latest|\d[\w.-]*))?",
)
PROVIDERS = {
    "openai": OPENAI, "deepseek": DEEPSEEK, "anthropic": ANTHROPIC, "qwen": QWEN,
    "kimi": KIMI, "glm": GLM, "minimax": MINIMAX, "gemini": GEMINI,
}

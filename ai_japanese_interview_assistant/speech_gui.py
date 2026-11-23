"""Speech engine selection and on-demand local model downloads."""
from threading import Event

import httpx
from PySide6.QtCore import QSignalBlocker, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .config import INTERVIEW_LANGUAGES
from .glass import GlassComboBox, glass_panel, plain_label
from .local_asr import LocalAsrError
from .local_models import DownloadCancelled, MANAGED_MODELS, download_model, model_installation, models_directory
from .speech import SPEECH_MODELS


SPEECH_GROUPS = (
    ("本地", (
        ("SenseVoice", ("sensevoice-int8", "sensevoice-fp32")),
        ("Qwen3-ASR", ("qwen3-asr-0.6b", "qwen3-asr-1.7b")),
        ("Whisper", ("local",)),
    )),
    ("云端", (
        ("Qwen ASR · 百炼", ("qwen-3.1", "qwen-3.0")),
        ("OpenAI", ("openai",)),
        ("豆包 · 火山引擎", ("doubao",)),
        ("DeepSeek", ("deepseek",)),
    )),
)


def display_size(size):
    return f"{size / 1_000_000_000:.2f} GB" if size >= 1_000_000_000 else f"{size / 1_000_000:.0f} MB"


class ModelDownload(QThread):
    progress = Signal(int)
    message = Signal(str)

    def __init__(self, directory, model, parent):
        super().__init__(parent)
        self.directory = directory
        self.model = model
        self.cancelled = Event()

    def run(self):
        percent = -1

        def progress(size):
            nonlocal percent
            updated = size * 100 // self.model.size
            if updated != percent:
                percent = updated
                self.progress.emit(percent)

        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(10)) as client:
                download_model(self.directory, self.model, client, cancelled=self.cancelled, progress=progress)
        except DownloadCancelled:
            self.message.emit("下载已取消。")
        except LocalAsrError as exc:
            self.message.emit(str(exc))
        else:
            self.message.emit(f"{self.model.label} 下载完成。")


class SpeechModelsPane(QWidget):
    idle = Signal()

    def __init__(self, cloud, parent=None):
        super().__init__(parent)
        self.cloud = cloud
        self.worker = None
        self.save_pending = False
        self.closing = False
        self.families = []
        self.family_buttons = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(plain_label("语音识别", "appTitle"))
        self.active = plain_label("", "muted")
        header.addWidget(self.active, 1)
        layout.addLayout(header)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        menu = glass_panel()
        menu_layout = QVBoxLayout(menu)
        menu_layout.setContentsMargins(12, 12, 12, 12)
        menu_layout.setSpacing(6)
        for group, families in SPEECH_GROUPS:
            menu_layout.addWidget(plain_label(group, "muted"))
            for name, codes in families:
                button = QPushButton(name)
                button.setCheckable(True)
                button.setProperty("nav", True)
                index = len(self.families)
                self.families.append((name, codes))
                self.family_buttons.addButton(button, index)
                menu_layout.addWidget(button)
        menu_layout.addStretch()
        columns.addWidget(menu)

        panel = glass_panel()
        detail = QVBoxLayout(panel)
        detail.setContentsMargins(18, 16, 18, 16)
        detail.setSpacing(10)
        self.title = plain_label("", "sectionTitle")
        detail.addWidget(self.title)
        self.variants = GlassComboBox()
        self.variants.setAccessibleName("模型版本")
        detail.addWidget(self.variants)
        self.languages = plain_label("", "muted")
        detail.addWidget(self.languages)
        self.state = plain_label("", "muted")
        detail.addWidget(self.state)
        detail.addWidget(cloud.speech_help)
        detail.addWidget(cloud.speech_key_row)
        self.directory_row = QWidget()
        directory_layout = QHBoxLayout(self.directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        self.directory = QLineEdit()
        self.directory.setReadOnly(True)
        self.directory.setAccessibleName("模型保存目录")
        self.choose_directory = QPushButton("更改目录")
        self.choose_directory.clicked.connect(self.pick_directory)
        directory_layout.addWidget(self.directory, 1)
        directory_layout.addWidget(self.choose_directory)
        detail.addWidget(self.directory_row)

        actions = QHBoxLayout()
        self.download = QPushButton("下载")
        self.download.clicked.connect(self.start_download)
        actions.addWidget(self.download)
        self.use = QPushButton("使用此模型")
        self.use.setObjectName("primaryAction")
        self.use.clicked.connect(self.apply_selection)
        actions.addWidget(self.use)
        actions.addStretch()
        detail.addLayout(actions)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setAccessibleName("模型下载进度")
        progress_row.addWidget(self.progress, 1)
        self.cancel = QPushButton("取消下载")
        self.cancel.clicked.connect(self.cancel_download)
        progress_row.addWidget(self.cancel)
        detail.addLayout(progress_row)
        self.message = plain_label("", "muted")
        self.message.hide()
        detail.addWidget(self.message)
        detail.addStretch()
        columns.addWidget(panel, 1)
        layout.addLayout(columns, 1)

        self.family_buttons.idClicked.connect(self.show_family)
        self.variants.currentIndexChanged.connect(self.refresh)
        cloud.speech_settings_changed.connect(self.refresh)
        cloud.idle.connect(self.save_if_ready)
        self.show_active()

    def show_active(self):
        code = self.cloud.speech_code
        for index, (_, codes) in enumerate(self.families):
            if code in codes:
                self.show_family(index, code)
                return
        self.show_family(0)

    def show_family(self, index, selected=None):
        name, codes = self.families[index]
        self.family_buttons.button(index).setChecked(True)
        model = MANAGED_MODELS.get(codes[0])
        self.title.setText(model.label if model and len(codes) == 1 else name)
        with QSignalBlocker(self.variants):
            self.variants.clear()
            for code in codes:
                model = MANAGED_MODELS.get(code)
                label = f"{model.label.split(' · ', 1)[1]} · {display_size(model.size)}" if model else SPEECH_MODELS[code].label
                self.variants.addItem(label, code)
            preferred = selected or self.cloud.speech_code
            self.variants.setCurrentIndex(max(0, self.variants.findData(preferred)))
        self.variants.setVisible(len(codes) > 1)
        self.refresh()

    def refresh(self):
        code = self.variants.currentData()
        if code is None:
            return
        speech = SPEECH_MODELS[code]
        model = MANAGED_MODELS.get(code)
        directory = models_directory(self.cloud.speech_models_dir)
        installation = model_installation(directory, model) if model else ""
        current = self.cloud.speech_code == code
        compatible = self.cloud.selected_language() in speech.languages
        configurable = self.cloud.can_configure_speech() and not self.closing
        active = self.cloud.selected_speech()
        self.active.setText(f"当前：{active.label}" if active else "尚未选择")
        self.languages.setText("支持 " + " / ".join(INTERVIEW_LANGUAGES[language] for language in speech.languages))
        self.directory.setText(str(directory))
        self.directory.setToolTip(str(directory))
        self.directory_row.setVisible(model is not None)
        self.choose_directory.setEnabled(configurable and self.worker is None)
        needs_download = model is not None and installation != "downloaded"
        self.download.setVisible(needs_download)
        download_label = "下载新版" if installation == "legacy" else "下载"
        if model and self.variants.count() == 1:
            download_label += f" · {display_size(model.size)}"
        self.download.setText(download_label)
        self.download.setEnabled(needs_download and self.worker is None and self.cloud.preferences_ready and not self.closing)
        available = model is None or bool(installation)
        self.use.setEnabled(configurable and compatible and not current and available)
        self.use.setText("使用中" if current and available else "使用此模型")
        self.cloud.speech_help.setVisible(current)
        show_key = current and self.cloud.speech_key_provider is not None
        self.cloud.speech_key_row.setVisible(show_key)
        if not compatible:
            status = "不支持当前识别语言"
        elif model:
            status = {"downloaded": "已下载", "legacy": "已安装旧版", "": "未下载"}[installation]
        else:
            status = ("API Key 已配置" if self.cloud.asr_key() else "等待配置 API Key") if current else "需要 API Key"
        self.state.setText(status)
        self.progress.setVisible(self.worker is not None)
        self.cancel.setVisible(self.worker is not None)

    def pick_directory(self):
        if not self.cloud.can_configure_speech() or self.worker is not None:
            return
        selected = QFileDialog.getExistingDirectory(self, "选择模型保存目录", self.directory.text())
        if selected:
            self.cloud.speech_models_dir = selected
            self.cloud.controls()
            self.cloud.persist_preferences()

    def apply_selection(self):
        if not self.use.isEnabled():
            return
        self.cloud.set_speech_model(self.variants.currentData())
        self.save_pending = True
        self.save_if_ready()

    def save_if_ready(self):
        if self.save_pending and self.cloud.can_configure_speech():
            self.save_pending = False
            self.cloud.persist_preferences()

    def start_download(self):
        if not self.download.isEnabled() or self.worker is not None:
            return
        model = MANAGED_MODELS[self.variants.currentData()]
        self.worker = ModelDownload(models_directory(self.cloud.speech_models_dir), model, self)
        self.progress.setValue(0)
        self.message.setText(f"正在下载 {model.label}…")
        self.message.show()
        self.cancel.setEnabled(True)
        self.worker.message.connect(self.message.setText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.download_finished)
        self.refresh()
        self.worker.start()

    def cancel_download(self):
        if self.worker is not None:
            self.cancel.setEnabled(False)
            self.worker.cancelled.set()

    def download_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.cloud.controls()
        self.idle.emit()

    def shutdown(self):
        self.closing = True
        self.cancel_download()
        return self.worker is None

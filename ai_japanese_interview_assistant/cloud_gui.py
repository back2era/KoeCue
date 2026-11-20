"""Consent-gated live bilingual interview tab."""
from dataclasses import dataclass
from html import escape
import asyncio
import os
import sys

from PySide6.QtCore import QPoint, QSignalBlocker, QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .answer_display import compact_annotations, paragraph_breaks
from .answer_format import ANSWER_LEVELS, DEFAULT_ANSWER_LEVEL
from .diagnostic import DeviceScan
from .config import DEEPSEEK, DEFAULT_INTERVIEW_LANGUAGE, INTERVIEW_LANGUAGES, OPENAI, PROVIDERS, QWEN
from .credentials import credential
from .glass import DEFAULT_THEME, THEMES, GlassComboBox, GlassDialog, glass_panel, plain_label
from .interview import Answer
from .live import ANSWER_PENDING, LiveWorker
from .local_asr import local_model_available
from .personal import PersonalInfo
from .profile_gui import PrivateIO, ProfileDialog
from .profiles import ProfileError
from .ruby_label import RubyLabel
from .services import TextService, client_for, error_message
from .settings import Preferences, load_preferences, save_preferences
from .speech import SPEECH_MODELS


class CaptionLabel(QLabel):
    def __init__(self, placeholder):
        super().__init__(placeholder)
        self.setObjectName("captionText")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMinimumHeight(34)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.placeholder = placeholder
        self.shown = ""
        self.target = ""
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.reveal_next)

    def set_caption(self, text, *, animate):
        if animate and text == self.target:
            return
        if not animate or not text.startswith(self.target):
            self.target = text
            self.shown = text
            self.timer.stop()
            self.setText(text or self.placeholder)
            return
        self.target = text
        if not self.shown and not self.timer.isActive():
            self.setText("")
        remaining = len(self.target) - len(self.shown)
        if remaining:
            self.timer.start(max(5, min(28, 420 // remaining)))
        else:
            self.timer.stop()

    def reveal_next(self):
        self.shown = self.target[:len(self.shown) + 1]
        self.setText(self.shown)
        if self.shown == self.target:
            self.timer.stop()


@dataclass
class Row:
    transcript: str = ""
    zh: str = ""
    finalized: bool = False
    asr: str = ""
    translation: str = ""
    answer: Answer | None = None
    answer_status: str = ""
    language: str = DEFAULT_INTERVIEW_LANGUAGE


class CloudPane(QWidget):
    idle = Signal()
    theme_changed = Signal(str)
    listening_state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.scan = None
        self.credential_worker = None
        self.settings_worker = None
        self.preferences = Preferences()
        self.preferences_ready = False
        self.model_choices = {}
        self.audio_selection = ("", False)
        self.vault_operation = ""
        self.vault_fields = ()
        self.text_key_provider = OPENAI
        self.speech_key_provider = None
        self.approved_facts = ()
        self.approved_personal = PersonalInfo()
        self.saved_personal = PersonalInfo()
        self.personal_busy = False
        self.reported_state = "idle"
        self.generation = 0
        self.session_id = 0
        self.capture_available = True
        self.state = "idle"
        self.closing = False
        self.close_save_attempted = False
        self.rows = {}
        self.rendered = []
        self.changed_rows = set()
        self.displayed_row = None
        self.preview_key = None
        self.preview_text = ""
        self.dirty = False

        self.source = GlassComboBox()
        self.source.setAccessibleName("音频来源")
        self.source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.refresh = QPushButton("刷新设备")
        self.theme = GlassComboBox()
        self.theme.setAccessibleName("界面主题")
        for theme_id, theme in THEMES.items():
            self.theme.addItem(theme.label, theme_id)
        self.theme.setCurrentIndex(self.theme.findData(DEFAULT_THEME))
        self.interview_language = GlassComboBox()
        self.interview_language.setAccessibleName("面试语言")
        self.interview_language.addItem("日语面试（带中文翻译）", "ja")
        self.interview_language.addItem("中文面试", "zh")
        self.answer_level = GlassComboBox()
        self.answer_level.setAccessibleName("AI 回答难度")
        for level in ANSWER_LEVELS:
            self.answer_level.addItem(level, level)
        self.answer_level.setCurrentIndex(self.answer_level.findData(DEFAULT_ANSWER_LEVEL))
        self.provider = GlassComboBox()
        self.provider.setAccessibleName("AI 回答服务商")
        for code, provider in PROVIDERS.items():
            self.provider.addItem(provider.label, code)
        self.model = GlassComboBox()
        self.model.setAccessibleName("文本模型")
        self.model.setEditable(True)
        self.model.setInsertPolicy(self.model.InsertPolicy.NoInsert)
        self.model.setSizeAdjustPolicy(self.model.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(18)
        self.model.lineEdit().setMaxLength(160)
        self.model.lineEdit().setPlaceholderText("输入模型 ID")
        self.set_model_options()
        self.workspace = QLineEdit()
        self.workspace.setAccessibleName("百炼北京工作空间 ID")
        self.workspace.setPlaceholderText("百炼北京工作空间 ID（可选）")
        self.workspace.setMaxLength(63)
        self.workspace.hide()
        self.model_refresh = QPushButton("刷新模型")
        self.model_refresh.setToolTip("从服务商获取模型列表。也可以直接输入模型 ID。")
        self.api_test = QPushButton("测试文本 API")
        self.api_test.setToolTip("向所选模型发送固定样例，检查文本 API。")
        self.api_status = plain_label("", "muted")
        self.api_status.hide()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setAccessibleName("AI 回答 API Key")
        self.key.setPlaceholderText("API Key")
        self.vault_button = self.make_vault_button()

        self.speech_model = GlassComboBox()
        self.speech_model.setAccessibleName("语音识别模型")
        self.speech_model.addItem("请选择语音识别模型", "")
        for code, model in SPEECH_MODELS.items():
            if code != "local" or not getattr(sys, "frozen", False):
                self.speech_model.addItem(model.label, code)
        self.speech_model.setCurrentIndex(self.speech_model.findData("openai"))
        self.speech_help = plain_label("", "muted")
        self.speech_key = QLineEdit()
        self.speech_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.speech_key.setAccessibleName("语音识别 API Key")
        self.speech_vault_button = self.make_vault_button(speech=True)
        self.speech_key_row = QWidget()
        speech_key_layout = QHBoxLayout(self.speech_key_row)
        speech_key_layout.setContentsMargins(0, 0, 0, 0)
        speech_key_layout.addWidget(self.speech_key, 1)
        speech_key_layout.addWidget(self.speech_vault_button)
        self.speech_key_row.hide()
        self.auto_answer = QCheckBox("自动为面试发言生成建议")
        self.auto_answer.setChecked(True)
        self.manage_facts = QPushButton("管理已核对事实")
        self.start = QPushButton("确认并开始云端监听")
        self.pause = QPushButton("暂停")
        self.stop = QPushButton("停止")
        self.retry = QPushButton("重试所选翻译")
        self.suggest = QPushButton("生成回答")
        self.copy = QPushButton("复制回答")
        self.asr_status = QLabel("转写未连接")
        self.text_status = QLabel("文本 API 未连接")
        self.audio_status = QLabel("音频未打开")
        for label in (self.asr_status, self.text_status, self.audio_status):
            label.setWordWrap(True)
        self.history = QTableWidget(0, 3)
        self.history.setAccessibleName("历史对话")
        self.history.setAlternatingRowColors(True)
        self.history.setShowGrid(False)
        self.history.verticalHeader().hide()
        self.history.setHorizontalHeaderLabels(["面试原文", "简体中文译文", "状态"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.history.setColumnWidth(2, 92)
        self.history.verticalHeader().setDefaultSectionSize(44)
        self.history.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerItem)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.empty_history = plain_label("识别到的语段会保留在这里", "muted")
        self.empty_history.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_history.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        empty_layout = QVBoxLayout(self.history.viewport())
        empty_layout.addWidget(self.empty_history)
        self.original = CaptionLabel("等待日语语音…")
        self.translated = CaptionLabel("等待中文译文…")
        self.live_caption = plain_label("", "captionText")
        self.live_caption.setAccessibleName("正在识别的日语")
        self.original_state = plain_label("", "captionState")
        self.translation_state = plain_label("", "captionState")
        self.answer_ja = RubyLabel()
        self.answer_zh = plain_label("", "answerTranslation")
        self.answer_zh.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer_translation_rule = self.rule()
        self.full_annotations = QPushButton("全部标注")
        self.full_annotations.setCheckable(True)
        self.full_annotations.setToolTip("切换重点标注和全部平假名、英文标注")
        self.answer_status = plain_label("", "muted")
        self.listening_badge = plain_label("", "listeningBadge")
        self.listening_badge.setWordWrap(False)
        self.input_summary = plain_label("", "muted")
        self.status_detail = plain_label("", "muted")
        self.capture_notice = plain_label("", "captionState")
        self.capture_notice.setAccessibleName("监听确认说明")
        self.capture_notice.hide()
        self.settings_toggle = QPushButton("设置")
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setToolTip("设置音源、服务商、模型与 API Key")
        self.latest = QPushButton("回到最新")
        self.start.setObjectName("primaryAction")
        self.build_layout()

        self.render_timer = QTimer(self)
        self.render_timer.setInterval(65)
        self.render_timer.timeout.connect(self.render_history)
        self.render_timer.start()
        self.refresh.clicked.connect(self.refresh_devices)
        self.source.currentIndexChanged.connect(self.source_changed)
        self.theme.currentIndexChanged.connect(lambda: self.theme_changed.emit(self.theme.currentData()))
        self.interview_language.currentIndexChanged.connect(self.select_row)
        self.answer_level.currentIndexChanged.connect(self.update_answer_level)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.speech_model.currentIndexChanged.connect(self.speech_changed)
        self.speech_key.textChanged.connect(self.controls)
        self.model.currentTextChanged.connect(self.model_changed)
        self.workspace.textChanged.connect(self.api_input_changed)
        self.model_refresh.clicked.connect(lambda: self.run_api_action(refresh=True))
        self.api_test.clicked.connect(lambda: self.run_api_action(refresh=False))
        self.auto_answer.toggled.connect(self.select_row)
        self.manage_facts.clicked.connect(self.open_profile)
        self.key.textChanged.connect(self.api_input_changed)
        self.start.clicked.connect(self.start_session)
        self.pause.clicked.connect(self.pause_session)
        self.stop.clicked.connect(self.stop_session)
        self.retry.clicked.connect(self.retry_translation)
        self.suggest.clicked.connect(self.request_answer)
        self.copy.clicked.connect(self.copy_answer)
        self.full_annotations.toggled.connect(self.render_answer)
        self.history.itemSelectionChanged.connect(self.select_row)
        self.history.itemClicked.connect(self.show_captions)
        self.settings_toggle.toggled.connect(self.toggle_settings)
        self.settings.finished.connect(lambda: self.settings_toggle.setChecked(False))
        self.settings.accepted.connect(self.persist_preferences)
        self.latest.clicked.connect(self.select_latest)
        self.run_settings_io(load_preferences, self.restore_preferences)
        self.refresh_devices()
        self.select_row()

    def build_layout(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        outer.addWidget(self.splitter, 1)

        live_card = glass_panel()
        layout = QVBoxLayout(live_card)
        layout.setContentsMargins(19, 15, 19, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(plain_label("实时字幕", "sectionTitle"), 1)
        header.addWidget(self.listening_badge)
        layout.addLayout(header)

        self.preview_card = glass_panel("glassInset")
        preview = QVBoxLayout(self.preview_card)
        preview.setContentsMargins(13, 8, 13, 9)
        preview.setSpacing(3)
        self.preview_title = plain_label("日语 · 识别中", "muted")
        preview.addWidget(self.preview_title)
        preview.addWidget(self.live_caption)
        self.preview_card.hide()
        layout.addWidget(self.preview_card)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("captionScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setMinimumHeight(125)
        layout.addWidget(self.scroll, 1)
        content = QWidget()
        content.setObjectName("captionContent")
        self.scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(0, 0, 4, 0)
        page.setSpacing(8)

        self.original_title = plain_label("日语原文", "muted")
        original_heading = QHBoxLayout()
        original_heading.addWidget(self.original_title, 1)
        original_heading.addWidget(self.original_state)
        page.addLayout(original_heading)
        page.addWidget(self.original)

        self.translation_panel = QWidget()
        translation = QVBoxLayout(self.translation_panel)
        translation.setContentsMargins(0, 0, 0, 0)
        translation.setSpacing(8)
        translation.addWidget(self.rule())
        translation_heading = QHBoxLayout()
        translation_heading.addWidget(plain_label("简体中文", "muted"), 1)
        translation_heading.addWidget(self.translation_state)
        translation.addLayout(translation_heading)
        translation.addWidget(self.translated)
        page.addWidget(self.translation_panel)

        answer_card = glass_panel("answerCard")
        answer_layout = QVBoxLayout(answer_card)
        answer_layout.setContentsMargins(15, 12, 15, 12)
        answer_layout.setSpacing(10)
        answer_heading = QHBoxLayout()
        answer_heading.addWidget(plain_label("AI 推荐回答", "sectionTitle"), 1)
        answer_heading.addWidget(self.full_annotations)
        answer_layout.addLayout(answer_heading)
        answer_layout.addWidget(self.answer_ja)
        answer_layout.addWidget(self.answer_translation_rule)
        answer_layout.addWidget(self.answer_zh)
        answer_layout.addWidget(self.answer_status)
        answer_actions = QHBoxLayout()
        answer_actions.addStretch(1)
        for button in (self.retry, self.suggest, self.copy):
            answer_actions.addWidget(button)
        answer_layout.addLayout(answer_actions)
        page.addWidget(answer_card)
        page.addStretch(1)
        self.splitter.addWidget(live_card)

        history_pane = glass_panel()
        history_layout = QVBoxLayout(history_pane)
        history_layout.setContentsMargins(17, 15, 17, 16)
        history_layout.setSpacing(12)
        history_heading = QHBoxLayout()
        history_heading.addWidget(plain_label("历史对话", "sectionTitle"), 1)
        history_heading.addWidget(self.latest)
        history_layout.addLayout(history_heading)
        self.history.setMinimumHeight(105)
        history_layout.addWidget(self.history, 1)
        self.splitter.addWidget(history_pane)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        bar = glass_panel("glassBar")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(16, 11, 13, 11)
        bar_layout.setSpacing(8)
        bar_layout.addWidget(self.capture_notice)
        footer = QHBoxLayout()
        bar_layout.addLayout(footer)
        info = QVBoxLayout()
        info.setSpacing(3)
        info.addWidget(self.input_summary)
        info.addWidget(self.status_detail)
        footer.addLayout(info, 1)
        for button in (self.settings_toggle, self.pause, self.stop, self.start):
            footer.addWidget(button)
        outer.addWidget(bar)
        self.build_settings()

    def make_vault_button(self, *, speech=False):
        button = QPushButton("Windows 凭据")
        button.setObjectName("vaultAction")
        menu = QMenu(button)
        for label, operation in (("读取已保存的 Key", "read"), ("保存当前 Key", "save"),
                                 ("删除已保存的 Key", "delete")):
            menu.addAction(label, lambda checked=False, op=operation: self.use_vault(op, speech=speech))
        button.setMenu(menu)
        return button

    def build_settings(self):
        self.settings = GlassDialog("设置", self)
        self.settings.resize(650, 635)
        content = QWidget()
        content.setObjectName("settingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.settings.body.addWidget(scroll, 1)
        options = glass_panel()
        option_layout = QVBoxLayout(options)
        option_layout.setContentsMargins(16, 12, 16, 12)
        for title, selector in (
            ("界面主题", self.theme), ("面试语言", self.interview_language), ("AI 日语回答难度", self.answer_level),
        ):
            row = QHBoxLayout()
            row.addWidget(plain_label(title, "sectionTitle"), 1)
            row.addWidget(selector)
            option_layout.addLayout(row)
        answer_options = QHBoxLayout()
        answer_options.addWidget(self.auto_answer, 1)
        answer_options.addWidget(self.manage_facts)
        option_layout.addLayout(answer_options)
        content_layout.addWidget(options)
        card = glass_panel()
        settings = QVBoxLayout(card)
        settings.setContentsMargins(16, 14, 16, 14)
        settings.setSpacing(9)
        settings.addWidget(plain_label("音频来源", "sectionTitle"))
        source = QHBoxLayout()
        source.addWidget(self.source, 1)
        source.addWidget(self.refresh)
        settings.addLayout(source)
        settings.addWidget(plain_label("系统音频会包含同一播放设备上的其他声音。", "muted"))
        settings.addWidget(self.rule())
        settings.addWidget(plain_label("语音识别", "sectionTitle"))
        settings.addWidget(self.speech_model)
        settings.addWidget(self.speech_help)
        settings.addWidget(self.speech_key_row)
        settings.addWidget(self.rule())
        settings.addWidget(plain_label("AI 回答与翻译", "sectionTitle"))
        key_row = QHBoxLayout()
        key_row.addWidget(self.provider)
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.vault_button)
        settings.addLayout(key_row)
        settings.addWidget(self.workspace)
        model_row = QHBoxLayout()
        model_row.addWidget(plain_label("文本模型", "muted"))
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.model_refresh)
        model_row.addWidget(self.api_test)
        settings.addLayout(model_row)
        settings.addWidget(self.api_status)
        content_layout.addWidget(card)
        content_layout.addStretch()
        done = QPushButton("完成")
        done.setObjectName("primaryAction")
        done.clicked.connect(self.settings.accept)
        self.settings.body.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        for button in self.settings.findChildren(QPushButton):
            button.setAutoDefault(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width, height = event.size().width(), event.size().height()
        side_by_side = width >= 850 or (width >= 720 and height < 550)
        orientation = Qt.Orientation.Horizontal if side_by_side else Qt.Orientation.Vertical
        if self.splitter.orientation() != orientation or not event.oldSize().isValid():
            scroll = self.history.verticalScrollBar()
            following = self.rendered and self.history.currentRow() == len(self.rendered) - 1
            following = following and scroll.value() == scroll.maximum()
            self.splitter.setOrientation(orientation)
            length = width if orientation == Qt.Orientation.Horizontal else height - 64
            self.splitter.setSizes([length * 3 // 5, length * 2 // 5])
            if following:
                QTimer.singleShot(0, self.history, self.history.scrollToBottom)

    @staticmethod
    def rule():
        line = QFrame()
        line.setObjectName("captionRule")
        line.setFixedHeight(1)
        return line

    def toggle_settings(self, visible):
        if visible and not self.settings.testAttribute(Qt.WidgetAttribute.WA_Moved):
            live = self.splitter.widget(0)
            anchor = live.mapToGlobal(QPoint(0, 0))
            available = self.screen().availableGeometry()
            width = self.settings.frameGeometry().width()
            height = self.settings.frameGeometry().height()
            x = anchor.x()
            if self.splitter.orientation() == Qt.Orientation.Vertical:
                right = live.mapToGlobal(QPoint(live.width(), 0)).x() + 20
                if right + width <= available.right():
                    x = right
                elif x - width - 20 >= available.left():
                    x -= width + 20
            self.settings.move(
                max(available.left(), min(x, available.right() - width)),
                max(available.top(), min(anchor.y(), available.bottom() - height)),
            )
        self.settings.setVisible(visible)
        if visible:
            self.settings.raise_()
            self.settings.activateWindow()

    def show_captions(self):
        self.scroll.verticalScrollBar().setValue(0)

    def source_changed(self):
        device = self.source.currentData()
        self.audio_selection = (device.name, device.loopback) if device else ("", False)
        self.controls()

    def refresh_devices(self):
        with QSignalBlocker(self.source):
            self.source.clear()
        self.scan = DeviceScan(self)
        self.scan.result.connect(self.set_devices)
        self.scan.failed.connect(self.asr_status.setText)
        self.scan.finished.connect(self.scan_finished)
        self.controls()
        self.scan.start()

    def set_devices(self, devices):
        with QSignalBlocker(self.source):
            self.source.addItem("选择音频来源", None)
            for device in devices:
                kind = "系统播放" if device.loopback else "麦克风 / 输入"
                self.source.addItem(f"{kind} · {device.name} · #{device.index}", device)
        self.restore_audio_source()
        if not devices:
            self.asr_status.setText("未找到可用的 WASAPI 输入")

    def restore_audio_source(self):
        matches = []
        for index in range(1, self.source.count()):
            device = self.source.itemData(index)
            if (device.name, device.loopback) == self.audio_selection:
                matches.append(index)
        with QSignalBlocker(self.source):
            self.source.setCurrentIndex(matches[0] if len(matches) == 1 else 0)

    def scan_finished(self):
        self.scan.deleteLater()
        self.scan = None
        self.controls()
        self.idle.emit()

    def api_key(self):
        return self.key.text().strip() or os.environ.get(self.selected_provider().key_env, "").strip()

    def selected_provider(self):
        return PROVIDERS[self.provider.currentData()]

    def selected_speech(self):
        return SPEECH_MODELS.get(self.speech_model.currentData())

    def asr_key(self):
        speech = self.selected_speech()
        if speech is None or speech.provider is None:
            return ""
        if speech.provider is self.selected_provider():
            return self.api_key()
        return self.speech_key.text().strip() or os.environ.get(speech.provider.key_env, "").strip()

    def selected_language(self):
        return self.interview_language.currentData()

    def selected_model(self):
        return self.model.currentText().strip() or self.selected_provider().model

    def set_model_options(self, additional=()):
        code = self.provider.currentData()
        provider = self.selected_provider()
        selected = self.model_choices.get(code, provider.model)
        models = list(dict.fromkeys((*provider.models, *additional, selected)))
        with QSignalBlocker(self.model):
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentText(selected)

    def model_changed(self, value):
        code = self.provider.currentData()
        value = value.strip()
        if value and value != self.selected_provider().model:
            self.model_choices[code] = value
        else:
            self.model_choices.pop(code, None)
        self.api_input_changed()

    def api_input_changed(self):
        self.api_status.hide()
        self.controls()

    @Slot(str)
    def show_api_status(self, message):
        self.api_status.setText(message)
        self.api_status.show()

    def endpoint_valid(self):
        try:
            self.selected_provider().endpoint(self.workspace.text().strip())
        except ValueError:
            return False
        return True

    def run_api_action(self, *, refresh):
        button = self.model_refresh if refresh else self.api_test
        if not button.isEnabled():
            return
        provider, key = self.selected_provider(), self.api_key()
        model, workspace = self.selected_model(), self.workspace.text().strip()
        language = self.selected_language()

        async def request():
            async with client_for(key, provider) as client:
                service = TextService(client, provider, model=model, workspace=workspace)
                if refresh:
                    return await service.list_models()
                await service.check_connection(language=language)

        def operation():
            try:
                return asyncio.run(request())
            except Exception as exc:
                raise ProfileError(error_message(exc)) from exc

        self.show_api_status("正在读取模型…" if refresh else "正在测试文本 API…")
        self.run_settings_io(operation, self.api_action_finished, self.show_api_status)

    @Slot(object)
    def api_action_finished(self, models):
        if models is None:
            self.show_api_status("连接测试通过，已收到完整译文。")
        else:
            self.set_model_options(models)
            self.show_api_status(f"已刷新 {len(models)} 个文本模型。" if models
                                 else "未发现可列出的文本模型。可继续手动输入模型 ID。")

    def provider_changed(self):
        if self.state != "idle":
            self.stop_session()
        provider = self.selected_provider()
        self.set_model_options()
        self.workspace.setVisible(provider is QWEN)
        self.api_status.hide()
        self.approved_facts = ()
        self.approved_personal = PersonalInfo()
        self.text_status.setText(f"{provider.label} 文本 API 未连接")
        self.speech_changed(load_text_key=True)

    def speech_changed(self, _index=None, *, load_text_key=False):
        speech = self.selected_speech()
        provider = self.selected_provider()
        speech_provider = speech.provider if speech and speech.provider is not provider else None
        speech_key_changed = speech_provider is not self.speech_key_provider
        previous = {
            old: (field.text(), field.isModified())
            for old, field in ((self.text_key_provider, self.key), (self.speech_key_provider, self.speech_key))
            if old is not None and field.text()
        }
        for old, new, field in ((self.text_key_provider, provider, self.key),
                                (self.speech_key_provider, speech_provider, self.speech_key)):
            if old is not new:
                value, modified = previous.get(new, ("", False))
                with QSignalBlocker(field):
                    field.setText(value)
                    field.setModified(modified)
            if new is not None:
                field.setPlaceholderText(f"{new.label} API Key")
        self.text_key_provider = provider
        self.speech_key_provider = speech_provider
        self.speech_key_row.setVisible(speech_provider is not None)
        self.asr_status.setText("转写未连接" if speech else "请选择语音识别模型")
        if self.preferences_ready and not self.closing:
            if load_text_key:
                self.use_vault("read", all_missing=True)
            elif speech_key_changed and speech_provider is not None and not self.speech_key.text():
                self.use_vault("read", speech=True)
        self.controls()

    def controls(self):
        idle = (self.worker is None and self.scan is None and self.credential_worker is None
                and self.settings_worker is None and not self.closing)
        configurable = idle and self.state != "paused"
        self.theme.setEnabled(self.preferences_ready and not self.closing)
        language = self.selected_language()
        self.answer_level.setEnabled(language == "ja" and self.preferences_ready and not self.closing)
        self.interview_language.setEnabled(configurable and self.preferences_ready and self.state == "idle")
        self.history.setColumnHidden(1, language == "zh")
        for widget in (self.source, self.refresh, self.provider, self.model, self.workspace, self.key,
                       self.vault_button, self.auto_answer, self.speech_model, self.speech_key,
                       self.speech_vault_button):
            widget.setEnabled(configurable)
        self.manage_facts.setEnabled(configurable and self.state == "idle" and self.preferences_ready)
        if self.state != self.reported_state:
            self.reported_state = self.state
            self.listening_state_changed.emit(self.state)
        endpoint_valid = self.endpoint_valid()
        self.workspace.setToolTip("" if endpoint_valid else "请输入有效的百炼北京工作空间 ID。")
        api_ready = bool(configurable and self.api_key() and endpoint_valid)
        self.api_test.setEnabled(api_ready)
        self.model_refresh.setEnabled(api_ready and bool(self.selected_provider().models_url))
        speech = self.selected_speech()
        provider = self.selected_provider()
        asr_issue = ""
        if speech is None:
            asr_issue = "请选择语音识别模型。"
            help_text = asr_issue
        elif language not in speech.languages:
            asr_issue = f"{speech.label} 不支持当前面试语言。"
            help_text = asr_issue
        elif speech.provider is None:
            help_text = "音频在本机转写，需自行安装本地组件和模型。"
        else:
            if not self.asr_key():
                asr_issue = f"请填写 {speech.provider.label} 的 API Key。"
            mode_hint = "停顿后提交整段音频。" if speech.provider is DEEPSEEK else "边听边显示实时字幕。"
            if speech.provider is provider:
                help_text = f"{mode_hint} 与 AI 回答共用 {provider.label} 的 Key。"
            else:
                help_text = f"{mode_hint} 使用 {speech.provider.label} 的 Key。"
        self.speech_help.setText(help_text)
        ready = bool(self.source.currentData() and self.api_key() and endpoint_valid and not asr_issue)
        can_start = (idle and ready and self.capture_available and not self.personal_busy
                     and self.state in {"idle", "paused"})
        self.start.setEnabled(can_start)
        self.start.setToolTip(asr_issue)
        mode = "本地转写" if speech and speech.provider is None else "云端监听"
        self.start.setText(("恢复" if self.state == "paused" else "确认并开始") + mode)
        data_route = (f"所选音频会发送至 {speech.provider.label} 转写。"
                      if speech and speech.provider else "音频在本机转写。")
        profile_notice = (f"生成回答时会向 {provider.label} 发送相关面试资料。"
                          if self.saved_personal or self.approved_facts else "")
        self.capture_notice.setText(
            f"开始前请确认已取得必要同意。{data_route}{INTERVIEW_LANGUAGES[language]}文字可发送至 {provider.label}。"
            f"{profile_notice}" if speech else asr_issue
        )
        self.capture_notice.setVisible(can_start and self.state == "idle")
        self.pause.setEnabled(self.state == "active")
        self.stop.setEnabled(self.state in {"active", "paused"})
        key, row = self.current_row()
        retryable = (row and row.language == "ja" and row.finalized and row.transcript
                     and row.translation not in {"翻译中", "已翻译"})
        self.retry.setEnabled(bool(self.can_send_row(key) and retryable))
        self.suggest.setEnabled(bool(self.can_send_row(key) and row and row.finalized and
                                     row.transcript and row.answer_status != ANSWER_PENDING))
        self.copy.setEnabled(bool(row and row.answer))
        self.latest.setEnabled(bool(self.rendered))
        self.refresh_status()

    def refresh_status(self):
        audio = self.audio_status.text()
        listening = self.state == "active" and audio == "音频 · 正在监听"
        if listening:
            badge, tone = "● 正在监听", "live"
        elif self.state == "active" and audio == "音频 · 当前没有输入帧":
            badge, tone = "等待声音", "neutral"
        elif self.state == "active":
            badge, tone = "正在启动", "pending"
        elif self.state == "paused":
            badge, tone = "已暂停", "pending"
        else:
            badge, tone = "待开始", "neutral"
        if self.listening_badge.text() != badge:
            self.listening_badge.setText(badge)
            self.listening_badge.setProperty("tone", tone)
            self.listening_badge.style().unpolish(self.listening_badge)
            self.listening_badge.style().polish(self.listening_badge)
        device = self.source.currentData()
        if device is None:
            source = "上次音源不可用，请重新选择" if self.audio_selection[0] and self.scan is None else "请选择音源"
        else:
            source = "系统音频" if device.loopback else "麦克风"
        language = self.selected_language()
        language_name = INTERVIEW_LANGUAGES[language]
        self.preview_title.setText(f"{language_name} · 识别中")
        self.live_caption.setAccessibleName(f"正在识别的{language_name}")
        self.input_summary.setText(f"{source} · {'日语 → 中文' if language == 'ja' else '中文面试'}")
        self.status_detail.setText("  ·  ".join((self.asr_status.text(), self.text_status.text(), audio)))

    def start_session(self):
        if not self.start.isEnabled():
            return
        if self.state != "paused":
            self.session_id += 1
            self.approved_personal = self.saved_personal
        self.generation += 1
        self.state = "active"
        self.persist_preferences()
        self.settings_toggle.setChecked(False)
        self.show_captions()
        self.asr_status.setText("正在启动转写")
        self.audio_status.setText("正在等待音频设备")
        self.worker = LiveWorker(self.generation, self.source.currentData(), self.api_key(), self,
                                 session_id=self.session_id, auto_answer=self.auto_answer.isChecked(),
                                 facts=self.approved_facts, personal_info=self.approved_personal,
                                 provider=self.selected_provider(), answer_level=self.answer_level.currentData(),
                                 model=self.selected_model(), workspace=self.workspace.text().strip(),
                                 language=self.selected_language(), speech_model=self.speech_model.currentData(),
                                 speech_key=self.asr_key())
        self.worker.status.connect(self.set_status)
        self.worker.partial_transcript.connect(self.add_partial_transcript)
        self.worker.transcript.connect(self.add_transcript)
        self.worker.order.connect(self.set_order)
        self.worker.translation.connect(self.add_translation)
        self.worker.answer.connect(self.add_answer)
        self.worker.finished.connect(self.worker_finished)
        self.controls()
        self.worker.start()

    def update_answer_level(self):
        if self.worker is not None:
            self.worker.answer_level = self.answer_level.currentData()

    def set_status(self, service, value):
        if self.state == "active":
            statuses = {"asr": self.asr_status, "text": self.text_status, "audio": self.audio_status}
            statuses[service].setText(value)
            self.refresh_status()

    def pause_session(self):
        if self.worker is not None:
            self.state = "paused"
            self.worker.stop()
            self.clear_live_caption()
            self.asr_status.setText("已暂停")
            self.text_status.setText("文本请求已暂停")
            self.audio_status.setText("音频已暂停")
            self.controls()

    def stop_session(self):
        self.state = "idle"
        self.clear_live_caption()
        if self.worker is not None:
            self.worker.stop()
        self.approved_facts = ()
        self.approved_personal = PersonalInfo()
        self.asr_status.setText("已停止")
        self.text_status.setText("文本 API 未连接")
        self.audio_status.setText("音频未打开")
        self.controls()

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.clear_live_caption()
        if self.state == "active":
            self.state = "idle"
            self.approved_facts = ()
            self.approved_personal = PersonalInfo()
            if self.audio_status.text().startswith(("正在", "音频 ·")):
                self.audio_status.setText("音频已停止")
        for key, row in self.rows.items():
            if row.translation == "翻译中":
                row.translation = "翻译已取消"
                self.mark_changed(key)
            if row.answer_status == ANSWER_PENDING:
                row.answer_status = "回答已取消"
                self.mark_changed(key)
        self.controls()
        self.idle.emit()

    @Slot(object)
    def add_partial_transcript(self, data):
        key, part = data
        if (self.state != "active" or key[:2] != (self.session_id, self.generation)
                or key in self.rows or not part.text.strip()):
            return
        if key != self.preview_key:
            self.preview_key, self.preview_text = key, ""
        if part.text != self.preview_text:
            self.preview_text = part.text
            self.live_caption.setText(part.text if len(part.text) <= 84 else "…" + part.text[-84:])
            self.preview_card.show()

    def clear_live_caption(self):
        self.preview_key, self.preview_text = None, ""
        self.live_caption.clear()
        self.preview_card.hide()

    @Slot(object)
    def add_transcript(self, data):
        key, part = data
        if (self.state != "active" or key[:2] != (self.session_id, self.generation)
                or key in self.rows or not (part.final or part.failed)):
            return
        if key == self.preview_key:
            self.clear_live_caption()
        language = self.selected_language()
        if part.failed:
            self.rows[key] = Row(asr="转写失败", language=language)
        elif part.text:
            self.rows[key] = Row(transcript=part.text, finalized=True, language=language,
                                 asr=f"{INTERVIEW_LANGUAGES[language]}定稿")
        else:
            return
        self.mark_changed(key)

    def set_order(self, order):
        if self.state != "active":
            return
        current = {key: self.rows[key] for key in order if key in self.rows}
        if not current:
            return
        self.rows = {key: row for key, row in self.rows.items() if key not in current} | current
        self.dirty = True

    def add_translation(self, key, text, state):
        if self.state != "active" or key not in self.rows:
            return
        row = self.rows[key]
        if row.language != "ja":
            return
        row.zh, row.translation = text, state
        self.mark_changed(key)

    @Slot(object, object, str, bool)
    def add_answer(self, key, answer, state, scoped):
        shared = self.approved_facts or self.approved_personal
        if self.can_send_row(key) and key in self.rows and (not scoped or shared):
            row = self.rows[key]
            row.answer, row.answer_status = answer, state
            self.mark_changed(key)

    def current_row(self):
        index = self.history.currentRow()
        if 0 <= index < len(self.rendered):
            key = self.rendered[index]
            return key, self.rows.get(key)
        return None, None

    def can_send_row(self, key):
        return self.state == "active" and key is not None and key[0] == self.session_id

    def retry_translation(self):
        key, row = self.current_row()
        if self.worker is not None and self.retry.isEnabled() and row and self.can_send_row(key):
            self.worker.dispatch(self.worker.start_translation, key, row.transcript)

    def request_answer(self):
        key, row = self.current_row()
        if self.worker is not None and self.can_send_row(key) and row and row.finalized and row.transcript:
            self.worker.dispatch(self.worker.start_answer, key, row.transcript)

    def copy_answer(self):
        _, row = self.current_row()
        if row and row.answer:
            QApplication.clipboard().setText("\n\n".join(part for part in (row.answer.ja, row.answer.zh) if part))

    def open_profile(self):
        dialog = ProfileDialog(self.approved_facts, self.window())
        dialog.authorized.connect(self.set_approved)
        dialog.changed.connect(lambda facts: self.revoke_profile())
        dialog.exec()
        dialog.deleteLater()

    def set_approved(self, facts):
        self.approved_facts = facts
        self.controls()

    @Slot(object)
    def set_saved_personal(self, info):
        self.saved_personal = info
        self.controls()

    @Slot(bool)
    def set_personal_busy(self, busy):
        self.personal_busy = busy
        self.controls()

    def revoke_profile(self):
        self.approved_personal = PersonalInfo()
        self.set_approved(())
        if self.worker is not None:
            self.worker.revoke_profile()
            for key, row in self.rows.items():
                if row.answer_status == ANSWER_PENDING:
                    row.answer_status = "回答已取消"
                    self.mark_changed(key)

    def use_vault(self, operation, *, speech=False, all_missing=False):
        if self.credential_worker is not None or self.settings_worker is not None:
            return
        bindings = ((self.key, self.text_key_provider), (self.speech_key, self.speech_key_provider))
        if all_missing:
            fields = tuple((field, provider) for field, provider in bindings
                           if provider and not field.text())
        else:
            field, provider = bindings[int(speech)]
            fields = ((field, provider),) if provider else ()
        if not fields:
            return
        requests = tuple((field.text().strip() if operation == "save" else "", provider)
                         for field, provider in fields)
        self.vault_operation = operation
        self.vault_fields = fields
        self.credential_worker = PrivateIO(
            lambda: tuple(credential(operation, key, provider) for key, provider in requests), self,
        )
        self.credential_worker.result.connect(self.vault_result)
        self.credential_worker.failed.connect((self.asr_status if speech else self.text_status).setText)
        self.credential_worker.finished.connect(self.vault_finished)
        self.controls()
        self.credential_worker.start()

    @Slot(object)
    def vault_result(self, values):
        operation = self.vault_operation
        for (field, provider), value in zip(self.vault_fields, values):
            is_text = field is self.key
            current = self.text_key_provider if is_text else self.speech_key_provider
            if provider is not current:
                continue
            if operation == "read" and value:
                field.setText(value)
            elif operation == "delete":
                field.clear()
            elif operation == "save":
                field.setModified(False)
            label = self.text_status if is_text else self.asr_status
            status = {"read": "已读取已保存的 Key" if value else "未找到已保存的 Key",
                      "save": "Key 已保存到 Windows 凭据管理器", "delete": "已清除保存的 Key"}[operation]
            label.setText(f"{provider.label} · {status}")

    def vault_finished(self):
        self.credential_worker.deleteLater()
        self.credential_worker = None
        self.vault_operation = ""
        self.vault_fields = ()
        self.controls()
        self.idle.emit()

    def run_settings_io(self, operation, receive, failed=None):
        self.settings_worker = PrivateIO(operation, self)
        self.settings_worker.result.connect(receive)
        self.settings_worker.failed.connect(failed or self.text_status.setText)
        self.settings_worker.finished.connect(self.settings_finished)
        self.controls()
        self.settings_worker.start()

    @Slot(object)
    def restore_preferences(self, preferences):
        self.preferences = preferences
        self.model_choices = dict(preferences.model_choices)
        self.workspace.setText(preferences.qwen_workspace)
        self.audio_selection = (preferences.audio_name, preferences.audio_loopback)
        with QSignalBlocker(self.provider):
            self.provider.setCurrentIndex(self.provider.findData(preferences.provider))
        speech_code = preferences.speech_model
        if not speech_code:
            if preferences.provider == "openai":
                speech_code = "openai"
            elif not getattr(sys, "frozen", False) and local_model_available():
                speech_code = "local"
        with QSignalBlocker(self.speech_model):
            self.speech_model.setCurrentIndex(max(0, self.speech_model.findData(speech_code)))
        self.auto_answer.setChecked(preferences.auto_answer)
        self.theme.setCurrentIndex(self.theme.findData(preferences.theme))
        self.answer_level.setCurrentIndex(self.answer_level.findData(preferences.answer_level))
        self.interview_language.setCurrentIndex(self.interview_language.findData(preferences.interview_language))
        self.restore_audio_source()

    def persist_preferences(self):
        if self.settings_worker is not None or self.credential_worker is not None:
            return
        preferences = Preferences(
            self.provider.currentData(), *self.audio_selection, self.auto_answer.isChecked(), self.theme.currentData(),
            self.answer_level.currentData(),
            tuple((code, self.model_choices[code]) for code in PROVIDERS if code in self.model_choices),
            self.workspace.text().strip(),
            self.selected_language(),
            self.speech_model.currentData(),
        )
        changed = preferences != self.preferences
        keys = tuple((provider, field.text().strip())
                     for provider, field in ((self.text_key_provider, self.key),
                                             (self.speech_key_provider, self.speech_key))
                     if provider and field.isModified() and field.text().strip())
        if not changed and not keys:
            return

        def save():
            if changed:
                save_preferences(preferences)
            for provider, key in keys:
                credential("save", key, provider)
            return preferences

        self.run_settings_io(save, self.preferences_saved)

    @Slot(object)
    def preferences_saved(self, preferences):
        self.preferences = preferences
        self.key.setModified(False)
        self.speech_key.setModified(False)

    def settings_finished(self):
        self.settings_worker.deleteLater()
        self.settings_worker = None
        if not self.preferences_ready:
            self.preferences_ready = True
            if not self.closing:
                self.provider_changed()
        self.controls()
        self.idle.emit()

    def mark_changed(self, key):
        self.changed_rows.add(key)
        self.dirty = True

    def select_latest(self):
        if self.rendered:
            self.history.selectRow(len(self.rendered) - 1)
            self.history.scrollToBottom()
            self.show_captions()

    def render_history(self):
        if not self.dirty:
            return
        self.dirty = False
        changed, self.changed_rows = self.changed_rows, set()
        selected, _ = self.current_row()
        previous = self.rendered
        scroll = self.history.verticalScrollBar()
        position = scroll.value()
        top_row = previous[position] if position < len(previous) else None
        following_latest = not previous or (position == scroll.maximum() and selected == previous[-1])
        self.history.blockSignals(True)
        self.rendered = list(self.rows)
        self.empty_history.setVisible(not self.rendered)
        positions = {key: index for index, key in enumerate(self.rendered)}
        if len(previous) != len(self.rendered):
            self.history.setRowCount(len(self.rendered))
        for index, (key, row) in enumerate(self.rows.items()):
            if key not in changed and index < len(previous) and previous[index] == key:
                continue
            statuses = " · ".join(filter(None, (row.asr, row.translation, row.answer_status)))
            for column, value in enumerate((row.transcript, row.zh, statuses)):
                cell = self.history.item(index, column)
                if cell is None:
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(f"<qt>{escape(value)}</qt>" if value else "")
                    self.history.setItem(index, column, cell)
                elif cell.text() != value:
                    cell.setText(value)
                    cell.setToolTip(f"<qt>{escape(value)}</qt>" if value else "")
        target = self.rendered[-1] if self.rendered and (following_latest or selected not in positions) else selected
        if target in positions and self.history.currentRow() != positions[target]:
            self.history.selectRow(positions[target])
        if following_latest:
            self.history.scrollToBottom()
        else:
            scroll.setValue(positions.get(top_row, position))
        self.history.blockSignals(False)
        if target != selected or target in changed:
            self.select_row()

    def select_row(self):
        key, row = self.current_row()
        changed = key != self.displayed_row
        if changed:
            with QSignalBlocker(self.full_annotations):
                self.full_annotations.setChecked(False)
        language = row.language if row else self.selected_language()
        language_name = INTERVIEW_LANGUAGES[language]
        self.original_title.setText(f"{language_name}原文")
        self.original.placeholder = f"等待{language_name}语音…"
        self.translation_panel.setVisible(language == "ja")
        self.retry.setVisible(language == "ja")
        animate = bool(self.can_send_row(key) and self.rendered and key == self.rendered[-1])
        for widget, value in ((self.original, row.transcript if row else ""), (self.translated, row.zh if row else "")):
            if changed:
                widget.set_caption("", animate=False)
            widget.set_caption(value, animate=animate and widget is self.translated)
        self.displayed_row = key
        self.original_state.setText(row.asr if row else "")
        translation = row.translation if row else ""
        self.translation_state.setText(translation)
        self.render_answer()
        self.controls()

    def render_answer(self):
        _, row = self.current_row()
        answer = row.answer if row else None
        language = row.language if row else self.selected_language()
        if answer and language == "ja":
            compact = compact_annotations(answer.ja, answer.annotations, answer.highlights)
            expanded = self.full_annotations.isChecked()
            self.full_annotations.setVisible(len(compact) < len(answer.annotations))
            self.full_annotations.setText("收起标注" if expanded else "全部标注")
            self.answer_ja.set_answer(
                answer.ja, answer.annotations if expanded else compact,
                highlights=answer.highlights, paragraph_breaks=paragraph_breaks(answer.ja),
            )
        elif answer:
            self.full_annotations.hide()
            self.answer_ja.set_answer(answer.zh, paragraph_breaks=paragraph_breaks(answer.zh))
        else:
            self.full_annotations.hide()
            name = INTERVIEW_LANGUAGES[language]
            placeholder = (f"每段发言识别完成后会自动生成{name}回应建议。" if self.auto_answer.isChecked()
                           else f"选中字幕后可生成{name}参考回答。")
            self.answer_ja.set_answer(placeholder)
        self.answer_zh.setText(answer.zh if answer else "")
        show_translation = bool(language == "ja" and answer and answer.zh)
        self.answer_translation_rule.setVisible(show_translation)
        self.answer_zh.setVisible(show_translation)
        answer_status = row.answer_status if row else ""
        self.answer_status.setText(answer_status)
        self.answer_status.setVisible(bool(answer_status))

    def shutdown(self):
        if not self.closing:
            self.closing = True
            self.settings_toggle.setChecked(False)
            self.stop_session()
        if self.settings_worker is None and self.credential_worker is None and not self.close_save_attempted:
            self.close_save_attempted = True
            self.persist_preferences()
        return (self.worker is None and self.scan is None and self.credential_worker is None
                and self.settings_worker is None)

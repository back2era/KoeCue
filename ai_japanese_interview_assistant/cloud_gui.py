"""Consent-gated live bilingual interview tab."""
from dataclasses import dataclass
import asyncio
import os

from PySide6.QtCore import QPoint, QSignalBlocker, QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .answer_format import ANSWER_LEVELS
from .config import OPENAI, PROVIDERS, QWEN
from .credentials import credential
from .diagnostic import DeviceScan
from .glass import (
    DEFAULT_THEME, THEMES, GlassComboBox, GlassDialog, IconButton, glass_panel,
    motion_enabled, plain_label, quiet_button, set_role,
)
from .interview import Answer
from .interview_ui import (
    AnswerPanel, ConversationItem, ConversationList, RescuePhrases, TranscriptionPanel, japanese_font,
)
from .live import ANSWER_PENDING, LiveWorker
from .personal import PersonalInfo
from .profile_gui import PrivateIO, ProfileDialog
from .profiles import ProfileError
from .services import TextService, client_for, error_message
from .settings import DEFAULT_INTERVIEW_LEVEL, Preferences, load_preferences, save_preferences
from .themes import GAP, GUTTER, INSET


@dataclass
class Row:
    ja: str = ""
    zh: str = ""
    finalized: bool = False
    asr: str = ""
    translation: str = ""
    answer: Answer | None = None
    answer_status: str = ""


class CloudPane(QWidget):
    idle = Signal()
    theme_changed = Signal(str)
    profile_changed = Signal(bool, object, int, str, str)
    view_changed = Signal()

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
        self.vault_provider = None
        self.approved_facts = ()
        self.approved_personal = PersonalInfo()
        self.profile_snapshot = None
        self.generation = 0
        self.session_id = 0
        self.capture_available = True
        self.state = "idle"
        self.closing = False
        self.close_save_attempted = False
        self.rows = {}
        self.rendered = []
        self.changed_rows = set()
        self.history_items = {}
        self.history_sizes = None
        self.confirmation = None
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
        self.answer_level = GlassComboBox()
        self.answer_level.setAccessibleName("AI 回答难度")
        for level in ANSWER_LEVELS:
            self.answer_level.addItem(level, level)
        self.answer_level.setCurrentIndex(self.answer_level.findData(DEFAULT_INTERVIEW_LEVEL))
        self.provider = GlassComboBox()
        self.provider.setAccessibleName("API 服务商")
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
        self.api_test = QPushButton("测试连接")
        self.api_test.setToolTip("向所选模型发送固定日语短句，检查流式译文。")
        self.api_status = plain_label("", "muted")
        self.api_status.hide()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API Key")
        self.vault_button = QPushButton("Windows 凭据")
        self.vault_button.setObjectName("vaultAction")
        vault_menu = QMenu(self.vault_button)
        for action, operation in (("读取已保存的 Key", "read"), ("保存当前 Key", "save"), ("删除已保存的 Key", "delete")):
            vault_menu.addAction(action, lambda checked=False, op=operation: self.use_vault(op))
        self.vault_button.setMenu(vault_menu)
        self.auto_answer = QCheckBox("自动为面试发言生成建议")
        self.auto_answer.setChecked(True)
        self.start = QPushButton("开始云端监听")
        self.pause = QPushButton("暂停")
        self.stop = quiet_button(QPushButton("停止"))
        self.retry = quiet_button(QPushButton("重试翻译"))
        self.suggest = quiet_button(QPushButton("生成回答"))
        self.asr_status = QLabel("转写未连接")
        self.text_status = QLabel("文本 API 未连接")
        self.audio_status = QLabel("音频未打开")
        self.history = ConversationList()
        self.empty_history = plain_label("还没有对话\n识别后的日语和译文会出现在这里。", "muted")
        self.empty_history.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_history.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        empty_layout = QVBoxLayout(self.history.viewport())
        empty_layout.addWidget(self.empty_history)

        self.transcription = TranscriptionPanel()
        self.original, self.translated = self.transcription.original, self.transcription.translated
        self.live_caption = plain_label("", "captionText")
        self.live_caption.setAccessibleName("正在识别的日语")
        japanese_font(self.live_caption)
        self.answer_panel = AnswerPanel()
        self.answer_ja = self.answer_panel.japanese
        self.full_annotations = self.answer_panel.annotations
        self.copy = self.answer_panel.copy
        self.listening_badge = plain_label("", "listeningBadge")
        self.listening_badge.setWordWrap(False)
        self.input_summary = plain_label("", "muted")
        self.status_detail = plain_label("", "captionState")
        self.settings_toggle = IconButton("settings", "设置 · 音源、模型与 API Key")
        self.settings_toggle.setCheckable(True)
        self.history_toggle = IconButton("history", "显示或收起历史对话")
        self.history_toggle.setCheckable(True)
        self.history_toggle.setChecked(True)
        self.latest = quiet_button(QPushButton("回到最新"))
        self.start.setObjectName("primaryAction")
        self.pause.setObjectName("primaryAction")
        self.build_layout()

        self.render_timer = QTimer(self)
        self.render_timer.setInterval(65)
        self.render_timer.timeout.connect(self.render_history)
        self.render_timer.start()
        self.refresh.clicked.connect(self.refresh_devices)
        self.source.currentIndexChanged.connect(self.source_changed)
        self.theme.currentIndexChanged.connect(lambda: self.theme_changed.emit(self.theme.currentData()))
        self.answer_level.currentIndexChanged.connect(self.update_answer_level)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.model.currentTextChanged.connect(self.model_changed)
        self.workspace.textChanged.connect(self.api_input_changed)
        self.model_refresh.clicked.connect(lambda: self.run_api_action(refresh=True))
        self.api_test.clicked.connect(lambda: self.run_api_action(refresh=False))
        self.auto_answer.toggled.connect(self.select_row)
        self.key.textChanged.connect(self.api_input_changed)
        self.start.clicked.connect(self.start_session)
        self.pause.clicked.connect(self.pause_session)
        self.stop.clicked.connect(self.stop_session)
        self.retry.clicked.connect(self.retry_translation)
        self.suggest.clicked.connect(self.request_answer)
        self.history.currentItemChanged.connect(self.select_row)
        self.history.itemActivated.connect(self.show_captions)
        self.history.itemClicked.connect(self.show_captions)
        self.history_toggle.toggled.connect(self.set_history_visible)
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
        outer.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        outer.addWidget(self.splitter, 1)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("captionScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(120)
        content = QWidget()
        content.setObjectName("captionContent")
        self.scroll.setWidget(content)
        page = QVBoxLayout(content)
        self.reading_layout = page
        page.setContentsMargins(GUTTER, GUTTER, GUTTER, GUTTER)
        page.setSpacing(INSET)

        self.preview_card = glass_panel("glassInset")
        preview = QVBoxLayout(self.preview_card)
        preview.setContentsMargins(12, GAP, 12, GAP)
        preview.setSpacing(4)
        preview.addWidget(plain_label("正在识别", "eyebrow"))
        preview.addWidget(self.live_caption)
        self.preview_card.hide()
        page.addWidget(self.preview_card)
        page.addWidget(self.transcription)
        page.addWidget(self.rule())
        page.addWidget(self.answer_panel)
        actions = QHBoxLayout()
        actions.addWidget(self.suggest)
        actions.addWidget(self.retry)
        actions.addStretch(1)
        page.addLayout(actions)
        page.addWidget(self.rule())
        page.addWidget(RescuePhrases())
        page.addStretch(1)
        self.splitter.addWidget(self.scroll)

        self.history_pane = glass_panel("historyPane")
        history_layout = QVBoxLayout(self.history_pane)
        history_layout.setContentsMargins(12, 12, 12, 12)
        history_layout.setSpacing(GAP)
        history_heading = QHBoxLayout()
        history_heading.addWidget(plain_label("历史对话", "sectionTitle"), 1)
        history_heading.addWidget(self.latest)
        history_layout.addLayout(history_heading)
        history_layout.addWidget(self.history, 1)
        self.splitter.addWidget(self.history_pane)

        bar = glass_panel("sessionBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(INSET, GAP, INSET, GAP)
        bar_layout.setSpacing(INSET)
        info = QVBoxLayout()
        info.setSpacing(2)
        summary = QHBoxLayout()
        summary.setSpacing(GAP)
        summary.addWidget(self.listening_badge)
        summary.addWidget(self.input_summary, 1)
        info.addLayout(summary)
        info.addWidget(self.status_detail)
        bar_layout.addLayout(info, 1)
        self.audio_settings = quiet_button(QPushButton("音源与 API"))
        self.audio_settings.clicked.connect(lambda: self.settings_toggle.setChecked(True))
        bar_layout.addWidget(self.audio_settings)
        for button in (self.stop, self.pause, self.start):
            bar_layout.addWidget(button)
        outer.addWidget(bar)
        self.build_settings()

    def set_history_visible(self, visible):
        if not visible:
            self.history_sizes = self.splitter.sizes()
        self.history_pane.setVisible(visible)
        if visible:
            self.reset_splitter()
            if self.rendered and self.current_row()[0] == self.rendered[-1]:
                self.history.scrollToBottom()

    def reset_splitter(self):
        if self.history_pane.isHidden():
            return
        horizontal = self.splitter.orientation() == Qt.Orientation.Horizontal
        length = self.splitter.width() if horizontal else self.splitter.height()
        sizes = self.history_sizes or [length * 2 // 3, length // 3]
        self.splitter.setSizes(sizes)
        self.history_sizes = None

    def build_settings(self):
        self.settings = GlassDialog("设置", self)
        self.settings.resize(650, 535)
        options = glass_panel()
        option_layout = QVBoxLayout(options)
        option_layout.setContentsMargins(16, 12, 16, 12)
        for title, selector in (("界面主题", self.theme), ("AI 回答难度", self.answer_level)):
            row = QHBoxLayout()
            row.addWidget(plain_label(title, "sectionTitle"), 1)
            row.addWidget(selector)
            option_layout.addLayout(row)
        self.settings.body.addWidget(options)
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
        settings.addWidget(plain_label("API 服务", "sectionTitle"))
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
        self.settings.body.addWidget(card)

        self.settings.body.addStretch()
        done = QPushButton("完成")
        done.setObjectName("primaryAction")
        done.clicked.connect(self.settings.accept)
        self.settings.body.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        for button in self.settings.findChildren(QPushButton):
            button.setAutoDefault(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width, height = event.size().width(), event.size().height()
        tight = width < 720 and height < 560
        margin = INSET if tight else GUTTER
        self.reading_layout.setContentsMargins(margin, margin, margin, margin)
        self.reading_layout.setSpacing(GAP if tight else INSET)
        limits = (2, 1) if tight else (3, 2)
        self.transcription.set_preview_limits(*limits)
        side_by_side = width >= 850 or (width >= 720 and height < 550)
        orientation = Qt.Orientation.Horizontal if side_by_side else Qt.Orientation.Vertical
        if self.splitter.orientation() != orientation or not event.oldSize().isValid():
            self.splitter.setOrientation(orientation)
            self.history_sizes = None
            self.reset_splitter()

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

        async def request():
            async with client_for(key, provider) as client:
                service = TextService(client, provider, model=model, workspace=workspace)
                if refresh:
                    return await service.list_models()
                await service.check_connection()

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
        self.key.clear()
        self.set_model_options()
        self.workspace.setVisible(provider is QWEN)
        self.api_status.hide()
        self.approved_facts = ()
        self.approved_personal = PersonalInfo()
        self.key.setPlaceholderText(f"{provider.label} API Key")
        self.asr_status.setText("转写未连接" if provider is OPENAI else "本地日语转写未启动")
        self.text_status.setText(f"{provider.label} 文本 API 未连接")
        if self.preferences_ready and not self.closing:
            self.use_vault("read")
        self.controls()

    def controls(self):
        idle = (self.worker is None and self.scan is None and self.credential_worker is None
                and self.settings_worker is None and not self.closing)
        configurable = idle and self.state != "paused"
        self.theme.setEnabled(self.preferences_ready and not self.closing)
        self.answer_level.setEnabled(self.preferences_ready and not self.closing)
        for widget in (self.source, self.refresh, self.provider, self.model, self.workspace, self.key,
                       self.vault_button, self.auto_answer):
            widget.setEnabled(configurable)
        profile_state = (
            configurable, self.approved_personal, len(self.approved_facts), self.selected_provider().label, self.state,
        )
        if profile_state != self.profile_snapshot:
            self.profile_snapshot = profile_state
            self.profile_changed.emit(*profile_state)
        endpoint_valid = self.endpoint_valid()
        self.workspace.setToolTip("" if endpoint_valid else "请输入有效的百炼北京工作空间 ID。")
        api_ready = bool(configurable and self.api_key() and endpoint_valid)
        self.api_test.setEnabled(api_ready)
        self.model_refresh.setEnabled(api_ready and bool(self.selected_provider().models_url))
        ready = bool(self.source.currentData() and self.api_key() and endpoint_valid)
        can_start = idle and ready and self.capture_available and self.state in {"idle", "paused"}
        self.start.setEnabled(can_start)
        provider = self.selected_provider()
        mode = "云端监听" if provider is OPENAI else "本地转写"
        self.start.setText(("恢复" if self.state == "paused" else "开始") + mode)
        self.start.setVisible(self.state != "active")
        self.pause.setVisible(self.state == "active")
        self.pause.setEnabled(self.state == "active")
        self.stop.setVisible(self.state in {"active", "paused"})
        self.stop.setEnabled(self.state in {"active", "paused"})
        key, row = self.current_row()
        retryable = row and row.finalized and row.ja and row.translation not in {"翻译中", "已翻译"}
        self.retry.setEnabled(bool(self.can_send_row(key) and retryable))
        self.suggest.setEnabled(bool(self.can_send_row(key) and row and row.finalized and
                                     row.ja and row.answer_status != ANSWER_PENDING))
        self.retry.setVisible(bool(retryable and self.can_send_row(key)))
        self.suggest.setText("重新生成" if row and row.answer else "生成回答")
        self.suggest.setVisible(self.suggest.isEnabled())
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
        self.listening_badge.setText(badge)
        set_role(self.listening_badge, "tone", tone)
        device = self.source.currentData()
        if device is None:
            source = "上次音源不可用，请重新选择" if self.audio_selection[0] and self.scan is None else "请选择音源"
        else:
            source = "系统音频" if device.loopback else "麦克风"
        self.input_summary.setText(f"{source} · 日语 → 中文")
        states = (audio, self.asr_status.text(), self.text_status.text())
        detail = "  ·  ".join(dict.fromkeys(states))
        self.status_detail.setText(detail)
        self.status_detail.setToolTip(detail)
        warning = any(word in detail for word in ("失败", "断开", "错误", "无效", "超时", "限流"))
        set_role(self.status_detail, "tone", "error" if warning else "neutral")
        self.view_changed.emit()

    def start_session(self):
        if not self.start.isEnabled() or self.confirmation is not None:
            return
        device, provider = self.source.currentData(), self.selected_provider()
        dialog = GlassDialog("确认开始监听", self)
        dialog.setMaximumWidth(520)
        dialog.resize(440, 245)
        scope = "系统播放设备的混音" if device.loopback else "麦克风输入"
        route = ("音频会发送至 OpenAI 转写。" if provider is OPENAI else "音频在本机转写。")
        dialog.body.addWidget(plain_label(f"{scope} · {device.name}", "sectionTitle"))
        dialog.body.addWidget(plain_label(
            f"{route}日语文字及本次授权的资料可发送至 {provider.label}。", "muted",
        ))
        dialog.body.addWidget(plain_label("请先确认参与者已给予必要同意。", "muted"))
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        confirm = buttons.addButton("已获同意，开始监听", QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName("primaryAction")
        cancel.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog.body.addWidget(buttons)
        self.confirmation = dialog

        def finished(result):
            self.confirmation = None
            dialog.deleteLater()
            same_route = (device, provider) == (self.source.currentData(), self.selected_provider())
            if result == QDialog.DialogCode.Accepted and same_route and self.start.isEnabled():
                self.start_confirmed()

        dialog.finished.connect(finished)
        dialog.open()
        cancel.setFocus()

    def start_confirmed(self):
        if self.state != "paused":
            self.session_id += 1
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
                                 model=self.selected_model(), workspace=self.workspace.text().strip())
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
            self.view_changed.emit()

    def clear_live_caption(self):
        self.preview_key, self.preview_text = None, ""
        self.live_caption.clear()
        self.preview_card.hide()
        self.view_changed.emit()

    @Slot(object)
    def add_transcript(self, data):
        key, part = data
        if self.state != "active" or key in self.rows or not (part.final or part.failed):
            return
        if key == self.preview_key:
            self.clear_live_caption()
        if part.failed:
            self.rows[key] = Row(asr="转写失败")
        elif part.text:
            self.rows[key] = Row(ja=part.text, finalized=True, asr="日语定稿")
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
        if self.worker is not None and self.can_send_row(key) and row and row.finalized and row.ja:
            self.worker.dispatch(self.worker.start_translation, key, row.ja)

    def request_answer(self):
        key, row = self.current_row()
        if self.worker is not None and self.can_send_row(key) and row and row.finalized and row.ja:
            self.worker.dispatch(self.worker.start_answer, key, row.ja)


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
    def set_approved_personal(self, info):
        if self.state == "idle":
            self.approved_personal = info
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

    def use_vault(self, operation):
        if self.credential_worker is not None or self.settings_worker is not None:
            return
        key = self.key.text().strip() if operation == "save" else ""
        provider = self.selected_provider()
        self.vault_operation = operation
        self.vault_provider = provider
        self.credential_worker = PrivateIO(lambda: credential(operation, key, provider), self)
        self.credential_worker.result.connect(self.vault_result)
        self.credential_worker.failed.connect(self.text_status.setText)
        self.credential_worker.finished.connect(self.vault_finished)
        self.controls()
        self.credential_worker.start()

    @Slot(object)
    def vault_result(self, value):
        if self.vault_provider is not self.selected_provider():
            return
        operation = self.vault_operation
        if operation == "read" and value:
            self.key.setText(value)
        elif operation == "delete":
            self.key.clear()
        elif operation == "save":
            self.key.setModified(False)
        self.text_status.setText({"read": "已读取已保存的 Key" if value else "未找到已保存的 Key",
                                  "save": "Key 已保存到 Windows 凭据管理器",
                                  "delete": "已清除保存的 Key"}[operation])

    def vault_finished(self):
        self.credential_worker.deleteLater()
        self.credential_worker = None
        self.vault_operation = ""
        self.vault_provider = None
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
        self.auto_answer.setChecked(preferences.auto_answer)
        self.theme.setCurrentIndex(self.theme.findData(preferences.theme))
        self.answer_level.setCurrentIndex(self.answer_level.findData(preferences.answer_level))
        self.restore_audio_source()

    def persist_preferences(self):
        if self.settings_worker is not None or self.credential_worker is not None:
            return
        preferences = Preferences(
            self.provider.currentData(), *self.audio_selection, self.auto_answer.isChecked(), self.theme.currentData(),
            self.answer_level.currentData(),
            tuple((code, self.model_choices[code]) for code in PROVIDERS if code in self.model_choices),
            self.workspace.text().strip(),
        )
        changed = preferences != self.preferences
        key = self.key.text().strip() if self.key.isModified() else ""
        if not changed and not key:
            return
        provider = self.selected_provider()

        def save():
            if changed:
                save_preferences(preferences)
            if key:
                credential("save", key, provider)
            return preferences

        self.run_settings_io(save, self.preferences_saved)

    @Slot(object)
    def preferences_saved(self, preferences):
        self.preferences = preferences
        self.key.setModified(False)

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
            self.history.setCurrentRow(len(self.rendered) - 1)
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
        with QSignalBlocker(self.history):
            self.rendered = list(self.rows)
            self.empty_history.setVisible(not self.rendered)
            positions = {key: index for index, key in enumerate(self.rendered)}
            for index, (key, row) in enumerate(self.rows.items()):
                item = self.history_items.get(key)
                if item is None:
                    item = self.history_items[key] = ConversationItem()
                if item.listWidget() is not self.history or self.history.item(index) is not item:
                    if item.listWidget() is self.history:
                        self.history.takeItem(self.history.row(item))
                    self.history.insertItem(index, item)
                if key in changed or not item.text():
                    statuses = " · ".join(filter(None, (row.asr, row.translation, row.answer_status)))
                    item.set_turn(row.ja, row.zh, statuses)
            target = self.rendered[-1] if self.rendered and (following_latest or selected not in positions) else selected
            if target in positions and self.history.currentRow() != positions[target]:
                self.history.setCurrentRow(positions[target])
            if previous != self.rendered:
                self.history.doItemsLayout()
            if following_latest:
                self.history.scrollToBottom()
            else:
                scroll.setValue(positions.get(top_row, position))
        became_historical = bool(previous and self.rendered and target == previous[-1] != self.rendered[-1])
        if target != selected or target in changed or became_historical:
            self.select_row()
        else:
            self.view_changed.emit()

    def select_row(self):
        key, row = self.current_row()
        changed = key != self.displayed_row
        if changed:
            self.transcription.expand.setChecked(False)
        animate = bool(self.can_send_row(key) and self.rendered and key == self.rendered[-1] and motion_enabled())
        for widget, value in ((self.original, row.ja if row else ""), (self.translated, row.zh if row else "")):
            if changed:
                widget.set_caption("")
            widget.set_caption(value, animate=animate and widget is self.translated)
        self.displayed_row = key
        self.transcription.title.setText("历史字幕" if key and key != self.rendered[-1] else "面试官")
        self.transcription.original_state.setText(row.asr if row else "")
        self.transcription.original_state.setVisible(bool(row and row.asr))
        self.transcription.translation_state.setText(row.translation if row else "")
        self.transcription.translation_state.setVisible(bool(row and row.translation and row.translation != "已翻译"))
        self.answer_panel.set_content(
            key, row.answer if row else None, row.answer_status if row else "", self.answer_placeholder(row),
        )
        self.controls()

    def answer_placeholder(self, row):
        if row and row.answer_status:
            return "正在准备日语建议…" if row.answer_status == ANSWER_PENDING else "这一段暂无回答。"
        if not row and self.state == "idle":
            return "开始监听后，日语回答建议会显示在这里。"
        if not self.auto_answer.isChecked():
            return "选择一段字幕后可以生成参考回答。"
        return "等待完整发言…"

    def shutdown(self):
        if not self.closing:
            self.closing = True
            if self.confirmation is not None:
                self.confirmation.reject()
            self.settings_toggle.setChecked(False)
            self.stop_session()
        if self.settings_worker is None and self.credential_worker is None and not self.close_save_attempted:
            self.close_save_attempted = True
            self.persist_preferences()
        return (self.worker is None and self.scan is None and self.credential_worker is None
                and self.settings_worker is None)

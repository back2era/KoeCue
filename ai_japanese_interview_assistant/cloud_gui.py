"""Consent-gated live bilingual interview tab."""
from dataclasses import dataclass
import os

from PySide6.QtCore import QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostic import DeviceScan
from .config import OPENAI, PROVIDERS
from .credentials import credential
from .interview import Answer
from .live import LiveWorker
from .profile_gui import PrivateIO, ProfileDialog


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.scan = None
        self.credential_worker = None
        self.vault_operation = ""
        self.vault_provider = None
        self.approved_facts = ()
        self.generation = 0
        self.session_id = 0
        self.capture_available = True
        self.state = "idle"
        self.closing = False
        self.rows = {}
        self.rendered = []
        self.dirty = False

        self.source = QComboBox()
        self.refresh = QPushButton("刷新设备")
        self.provider = QComboBox()
        self.provider.setAccessibleName("API 服务商")
        for code, provider in PROVIDERS.items():
            self.provider.addItem(provider.label, code)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API Key · 仅在本次运行使用")
        self.vault_button = QPushButton("Windows 凭据")
        vault_menu = QMenu(self.vault_button)
        for action, operation in (("读取已保存的 Key", "read"), ("保存当前 Key", "save"), ("删除已保存的 Key", "delete")):
            vault_menu.addAction(action, lambda checked=False, op=operation: self.use_vault(op))
        self.vault_button.setMenu(vault_menu)
        self.profile = QPushButton("编辑资料 / 本次授权")
        self.revoke = QPushButton("撤销资料分享")
        self.profile_status = QLabel("本次未授权资料分享")
        self.consent = QCheckBox()
        self.local_hint = QLabel("首次使用本地语音需按 README 安装组件并下载日语模型。")
        self.local_hint.setWordWrap(True)
        self.auto_answer = QCheckBox("为本次会话自动识别问题并生成回答建议")
        self.start = QPushButton("开始云端监听")
        self.pause = QPushButton("暂停")
        self.stop = QPushButton("停止")
        self.retry = QPushButton("重试所选翻译")
        self.suggest = QPushButton("为所选段生成回答")
        self.copy = QPushButton("复制双语回答")
        self.asr_status = QLabel("转写未连接")
        self.text_status = QLabel("文本 API 未连接")
        self.audio_status = QLabel("音频未打开")
        for label in (self.asr_status, self.text_status, self.audio_status):
            label.setWordWrap(True)
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["日语原文", "简体中文", "状态"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.original = QPlainTextEdit(readOnly=True, placeholderText="日语原文")
        self.translated = QPlainTextEdit(readOnly=True, placeholderText="中文翻译")
        self.answer_box = QPlainTextEdit(readOnly=True, placeholderText="AI 回答建议")
        self.answer_status = QLabel()
        self.answer_status.setWordWrap(True)
        details = QSplitter(Qt.Orientation.Horizontal)
        details.addWidget(self.original)
        details.addWidget(self.translated)

        layout = QVBoxLayout(self)
        hint = QLabel("请选择授权的模拟或线上面试。系统回环包含同一播放设备上的其他声音。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        source = QHBoxLayout()
        source.addWidget(self.source, 1)
        source.addWidget(self.refresh)
        layout.addLayout(source)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("服务商"))
        key_row.addWidget(self.provider)
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.vault_button)
        layout.addLayout(key_row)
        layout.addWidget(self.local_hint)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.profile)
        profile_row.addWidget(self.revoke)
        profile_row.addWidget(self.profile_status, 1)
        layout.addLayout(profile_row)
        layout.addWidget(self.consent)
        layout.addWidget(self.auto_answer)
        buttons = QHBoxLayout()
        for button in (self.start, self.pause, self.stop, self.retry):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.asr_status)
        layout.addWidget(self.text_status)
        layout.addWidget(self.audio_status)
        layout.addWidget(self.history, 3)
        layout.addWidget(details, 2)
        answer_actions = QHBoxLayout()
        answer_actions.addWidget(self.suggest)
        answer_actions.addWidget(self.copy)
        layout.addLayout(answer_actions)
        layout.addWidget(self.answer_status)
        layout.addWidget(self.answer_box, 2)

        self.render_timer = QTimer(self)
        self.render_timer.setInterval(100)
        self.render_timer.timeout.connect(self.render_history)
        self.render_timer.start()
        self.refresh.clicked.connect(self.refresh_devices)
        self.source.currentIndexChanged.connect(self.source_changed)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.consent.toggled.connect(self.controls)
        self.key.textChanged.connect(self.controls)
        self.start.clicked.connect(self.start_session)
        self.pause.clicked.connect(self.pause_session)
        self.stop.clicked.connect(self.stop_session)
        self.retry.clicked.connect(self.retry_translation)
        self.suggest.clicked.connect(self.request_answer)
        self.copy.clicked.connect(self.copy_answer)
        self.profile.clicked.connect(self.open_profile)
        self.revoke.clicked.connect(self.revoke_profile)
        self.history.itemSelectionChanged.connect(self.select_row)
        self.provider_changed()
        self.refresh_devices()

    def source_changed(self):
        self.consent.setChecked(False)
        self.controls()

    def refresh_devices(self):
        self.source.clear()
        self.scan = DeviceScan(self)
        self.scan.result.connect(self.set_devices)
        self.scan.failed.connect(self.asr_status.setText)
        self.scan.finished.connect(self.scan_finished)
        self.controls()
        self.scan.start()

    def set_devices(self, devices):
        self.source.addItem("选择音频来源", None)
        for device in devices:
            kind = "系统播放" if device.loopback else "麦克风 / 输入"
            self.source.addItem(f"{kind} · {device.name} · #{device.index}", device)
        if not devices:
            self.asr_status.setText("未找到可用的 WASAPI 输入")

    def scan_finished(self):
        self.scan.deleteLater()
        self.scan = None
        self.controls()
        self.idle.emit()

    def api_key(self):
        return self.key.text().strip() or os.environ.get(self.selected_provider().key_env, "").strip()

    def selected_provider(self):
        return PROVIDERS[self.provider.currentData()]

    def provider_changed(self):
        if self.state != "idle":
            self.stop_session()
        provider = self.selected_provider()
        self.key.clear()
        self.consent.setChecked(False)
        self.auto_answer.setChecked(False)
        self.approved_facts = ()
        self.key.setPlaceholderText(f"{provider.label} API Key · 仅在本次运行使用")
        self.local_hint.setVisible(provider is not OPENAI)
        self.consent.setText(
            "已取得必要同意，允许将所选来源的音频及转写发送至 OpenAI"
            if provider is OPENAI else
            f"已取得必要同意。音频在本机转写，日语文字及单独授权的资料可发送至 {provider.label}"
        )
        self.asr_status.setText("转写未连接" if provider is OPENAI else "本地日语转写未启动")
        self.text_status.setText(f"{provider.label} 文本 API 未连接")
        self.controls()

    def controls(self):
        idle = self.worker is None and self.scan is None and self.credential_worker is None and not self.closing
        configurable = idle and self.state != "paused"
        for widget in (self.source, self.refresh, self.provider, self.key, self.vault_button, self.consent, self.auto_answer, self.profile):
            widget.setEnabled(configurable)
        self.revoke.setEnabled(bool(self.approved_facts))
        self.profile_status.setText(f"本次授权 {len(self.approved_facts)} 条资料" if self.approved_facts else "本次未授权资料分享")
        allowed = bool(self.consent.isChecked() and self.source.currentData() and self.api_key())
        self.start.setEnabled(idle and allowed and self.capture_available)
        mode = "云端监听" if self.selected_provider() is OPENAI else "本地转写"
        self.start.setText(("恢复" if self.state == "paused" else "开始") + mode)
        self.pause.setEnabled(self.state == "active")
        self.stop.setEnabled(self.state in {"active", "paused"})
        key, row = self.current_row()
        retryable = row and row.finalized and row.ja and row.translation not in {"翻译中", "已翻译"}
        self.retry.setEnabled(bool(self.can_send_row(key) and retryable))
        self.suggest.setEnabled(bool(self.can_send_row(key) and row and row.finalized and
                                     row.ja and row.answer_status != "正在检查问题…"))
        self.copy.setEnabled(bool(row and row.answer))

    def start_session(self):
        if not self.start.isEnabled():
            return
        if self.state != "paused":
            self.session_id += 1
        self.generation += 1
        self.state = "active"
        self.worker = LiveWorker(self.generation, self.source.currentData(), self.api_key(), self,
                                 session_id=self.session_id, auto_answer=self.auto_answer.isChecked(),
                                 facts=self.approved_facts, provider=self.selected_provider())
        self.worker.status.connect(self.set_status)
        self.worker.transcript.connect(self.add_transcript)
        self.worker.order.connect(self.set_order)
        self.worker.translation.connect(self.add_translation)
        self.worker.answer.connect(self.add_answer)
        self.worker.finished.connect(self.worker_finished)
        self.controls()
        self.worker.start()

    def set_status(self, service, value):
        if self.state == "active":
            statuses = {"asr": self.asr_status, "text": self.text_status, "audio": self.audio_status}
            statuses[service].setText(value)

    def pause_session(self):
        if self.worker is not None:
            self.state = "paused"
            self.worker.stop()
            self.asr_status.setText("已暂停")
            self.text_status.setText("文本请求已暂停")
            self.audio_status.setText("音频已暂停")
            self.controls()

    def stop_session(self):
        self.state = "idle"
        if self.worker is not None:
            self.worker.stop()
        self.consent.setChecked(False)
        self.auto_answer.setChecked(False)
        self.approved_facts = ()
        self.asr_status.setText("已停止")
        self.text_status.setText("文本 API 未连接")
        self.audio_status.setText("音频未打开")
        self.controls()

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        if self.state == "active":
            self.state = "idle"
            self.consent.setChecked(False)
            self.auto_answer.setChecked(False)
            self.approved_facts = ()
            if self.audio_status.text().startswith(("正在打开", "音频 ·")):
                self.audio_status.setText("音频已停止")
        for row in self.rows.values():
            if not row.finalized and row.asr != "转写失败":
                row.asr = "转写已中断"
            if row.translation == "翻译中":
                row.translation = "翻译已取消"
            if row.answer_status == "正在检查问题…":
                row.answer_status = "回答已取消"
        self.dirty = True
        self.controls()
        self.idle.emit()

    def add_transcript(self, data):
        key, part = data
        if self.state != "active":
            return
        row = self.rows.setdefault(key, Row())
        row.ja, row.finalized = part.text, part.final
        row.asr = "转写失败" if part.failed else "日语定稿" if part.final else "转写中"
        if len(self.rows) > 500:
            del self.rows[next(iter(self.rows))]
        self.dirty = True

    def set_order(self, order):
        if self.state != "active":
            return
        current = {key: self.rows[key] for key in order if key in self.rows}
        self.rows = {key: row for key, row in self.rows.items() if key not in current} | current
        self.dirty = True

    def add_translation(self, key, text, state):
        if self.state != "active" or key not in self.rows:
            return
        row = self.rows[key]
        row.zh, row.translation = text, state
        self.dirty = True

    @Slot(object, object, str, bool)
    def add_answer(self, key, answer, state, scoped):
        if self.can_send_row(key) and key in self.rows and (not scoped or self.approved_facts):
            row = self.rows[key]
            row.answer, row.answer_status = answer, state
            self.dirty = True

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

    def copy_answer(self):
        _, row = self.current_row()
        if row and row.answer:
            QApplication.clipboard().setText(self.answer_box.toPlainText())

    def open_profile(self):
        dialog = ProfileDialog(self.approved_facts, self)
        dialog.authorized.connect(self.set_approved)
        dialog.changed.connect(lambda facts: self.revoke_profile())
        dialog.exec()
        dialog.deleteLater()

    def set_approved(self, facts):
        self.approved_facts = facts
        self.controls()

    def revoke_profile(self):
        self.set_approved(())
        if self.worker is not None:
            self.worker.revoke_profile()
            for row in self.rows.values():
                if row.answer_status == "正在检查问题…":
                    row.answer_status = "回答已取消"
            self.dirty = True

    def use_vault(self, operation):
        if self.credential_worker is not None:
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

    def render_history(self):
        if not self.dirty:
            return
        self.dirty = False
        selected, _ = self.current_row()
        following_latest = not self.rendered or selected == self.rendered[-1]
        scroll = self.history.verticalScrollBar()
        at_end = scroll.value() == scroll.maximum()
        self.history.blockSignals(True)
        self.rendered = list(self.rows)
        self.history.setRowCount(len(self.rendered))
        for index, row in enumerate(self.rows.values()):
            statuses = " · ".join(filter(None, (row.asr, row.translation, row.answer_status)))
            for column, value in enumerate((row.ja, row.zh, statuses)):
                cell = self.history.item(index, column)
                if cell is None:
                    self.history.setItem(index, column, QTableWidgetItem(value))
                elif cell.text() != value:
                    cell.setText(value)
        if at_end and following_latest and self.rendered:
            self.history.selectRow(len(self.rendered) - 1)
        elif selected in self.rows:
            self.history.selectRow(self.rendered.index(selected))
        elif self.rendered:
            self.history.selectRow(len(self.rendered) - 1)
        if at_end:
            self.history.scrollToBottom()
        self.history.blockSignals(False)
        self.select_row()

    def select_row(self):
        _, row = self.current_row()
        for widget, value in ((self.original, row.ja if row else ""), (self.translated, row.zh if row else "")):
            if widget.toPlainText() != value:
                widget.setPlainText(value)
        answer = row.answer if row else None
        answer_text = f"{answer.ja}\n\n{answer.zh}" if answer else ""
        if self.answer_box.toPlainText() != answer_text:
            self.answer_box.setPlainText(answer_text)
        self.answer_status.setText(row.answer_status if row else "")
        self.controls()

    def shutdown(self):
        self.closing = True
        self.stop_session()
        return self.worker is None and self.scan is None and self.credential_worker is None

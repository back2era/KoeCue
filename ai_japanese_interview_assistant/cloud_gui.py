"""Consent-gated live bilingual interview tab."""
from dataclasses import dataclass
import os

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .diagnostic import DeviceScan
from .interview import Answer
from .live import LiveWorker


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
        self.generation = 0
        self.state = "idle"
        self.closing = False
        self.rows = {}
        self.rendered = []
        self.dirty = False

        self.source = QComboBox()
        self.refresh = QPushButton("刷新设备")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API Key · 仅在本次运行使用")
        self.consent = QCheckBox("已取得必要同意，允许将所选来源的音频及转写发送至 OpenAI")
        self.auto_answer = QCheckBox("为本次会话自动识别问题并生成回答建议")
        self.start = QPushButton("开始云端监听")
        self.pause = QPushButton("暂停")
        self.stop = QPushButton("停止")
        self.retry = QPushButton("重试所选翻译")
        self.suggest = QPushButton("为所选段生成回答")
        self.copy = QPushButton("复制双语回答")
        self.asr_status = QLabel("转写未连接")
        self.text_status = QLabel("文本 API 未连接")
        for label in (self.asr_status, self.text_status):
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
        layout.addWidget(self.key)
        layout.addWidget(self.consent)
        layout.addWidget(self.auto_answer)
        buttons = QHBoxLayout()
        for button in (self.start, self.pause, self.stop, self.retry):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.asr_status)
        layout.addWidget(self.text_status)
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
        self.consent.toggled.connect(self.controls)
        self.key.textChanged.connect(self.controls)
        self.start.clicked.connect(self.start_session)
        self.pause.clicked.connect(self.pause_session)
        self.stop.clicked.connect(self.stop_session)
        self.retry.clicked.connect(self.retry_translation)
        self.suggest.clicked.connect(self.request_answer)
        self.copy.clicked.connect(self.copy_answer)
        self.history.itemSelectionChanged.connect(self.select_row)
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
        return self.key.text().strip() or os.environ.get("OPENAI_API_KEY", "").strip()

    def controls(self):
        idle = self.worker is None and self.scan is None and not self.closing
        configurable = idle and self.state != "paused"
        for widget in (self.source, self.refresh, self.key, self.consent, self.auto_answer):
            widget.setEnabled(configurable)
        allowed = bool(self.consent.isChecked() and self.source.currentData() and self.api_key())
        self.start.setEnabled(idle and allowed)
        self.start.setText("恢复云端监听" if self.state == "paused" else "开始云端监听")
        self.pause.setEnabled(self.state == "active")
        self.stop.setEnabled(self.state in {"active", "paused"})
        _, row = self.current_row()
        retryable = row and row.finalized and row.translation not in {"翻译中", "已翻译"}
        self.retry.setEnabled(bool(self.state == "active" and retryable))
        self.suggest.setEnabled(bool(self.state == "active" and row and row.finalized and
                                     row.ja and row.answer_status != "正在检查问题…"))
        self.copy.setEnabled(bool(row and row.answer))

    def start_session(self):
        if not self.start.isEnabled():
            return
        self.generation += 1
        self.state = "active"
        self.worker = LiveWorker(self.generation, self.source.currentData(), self.api_key(), self,
                                 auto_answer=self.auto_answer.isChecked())
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
            (self.asr_status if service == "asr" else self.text_status).setText(value)

    def pause_session(self):
        if self.worker is not None:
            self.state = "paused"
            self.worker.stop()
            self.asr_status.setText("已暂停")
            self.text_status.setText("文本请求已暂停")
            self.controls()

    def stop_session(self):
        self.state = "idle"
        if self.worker is not None:
            self.worker.stop()
        self.consent.setChecked(False)
        self.auto_answer.setChecked(False)
        self.asr_status.setText("已停止")
        self.text_status.setText("文本 API 未连接")
        self.controls()

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        if self.state == "active":
            self.state = "idle"
            self.consent.setChecked(False)
            self.auto_answer.setChecked(False)
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

    def add_answer(self, key, answer, state):
        if self.state == "active" and key in self.rows:
            row = self.rows[key]
            row.answer, row.answer_status = answer, state
            self.dirty = True

    def current_row(self):
        index = self.history.currentRow()
        if 0 <= index < len(self.rendered):
            key = self.rendered[index]
            return key, self.rows.get(key)
        return None, None

    def retry_translation(self):
        key, row = self.current_row()
        if self.worker is not None and row and row.finalized:
            self.worker.dispatch(self.worker.start_translation, key, row.ja)

    def request_answer(self):
        key, row = self.current_row()
        if self.worker is not None and row and row.finalized and row.ja:
            self.worker.dispatch(self.worker.start_answer, key, row.ja)

    def copy_answer(self):
        _, row = self.current_row()
        if row and row.answer:
            QApplication.clipboard().setText(self.answer_box.toPlainText())

    def render_history(self):
        if not self.dirty:
            return
        self.dirty = False
        selected, _ = self.current_row()
        scroll = self.history.verticalScrollBar()
        at_end = scroll.value() == scroll.maximum()
        self.history.blockSignals(True)
        self.rendered = list(self.rows)
        self.history.setRowCount(len(self.rendered))
        for index, row in enumerate(self.rows.values()):
            for column, value in enumerate((row.ja, row.zh, " · ".join(filter(None, (row.asr, row.translation))))):
                cell = self.history.item(index, column)
                if cell is None:
                    self.history.setItem(index, column, QTableWidgetItem(value))
                elif cell.text() != value:
                    cell.setText(value)
        if selected in self.rows:
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
        return self.worker is None and self.scan is None

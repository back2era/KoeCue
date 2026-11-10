"""Standalone audio diagnostics. This module does not open network connections."""
from time import monotonic

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from .audio import AudioBuffer, AudioError, capture, check_topology, list_devices, pcm_level
from .telemetry import Event, record


class DeviceScan(QThread):
    result = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.result.emit(list_devices())
        except AudioError as exc:
            self.failed.emit(str(exc))
        except (ImportError, OSError, RuntimeError, ValueError):
            self.failed.emit("无法枚举 WASAPI 设备。请检查音频服务和 PyAudioWPatch 安装。")


class MeterWorker(QThread):
    ready = Signal()
    metered = Signal(int, int)
    failed = Signal(str)

    def __init__(self, device, parent):
        super().__init__(parent)
        self.device = device
        self.buffer = AudioBuffer()

    def request_stop(self):
        self.requestInterruption()
        self.buffer.close()

    def run(self):
        started = None
        try:
            if self.isInterruptionRequested():
                return
            with capture(self.device, self.buffer) as stream:
                started = monotonic()
                record(Event.AUDIO_OPEN)
                self.ready.emit()
                samples = 0
                level = 0
                next_update = monotonic()
                next_topology = next_update + 1
                while not self.isInterruptionRequested():
                    pcm = self.buffer.pop()
                    if pcm is None:
                        if not stream.is_active():
                            raise AudioError("音频流已关闭。请检查设备并刷新列表。")
                        self.msleep(10)
                    else:
                        samples += len(pcm) // (2 * self.device.channels)
                        level = max(level, pcm_level(pcm))
                    if monotonic() >= next_update:
                        self.metered.emit(level, samples)
                        level = 0
                        next_update = monotonic() + 0.1
                    if monotonic() >= next_topology:
                        check_topology(self.device)
                        next_topology = monotonic() + 1
        except AudioError as exc:
            if not self.isInterruptionRequested():
                record(Event.AUDIO_ERROR)
            self.failed.emit(str(exc))
        except (ImportError, OSError, RuntimeError, ValueError):
            record(Event.AUDIO_ERROR)
            self.failed.emit("无法读取所选设备。请检查 Windows 声音设置并刷新列表。")
        finally:
            if started is not None:
                record(Event.AUDIO_CLOSE, monotonic() - started)


class DiagnosticPane(QWidget):
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scan = None
        self.worker = None
        self.state = "idle"
        self.closing = False
        self.capture_available = True
        self.device = QComboBox()
        self.refresh = QPushButton("刷新设备")
        self.start = QPushButton("开始本地诊断")
        self.pause = QPushButton("暂停")
        self.stop = QPushButton("停止")
        self.consent = QCheckBox("我已确认有权采集这个来源的声音")
        self.status = QLabel("尚未开始")
        self.count = QLabel("已接收 0 帧")
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)

        layout = QVBoxLayout(self)
        info = QLabel("回环会读取所选播放设备上的混音。此页面仅显示本地电平与帧数。")
        info.setWordWrap(True)
        layout.addWidget(info)
        source = QGroupBox("音频来源")
        row = QHBoxLayout(source)
        row.addWidget(self.device, 1)
        row.addWidget(self.refresh)
        layout.addWidget(source)
        layout.addWidget(self.consent)
        controls = QHBoxLayout()
        for button in (self.start, self.pause, self.stop):
            controls.addWidget(button)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(self.meter)
        layout.addWidget(self.count)
        layout.addStretch()

        self.refresh.clicked.connect(self.refresh_devices)
        self.consent.toggled.connect(self.update_controls)
        self.device.currentIndexChanged.connect(self.source_changed)
        self.start.clicked.connect(self.start_capture)
        self.pause.clicked.connect(self.pause_capture)
        self.stop.clicked.connect(self.stop_capture)
        self.refresh_devices()

    def update_controls(self):
        selectable = not self.closing and self.worker is None and self.scan is None
        self.device.setEnabled(selectable and self.state != "paused")
        self.refresh.setEnabled(selectable and self.state != "paused")
        self.consent.setEnabled(selectable and self.state != "paused")
        self.start.setEnabled(selectable and self.capture_available and self.consent.isChecked()
                              and self.device.currentData() is not None)
        self.start.setText("恢复监听" if self.state == "paused" else "开始本地诊断")
        self.pause.setEnabled(self.state == "running")
        self.stop.setEnabled(self.state in {"starting", "running", "paused"})

    def source_changed(self):
        self.consent.setChecked(False)
        self.update_controls()

    def refresh_devices(self):
        self.device.clear()
        self.status.setText("正在枚举 WASAPI 设备…")
        self.scan = DeviceScan(self)
        self.scan.result.connect(self.show_devices)
        self.scan.failed.connect(self.status.setText)
        self.scan.finished.connect(self.scan_finished)
        self.update_controls()
        self.scan.start()

    def show_devices(self, devices):
        self.device.addItem("请选择播放设备或麦克风", None)
        for device in devices:
            kind = "系统播放" if device.loopback else "麦克风 / 输入"
            self.device.addItem(f"{kind} · {device.name} · #{device.index}", device)
        self.status.setText("请选择音频来源" if devices else "未找到可用的 WASAPI 输入")

    def scan_finished(self):
        self.scan.deleteLater()
        self.scan = None
        self.update_controls()
        self.idle.emit()

    def start_capture(self):
        device = self.device.currentData()
        if not self.start.isEnabled():
            return
        self.state = "starting"
        self.meter.setValue(0)
        self.count.setText("已接收 0 帧")
        self.status.setText("正在打开设备…")
        self.worker = MeterWorker(device, self)
        self.worker.ready.connect(self.on_ready)
        self.worker.metered.connect(self.on_meter)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.worker_finished)
        self.update_controls()
        self.worker.start()

    def on_ready(self):
        if self.state == "starting":
            self.state = "running"
            self.status.setText("正在监听 · 仅本地")
            self.update_controls()

    def on_meter(self, level, frames):
        if self.state == "running":
            self.meter.setValue(level)
            self.count.setText(f"已接收 {frames:,} 帧")

    def on_failure(self, message):
        if self.state in {"starting", "running"}:
            self.state = "idle"
            self.consent.setChecked(False)
            self.meter.setValue(0)
            self.status.setText(message)
            self.update_controls()

    def pause_capture(self):
        self.state = "paused"
        self.worker.request_stop()
        self.meter.setValue(0)
        self.status.setText("已暂停")
        self.update_controls()

    def stop_capture(self):
        self.state = "idle"
        if self.worker is not None:
            self.worker.request_stop()
        self.consent.setChecked(False)
        self.meter.setValue(0)
        self.status.setText("已停止")
        self.update_controls()

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.update_controls()
        self.idle.emit()

    def shutdown(self):
        self.closing = True
        self.stop_capture()
        return self.worker is None and self.scan is None

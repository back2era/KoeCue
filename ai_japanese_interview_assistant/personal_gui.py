"""Local résumé and interview context editor."""
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QBoxLayout, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from .glass import glass_panel, plain_label
from .personal import MAX_BACKGROUND, MAX_FIELD, MAX_RESUME, MAX_SCENARIO, PersonalInfo, PersonalStore, import_resume
from .profile_gui import PrivateIO


class PersonalPane(QWidget):
    saved_changed = Signal(object)
    busy_changed = Signal(bool)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.loaded = False
        self.closing = False
        self.saved = PersonalInfo()
        self.state = "idle"

        self.background = self.editor("自我介绍", "例如：我学电子信息工程，做过嵌入式项目，日语约 N3。", 90)
        self.resume = self.editor("简历文本", "可导入或粘贴中文、日文、英文简历。可先在这里删去不需要的联系方式。", 128)
        self.company = self.field("对方公司", "例如：○○株式会社")
        self.role = self.field("应聘岗位", "例如：嵌入式软件工程师")
        self.scenario = self.editor("场景说明", "例如：技术一面，重点介绍毕业设计，回答简短一点。", 90)
        self.import_button = QPushButton("导入简历")
        self.clear_resume = QPushButton("清空简历文本")
        self.save = QPushButton("保存个人信息")
        self.save.setObjectName("primaryAction")
        self.status = plain_label("", "muted")
        self.listening_status = plain_label("", "muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(plain_label("个人信息", "pageTitle"), 1)
        header.addWidget(self.listening_status)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setObjectName("captionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)
        content = QWidget()
        content.setObjectName("captionContent")
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(0, 0, 4, 0)
        page.setSpacing(11)

        self.fields_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.fields_layout.setSpacing(11)
        page.addLayout(self.fields_layout)
        profile = self.section(self.fields_layout, "关于我")
        profile.addWidget(plain_label("自我介绍", "muted"))
        profile.addWidget(self.background)
        resume_heading = QHBoxLayout()
        resume_heading.addWidget(plain_label("简历文本", "muted"), 1)
        resume_heading.addWidget(self.import_button)
        resume_heading.addWidget(self.clear_resume)
        profile.addLayout(resume_heading)
        profile.addWidget(self.resume)

        context = self.section(self.fields_layout, "面试场景")
        fields = QHBoxLayout()
        for label, editor in (("对方公司", self.company), ("应聘岗位", self.role)):
            field = QVBoxLayout()
            field.setSpacing(5)
            field.addWidget(plain_label(label, "muted"))
            field.addWidget(editor)
            fields.addLayout(field, 1)
        context.addLayout(fields)
        context.addWidget(plain_label("场景说明", "muted"))
        context.addWidget(self.scenario)
        context.addStretch(1)
        self.fields_layout.setStretch(0, 3)
        self.fields_layout.setStretch(1, 2)

        page.addStretch(1)
        save_bar = glass_panel("glassBar")
        save_layout = QHBoxLayout(save_bar)
        save_layout.setContentsMargins(16, 9, 12, 9)
        save_feedback = QVBoxLayout()
        save_feedback.addWidget(plain_label(
            "资料保存在本机。确认开始监听后，生成回答时会向所选服务商发送相关的已保存资料。",
            "muted",
        ))
        save_feedback.addWidget(self.status)
        save_layout.addLayout(save_feedback, 1)
        save_layout.addWidget(self.save)
        layout.addWidget(save_bar)

        self.import_button.clicked.connect(self.choose_resume)
        self.clear_resume.clicked.connect(self.resume.clear)
        self.save.clicked.connect(self.save_info)
        for widget in (self.background, self.resume, self.company, self.role, self.scenario):
            widget.textChanged.connect(self.form_changed)
        self.run_io(lambda: PersonalStore().load(), self.load_info, "正在读取本机资料…")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (
            QBoxLayout.Direction.LeftToRight if event.size().width() >= 820
            else QBoxLayout.Direction.TopToBottom
        )
        self.fields_layout.setDirection(direction)

    @staticmethod
    def editor(name, placeholder, height):
        widget = QPlainTextEdit()
        widget.setAccessibleName(name)
        widget.setPlaceholderText(placeholder)
        widget.setFixedHeight(height)
        return widget

    @staticmethod
    def field(name, placeholder):
        widget = QLineEdit()
        widget.setAccessibleName(name)
        widget.setPlaceholderText(placeholder)
        widget.setMaxLength(MAX_FIELD)
        return widget

    @staticmethod
    def section(parent_layout, title):
        card = glass_panel()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(8)
        layout.addWidget(plain_label(title, "sectionTitle"))
        parent_layout.addWidget(card)
        return layout

    def current(self):
        return PersonalInfo(
            background=self.background.toPlainText().strip(), resume=self.resume.toPlainText().strip(),
            company=self.company.text().strip(), role=self.role.text().strip(),
            scenario=self.scenario.toPlainText().strip(),
        )

    def run_io(self, operation, success, progress):
        self.status.setText(progress)
        self.worker = PrivateIO(operation, self)
        self.worker.result.connect(success)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.io_finished)
        self.update_controls()
        self.busy_changed.emit(True)
        self.worker.start()

    def io_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.update_controls()
        self.busy_changed.emit(False)
        self.idle.emit()

    @Slot(object)
    def load_info(self, info):
        self.saved = info
        self.background.setPlainText(info.background)
        self.resume.setPlainText(info.resume)
        self.company.setText(info.company)
        self.role.setText(info.role)
        self.scenario.setPlainText(info.scenario)
        self.loaded = True
        self.status.setText("资料保存在本机。修改后请保存。")
        self.saved_changed.emit(info)

    def choose_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入简历", "", "简历文档 (*.pdf *.docx *.txt);;所有文件 (*)",
        )
        if path:
            self.run_io(lambda: import_resume(Path(path)), self.resume_imported, "正在本机提取简历文字…")

    @Slot(object)
    def resume_imported(self, content):
        self.resume.setPlainText(content)
        self.status.setText("已提取简历文字。请检查内容并保存到本机。")

    def save_info(self):
        if not self.save.isEnabled():
            return
        info = self.current()
        for label, value, limit in (
            ("自我介绍", info.background, MAX_BACKGROUND), ("简历文本", info.resume, MAX_RESUME),
            ("场景说明", info.scenario, MAX_SCENARIO),
        ):
            if len(value) > limit:
                self.status.setText(f"{label}最多可填写 {limit} 字。")
                return

        def save():
            PersonalStore().save(info)
            return info

        self.run_io(save, self.info_saved, "正在保存到本机…")

    @Slot(object)
    def info_saved(self, info):
        self.saved = info
        self.status.setText("已保存到本机。")
        self.saved_changed.emit(info)

    def form_changed(self):
        self.update_controls()
        if self.loaded and self.worker is None:
            self.status.setText("有未保存的修改。" if self.save.isEnabled() else "资料已保存到本机。")

    @Slot(str)
    def session_state(self, state):
        self.state = state
        self.update_controls()

    def update_controls(self):
        ready = self.loaded and self.worker is None and not self.closing
        current = self.current()
        editable = ready and self.state == "idle"
        for widget in (self.background, self.resume, self.company, self.role, self.scenario, self.import_button):
            widget.setEnabled(editable)
        self.clear_resume.setEnabled(editable and bool(current.resume))
        self.save.setEnabled(editable and current != self.saved)
        self.listening_status.setText({
            "active": "监听仍在进行，可返回实时面试暂停或停止。",
            "paused": "监听已暂停，可返回实时面试恢复。",
        }.get(self.state, ""))

    def shutdown(self):
        self.closing = True
        self.update_controls()
        return self.worker is None

"""Local profile editor with editable records and résumé autofill."""
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .glass import GlassComboBox, glass_panel, plain_label
from .personal import MAX_FIELD, PersonalInfo, PersonalStore, import_resume
from .personal_details import (
    EXPERIENCE_KINDS, LONG_FIELDS, MAX_RECORDS, PREFERENCE_OPTIONS, AnswerPreferences,
    Basics, Education, Experience, Target, filled,
)
from .profile_gui import PrivateIO
from .profile_autofill import merge_resume, organize_resume


PAGES = ("基本资料", "求职目标", "教育经历", "项目与实习", "回答偏好", "AI 规则")
_BASICS = (
    ("name", "姓名"), ("reading", "姓名日语读音"), ("japanese_level", "日语水平"), ("languages", "其他语言能力"),
)
_EDUCATION = (("school", "学校"), ("major", "专业"), ("degree", "学历 / 学位"), ("graduation", "就读 / 毕业时间"))
_TARGET = (
    ("role", "应聘岗位"), ("company", "公司"), ("industry", "行业"), ("location", "工作地点"),
    ("motivation", "志望动机"), ("requirements", "岗位要求 / 公司业务"), ("scenario", "面试场景"),
)
_EXPERIENCE = (
    ("title", "经历名称"), ("kind", "类型"), ("organization", "公司 / 团队"), ("period", "持续时间"),
    ("background", "背景"), ("responsibilities", "我的职责"), ("tools", "使用技术 / 工具"),
    ("challenge", "遇到的问题"), ("actions", "我的解决过程"), ("result", "结果及归属"),
    ("learning", "我的收获"), ("notes", "原文补充"), ("priority", "同等相关时优先引用"),
)
_PREFERENCES = (
    ("level", "回答日语难度"), ("tone", "语气"), ("length", "口述长度"), ("terms", "技术术语"),
    ("translation", "回答译文"),
)


def text_editor(label, height, placeholder=""):
    editor = QPlainTextEdit()
    editor.setAccessibleName(label)
    editor.setPlaceholderText(placeholder)
    editor.setFixedHeight(height)
    return editor


class Fields(QWidget):
    changed = Signal()

    def __init__(self, specs, record_type, *, choices=None):
        super().__init__()
        self.record_type = record_type
        self.editors = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        row, col = 0, 0
        for key, label in specs:
            options = (choices or {}).get(key)
            if options:
                editor = GlassComboBox()
                for value, title in options.items():
                    editor.addItem(title, value)
                editor.currentIndexChanged.connect(self.changed)
            elif key == "priority":
                editor = QCheckBox(label)
                editor.toggled.connect(self.changed)
            elif key in LONG_FIELDS:
                editor = text_editor(label, 66)
                editor.textChanged.connect(self.changed)
            else:
                editor = QLineEdit()
                editor.setMaxLength(MAX_FIELD)
                editor.textChanged.connect(self.changed)
            self.editors[key] = editor
            editor.setAccessibleName(label)
            field = QVBoxLayout()
            field.setSpacing(5)
            if key != "priority":
                field.addWidget(plain_label(label, "muted"))
            field.addWidget(editor)
            if key in LONG_FIELDS or key == "priority":
                if col:
                    row, col = row + 1, 0
                grid.addLayout(field, row, 0, 1, 2)
                row += 1
            else:
                grid.addLayout(field, row, col)
                row, col = (row + 1, 0) if col else (row, 1)

    def load(self, record):
        for key, value in asdict(record).items():
            editor = self.editors[key]
            if isinstance(editor, GlassComboBox):
                editor.setCurrentIndex(editor.findData(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(value)
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlainText(value)
            else:
                editor.setText(value)

    def current(self):
        data = {}
        for name, editor in self.editors.items():
            if isinstance(editor, GlassComboBox):
                data[name] = editor.currentData()
            elif isinstance(editor, QCheckBox):
                data[name] = editor.isChecked()
            elif isinstance(editor, QPlainTextEdit):
                data[name] = editor.toPlainText().strip()
            else:
                data[name] = editor.text().strip()
        return self.record_type(**data)


class RecordCard(QFrame):
    changed = Signal()
    removed = Signal()

    def __init__(self, record, specs, options, *, selectable=False, expanded=False):
        super().__init__()
        self.setObjectName("glassInset")
        self.fields = Fields(specs, type(record), choices=options)
        self.fields.load(record)
        self.title = plain_label("", "sectionTitle")
        self.summary = plain_label("", "muted")
        self.edit = QPushButton("编辑")
        self.edit.setCheckable(True)
        self.remove = QPushButton("移除")
        self.active = QRadioButton("用于下次面试") if selectable else None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.edit)
        layout.addLayout(header)
        layout.addWidget(self.summary)
        if self.active is not None:
            layout.addWidget(self.active)
        self.edit_area = QWidget()
        editor_layout = QVBoxLayout(self.edit_area)
        editor_layout.setContentsMargins(0, 2, 0, 0)
        editor_layout.addWidget(self.fields)
        editor_layout.addWidget(self.remove, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.edit_area)
        self.edit_area.setVisible(expanded)
        self.edit.toggled.connect(self.toggle_edit)
        self.edit.setChecked(expanded)
        self.remove.clicked.connect(self.removed)
        self.fields.changed.connect(self.update_preview)
        self.update_preview()

    def toggle_edit(self, expanded):
        self.edit_area.setVisible(expanded)
        self.edit.setText("收起" if expanded else "编辑")

    def update_preview(self):
        record = self.fields.current()
        if isinstance(record, Experience):
            title = record.title or record.organization or "新经历"
            meta = " · ".join(part for part in (EXPERIENCE_KINDS[record.kind], record.organization, record.period) if part)
            detail = [f"{label}  {value[:156]}" for label, value in (
                ("职责", record.responsibilities), ("工具", record.tools),
            ) if value]
            summary = "\n".join((meta, *detail))
        elif isinstance(record, Education):
            title = record.school or "新教育经历"
            summary = " · ".join(part for part in (record.major, record.degree, record.graduation) if part)
        else:
            title = record.role or record.company or "新求职目标"
            summary = " · ".join(part for part in (record.company, record.industry, record.location) if part and part != title)
        self.title.setText(title)
        self.summary.setText(summary)
        self.summary.setVisible(bool(summary))
        self.changed.emit()


class RecordList(QWidget):
    changed = Signal()

    def __init__(self, record_type, specs, caption, *, options=None, selectable=False):
        super().__init__()
        self.record_type, self.specs, self.options = record_type, specs, options
        self.cards = []
        self.group = QButtonGroup(self) if selectable else None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        self.empty = plain_label("暂无记录", "muted")
        self.layout.addWidget(self.empty)
        self.add_button = QPushButton(caption)
        self.layout.addWidget(self.add_button)
        self.add_button.clicked.connect(lambda: self.add(self.record_type(), expanded=True))

    def add(self, record, *, expanded=False):
        if len(self.cards) >= MAX_RECORDS:
            return
        card = RecordCard(record, self.specs, self.options, selectable=self.group is not None, expanded=expanded)
        self.cards.append(card)
        self.layout.insertWidget(self.layout.count() - 1, card)
        card.changed.connect(self.changed)
        card.removed.connect(lambda: self.remove(card))
        if self.group is not None:
            self.group.addButton(card.active)
            card.active.toggled.connect(self.changed)
            if self.group.checkedButton() is None:
                card.active.setChecked(True)
        self.changed_list()

    def remove(self, card):
        self.cards.remove(card)
        if self.group is not None:
            self.group.removeButton(card.active)
            if self.group.checkedButton() is None and self.cards:
                self.cards[0].active.setChecked(True)
        self.layout.removeWidget(card)
        card.hide()
        card.deleteLater()
        self.changed_list()

    def changed_list(self):
        self.empty.setVisible(not self.cards)
        self.add_button.setEnabled(len(self.cards) < MAX_RECORDS)
        self.changed.emit()

    def load(self, records, active=0):
        for card in list(self.cards):
            self.remove(card)
        for record in records:
            self.add(record)
        if self.group is not None and self.cards:
            self.cards[active].active.setChecked(True)

    def current(self):
        return tuple(value for card in self.cards if filled(value := card.fields.current()))

    def active_index(self):
        if self.group is None:
            return 0
        cards = [card for card in self.cards if filled(card.fields.current())]
        return next((index for index, card in enumerate(cards) if card.active.isChecked()), 0)


class PersonalPane(QWidget):
    saved_changed = Signal(object)
    busy_changed = Signal(bool)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.loaded = False
        self.loading_form = False
        self.closing = False
        self.saved = PersonalInfo()
        self.state = "idle"
        self.import_button = QPushButton("导入简历")
        self.import_button.setToolTip("选择带文字层的 PDF，也支持 DOCX 和 TXT。")
        self.save = QPushButton("保存个人信息")
        self.save.setObjectName("primaryAction")
        self.status = plain_label("", "muted")
        self.listening_status = plain_label("", "muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        header = QHBoxLayout()
        header.addWidget(plain_label("个人信息", "pageTitle"), 1)
        header.addWidget(self.listening_status)
        header.addWidget(self.import_button)
        layout.addLayout(header)

        columns = QHBoxLayout()
        columns.setSpacing(15)
        sidebar = glass_panel("glassInset")
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(8, 10, 8, 10)
        navigation.setSpacing(5)
        self.navigation = QButtonGroup(self)
        for index, label in enumerate(PAGES):
            button = QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            self.navigation.addButton(button, index)
            navigation.addWidget(button)
        navigation.addStretch(1)
        columns.addWidget(sidebar)
        self.pages = QStackedWidget()
        columns.addWidget(self.pages, 1)
        layout.addLayout(columns, 1)

        basics = self.page(PAGES[0])
        self.basics = Fields(_BASICS, Basics, choices={"japanese_level": {
            "": "未填写", **{level: level for level in PREFERENCE_OPTIONS["level"] if level},
        }})
        basics.addWidget(self.basics)
        self.background = text_editor("自我介绍", 85, "可补充背景或简短自我介绍")
        basics.addWidget(plain_label("个人背景", "muted"))
        basics.addWidget(self.background)
        self.raw_toggle = QPushButton("查看或粘贴简历原文")
        self.raw_toggle.setCheckable(True)
        basics.addWidget(self.raw_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.raw_panel = QWidget()
        raw_layout = QVBoxLayout(self.raw_panel)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        self.resume = text_editor("简历原文", 128, "可粘贴带栏目标题的中、日、英简历")
        raw_layout.addWidget(self.resume)
        self.fill_from_text = QPushButton("从原文填充")
        self.clear_resume = QPushButton("清空原文")
        tools = QHBoxLayout()
        tools.addWidget(self.fill_from_text)
        tools.addWidget(self.clear_resume)
        tools.addStretch(1)
        raw_layout.addLayout(tools)
        basics.addWidget(self.raw_panel)
        self.raw_panel.hide()
        self.raw_toggle.toggled.connect(self.raw_panel.setVisible)
        basics.addStretch(1)

        targets = self.page(PAGES[1])
        self.targets = RecordList(Target, _TARGET, "添加求职目标", selectable=True)
        targets.addWidget(self.targets)
        targets.addStretch(1)
        education = self.page(PAGES[2])
        self.education = RecordList(Education, _EDUCATION, "添加教育经历")
        education.addWidget(self.education)
        education.addStretch(1)
        experiences = self.page(PAGES[3])
        experiences.addWidget(plain_label("填写实际职责、解决过程和结果，便于面试时按问题引用。", "muted"))
        self.experiences = RecordList(Experience, _EXPERIENCE, "添加项目、实习或工作经历",
                                      options={"kind": EXPERIENCE_KINDS})
        experiences.addWidget(self.experiences)
        experiences.addStretch(1)
        preferences = self.page(PAGES[4])
        self.preferences = Fields(_PREFERENCES, AnswerPreferences, choices=PREFERENCE_OPTIONS)
        preferences.addWidget(self.preferences)
        preferences.addStretch(1)
        rules = self.page(PAGES[5])
        for title, explanation in (
            ("个人职责与团队成果", "只使用已保存资料支持的事实，明确区分我做了什么和团队取得的结果。"),
            ("按问题选经历", "先按题目和追问匹配项目、技术和职责。相关度相同时，优先选标记为「优先引用」的经历。"),
            ("保留真实细节", "行为题根据已有背景、行动和结果组织。技术题直接回答原理，涉及实际经验时引用对应事实。"),
            ("信息不足时", "关键细节不明时，用假设、通用方法或澄清问题回应。"),
        ):
            rules.addWidget(plain_label(title, "sectionTitle"))
            rules.addWidget(plain_label(explanation, "muted"))
        rules.addStretch(1)

        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.save.setToolTip("保存到本机。开始面试后，仅向所选文本服务发送回答所需的已保存资料。")
        self.navigation.button(0).setChecked(True)
        self.navigation.idClicked.connect(self.pages.setCurrentIndex)
        self.import_button.clicked.connect(self.choose_resume)
        self.fill_from_text.clicked.connect(self.fill_resume_text)
        self.clear_resume.clicked.connect(self.resume.clear)
        self.save.clicked.connect(self.save_info)
        for form in (self.basics, self.targets, self.education, self.experiences, self.preferences):
            form.changed.connect(self.form_changed)
        for editor in (self.background, self.resume):
            editor.textChanged.connect(self.form_changed)
        self.run_io(lambda: PersonalStore().load(), self.load_info, "正在读取本机资料…")

    def page(self, title):
        scroll = QScrollArea()
        scroll.setObjectName("captionScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("captionContent")
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(4, 2, 9, 4)
        page.setSpacing(13)
        page.addWidget(plain_label(title, "sectionTitle"))
        self.pages.addWidget(scroll)
        return page

    def current(self):
        targets = self.targets.current()
        active = self.targets.active_index()
        target = targets[active] if targets else Target()
        return PersonalInfo(
            background=self.background.toPlainText().strip(), resume=self.resume.toPlainText().strip(),
            company=target.company, role=target.role, scenario=target.scenario, basics=self.basics.current(),
            education=self.education.current(), targets=targets, active_target=active,
            experiences=self.experiences.current(), preferences=self.preferences.current(),
        )

    def populate(self, info):
        self.loading_form = True
        try:
            self.background.setPlainText(info.background)
            self.resume.setPlainText(info.resume)
            self.basics.load(info.basics)
            self.preferences.load(info.preferences)
            self.education.load(info.education)
            self.experiences.load(info.experiences)
            targets = info.targets
            if not targets and (info.company or info.role or info.scenario):
                targets = (Target(company=info.company, role=info.role, scenario=info.scenario),)
            self.targets.load(targets, info.active_target)
        finally:
            self.loading_form = False

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
        self.populate(info)
        self.saved = self.current()
        self.loaded = True
        self.status.setText("资料保存在本机。")
        self.saved_changed.emit(info)

    def choose_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入简历", "", "PDF 简历 (*.pdf);;简历文档 (*.pdf *.docx *.txt)",
        )
        if path:
            self.run_io(lambda: organize_resume(import_resume(Path(path))), self.resume_imported, "正在本机读取并整理简历…")

    def fill_resume_text(self):
        text = self.resume.toPlainText().strip()
        if text:
            self.run_io(lambda: organize_resume(text), self.resume_imported, "正在本机整理简历…")

    @Slot(object)
    def resume_imported(self, imported):
        self.populate(merge_resume(self.current(), imported))
        self.status.setText("已填入可识别的内容。核对后保存。" if (
            filled(imported.basics) or imported.education or imported.experiences or imported.targets
        ) else "已保留原文。可在对应栏目手动填写。")

    def save_info(self):
        if not self.save.isEnabled():
            return
        info = self.current()

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
        if self.loading_form:
            return
        self.update_controls()
        if self.loaded and self.worker is None:
            self.status.setText("有未保存的修改。" if self.save.isEnabled() else "资料已保存到本机。")

    @Slot(str)
    def session_state(self, state):
        self.state = state
        self.update_controls()

    def update_controls(self):
        editable = self.loaded and self.worker is None and not self.closing and self.state == "idle"
        for widget in (self.basics, self.background, self.resume, self.targets, self.education, self.experiences,
                       self.preferences, self.import_button):
            widget.setEnabled(editable)
        has_text = bool(self.resume.toPlainText().strip())
        self.clear_resume.setEnabled(editable and has_text)
        self.fill_from_text.setEnabled(editable and has_text)
        self.save.setEnabled(editable and self.current() != self.saved)
        self.listening_status.setText({"active": "监听中", "paused": "监听已暂停"}.get(self.state, ""))

    def shutdown(self):
        self.closing = True
        self.update_controls()
        return self.worker is None

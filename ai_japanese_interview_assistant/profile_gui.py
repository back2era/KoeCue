"""Local profile editor and explicit per-session sharing."""
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHeaderView, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from .profiles import CATEGORIES, Fact, ProfileError, ProfileStore, validate_facts


LABELS = ("教育背景", "技能", "工作经历", "项目经历", "求职岗位")


class PrivateIO(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation())
        except ProfileError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("无法访问本地资料或 Windows 凭据。")
        finally:
            self.operation = None


class ProfileDialog(QDialog):
    authorized = Signal(object)
    changed = Signal(object)

    def __init__(self, approved, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本地资料与会话授权")
        self.resize(900, 430)
        self.approved = {fact.id: fact for fact in approved}
        self.worker = None
        self.loaded = False
        self.saved = ()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["本次分享", "类别", "日语事实句", "中文事实句", "关键词"])
        header = self.table.horizontalHeader()
        for index in (2, 3, 4):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        self.add = QPushButton("新增条目")
        self.remove = QPushButton("删除所选")
        self.save = QPushButton("保存到本地")
        self.share = QPushButton("授权勾选条目")
        self.close_button = QPushButton("关闭")
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        note = QLabel("请填写你核对过的日语和中文事实句。保存留在本机。授权后，生成答案时才会按问题选用。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        for button in (self.add, self.remove, self.save, self.share, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.add.clicked.connect(self.add_blank)
        self.remove.clicked.connect(self.remove_selected)
        self.save.clicked.connect(self.save_profile)
        self.share.clicked.connect(self.share_profile)
        self.close_button.clicked.connect(self.reject)
        self.run_io(lambda: ProfileStore().load(), self.load_profile, "正在读取本地资料…")

    def run_io(self, operation, success, progress):
        self.status.setText(progress)
        self.worker = PrivateIO(operation, self)
        self.worker.result.connect(success)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.io_finished)
        self.set_controls()
        self.worker.start()

    def set_controls(self):
        ready = self.loaded and self.worker is None
        for widget in (self.add, self.remove, self.save, self.share, self.table):
            widget.setEnabled(ready)
        self.close_button.setEnabled(self.worker is None)

    def io_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_controls()

    def reject(self):
        if self.worker is None:
            super().reject()

    @Slot(object)
    def load_profile(self, facts):
        self.saved = facts
        for fact in facts:
            self.add_row(fact)
        self.loaded = True
        self.status.setText("选择类别并输入两种语言。可用英文逗号分隔关键词。")

    def add_blank(self):
        self.add_row(Fact(uuid4().hex, "education", "", ""))

    def add_row(self, fact):
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked if self.approved.get(fact.id) == fact else Qt.CheckState.Unchecked)
        check.setData(Qt.ItemDataRole.UserRole, fact.id)
        self.table.setItem(row, 0, check)
        category = QComboBox()
        for code, label in zip(CATEGORIES, LABELS):
            category.addItem(label, code)
        category.setCurrentIndex(category.findData(fact.category))
        self.table.setCellWidget(row, 1, category)
        for column, value in enumerate((fact.ja, fact.zh, ", ".join(fact.tags)), start=2):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def remove_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def table_facts(self):
        facts = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            tags = self.table.item(row, 4).text().replace("，", ",")
            facts.append(Fact(
                item.data(Qt.ItemDataRole.UserRole), self.table.cellWidget(row, 1).currentData(),
                self.table.item(row, 2).text().strip(), self.table.item(row, 3).text().strip(),
                tuple(tag.strip() for tag in tags.split(",") if tag.strip()),
            ))
        validate_facts(facts)
        return tuple(facts)

    def save_profile(self):
        try:
            facts = self.table_facts()
        except ProfileError as exc:
            self.status.setText(str(exc))
            return

        def save():
            ProfileStore().save(facts)
            return facts

        self.run_io(save, self.on_saved, "正在保存本地资料…")

    @Slot(object)
    def on_saved(self, facts):
        if self.saved != facts:
            self.changed.emit(facts)
        self.saved = facts
        self.status.setText("已保存到本地。可单独授权勾选的条目。")

    def share_profile(self):
        try:
            facts = self.table_facts()
        except ProfileError as exc:
            self.status.setText(str(exc))
            return
        if facts != self.saved:
            self.status.setText("请先保存资料，再授权。")
            return
        approved = tuple(
            fact for row, fact in enumerate(facts)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        )
        self.authorized.emit(approved)
        self.accept()

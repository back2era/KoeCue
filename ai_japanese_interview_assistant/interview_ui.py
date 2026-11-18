"""Live interview presentation shared by the main and compact windows."""
from datetime import datetime
from html import escape

from PySide6.QtCore import QRect, QSize, Qt, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .answer_display import compact_annotations, paragraph_breaks, preview_end
from .glass import active_theme, plain_label, quiet_button, set_role
from .ruby_label import RubyLabel
from .themes import GAP, INSET, JAPANESE_FONTS, PANEL_RADIUS, TEXT_ANSWER, TEXT_BODY, TEXT_SMALL


def japanese_font(widget):
    font = widget.font()
    font.setFamilies(list(JAPANESE_FONTS))
    widget.setFont(font)


class CaptionLabel(QLabel):
    clipping_changed = Signal()

    def __init__(self, placeholder, *, translated=False, line_limit=0):
        super().__init__()
        self.setObjectName("translatedCaption" if translated else "captionText")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        if not translated:
            japanese_font(self)
        self.placeholder = placeholder
        self.line_limit = line_limit
        self.clipped = False
        self.tail = False
        self.shown = ""
        self.target = ""
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.reveal_next)
        self.setText(placeholder)

    def set_caption(self, text, *, animate=False, tail=False):
        if text == self.target and tail == self.tail and (animate or self.shown == text):
            return
        self.tail = tail
        if not animate or not text.startswith(self.target):
            self.target = self.shown = text
            self.timer.stop()
            self.show_text()
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
        self.show_text()
        if self.shown == self.target:
            self.timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.line_limit:
            self.show_text()

    def limit_lines(self, limit):
        if self.line_limit != limit:
            self.line_limit = limit
            self.show_text()

    def show_text(self):
        text = self.shown or self.placeholder
        clipped = text
        if self.tail and self.width() > 0:
            clipped = self.fontMetrics().elidedText(
                " ".join(text.splitlines()), Qt.TextElideMode.ElideLeft, self.width(),
            )
        elif self.line_limit and self.width() > 0:
            layout = QTextLayout(text, self.font())
            options = QTextOption(Qt.AlignmentFlag.AlignLeft)
            options.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(options)
            utf16 = text.encode("utf-16-le")
            layout.beginLayout()
            for _ in range(self.line_limit):
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(self.width())
                end = line.textStart() + line.textLength()
                if end * 2 < len(utf16):
                    start = line.textStart() * 2
                    tail = utf16[start:].decode("utf-16-le").replace("\n", " ")
                    clipped = utf16[:start].decode("utf-16-le") + self.fontMetrics().elidedText(
                        tail, Qt.TextElideMode.ElideRight, self.width(),
                    )
                else:
                    clipped = text
            layout.endLayout()
        if self.text() != clipped:
            self.setText(clipped)
        was_clipped = self.clipped
        self.clipped = clipped != text
        self.setToolTip(f"<qt>{escape(text)}</qt>" if self.clipped else "")
        self.setAccessibleDescription(text)
        if was_clipped != self.clipped:
            self.clipping_changed.emit()


class TranscriptionPanel(QWidget):
    def __init__(self, *, compact=False):
        super().__init__()
        self.title = plain_label("面试官", "eyebrow")
        self.original_state = plain_label("", "captionState")
        self.translation_state = plain_label("", "captionState")
        self.preview_limits = (3, 2)
        self.original = CaptionLabel("等待日语语音…", line_limit=2 if compact else 3)
        self.translated = CaptionLabel(
            "" if compact else "等待中文译文…", translated=True, line_limit=1 if compact else 2,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        heading.addWidget(self.title, 1)
        heading.addWidget(self.original_state)
        if not compact:
            self.expand = quiet_button(QPushButton("展开字幕"))
            self.expand.setCheckable(True)
            self.expand.hide()
            self.expand.toggled.connect(self.expand_captions)
            self.original.clipping_changed.connect(self.update_expand)
            self.translated.clipping_changed.connect(self.update_expand)
            heading.addWidget(self.expand)
        layout.addLayout(heading)
        layout.addWidget(self.original)
        layout.addWidget(self.translated)
        if not compact:
            layout.addWidget(self.translation_state)
        else:
            self.translated.hide()

    def expand_captions(self, expanded):
        original, translated = (0, 0) if expanded else self.preview_limits
        self.original.limit_lines(original)
        self.translated.limit_lines(translated)
        self.update_expand()

    def set_preview_limits(self, original, translated):
        limits = original, translated
        if self.preview_limits != limits:
            self.preview_limits = limits
            self.expand_captions(self.expand.isChecked())

    def update_expand(self):
        expanded = self.expand.isChecked()
        self.expand.setText("收起字幕" if expanded else "展开字幕")
        self.expand.setVisible(expanded or self.original.clipped or self.translated.clipped)


class KeywordLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.term = ""
        self.setObjectName("keyword")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(24)
        self.setMaximumWidth(152)
        japanese_font(self)

    def set_term(self, term):
        self.term = term
        self.setToolTip(f"<qt>{escape(term)}</qt>" if term else "")
        self.setAccessibleName(term)
        self.update_text()
        self.updateGeometry()
        self.setVisible(bool(term))

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(min(self.maximumWidth(), self.fontMetrics().horizontalAdvance(self.term) + 16))
        return size

    def minimumSizeHint(self):
        return QSize(24, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_text()

    def update_text(self):
        text = self.fontMetrics().elidedText(self.term, Qt.TextElideMode.ElideRight, max(0, self.width() - 16))
        if self.text() != text:
            self.setText(text)


class AnswerPanel(QWidget):
    def __init__(self, *, compact=False):
        super().__init__()
        self.compact = compact
        self.data = None
        self.row_key = None
        self.placeholder = None
        self.heading = plain_label("AI 推荐回答", "sectionTitle")
        self.japanese = RubyLabel()
        japanese_font(self.japanese)
        font = self.japanese.font()
        font.setPixelSize(TEXT_ANSWER)
        self.japanese.setFont(font)
        self.japanese.setAccessibleName("日语回答")
        self.translation = plain_label("", "answerTranslation")
        self.translation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status = plain_label("", "captionState")
        self.expand = quiet_button(QPushButton("展开全文"))
        self.expand.setCheckable(True)
        self.annotations = quiet_button(QPushButton("全部标注"))
        self.annotations.setCheckable(True)
        self.annotations.setToolTip("在重点读音和全部读音之间切换")
        self.copy = quiet_button(QPushButton("复制回答"))
        self.copy.setToolTip("复制完整的日语回答与中文译文")
        self.keywords = QWidget()
        self.keywords.setAccessibleName("回答关键词")
        chips = QHBoxLayout(self.keywords)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(GAP)
        self.tags = [KeywordLabel() for _ in range(3)]
        for tag in self.tags:
            chips.addWidget(tag)
        chips.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4 if compact else GAP)
        heading = QHBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(self.heading, 1)
        if compact:
            heading.addWidget(self.expand)
        heading.addWidget(self.copy)
        layout.addLayout(heading)
        layout.addWidget(self.status)
        layout.addWidget(self.keywords)
        layout.addWidget(self.japanese)
        layout.addWidget(self.translation)
        actions = QHBoxLayout()
        if not compact:
            actions.addWidget(self.expand)
        actions.addWidget(self.annotations)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.expand.toggled.connect(self.render)
        self.annotations.toggled.connect(self.render)
        self.copy.clicked.connect(self.copy_answer)
        self.copied = QTimer(self)
        self.copied.setSingleShot(True)
        self.copied.timeout.connect(lambda: self.copy.setText("复制回答"))

    def set_content(self, key, answer, status, placeholder, *, prior=False):
        heading = "上一段回答" if prior else "AI 推荐回答"
        if (key, answer, status, placeholder, heading) == (
            self.row_key, self.data, self.status.text(), self.placeholder, self.heading.text(),
        ):
            return
        if key != self.row_key:
            self.row_key = key
            with QSignalBlocker(self.expand), QSignalBlocker(self.annotations):
                self.expand.setChecked(False)
                self.annotations.setChecked(False)
            self.copied.stop()
            self.copy.setText("复制回答")
        self.data = answer
        self.placeholder = placeholder
        self.heading.setText(heading)
        self.status.setText(status)
        self.status.setVisible(bool(status) and status != "建议已生成")
        self.render()

    def render(self):
        answer = self.data
        text = self.placeholder
        annotations = highlights = breaks = ()
        words = ()
        self.copy.setVisible(answer is not None)
        if answer:
            cutoff = preview_end(answer.ja)
            expanded = self.expand.isChecked()
            text = answer.ja if expanded else answer.ja[:cutoff].rstrip()
            highlights = tuple(h for h in answer.highlights if h.end <= len(text))
            spans = tuple(a for a in answer.annotations if a.end <= len(text))
            compact = compact_annotations(text, spans, highlights)
            annotations = spans if self.annotations.isChecked() else compact
            breaks = paragraph_breaks(text)
            words = tuple(dict.fromkeys(text[span.start:span.end] for span in highlights))[:3]
            has_more = cutoff < len(answer.ja)
            self.expand.setVisible(has_more or (self.compact and bool(answer.zh)))
            if has_more:
                self.expand.setText("收起全文" if expanded else "展开全文")
            else:
                self.expand.setText("收起译文" if expanded else "查看译文")
            self.annotations.setVisible(not self.compact and len(compact) < len(spans))
            self.annotations.setText("收起标注" if self.annotations.isChecked() else "全部标注")
            self.translation.setText(answer.zh)
            self.translation.setVisible(
                bool(answer.zh) and (expanded or (not self.compact and cutoff == len(answer.ja))),
            )
        else:
            self.expand.hide()
            self.annotations.hide()
            self.translation.clear()
            self.translation.hide()
        for index, tag in enumerate(self.tags):
            tag.set_term(words[index] if index < len(words) else "")
        self.keywords.setVisible(bool(words))
        set_role(self.japanese, "empty", answer is None)
        self.japanese.set_answer(text, annotations, highlights=highlights, paragraph_breaks=breaks)

    def copy_answer(self):
        if self.data:
            QApplication.clipboard().setText(f"{self.data.ja}\n\n{self.data.zh}")
            self.copy.setText("已复制")
            self.copied.start(1400)


_RESCUE_PHRASES = (
    ("そうですね、少し考えさせてください。", "请让我想一想。"),
    ("すみません、もう一度お願いします。", "不好意思，能再说一遍吗？"),
    ("つまり、〇〇ということでしょうか？", "您的意思是……吗？"),
    ("うまく説明できないのですが……", "我可能解释得不太好……"),
    ("もう一つあります。", "我还有一点想补充。"),
)


class RescuePhrases(QWidget):
    def __init__(self, *, compact=False):
        super().__init__()
        heading = QHBoxLayout()
        heading.addWidget(plain_label("救场句", "eyebrow"), 1)
        more = quiet_button(QPushButton("更多"))
        more.setAccessibleName("选择救场句")
        menu = QMenu(more)
        for jp, zh in _RESCUE_PHRASES:
            menu.addAction(f"{jp}  {zh}", lambda checked=False, jp=jp, zh=zh: self.show_phrase(jp, zh))
        more.setMenu(menu)
        heading.addWidget(more)
        self.japanese = CaptionLabel("", line_limit=1) if compact else plain_label("", "sectionTitle")
        if compact:
            self.japanese.setObjectName("compactRescue")
        japanese_font(self.japanese)
        self.japanese.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.chinese = plain_label("", "muted")
        self.chinese.setVisible(not compact)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if compact:
            heading.insertWidget(1, self.japanese, 5)
        else:
            layout.addWidget(self.japanese)
            layout.addWidget(self.chinese)
        layout.insertLayout(0, heading)
        self.show_phrase(*_RESCUE_PHRASES[0])

    def show_phrase(self, jp, zh):
        if isinstance(self.japanese, CaptionLabel):
            self.japanese.set_caption(jp)
        else:
            self.japanese.setText(jp)
            self.japanese.setToolTip(zh)
        self.chinese.setText(zh)


_TURN_ROLE = Qt.ItemDataRole.UserRole + 1


class ConversationItem(QListWidgetItem):
    def __init__(self, time=None):
        super().__init__()
        self.time = time or datetime.now().strftime("%H:%M:%S")
        self.setSizeHint(QSize(0, 76))

    def set_turn(self, ja, zh, status):
        data = (self.time, ja, zh, status)
        if self.data(_TURN_ROLE) != data:
            self.setData(_TURN_ROLE, data)
            accessible = "\n".join(filter(None, data))
            self.setText(accessible)
            self.setToolTip(f"<qt>{escape(accessible).replace(chr(10), '<br>')}</qt>")


class ConversationDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        time, ja, zh, status = index.data(_TURN_ROLE)
        theme = active_theme()
        selected = option.state & QStyle.StateFlag.State_Selected
        focus = option.state & QStyle.StateFlag.State_HasFocus
        hover = option.state & QStyle.StateFlag.State_MouseOver
        rect = option.rect.adjusted(2, 2, -2, -2)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        if selected or hover:
            painter.setPen(QPen(QColor(theme.accent)) if focus else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.selection if selected else theme.elevated))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), PANEL_RADIUS - 4, PANEL_RADIUS - 4)
        elif focus:
            painter.setPen(QColor(theme.accent))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), PANEL_RADIUS - 4, PANEL_RADIUS - 4)
        if selected:
            painter.fillRect(rect.left() + 3, rect.top() + INSET, 2, rect.height() - 2 * INSET, QColor(theme.accent))
        column = rect.adjusted(12, 0, -10, 0)
        font = option.font
        font.setPixelSize(TEXT_SMALL)
        painter.setFont(font)
        painter.setPen(QColor(theme.secondary))
        normal = {"日语定稿", "已翻译", "建议已生成"}
        details = [state for state in status.split(" · ") if state and state not in normal]
        header = "   ·   ".join((time, *details))
        self.draw_line(painter, column, 7, 16, header)
        font.setPixelSize(TEXT_BODY)
        font.setFamilies(list(JAPANESE_FONTS))
        painter.setFont(font)
        painter.setPen(QColor(theme.text))
        self.draw_line(painter, column, 25, 20, ja or "转写失败")
        font = option.font
        font.setPixelSize(TEXT_SMALL)
        painter.setFont(font)
        painter.setPen(QColor(theme.secondary))
        self.draw_line(painter, column, 48, 16, zh)
        painter.restore()

    @staticmethod
    def draw_line(painter, rect, offset, height, text):
        line = QRect(rect.x(), rect.y() + offset, rect.width(), height)
        text = QFontMetrics(painter.font()).elidedText(" ".join(text.splitlines()), Qt.TextElideMode.ElideRight, line.width())
        painter.drawText(line, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class ConversationList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("conversationList")
        self.setAccessibleName("历史对话")
        self.setMinimumHeight(96)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerItem)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(ConversationDelegate(self))

    def resizeEvent(self, event):
        scroll = self.verticalScrollBar()
        following = self.count() and self.currentRow() == self.count() - 1 and scroll.value() == scroll.maximum()
        super().resizeEvent(event)
        if following:
            self.scrollToBottom()

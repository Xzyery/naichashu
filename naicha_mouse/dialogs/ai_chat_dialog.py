"""AI chat dialog."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from naicha_mouse.constants import FONT_FAMILY


class AiChatDialog(QDialog):
    send_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("和奶茶鼠聊天")
        self.setModal(False)
        self.setMinimumSize(420, 380)

        title = QLabel("和奶茶鼠聊天")
        title.setObjectName("title")

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setPlaceholderText("奶茶鼠在这里等你说话。")

        self.input_edit = QTextEdit()
        self.input_edit.setFixedHeight(82)
        self.input_edit.setPlaceholderText("在气泡里输入想说的话...")

        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.emit_send)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear_requested.emit)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.chat_view)
        layout.addWidget(self.input_edit)
        layout.addLayout(button_row)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: #fff8ee;
                color: #6f4b3e;
                font-family: {FONT_FAMILY};
            }}
            QLabel#title {{
                font-size: 17px;
                font-weight: 700;
                color: #6f4b3e;
            }}
            QTextEdit {{
                border: 2px solid rgba(188, 132, 103, 220);
                border-radius: 13px;
                background: #fffdf8;
                color: #4d342b;
                padding: 9px 11px;
                font-size: 13px;
                selection-background-color: #f4d7b6;
            }}
            QTextEdit:focus {{
                border: 2px solid #c58761;
            }}
            QPushButton {{
                min-width: 82px;
                min-height: 32px;
                border: 1px solid #c99772;
                border-radius: 8px;
                padding: 5px 14px;
                background: #f8dfc3;
                color: #6f4b3e;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #f1cda7;
            }}
            QPushButton:disabled {{
                background: #ead9c8;
                color: #a58d7f;
            }}
            """
        )

    def emit_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self.send_requested.emit(text)

    def append_line(self, speaker: str, text: str) -> None:
        old = self.chat_view.toPlainText().strip()
        line = f"{speaker}：{text.strip()}"
        self.chat_view.setPlainText(f"{old}\n\n{line}" if old else line)
        self.chat_view.moveCursor(self.chat_view.textCursor().End)

    def replace_last_line(self, speaker: str, text: str) -> None:
        content = self.chat_view.toPlainText().strip()
        if not content:
            self.append_line(speaker, text)
            return
        chunks = content.split("\n\n")
        chunks[-1] = f"{speaker}：{text.strip()}"
        self.chat_view.setPlainText("\n\n".join(chunks))
        self.chat_view.moveCursor(self.chat_view.textCursor().End)

    def set_waiting(self, waiting: bool) -> None:
        self.send_button.setEnabled(not waiting)
        self.input_edit.setEnabled(not waiting)

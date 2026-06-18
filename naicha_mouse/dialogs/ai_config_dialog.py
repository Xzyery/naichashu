"""AI configuration dialog."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from naicha_mouse.constants import FONT_FAMILY


class AiConfigDialog(QDialog):
    def __init__(self, config: dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 聊天配置")
        self.setModal(True)
        self.setMinimumWidth(460)

        self.provider_input = QComboBox()
        self.provider_input.addItem("OpenAI / DeepSeek / OpenAI 兼容", "openai")
        self.provider_input.addItem("Anthropic Claude Messages", "anthropic")
        self.provider_input.addItem("Google Gemini generateContent", "gemini")
        provider = config.get("provider", "openai")
        index = self.provider_input.findData(provider)
        self.provider_input.setCurrentIndex(max(0, index))
        self.base_url_input = QLineEdit(config.get("base_url", ""))
        self.base_url_input.setPlaceholderText("https://api.openai.com/v1")
        self.model_input = QLineEdit(config.get("model", ""))
        self.model_input.setPlaceholderText("gpt-4.1-mini / deepseek-chat")
        self.api_key_input = QLineEdit(config.get("api_key", ""))
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.setEchoMode(QLineEdit.Password)

        title = QLabel("奶茶鼠 AI 聊天")
        title.setObjectName("title")
        subtitle = QLabel("一次填好接口格式、地址、模型名和 Key；支持 OpenAI 兼容、Anthropic、Gemini。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.addRow("接口格式", self.provider_input)
        form.addRow("Base URL", self.base_url_input)
        form.addRow("模型名", self.model_input)
        form.addRow("API Key", self.api_key_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_button = buttons.button(QDialogButtonBox.Save)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if save_button:
            save_button.setText("保存")
        if cancel_button:
            cancel_button.setText("取消")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: #fff8ee;
                color: #6f4b3e;
                font-family: {FONT_FAMILY};
            }}
            QLabel#title {{
                font-size: 18px;
                font-weight: 700;
                color: #6f4b3e;
            }}
            QLabel#subtitle {{
                color: #9b735f;
                font-size: 12px;
                line-height: 130%;
            }}
            QLabel {{
                color: #6f4b3e;
                font-size: 13px;
            }}
            QLineEdit, QComboBox {{
                min-height: 32px;
                border: 1px solid #d7aa86;
                border-radius: 7px;
                padding: 5px 9px;
                background: #fffdf8;
                color: #4d342b;
                selection-background-color: #f4d7b6;
            }}
            QLineEdit:focus {{
                border: 2px solid #c58761;
                padding: 4px 8px;
            }}
            QComboBox::drop-down {{
                border: 0;
                width: 24px;
            }}
            QPushButton {{
                min-width: 78px;
                min-height: 30px;
                border: 1px solid #c99772;
                border-radius: 7px;
                padding: 5px 12px;
                background: #f8dfc3;
                color: #6f4b3e;
            }}
            QPushButton:hover {{
                background: #f1cda7;
            }}
            QPushButton:pressed {{
                background: #e9ba8e;
            }}
            """
        )

    def values(self) -> dict[str, str]:
        return {
            "provider": str(self.provider_input.currentData() or "openai"),
            "base_url": self.base_url_input.text().strip(),
            "model": self.model_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
        }

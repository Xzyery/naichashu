"""NaichaMouse — 奶茶鼠桌宠 (Milk Tea Mouse Desktop Pet)."""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from naicha_mouse.pet_widget import NaichaMouse


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = NaichaMouse()
    pet.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())

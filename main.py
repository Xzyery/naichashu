"""NaichaMouse — 奶茶鼠桌宠 (Milk Tea Mouse Desktop Pet)."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from naicha_mouse.pet_widget import NaichaMouse


def _load_app_icon() -> QIcon:
    candidates = [
        Path(__file__).resolve().parent / "IMG_5791" / "静态卖萌.png",
        Path(__file__).resolve().parent / "app_icon.ico",
    ]
    for path in candidates:
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


def _configure_macos_app() -> None:
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory  # type: ignore[import-untyped]

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        pass


def _create_macos_tray(app: QApplication, pet: NaichaMouse, icon: QIcon) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("奶茶鼠")

    menu = QMenu()
    toggle_action = QAction("", menu)
    summon_action = QAction("召唤回来", menu)
    status_action = QAction("状态面板", menu)
    quit_action = QAction("退出", menu)

    toggle_action.triggered.connect(pet.toggle_visibility_from_tray)
    summon_action.triggered.connect(lambda: (pet.show_from_tray(), pet.summon_back()))
    status_action.triggered.connect(lambda: (pet.show_from_tray(), pet.show_status_panel()))
    quit_action.triggered.connect(pet.exit_sequence)

    menu.addAction(toggle_action)
    menu.addAction(summon_action)
    menu.addAction(status_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    def refresh_menu() -> None:
        toggle_action.setText("隐藏桌宠" if pet.isVisible() else "显示桌宠")

    menu.aboutToShow.connect(refresh_menu)
    refresh_menu()

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: pet.show_from_tray()
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
        else None
    )
    tray.show()
    return tray


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    is_macos = platform.system() == "Darwin"
    app.setQuitOnLastWindowClosed(not is_macos)
    if is_macos:
        _configure_macos_app()

    pet = NaichaMouse()
    if not icon.isNull():
        pet.setWindowIcon(icon)

    if is_macos and QSystemTrayIcon.isSystemTrayAvailable():
        app._naicha_tray = _create_macos_tray(app, pet, icon)  # type: ignore[attr-defined]

    pet.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())

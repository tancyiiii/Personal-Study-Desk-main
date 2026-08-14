# main_gui.py — PySide6 native desktop GUI
# ==========================================
# Pure GUI layer. Every computation delegates to business.py.
# No Streamlit, no browser embedding.

import sys
import os
import subprocess
import traceback
import datetime
import json
import ctypes


def _relaunch_without_console() -> None:
    """Relaunch with pythonw so double-clicking main_gui.py leaves no console."""
    if "--console" in sys.argv or getattr(sys, "frozen", False):
        return
    exe_name = os.path.basename(sys.executable).lower()
    if exe_name not in ("python.exe", "python3.exe"):
        return
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        return
    args = [pythonw, os.path.abspath(__file__)]
    args.extend(arg for arg in sys.argv[1:] if arg != "--console")
    subprocess.Popen(args, close_fds=True)
    sys.exit(0)


_relaunch_without_console()

from PySide6.QtCore import (
    Qt, QThread, QTimer, Signal, Slot, QObject, QEvent,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QTextEdit, QTextBrowser, QCheckBox, QSlider, QFileDialog,
    QMessageBox, QProgressBar, QGroupBox, QFormLayout, QFrame,
    QListWidget,
    QTabWidget, QSpinBox, QDockWidget, QScrollArea, QSizePolicy,
    QGridLayout, QMenu,
)
from PySide6.QtGui import (
    QFont, QIcon, QAction, QPixmap,
    QTextCursor, QTextDocument, QTextBlockFormat,
    QPalette, QColor,
)

from business import (
    StudyAssistantHandler,
    ConfigManager,
    set_api_key_env,
)
from resource_path import resource_path


def _app_icon() -> QIcon:
    """Return the custom app icon, falling back to the default if missing."""
    for name in ("icon.png", "icon.jpg", "icon.jpeg", "icon.ico"):
        icon_path = resource_path(os.path.join("assets", name))
        if os.path.isfile(icon_path):
            return QIcon(icon_path)
    return QIcon()


def _chat_label_html(
    text: str,
    text_color: str = None,
    link_color: str = "#10a37f",
    markdown: bool = True,
) -> str:
    """Render chat text as compact HTML so bubbles do not look airy."""
    doc = QTextDocument()
    if text_color:
        body_style = f"p, li, h1, h2, h3 {{ color: {text_color}; margin: 0; }}"
    else:
        body_style = "p, li, h1, h2, h3 { margin: 0; }"
    doc.setDefaultStyleSheet(f"{body_style} a {{ color: {link_color}; }}")
    if markdown:
        doc.setMarkdown(text)
    else:
        doc.setPlainText(text)
    cursor = QTextCursor(doc)
    cursor.select(QTextCursor.Document)
    block_fmt = QTextBlockFormat()
    block_fmt.setTopMargin(1)
    block_fmt.setBottomMargin(1)
    block_fmt.setLineHeight(130.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    cursor.mergeBlockFormat(block_fmt)
    return doc.toHtml()


def _make_chat_label(role: str, text: str) -> QLabel:
    label = QLabel()
    label.setObjectName("chatBubbleUser" if role == "user" else "chatBubbleAssistant")
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    label.setMaximumWidth(560)
    label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    label.setText(
        _chat_label_html(
            text,
            "#ffffff" if role == "user" else None,
            "#c7f5e6" if role == "user" else "#10a37f",
            markdown=(role != "user"),
        )
    )
    label.adjustSize()
    return label


def _apply_compact_markdown(browser: QTextBrowser, text: str = None) -> None:
    """Tighten block spacing and line height inside a markdown browser."""
    if text is not None:
        browser.setMarkdown(text)
    browser.document().setDocumentMargin(10)
    cursor = QTextCursor(browser.document())
    cursor.select(QTextCursor.Document)
    block_fmt = QTextBlockFormat()
    block_fmt.setTopMargin(2)
    block_fmt.setBottomMargin(2)
    block_fmt.setLineHeight(130.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    cursor.mergeBlockFormat(block_fmt)


def _state_file() -> str:
    """Return the persistent plan-state file path in the user's app-data folder."""
    return os.path.join(_app_data_dir(), "study_assistant_state.json")


def _app_data_dir() -> str:
    """Return a stable per-user folder shared by source runs and the packaged EXE."""
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "StudyAssistant")


def _legacy_state_file() -> str:
    """Return the old state path used before app-data persistence."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "study_assistant_state.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "study_assistant_state.json")


def _settings_path() -> str:
    return os.path.join(_app_data_dir(), "settings.json")


def _load_settings() -> dict:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(settings: dict) -> None:
    try:
        path = _settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = _load_settings()
        existing.update(settings)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception:
        _log_error(traceback.format_exc())


def _load_history() -> list:
    """Return saved generation history, newest first."""
    try:
        with open(_state_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            history = data.get("history")
            if isinstance(history, list):
                return [item for item in history if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _save_plan_state(
    handler, analysis, roadmap, resources, quiz="", record_history=False
) -> None:
    """Persist the current plan so it can be reopened after restart."""
    data = {
        "topic": handler.topic,
        "subject_category": handler.subject_category,
        "knowledge_level": handler.knowledge_level,
        "learning_goal": handler.learning_goal,
        "time_available": handler.time_available,
        "learning_style": handler.learning_style,
        "model_name": handler.model_name,
        "provider": handler.provider,
        "analysis": analysis,
        "roadmap": roadmap,
        "resources": resources,
        "quiz": quiz,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    history = _load_history()
    if record_history:
        entry = {key: data[key] for key in (
            "topic", "subject_category", "knowledge_level", "learning_goal",
            "time_available", "learning_style", "model_name", "provider",
            "analysis", "roadmap", "resources", "quiz", "saved_at",
        )}
        history = [entry] + [
            item for item in history
            if not (item.get("topic") == entry["topic"]
                    and item.get("saved_at") == entry["saved_at"])
        ]
        data["history"] = history[:20]
    else:
        data["history"] = history
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        _log_error(traceback.format_exc())


def _load_plan_state():
    """Load the persisted plan from app data, migrating older state if needed."""
    path = _state_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    except Exception:
        _log_error(traceback.format_exc())
        return None

    legacy = _legacy_state_file()
    if os.path.isfile(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                state = json.load(f)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            return state
        except Exception:
            _log_error(traceback.format_exc())
    return None


def _set_taskbar_app_id() -> None:
    """Give the app its own Windows taskbar identity so the custom icon is used."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [
            ctypes.c_wchar_p
        ]
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PersonalStudyDesk.StudyAssistant"
        )
    except Exception:
        pass


def _apply_titlebar_theme(window, dark: bool) -> None:
    """Make the native Windows title bar follow the active theme."""
    if sys.platform != "win32" or window is None:
        return
    try:
        handle = window.windowHandle()
        if handle is None:
            return
        hwnd = int(handle.winId())
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        for attribute in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
        )
    except Exception:
        pass


def _apply_theme(dark: bool, window=None) -> None:
    """Apply light or dark palette plus stylesheet at runtime."""
    app = QApplication.instance()
    if app is None:
        return
    if dark:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#17181c"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#1a1b21"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1f2026"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#e6e7eb"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6e7eb"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#26272e"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e7eb"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#10a37f"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2c2e35"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6e7eb"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#4fd1ad"))
        app.setPalette(palette)
        app.setStyleSheet(APP_STYLE_SHEET_DARK)
    else:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(APP_STYLE_SHEET)
    _apply_titlebar_theme(window, dark)
    if window is not None:
        QTimer.singleShot(50, lambda: _apply_titlebar_theme(window, dark))


APP_STYLE_SHEET = """
QMainWindow {
    background-color: #f7f7f8;
}
QWidget {
    color: #0d0d0d;
    font-size: 13px;
}
QWidget#sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e5e5ea;
}
QStackedWidget {
    background-color: #ffffff;
}
QLabel {
    background: transparent;
}
QPushButton {
    background-color: #ffffff;
    color: #0d0d0d;
    border: 1px solid #d9d9e3;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f4f4f5;
    border-color: #c2c2cc;
}
QPushButton:pressed {
    background-color: #e8e8ea;
}
QPushButton:disabled {
    color: #b5b5bd;
    background-color: #f2f2f4;
    border-color: #e5e5e8;
}
QPushButton#primaryButton {
    background-color: #0d0d0d;
    color: #ffffff;
    border: 1px solid #0d0d0d;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #1f1f1f;
    border-color: #1f1f1f;
}
QPushButton#primaryButton:pressed {
    background-color: #2f2f2f;
}
QPushButton#primaryButton:disabled {
    background-color: #d9d9e3;
    border-color: #d9d9e3;
    color: #ffffff;
}
QPushButton[card="true"] {
    background-color: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    font-size: 14px;
}
QPushButton[card="true"]:hover {
    border-color: #10a37f;
    background-color: #f7fbfa;
}
QPushButton#settingsButton {
    background-color: #f4f4f5;
    border: 1px solid #d9d9e3;
    color: #0d0d0d;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
    text-align: left;
}
QPushButton#settingsButton:hover {
    background-color: #ececf1;
    border-color: #c2c2cc;
}
QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d9d9e3;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #b7e4d7;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #10a37f;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d9d9e3;
    border-radius: 8px;
    selection-background-color: #ececf1;
    selection-color: #0d0d0d;
}
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #0d0d0d;
}
QTabWidget {
    background-color: #ffffff;
}
QTabWidget::pane {
    border: 1px solid #e5e5ea;
    background-color: #ffffff;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 16px;
    color: #6e6e80;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #0d0d0d;
    border-bottom: 2px solid #0d0d0d;
}
QTabBar::tab:hover {
    color: #0d0d0d;
}
QProgressBar {
    background-color: #ececf1;
    border: none;
    border-radius: 6px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #10a37f;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #d4d4d8;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background-color: #0d0d0d;
    color: #ffffff;
    border: none;
    padding: 6px 8px;
}
QLabel#chatHeader {
    font-size: 15px;
    font-weight: 600;
    color: #0d0d0d;
}
QLabel#mutedLabel {
    color: #6e6e80;
    font-size: 12px;
}
QLabel#chatPlaceholder {
    color: #b5b5bd;
    font-size: 13px;
}
QLabel#chatBubbleUser {
    background-color: #10a37f;
    color: #ffffff;
    border-radius: 14px;
    padding: 10px 14px;
}
QLabel#chatBubbleAssistant {
    background-color: #f0f0f4;
    color: #0d0d0d;
    border-radius: 14px;
    padding: 10px 14px;
}
QScrollArea#chatScroll {
    background: transparent;
    border: none;
}
QScrollArea#settingsScroll {
    background: transparent;
    border: none;
}
QListWidget#historyList {
    background-color: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 8px;
    padding: 4px;
}
QListWidget#historyList::item {
    padding: 8px;
    border-bottom: 1px solid #f0f0f2;
}
QListWidget#historyList::item:selected {
    background-color: #ececf1;
    color: #0d0d0d;
}
QListWidget#historyList::item:hover {
    background-color: #f7f7f8;
}
QTextBrowser#answerBrowser {
    background-color: #f7f7f8;
    border: 1px solid #e8e8ec;
    border-radius: 12px;
    padding: 10px 12px;
}
"""

APP_STYLE_SHEET_DARK = """
QMainWindow {
    background-color: #17181c;
}
QWidget {
    color: #e6e7eb;
    font-size: 13px;
}
QWidget#sidebar {
    background-color: #1f2026;
    border-right: 1px solid #2c2e35;
}
QStackedWidget {
    background-color: #17181c;
}
QLabel {
    background: transparent;
}
QPushButton {
    background-color: #26272e;
    color: #e6e7eb;
    border: 1px solid #383a42;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #2f313a;
    border-color: #4a4d58;
}
QPushButton:pressed {
    background-color: #3a3c45;
}
QPushButton:disabled {
    color: #6b6e78;
    background-color: #1f2026;
    border-color: #2c2e35;
}
QPushButton#primaryButton {
    background-color: #10a37f;
    color: #ffffff;
    border: 1px solid #10a37f;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #0e8a6d;
    border-color: #0e8a6d;
}
QPushButton#primaryButton:pressed {
    background-color: #0b7059;
}
QPushButton#primaryButton:disabled {
    background-color: #2c3b37;
    border-color: #2c3b37;
    color: #9aa8a3;
}
QPushButton[card="true"] {
    background-color: #1f2026;
    border: 1px solid #2c2e35;
    border-radius: 10px;
    font-size: 14px;
}
QPushButton[card="true"]:hover {
    border-color: #10a37f;
    background-color: #17251f;
}
QPushButton#settingsButton {
    background-color: #26272e;
    border: 1px solid #383a42;
    color: #e6e7eb;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
    text-align: left;
}
QPushButton#settingsButton:hover {
    background-color: #2f313a;
    border-color: #4a4d58;
}
QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {
    background-color: #1a1b21;
    border: 1px solid #383a42;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #1f5c4b;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #10a37f;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #1f2026;
    border: 1px solid #383a42;
    border-radius: 8px;
    selection-background-color: #30323b;
    selection-color: #e6e7eb;
}
QGroupBox {
    background-color: #1f2026;
    border: 1px solid #2c2e35;
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #e6e7eb;
}
QTabWidget {
    background-color: #17181c;
}
QTabBar {
    background-color: #17181c;
}
QTabWidget::pane {
    border: 1px solid #2c2e35;
    background-color: #17181c;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 16px;
    color: #9a9da8;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #ffffff;
    border-bottom: 2px solid #10a37f;
}
QTabBar::tab:hover {
    color: #ffffff;
}
QProgressBar {
    background-color: #2c2e35;
    border: none;
    border-radius: 6px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #10a37f;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #454852;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background-color: #2c2e35;
    color: #e6e7eb;
    border: none;
    padding: 6px 8px;
}
QLabel#chatHeader {
    font-size: 15px;
    font-weight: 600;
    color: #e6e7eb;
}
QLabel#mutedLabel {
    color: #9a9da8;
    font-size: 12px;
}
QLabel#chatPlaceholder {
    color: #6b6e78;
    font-size: 13px;
}
QLabel#chatBubbleUser {
    background-color: #10a37f;
    color: #ffffff;
    border-radius: 14px;
    padding: 10px 14px;
}
QLabel#chatBubbleAssistant {
    background-color: #2c2e35;
    color: #e6e7eb;
    border-radius: 14px;
    padding: 10px 14px;
}
QScrollArea#chatScroll {
    background: transparent;
    border: none;
}
QScrollArea#settingsScroll {
    background: transparent;
    border: none;
}
QListWidget#historyList {
    background-color: #1a1b21;
    border: 1px solid #383a42;
    border-radius: 8px;
    padding: 4px;
}
QListWidget#historyList::item {
    padding: 8px;
    border-bottom: 1px solid #2c2e35;
}
QListWidget#historyList::item:selected {
    background-color: #30323b;
    color: #e6e7eb;
}
QListWidget#historyList::item:hover {
    background-color: #26272e;
}
QTextBrowser#answerBrowser {
    background-color: #1f2026;
    border: 1px solid #2c2e35;
    border-radius: 12px;
    padding: 10px 12px;
    color: #e6e7eb;
}
"""


def _log_error(message: str) -> None:
    """Append a diagnostic line next to the app so packaged errors are visible."""
    try:
        log_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        log_path = os.path.join(log_dir, "study_assistant.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {message}\n")
    except Exception:
        pass

# ────────────────────────────────────────────
#  Worker thread for long-running AI tasks
# ────────────────────────────────────────────

class WorkerSignals(QObject):
    """Signals emitted by the worker thread."""
    finished = Signal(object)   # result payload
    error    = Signal(str)      # error message
    progress = Signal(str)      # status text


class WorkerThread(QThread):
    """Run a callable in a background thread with signals."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            _log_error(traceback.format_exc())
            self.signals.error.emit(str(e))


class ChineseContextMenuFilter(QObject):
    """Show a Chinese right-click menu on editable text widgets."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu and isinstance(obj, (QLineEdit, QTextEdit)):
            self._show_menu(obj, event.globalPos())
            return True
        return super().eventFilter(obj, event)

    def _show_menu(self, widget, global_pos):
        menu = QMenu(widget)

        if isinstance(widget, QTextBrowser):
            copy_action = menu.addAction("复制")
            copy_action.setEnabled(widget.textCursor().hasSelection())
            copy_action.triggered.connect(widget.copy)
            menu.addSeparator()
            select_all = menu.addAction("全选")
            select_all.triggered.connect(widget.selectAll)
            menu.exec(global_pos)
            return

        has_selection = (
            widget.hasSelectedText()
            if isinstance(widget, QLineEdit)
            else widget.textCursor().hasSelection()
        )

        if isinstance(widget, QLineEdit):
            undo_ok, redo_ok = widget.isUndoAvailable(), widget.isRedoAvailable()
        else:
            undo_ok, redo_ok = widget.document().isUndoAvailable(), widget.document().isRedoAvailable()

        undo_action = menu.addAction("撤销")
        undo_action.setEnabled(undo_ok)
        undo_action.triggered.connect(widget.undo)

        redo_action = menu.addAction("重做")
        redo_action.setEnabled(redo_ok)
        redo_action.triggered.connect(widget.redo)

        menu.addSeparator()

        cut_action = menu.addAction("剪切")
        cut_action.setEnabled(has_selection)
        cut_action.triggered.connect(widget.cut)

        copy_action = menu.addAction("复制")
        copy_action.setEnabled(has_selection)
        copy_action.triggered.connect(widget.copy)

        paste_action = menu.addAction("粘贴")
        paste_action.setEnabled(not widget.isReadOnly())
        paste_action.triggered.connect(widget.paste)

        delete_action = menu.addAction("删除")
        delete_action.setEnabled(has_selection)
        if isinstance(widget, QLineEdit):
            delete_action.triggered.connect(lambda: getattr(widget, "del")())
        else:
            delete_action.triggered.connect(lambda: widget.textCursor().removeSelectedText())

        menu.addSeparator()

        select_all = menu.addAction("全选")
        select_all.triggered.connect(widget.selectAll)

        menu.exec(global_pos)


# ────────────────────────────────────────────
#  Sidebar settings pane (always visible)
# ────────────────────────────────────────────

class SidebarWidget(QWidget):
    """Provider / model / API key settings, always visible on the left."""

    providerChanged = Signal(str)
    apiKeyChanged   = Signal(str, str)   # provider, key
    themeChanged    = Signal(bool)
    historySelected = Signal(dict)

    MODEL_OPTIONS = {
        "groq":     ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
        "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "openai":   ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "gpt-3.5-turbo"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("sidebar")
        self.setFixedWidth(280)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("AI 学习助手")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("个性化学习规划与 AI 辅导")
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("settingsButton")
        layout.addWidget(self.settings_btn)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("settingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        settings_host = QWidget()
        settings_layout = QVBoxLayout(settings_host)
        settings_layout.setContentsMargins(0, 4, 0, 0)
        settings_layout.setSpacing(10)

        settings_layout.addWidget(QLabel("AI 提供商"))

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["deepseek", "groq", "openai"])
        self.provider_combo.setToolTip(
            "DeepSeek 性价比高、推理能力强。Groq 免费且快速。OpenAI 需要付费 API 密钥。"
        )
        settings_layout.addWidget(self.provider_combo)

        settings_layout.addWidget(QLabel("选择模型"))

        self.model_combo = QComboBox()
        self._update_model_options("deepseek")
        settings_layout.addWidget(self.model_combo)

        settings_layout.addWidget(QLabel("API 密钥"))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("在此粘贴你的 API 密钥")
        self.api_key_edit.setToolTip("输入所选提供商的 API 密钥。")
        settings_layout.addWidget(self.api_key_edit)

        self.dark_mode_check = QCheckBox("深色模式")
        self.dark_mode_check.setChecked(_load_settings().get("dark_mode", False))
        settings_layout.addWidget(self.dark_mode_check)

        settings_layout.addWidget(QLabel("关于"))
        about_text = QTextBrowser()
        about_text.setOpenExternalLinks(True)
        about_text.setMaximumHeight(180)
        about_text.setHtml(
            "<p>AI 学习助手集成多种智能体，帮助完成：</p>"
            "<ul>"
            "<li><b>分析</b>你的学习需求</li>"
            "<li><b>制定</b>个性化学习路线</li>"
            "<li><b>生成</b>定制测验</li>"
            "<li><b>AI 辅导</b>与文档问答</li>"
            "<li><b>查找</b>最佳学习资源</li>"
            "</ul>"
            "<p><b>DeepSeek</b>：性价比高、推理能力强<br>"
            "<b>Groq</b>：免费且响应快<br>"
            "<b>OpenAI</b>：需要付费 API 密钥</p>"
        )
        settings_layout.addWidget(about_text)

        self.settings_scroll.setWidget(settings_host)
        layout.addWidget(self.settings_scroll)
        self.settings_scroll.setVisible(False)

        history_label = QLabel("历史生成")
        history_label.setObjectName("mutedLabel")
        layout.addWidget(history_label)

        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        layout.addWidget(self.history_list, 1)
        self.refresh_history()

    def _toggle_settings(self):
        visible = not self.settings_scroll.isVisible()
        self.settings_scroll.setVisible(visible)
        self.settings_btn.setText("收起设置" if visible else "设置")

    def refresh_history(self):
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        for entry in _load_history():
            topic = entry.get("topic") or "未命名计划"
            when = (entry.get("saved_at") or "")[:16].replace("T", " ")
            self.history_list.addItem(f"{topic}  {when}")
            index = self.history_list.count() - 1
            self.history_list.item(index).setData(Qt.UserRole, entry)

    def _on_history_clicked(self, item):
        entry = item.data(Qt.UserRole)
        if isinstance(entry, dict):
            self.historySelected.emit(entry)

    def _connect_signals(self):
        self.settings_btn.clicked.connect(self._toggle_settings)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.api_key_edit.textChanged.connect(self._on_api_key_changed)
        self.dark_mode_check.toggled.connect(self.themeChanged.emit)
        self.history_list.itemClicked.connect(self._on_history_clicked)

    def _on_provider_changed(self, provider: str):
        self._update_model_options(provider)
        self.providerChanged.emit(provider)
        # Re-emit API key for new provider
        key = self.api_key_edit.text().strip()
        if key:
            self.apiKeyChanged.emit(provider, key)

    def _on_api_key_changed(self, key: str):
        provider = self.provider_combo.currentText()
        self.apiKeyChanged.emit(provider, key.strip())

    def _update_model_options(self, provider: str):
        self.model_combo.clear()
        models = self.MODEL_OPTIONS.get(provider, ["deepseek-chat"])
        self.model_combo.addItems(models)

    def set_provider_model(self, provider: str, model: str):
        idx = self.provider_combo.findText(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._update_model_options(provider)
        midx = self.model_combo.findText(model)
        if midx >= 0:
            self.model_combo.setCurrentIndex(midx)

    def current_provider(self) -> str:
        return self.provider_combo.currentText()

    def current_model(self) -> str:
        return self.model_combo.currentText()

    def current_api_key(self) -> str:
        return self.api_key_edit.text()


# ────────────────────────────────────────────
#  Step 1 — Subject Category Selection
# ────────────────────────────────────────────

CATEGORY_DISPLAY = {
    "programming":      " 编程",
    "mathematics":      " 数学",
    "science":          " 科学",
    "languages":        " 语言",
    "business":         " 商业",
    "test_preparation": " 考试准备",
}


class Step1CategoryWidget(QWidget):
    """Grid of category buttons."""

    categorySelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        heading = QLabel("第 1 步：选择学科类别")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        heading.setFont(hf)
        layout.addWidget(heading)

        desc = QLabel("请选择你想学习的学科方向，AI 将为你定制个性化学习计划。")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        grid = QGridLayout()
        grid.setSpacing(12)
        categories = ConfigManager().get_all_subject_categories()
        row = col = 0
        for cat in categories:
            btn = QPushButton(CATEGORY_DISPLAY.get(cat, cat.title()))
            btn.setMinimumHeight(80)
            btn.setProperty("category", cat)
            btn.setProperty("card", True)
            font = btn.font()
            font.setPointSize(13)
            btn.setFont(font)
            btn.clicked.connect(self._on_category_clicked)
            grid.addWidget(btn, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
        layout.addLayout(grid)
        layout.addStretch()

    def _on_category_clicked(self):
        btn = self.sender()
        if btn:
            cat = btn.property("category")
            self.categorySelected.emit(cat)


# ────────────────────────────────────────────
#  Step 2 — Learning Details Form
# ────────────────────────────────────────────

class Step2DetailsWidget(QWidget):
    """Form for topic, knowledge level, goal, time, learning style."""

    backRequested = Signal()
    generateRequested = Signal(dict)   # emits form data dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._category = ""
        self._build_ui()

    def set_category(self, cat: str):
        self._category = cat
        self.category_label.setText(f"类别：{cat.title()}")
        self._update_category_info(cat)

    def _update_category_info(self, cat: str):
        info = ConfigManager().get_subject_category_info(cat)
        if info:
            topics = ", ".join(info.get("topics", []))
            duration = info.get("typical_duration", "Varies")
            self.category_info.setText(
                f"<b>涵盖主题：</b>{topics}<br><b>典型时长：</b>{duration}"
            )
            self.category_info.setVisible(True)
        else:
            self.category_info.setVisible(False)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(14)

        # ── heading ──
        heading = QLabel("第 2 步：告诉我们你的学习目标")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        heading.setFont(hf)
        outer.addWidget(heading)

        self.category_label = QLabel()
        cf = QFont()
        cf.setPointSize(12)
        self.category_label.setFont(cf)
        outer.addWidget(self.category_label)

        self.category_info = QTextBrowser()
        self.category_info.setMaximumHeight(80)
        self.category_info.setVisible(False)
        outer.addWidget(self.category_info)

        # ── two-column form ──
        form_row = QHBoxLayout()

        # Left column
        left_group = QGroupBox()
        left_layout = QFormLayout(left_group)

        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("例如：Python 数据科学、微积分、西班牙语语法")
        left_layout.addRow("你想学习什么具体主题？", self.topic_edit)

        self.knowledge_combo = QComboBox()
        levels = ConfigManager().get_all_knowledge_levels()
        level_map = {"beginner": "入门", "intermediate": "中级",
                      "advanced": "高级", "expert": "专家"}
        for lv in levels:
            self.knowledge_combo.addItem(level_map.get(lv, lv.title()), lv)
        self.knowledge_combo.currentIndexChanged.connect(self._on_knowledge_changed)
        left_layout.addRow("你当前的知识水平是？", self.knowledge_combo)

        self.level_info_label = QLabel()
        self.level_info_label.setWordWrap(True)
        self.level_info_label.setStyleSheet("color: #6e6e80;")
        self.level_info_label.setVisible(False)
        left_layout.addRow(self.level_info_label)

        form_row.addWidget(left_group)

        # Right column
        right_group = QGroupBox()
        right_layout = QFormLayout(right_group)

        self.goal_edit = QTextEdit()
        self.goal_edit.setPlaceholderText("例如：完成一个作品集项目、通过考试、达到就业水平")
        self.goal_edit.setMaximumHeight(80)
        right_layout.addRow("你想达到什么目标？", self.goal_edit)

        self.time_combo = QComboBox()
        for t in ["每周 1-2 小时", "每周 3-5 小时", "每周 6-10 小时",
                   "每周 10+ 小时", "全职（每周 30+ 小时）"]:
            self.time_combo.addItem(t)
        right_layout.addRow("你每周能投入多少时间？", self.time_combo)

        self.style_combo = QComboBox()
        styles = ConfigManager().get_all_learning_styles()
        for s in styles:
            self.style_combo.addItem(s.replace("_", " ").title(), s)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        right_layout.addRow("What's your preferred learning style?", self.style_combo)

        self.style_info_label = QLabel()
        self.style_info_label.setWordWrap(True)
        self.style_info_label.setStyleSheet("color: #6e6e80;")
        self.style_info_label.setVisible(False)
        right_layout.addRow(self.style_info_label)

        form_row.addWidget(right_group)
        outer.addLayout(form_row)

        # ── bottom navigation ──
        nav = QHBoxLayout()
        self.back_btn = QPushButton("← 返回")
        self.back_btn.clicked.connect(self.backRequested.emit)
        nav.addWidget(self.back_btn)

        nav.addStretch()

        self.generate_btn = QPushButton("创建我的学习计划")
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate)
        nav.addWidget(self.generate_btn)

        outer.addLayout(nav)

        # Enable button only when topic and goal are non-empty
        self.topic_edit.textChanged.connect(self._validate_form)
        self.goal_edit.textChanged.connect(self._validate_form)

    def _validate_form(self):
        ok = bool(self.topic_edit.text().strip()) and bool(self.goal_edit.toPlainText().strip())
        self.generate_btn.setEnabled(ok)

    def _on_knowledge_changed(self, idx: int):
        level_key = self.knowledge_combo.itemData(idx)
        info = ConfigManager().get_knowledge_level_info(level_key)
        if info:
            self.level_info_label.setText(f"<b>{level_key.title()}:</b> {info.get('description', '')}")
            self.level_info_label.setVisible(True)
        else:
            self.level_info_label.setVisible(False)

    def _on_style_changed(self, idx: int):
        style_key = self.style_combo.itemData(idx)
        info = ConfigManager().get_learning_style_info(style_key)
        if info:
            display = style_key.replace("_", " ").title()
            self.style_info_label.setText(f"<b>{display}:</b> {info.get('description', '')}")
            self.style_info_label.setVisible(True)
        else:
            self.style_info_label.setVisible(False)

    def _on_generate(self):
        data = {
            "topic":            self.topic_edit.text().strip(),
            "knowledge_level":  self.knowledge_combo.currentData(),
            "learning_goal":    self.goal_edit.toPlainText().strip(),
            "time_available":   self.time_combo.currentText(),
            "learning_style":   self.style_combo.currentData(),
        }
        self.generateRequested.emit(data)


# ────────────────────────────────────────────
#  Step 3 — Generating (loading / progress)
# ────────────────────────────────────────────

class Step3GeneratingWidget(QWidget):
    """Shows progress while the AI generates the learning plan."""

    generationComplete = Signal(dict)  # {analysis, roadmap, resources}
    generationError    = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topic = ""
        self._worker = None
        self._status_base = ""
        self._status_index = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_status)
        self._build_ui()

    def set_topic(self, topic: str):
        self._topic = topic
        self.topic_label.setText(f"主题：{topic}")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        heading = QLabel("正在为你创建个性化学习计划")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        heading.setFont(hf)
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)

        self.topic_label = QLabel()
        tf = QFont()
        tf.setPointSize(13)
        self.topic_label.setFont(tf)
        self.topic_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.topic_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 3)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(400)
        layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)

        self.status_label = QLabel("准备中...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        layout.addStretch()

    def start_generation(self, handler: StudyAssistantHandler):
        """Start the 3-step generation sequence in background threads."""
        self._handler = handler
        self._results = {}
        self._run_analysis()

    def _run_analysis(self):
        self.progress_bar.setValue(0)
        self._start_status_animation("正在分析学习需求")
        self._worker = WorkerThread(self._handler.analyze_student)
        self._worker.signals.finished.connect(self._on_analysis_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_analysis_done(self, result: str):
        self._results["analysis"] = result
        self.progress_bar.setValue(1)
        self._start_status_animation("分析完成！正在创建学习路线")
        self._run_roadmap()

    def _run_roadmap(self):
        worker = WorkerThread(
            self._handler.create_roadmap,
            self._results["analysis"]
        )
        worker.signals.finished.connect(self._on_roadmap_done)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _on_roadmap_done(self, result: str):
        self._results["roadmap"] = result
        self.progress_bar.setValue(2)
        self._start_status_animation("路线已生成！正在查找学习资源")
        self._run_resources()

    def _run_resources(self):
        worker = WorkerThread(self._handler.find_resources)
        worker.signals.finished.connect(self._on_resources_done)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _on_resources_done(self, result: str):
        self._results["resources"] = result
        self.progress_bar.setValue(3)
        self._stop_status_animation()
        self.status_label.setText("全部完成！")
        self.generationComplete.emit(self._results)

    def _on_error(self, msg: str):
        self._stop_status_animation()
        self.generationError.emit(msg)

    def _start_status_animation(self, base_text: str):
        self._status_base = base_text
        self._status_index = 0
        self._update_status_text()
        self._status_timer.start()

    def _stop_status_animation(self):
        self._status_timer.stop()
        self._status_base = ""

    def _tick_status(self):
        self._status_index = (self._status_index + 1) % 3
        self._update_status_text()

    def _update_status_text(self):
        suffix = (".", "..", "...")[self._status_index]
        self.status_label.setText(f"{self._status_base}{suffix}")


# ────────────────────────────────────────────
#  Step 4 — Learning Dashboard (TabWidget)
# ────────────────────────────────────────────

class DashboardWidget(QWidget):
    """Main dashboard with 5 tabs."""

    resetRequested = Signal()

    def __init__(self, handler: StudyAssistantHandler,
                 analysis: str, roadmap: str, resources: str,
                 quiz: str = "", parent=None):
        super().__init__(parent)
        self._handler = handler
        self._analysis = analysis
        self._roadmap = roadmap
        self._resources = resources
        self._workers: list[WorkerThread] = []
        self._current_quiz = quiz
        self._tutor_response = ""
        self._rag_answer = ""
        self._chat_messages: list[tuple[str, str]] = []
        self._build_ui()
        if quiz:
            self.quiz_browser.setMarkdown(quiz)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(8)

        # heading
        heading = QLabel("🎯 学习仪表盘")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        heading.setFont(hf)
        outer.addWidget(heading)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_roadmap_tab(), " 学习路线")
        tabs.addTab(self._build_resources_tab(), " 学习资源")
        tabs.addTab(self._build_quiz_tab(), " 生成测验")
        tabs.addTab(self._build_tutor_tab(), " AI 辅导")
        tabs.addTab(self._build_rag_tab(), " 文档问答 (RAG)")
        outer.addWidget(tabs)

        # bottom reset button
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        outer.addWidget(sep)

        reset_btn = QPushButton("🏠 开始新的学习计划")
        reset_btn.clicked.connect(self.resetRequested.emit)
        outer.addWidget(reset_btn)

    # ── Tab 1: Learning Roadmap ──
    def _build_roadmap_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        info_row = QHBoxLayout()
        info_label = QLabel(
            f"<b>主题：</b>{self._handler.topic} | "
            f"<b>水平：</b>{self._handler.knowledge_level.title()}"
        )
        info_row.addWidget(info_label)
        info_row.addStretch()

        refresh_btn = QPushButton("🔄 重新生成路线")
        refresh_btn.clicked.connect(self._refresh_roadmap)
        info_row.addWidget(refresh_btn)
        layout.addLayout(info_row)

        self.roadmap_browser = QTextBrowser()
        self.roadmap_browser.setMarkdown(self._roadmap)
        layout.addWidget(self.roadmap_browser)

        self.analysis_browser = QTextBrowser()
        self.analysis_browser.setMarkdown(self._analysis)
        analysis_group = QGroupBox(" 查看学情分析")
        ag_layout = QVBoxLayout(analysis_group)
        ag_layout.addWidget(self.analysis_browser)
        layout.addWidget(analysis_group)

        download_btn = QPushButton(" 下载路线图")
        download_btn.clicked.connect(self._download_roadmap)
        layout.addWidget(download_btn)

        return w

    def _refresh_roadmap(self):
        self._run_worker(
            self._handler.create_roadmap, self._analysis,
            callback=self._on_roadmap_refreshed
        )

    def _on_roadmap_refreshed(self, result):
        self._roadmap = result
        self.roadmap_browser.setMarkdown(result)
        _save_plan_state(self._handler, self._analysis, result, self._resources, self._current_quiz)

    def _download_roadmap(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存路线图",
            f"roadmap_{self._handler.topic.replace(' ', '_')}.md",
            "Markdown (*.md)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Learning Roadmap: {self._handler.topic}\n\n")
                f.write(self._roadmap)

    # ── Tab 2: Resources ──
    def _build_resources_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        refresh_btn = QPushButton(" 重新查找资源")
        refresh_btn.clicked.connect(self._refresh_resources)
        layout.addWidget(refresh_btn, 0, Qt.AlignRight)

        self.resources_browser = QTextBrowser()
        self.resources_browser.setMarkdown(self._resources)
        layout.addWidget(self.resources_browser)

        download_btn = QPushButton(" 下载资源列表")
        download_btn.clicked.connect(self._download_resources)
        layout.addWidget(download_btn)

        return w

    def _refresh_resources(self):
        self._run_worker(
            self._handler.find_resources,
            callback=self._on_resources_refreshed
        )

    def _on_resources_refreshed(self, result):
        self._resources = result
        self.resources_browser.setMarkdown(result)
        _save_plan_state(self._handler, self._analysis, self._roadmap, result, self._current_quiz)

    def _download_resources(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存资源列表",
            f"resources_{self._handler.topic.replace(' ', '_')}.md",
            "Markdown (*.md)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Learning Resources: {self._handler.topic}\n\n")
                f.write(self._resources)

    # ── Tab 3: Quiz Generator ──
    def _build_quiz_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        form_row = QHBoxLayout()

        # Difficulty
        form_row.addWidget(QLabel("难度等级"))
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItems(["入门", "中级", "高级"])
        self.difficulty_combo.setCurrentIndex(1)
        form_row.addWidget(self.difficulty_combo)

        # Num questions
        form_row.addWidget(QLabel("题目数量"))
        self.num_spin = QSpinBox()
        self.num_spin.setRange(5, 20)
        self.num_spin.setValue(10)
        form_row.addWidget(self.num_spin)

        # Focus areas
        form_row.addWidget(QLabel("重点领域（可选）"))
        self.focus_edit = QLineEdit()
        self.focus_edit.setPlaceholderText("例如：循环、函数")
        form_row.addWidget(self.focus_edit)

        layout.addLayout(form_row)

        generate_btn = QPushButton(" 生成测验")
        generate_btn.setObjectName("primaryButton")
        generate_btn.clicked.connect(self._generate_quiz)
        layout.addWidget(generate_btn)

        self.quiz_browser = QTextBrowser()
        layout.addWidget(self.quiz_browser)

        download_btn = QPushButton(" 下载测验")
        download_btn.clicked.connect(self._download_quiz)
        layout.addWidget(download_btn)

        return w

    def _generate_quiz(self):
        diff_map = {"入门": "beginner", "中级": "intermediate", "高级": "advanced"}
        difficulty = diff_map[self.difficulty_combo.currentText()]
        focus = self.focus_edit.text().strip() or "general"
        num = self.num_spin.value()
        self._run_worker(
            self._handler.generate_quiz, difficulty, focus, num,
            callback=self._on_quiz_generated
        )

    def _on_quiz_generated(self, result):
        self._current_quiz = result
        self.quiz_browser.setMarkdown(result)
        _save_plan_state(self._handler, self._analysis, self._roadmap, self._resources, result)

    def _download_quiz(self):
        if not self._current_quiz:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存测验",
            f"quiz_{self._handler.topic.replace(' ', '_')}.md",
            "Markdown (*.md)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Quiz: {self._handler.topic}\n\n")
                f.write(self._current_quiz)

    # ── Tab 4: AI Tutor ──
    def _build_tutor_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("AI 辅导")
        header.setObjectName("chatHeader")
        header.setContentsMargins(18, 14, 18, 6)
        layout.addWidget(header)

        self.tutor_scroll = QScrollArea()
        self.tutor_scroll.setObjectName("chatScroll")
        self.tutor_scroll.setWidgetResizable(True)
        self.tutor_scroll.setFrameShape(QFrame.NoFrame)

        chat_host = QWidget()
        self.tutor_chat_layout = QVBoxLayout(chat_host)
        self.tutor_chat_layout.setContentsMargins(16, 8, 16, 8)
        self.tutor_chat_layout.setSpacing(10)

        self._tutor_placeholder = QLabel("向 AI 导师提问，获得个性化讲解与帮助")
        self._tutor_placeholder.setObjectName("chatPlaceholder")
        self._tutor_placeholder.setAlignment(Qt.AlignCenter)
        self._tutor_placeholder.setWordWrap(True)
        self.tutor_chat_layout.addWidget(self._tutor_placeholder)
        self.tutor_chat_layout.addStretch(1)

        self.tutor_scroll.setWidget(chat_host)
        layout.addWidget(self.tutor_scroll, 1)

        context_row = QHBoxLayout()
        context_row.setContentsMargins(16, 4, 16, 0)
        self.tutor_context = QLineEdit()
        self.tutor_context.setPlaceholderText("补充背景（可选）")
        context_row.addWidget(self.tutor_context, 1)
        layout.addLayout(context_row)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(16, 8, 16, 12)
        input_row.setSpacing(8)
        self.tutor_question = QTextEdit()
        self.tutor_question.setPlaceholderText("例如：能举一个例子解释递归吗？")
        self.tutor_question.setMaximumHeight(84)
        input_row.addWidget(self.tutor_question, 1)

        ask_btn = QPushButton("发送")
        ask_btn.setObjectName("primaryButton")
        ask_btn.setMinimumWidth(84)
        ask_btn.clicked.connect(self._ask_tutor)
        input_row.addWidget(ask_btn, 0, Qt.AlignBottom)
        layout.addLayout(input_row)

        return w

    def _append_chat_message(self, role: str, text: str) -> None:
        self._chat_messages.append((role, text))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        bubble = _make_chat_label(role, text)

        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)

        self._tutor_placeholder.setVisible(False)
        self.tutor_chat_layout.insertLayout(
            max(0, self.tutor_chat_layout.count() - 1), row
        )
        QTimer.singleShot(0, self._scroll_tutor_to_bottom)

    def _rebuild_chat_messages(self) -> None:
        if not hasattr(self, "tutor_chat_layout"):
            return
        while self.tutor_chat_layout.count() > 2:
            item = self.tutor_chat_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    widget = child.widget()
                    if widget:
                        widget.deleteLater()
        messages = list(self._chat_messages)
        self._chat_messages.clear()
        for role, text in messages:
            self._append_chat_message(role, text)

    def refresh_theme(self) -> None:
        """Re-render markdown views so palette colors match the active theme."""
        self.roadmap_browser.setMarkdown(self._roadmap)
        self.resources_browser.setMarkdown(self._resources)
        self.quiz_browser.setMarkdown(self._current_quiz)
        if self._rag_answer:
            _apply_compact_markdown(self.rag_browser, self._rag_answer)
        self._rebuild_chat_messages()

    def _scroll_tutor_to_bottom(self) -> None:
        bar = self.tutor_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _ask_tutor(self):
        question = self.tutor_question.toPlainText().strip()
        if not question:
            return
        context = self.tutor_context.text().strip()
        self._append_chat_message("user", question)
        self.tutor_question.clear()
        self._run_worker(
            self._handler.get_tutoring, question, context,
            callback=self._on_tutor_response
        )

    def _on_tutor_response(self, result):
        self._tutor_response = result
        self._append_chat_message("assistant", result)

    # ── Tab 5: Document Q&A (RAG) ──
    def _build_rag_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QLabel("文档问答 (RAG)")
        header.setObjectName("chatHeader")
        layout.addWidget(header)

        desc = QLabel("上传 PDF 或文本文件，向文件内容提问")
        desc.setObjectName("mutedLabel")
        layout.addWidget(desc)

        # File upload row
        upload_row = QHBoxLayout()
        upload_row.setSpacing(8)

        upload_btn = QPushButton("选择文件上传")
        upload_btn.clicked.connect(self._upload_files)
        upload_row.addWidget(upload_btn)

        self.doc_count_label = QLabel("已加载文档: 0")
        self.doc_count_label.setObjectName("mutedLabel")
        upload_row.addWidget(self.doc_count_label)

        upload_row.addStretch()

        clear_btn = QPushButton("清空文档")
        clear_btn.clicked.connect(self._clear_documents)
        upload_row.addWidget(clear_btn)

        layout.addLayout(upload_row)

        self.upload_status = QLabel()
        self.upload_status.setWordWrap(True)
        self.upload_status.setVisible(False)
        layout.addWidget(self.upload_status)

        question_row = QHBoxLayout()
        question_row.setSpacing(8)
        self.rag_question = QTextEdit()
        self.rag_question.setPlaceholderText("例如：第 2 章的核心概念是什么？")
        self.rag_question.setMaximumHeight(80)
        question_row.addWidget(self.rag_question, 1)

        search_btn = QPushButton("搜索")
        search_btn.setObjectName("primaryButton")
        search_btn.clicked.connect(self._search_documents)
        search_btn.setMinimumWidth(84)
        question_row.addWidget(search_btn, 0, Qt.AlignBottom)
        layout.addLayout(question_row)

        self.rag_browser = QTextBrowser()
        self.rag_browser.setObjectName("answerBrowser")
        self.rag_browser.setVisible(False)
        layout.addWidget(self.rag_browser, 1)

        self._update_doc_count()
        return w

    def _upload_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择学习资料", "",
            "文档文件 (*.pdf *.txt);;PDF 文件 (*.pdf);;文本文件 (*.txt)"
        )
        if not paths:
            return
        self.upload_status.setVisible(True)
        messages = []
        for path in paths:
            _, ext = os.path.splitext(path)
            if ext.lower() == ".pdf":
                ok = self._handler.add_document_to_rag(path, "pdf")
            elif ext.lower() == ".txt":
                ok = self._handler.add_document_to_rag(path, "text")
            else:
                ok = False
            fname = os.path.basename(path)
            if ok:
                messages.append(f"✅ 已加载：{fname}")
            else:
                messages.append(f"❌ 加载失败：{fname}")
        self.upload_status.setText("\n".join(messages))
        self._update_doc_count()

    def _clear_documents(self):
        self._handler.clear_documents()
        self._update_doc_count()
        QMessageBox.information(self, "清空完成", "所有文档已清空！")

    def _update_doc_count(self):
        count = self._handler.get_document_count()
        self.doc_count_label.setText(f"已加载文档: {count}")

    def _search_documents(self):
        if self._handler.get_document_count() == 0:
            QMessageBox.information(self, "提示", "请先上传文档后再提问！")
            return
        question = self.rag_question.toPlainText().strip()
        if not question:
            return
        self._run_worker(
            self._handler.query_documents, question, 4,
            callback=self._on_rag_answer
        )

    def _on_rag_answer(self, result):
        self._rag_answer = result
        self.rag_browser.setVisible(True)
        _apply_compact_markdown(self.rag_browser, result)

    # ── Generic worker helper ──
    def _run_worker(self, fn, *args, callback=None):
        """Run fn in a background thread, call callback on completion."""
        if self._workers:
            QMessageBox.information(self, "请稍候", "上一个任务仍在运行，请稍候再试。")
            return

        worker = WorkerThread(fn, *args)
        if callback:
            worker.signals.finished.connect(callback)
        worker.signals.error.connect(self._show_worker_error)

        def _cleanup():
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        worker.finished.connect(_cleanup)
        self._workers.append(worker)
        worker.start()

    def _show_worker_error(self, msg: str):
        QMessageBox.critical(self, "错误", f"操作执行失败：\n{msg}")


# ────────────────────────────────────────────
#  Main Window
# ────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(" 多智能体 AI 学习助手")
        self.resize(1100, 720)

        # ── state (replaces st.session_state) ──
        self._category = ""
        self._handler: Optional[StudyAssistantHandler] = None
        self.step4 = None

        # ── central layout: sidebar | stacked widget ──
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self.sidebar = SidebarWidget()
        root.addWidget(self.sidebar)

        # Separator
        vsep = QFrame()
        vsep.setFrameShape(QFrame.VLine)
        root.addWidget(vsep)

        # Stacked pages
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # ── create step widgets ──
        self.step1 = Step1CategoryWidget()
        self.step2 = Step2DetailsWidget()
        self.step3 = Step3GeneratingWidget()
        # step4 created dynamically when generation completes

        self.stack.addWidget(self.step1)   # index 0
        self.stack.addWidget(self.step2)   # index 1
        self.stack.addWidget(self.step3)   # index 2

        self.stack.setCurrentIndex(0)

        # ── connect signals ──
        self._connect_signals()
        self._maybe_restore_plan()

    def _connect_signals(self):
        # Step 1 → Step 2
        self.step1.categorySelected.connect(self._on_category_selected)

        # Step 2 → Step 3
        self.step2.backRequested.connect(lambda: self.stack.setCurrentIndex(0))
        self.step2.generateRequested.connect(self._on_generate_requested)

        # Step 3 → Step 4
        self.step3.generationComplete.connect(self._on_generation_complete)
        self.step3.generationError.connect(self._on_generation_error)

        # Sidebar → API key env
        self.sidebar.apiKeyChanged.connect(
            lambda provider, key: set_api_key_env(provider, key) if key else None
        )
        self.sidebar.themeChanged.connect(self._on_theme_changed)
        self.sidebar.historySelected.connect(self._open_history_plan)

    def _on_theme_changed(self, dark: bool):
        _apply_theme(dark, self)
        _save_settings({"dark_mode": dark})
        if self.step4 is not None:
            self.step4.refresh_theme()

    def _open_history_plan(self, state: dict):
        try:
            handler = StudyAssistantHandler(
                topic=state["topic"],
                subject_category=state.get("subject_category", ""),
                knowledge_level=state.get("knowledge_level", "beginner"),
                learning_goal=state.get("learning_goal", ""),
                time_available=state.get("time_available", ""),
                learning_style=state.get("learning_style", ""),
                model_name=state.get("model_name", "deepseek-chat"),
                provider=state.get("provider", "deepseek"),
            )
        except Exception:
            _log_error(traceback.format_exc())
            QMessageBox.critical(self, "加载失败", "这条历史记录无法打开。")
            return
        self._category = state.get("subject_category", "")
        self.sidebar.set_provider_model(
            state.get("provider", "deepseek"),
            state.get("model_name", "deepseek-chat"),
        )
        dashboard = DashboardWidget(
            handler,
            state.get("analysis", ""),
            state.get("roadmap", ""),
            state.get("resources", ""),
            quiz=state.get("quiz", ""),
        )
        dashboard.resetRequested.connect(self._reset_all)
        if self.step4 is not None:
            index = self.stack.indexOf(self.step4)
            if index >= 0:
                self.stack.removeWidget(self.step4)
                self.step4.deleteLater()
        self.step4 = dashboard
        self.stack.addWidget(dashboard)
        self.stack.setCurrentWidget(dashboard)

    # ── slot: restore last saved plan ──
    def _maybe_restore_plan(self):
        state = _load_plan_state()
        if not state:
            return
        answer = QMessageBox.question(
            self,
            "继续上次计划",
            f"检测到上次生成的学习计划（{state.get('topic', '')}），是否直接打开？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            handler = StudyAssistantHandler(
                topic=state["topic"],
                subject_category=state.get("subject_category", ""),
                knowledge_level=state["knowledge_level"],
                learning_goal=state["learning_goal"],
                time_available=state["time_available"],
                learning_style=state["learning_style"],
                model_name=state.get("model_name", "deepseek-chat"),
                provider=state.get("provider", "deepseek"),
            )
        except Exception:
            _log_error(traceback.format_exc())
            QMessageBox.critical(self, "恢复失败", "上次的学习计划无法恢复，请重新生成。")
            return
        self._category = state.get("subject_category", "")
        self.sidebar.set_provider_model(state.get("provider", "deepseek"), state.get("model_name", "deepseek-chat"))
        dashboard = DashboardWidget(
            handler,
            state.get("analysis", ""),
            state.get("roadmap", ""),
            state.get("resources", ""),
            quiz=state.get("quiz", ""),
        )
        dashboard.resetRequested.connect(self._reset_all)
        self.step4 = dashboard
        self.stack.addWidget(dashboard)
        self.stack.setCurrentWidget(dashboard)

    # ── slot: category selected ──
    def _on_category_selected(self, category: str):
        self._category = category
        self.step2.set_category(category)
        self.stack.setCurrentIndex(1)

    # ── slot: generate requested ──
    def _on_generate_requested(self, data: dict):
        provider = self.sidebar.current_provider()
        model = self.sidebar.current_model()
        api_key = self.sidebar.current_api_key().strip()

        if not api_key:
            QMessageBox.warning(self, "Missing API Key", "请填入api")
            return

        if not api_key.isascii():
            QMessageBox.warning(
                self,
                "API 密钥无效",
                "API 密钥包含中文或非 ASCII 字符，请粘贴有效的密钥。",
            )
            return

        try:
            set_api_key_env(provider, api_key)
        except ValueError as exc:
            QMessageBox.warning(self, "API 密钥无效", str(exc))
            return

        try:
            self._handler = StudyAssistantHandler(
                topic=data["topic"],
                subject_category=self._category,
                knowledge_level=data["knowledge_level"],
                learning_goal=data["learning_goal"],
                time_available=data["time_available"],
                learning_style=data["learning_style"],
                model_name=model,
                provider=provider,
            )
        except Exception as e:
            _log_error(traceback.format_exc())
            QMessageBox.critical(self, "Initialization Failed", f"Failed to initialize the study assistant:\n{e}")
            return

        self.step3.set_topic(data["topic"])
        self.stack.setCurrentIndex(2)
        self.step3.start_generation(self._handler)

    # ── slot: generation complete ──
    def _on_generation_complete(self, results: dict):
        self.step4 = DashboardWidget(
            self._handler,
            results["analysis"],
            results["roadmap"],
            results["resources"],
        )
        self.step4.resetRequested.connect(self._reset_all)
        self.stack.addWidget(self.step4)   # index 3
        self.stack.setCurrentWidget(self.step4)
        _save_plan_state(
            self._handler,
            results["analysis"],
            results["roadmap"],
            results["resources"],
            record_history=True,
        )
        self.sidebar.refresh_history()

    # ── slot: generation error ──
    def _on_generation_error(self, msg: str):
        QMessageBox.critical(self, "生成失败", f"学习计划生成失败：\n{msg}")
        self.stack.setCurrentIndex(1)

    # ── reset: start a new plan ──
    def _reset_all(self):
        self._category = ""
        self._handler = None
        self.step2 = Step2DetailsWidget()
        self.step3 = Step3GeneratingWidget()

        # re-connect step 2 & 3 signals
        self.step2.backRequested.connect(lambda: self.stack.setCurrentIndex(0))
        self.step2.generateRequested.connect(self._on_generate_requested)
        self.step3.generationComplete.connect(self._on_generation_complete)
        self.step3.generationError.connect(self._on_generation_error)

        # remove step4 if present
        if self.stack.count() > 3:
            w = self.stack.widget(3)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.step4 = None

        self.stack.insertWidget(1, self.step2)
        self.stack.insertWidget(2, self.step3)
        self.stack.setCurrentIndex(0)
        self.sidebar.provider_combo.setCurrentIndex(0)
        self.sidebar.api_key_edit.clear()


# ────────────────────────────────────────────
#  Entry point
# ────────────────────────────────────────────

def main():
    _set_taskbar_app_id()
    app = QApplication(sys.argv)
    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setApplicationName("StudyAssistant")
    app.setApplicationDisplayName("StudyAssistant")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    dark = bool(_load_settings().get("dark_mode", False))
    _apply_theme(dark)
    app.installEventFilter(ChineseContextMenuFilter(app))
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    if window.windowHandle() is not None:
        window.windowHandle().setIcon(icon)
    _apply_titlebar_theme(window, dark)
    QTimer.singleShot(50, lambda: _apply_titlebar_theme(window, dark))
    app.setWindowIcon(icon)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

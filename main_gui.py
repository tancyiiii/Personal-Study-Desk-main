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
import time
from queue import Empty, Queue


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
    Qt, QThread, QTimer, Signal, Slot, QObject, QEvent, QRectF,
    QVariantAnimation, QEasingCurve, QPointF,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QTextEdit, QTextBrowser, QCheckBox, QSlider, QFileDialog,
    QMessageBox, QProgressBar, QGroupBox, QFormLayout, QFrame,
    QListWidget, QListWidgetItem, QRadioButton, QButtonGroup,
    QTabWidget, QSpinBox, QDockWidget, QScrollArea, QSizePolicy,
    QGridLayout, QMenu, QSizeGrip, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QStyleOptionComboBox,
)
from PySide6.QtGui import (
    QFont, QIcon, QAction, QPixmap,
    QTextCursor, QTextDocument, QTextBlockFormat,
    QPalette, QColor, QPainter, QPen, QFontDatabase, QPainterPath,
    QRegion,
)

from business import (
    StudyAssistantHandler,
    DemoStudyAssistantHandler,
    ConfigManager,
    set_api_key_env,
)
from resource_path import resource_path
from quiz_engine import grade_quiz


def _app_icon() -> QIcon:
    """Return the custom app icon, falling back to the default if missing."""
    for name in ("icon.png", "icon.jpg", "icon.jpeg", "icon.ico"):
        icon_path = resource_path(os.path.join("assets", name))
        if os.path.isfile(icon_path):
            return QIcon(icon_path)
    return QIcon()


def _load_app_font() -> QFont:
    """Load bundled Claude-style fonts, falling back to the system font."""
    font_files = (
        "AnthropicSans.ttf",
        "AnthropicSerif.ttf",
        "AnthropicMono.ttf",
    )
    loaded_families = []
    for file_name in font_files:
        path = resource_path(os.path.join("assets", "fonts", file_name))
        try:
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id >= 0:
                loaded_families.extend(
                    QFontDatabase.applicationFontFamilies(font_id)
                )
        except Exception:
            pass
    for family in loaded_families:
        if family.lower().startswith("anthropic sans"):
            return QFont(family, 11)
    font_path = resource_path(
        os.path.join("assets", "fonts", "LXGWNeoXiHei.ttf")
    )
    try:
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return QFont(families[0], 11)
    except Exception:
        pass
    return QFont("Microsoft YaHei UI", 11)


def _chat_label_html(
    text: str,
    text_color: str = None,
    link_color: str = "#c9562b",
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
            "#f2c4b5" if role == "user" else "#c9562b",
            markdown=(role != "user"),
        )
    )
    label.adjustSize()
    return label


class RoundedComboDelegate(QStyledItemDelegate):
    """Rounded, theme-aware selection highlight inside combo popups."""

    def paint(self, painter, option, index):
        state = option.state
        if state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver):
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            fill = QColor(option.palette.color(QPalette.ColorRole.Highlight))
            if (
                state & QStyle.StateFlag.State_MouseOver
                and not state & QStyle.StateFlag.State_Selected
            ):
                fill.setAlpha(110)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(option.rect).adjusted(4.0, 3.0, -4.0, -3.0),
                7.0,
                7.0,
            )
            painter.restore()
            option = QStyleOptionViewItem(option)
            option.state &= ~(
                QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
            )
        super().paint(painter, option, index)


def _apply_rounded_combo(combo: QComboBox) -> None:
    """Give a combo box rounded popup items matching the Claude theme."""
    view = combo.view()
    view.setItemDelegate(RoundedComboDelegate(view))
    view.setMouseTracking(True)


class RoundedComboBox(QComboBox):
    """Combo box with a painted chevron and a truly rounded popup panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _apply_rounded_combo(self)

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        if arrow_rect.isEmpty():
            arrow_rect = QRectF(
                self.width() - 30.0, 0.0, 30.0, self.height()
            )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self.palette().color(QPalette.ColorRole.Text), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center = arrow_rect.center()
        x, y = center.x(), center.y()
        painter.drawLine(QPointF(x - 4.5, y - 1.5), QPointF(x, y + 2.5))
        painter.drawLine(QPointF(x, y + 2.5), QPointF(x + 4.5, y - 1.5))
        painter.end()

    def showPopup(self):
        super().showPopup()
        view = self.view()
        popup = view.window() if view is not None else None
        if popup is None:
            return
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setAttribute(Qt.WA_StyledBackground, True)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        background = "#30302e" if dark else "#ffffff"
        border = "#4b4b46" if dark else "#e0dcd2"
        popup.setStyleSheet(
            f"QFrame {{ background-color: {background}; "
            f"border: 1px solid {border}; border-radius: 12px; }}"
        )
        view.setStyleSheet(
            "QListView { background: transparent; border: none; outline: none; }"
        )
        view.viewport().setAutoFillBackground(False)
        view.viewport().setAttribute(Qt.WA_TranslucentBackground, False)
        path = QPainterPath()
        path.addRoundedRect(QRectF(popup.rect()), 12.0, 12.0)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))
        popup.update()


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
        palette.setColor(QPalette.ColorRole.Window, QColor("#262624"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#1f1e1d"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#30302e"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#faf9f5"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#faf9f5"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#30302e"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#faf9f5"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#d97757"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1f1e1d"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#30302e"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#faf9f5"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#e6987d"))
        app.setPalette(palette)
        app.setStyleSheet(APP_STYLE_SHEET_DARK)
    else:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#f6f2e9"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f1ece1"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#141413"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#141413"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#f6f2e9"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#141413"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#d97757"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1f1e1d"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#faf9f5"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#c9562b"))
        app.setPalette(palette)
        app.setStyleSheet(APP_STYLE_SHEET)
    _apply_titlebar_theme(window, dark)
    if window is not None:
        QTimer.singleShot(50, lambda: _apply_titlebar_theme(window, dark))


APP_STYLE_SHEET = """
QMainWindow {
    background-color: #f6f2e9;
}
QWidget#titleBar {
    background-color: #f6f2e9;
    border-bottom: 1px solid #e8e4d8;
}
QWidget#mainContent {
    background-color: #f6f2e9;
}
QWidget {
    color: #141413;
    font-size: 14px;
    font-family: "Anthropic Sans Web Text", "LXGW Neo XiHei", "Microsoft YaHei UI";
}
QLabel#windowTitleLabel {
    color: #141413;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#windowButton, QPushButton#windowButtonClose {
    background: transparent;
    color: #141413;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: 17px;
    font-weight: 500;
}
QPushButton#windowButton:hover {
    background-color: #ebe6da;
}
QPushButton#windowButton:pressed {
    background-color: #e8e4d8;
}
QPushButton#windowButtonClose:hover {
    background-color: #c9562b;
    color: #ffffff;
}
QPushButton#windowButtonClose:pressed {
    background-color: #a94f2d;
    color: #ffffff;
}
QWidget#sidebar {
    background-color: #f1ece1;
    border-right: 1px solid #e8e4d8;
}
QStackedWidget {
    background-color: #f6f2e9;
}
QLabel {
    background: transparent;
}
QPushButton {
    background-color: #f6f2e9;
    color: #141413;
    border: 1px solid #d8d2c6;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #ebe6da;
    border-color: #c4bdb0;
}
QPushButton:pressed {
    background-color: #e8e4d8;
}
QPushButton:disabled {
    color: #a5a49d;
    background-color: #f2f0e8;
    border-color: #e8e4d8;
}
QPushButton#primaryButton {
    background-color: #1f1e1d;
    color: #faf9f5;
    border: 1px solid #1f1e1d;
    border-radius: 8px;
    padding: 9px 22px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #3d3d3a;
    border-color: #3d3d3a;
}
QPushButton#primaryButton:pressed {
    background-color: #5a5959;
}
QPushButton#primaryButton:disabled {
    background-color: #d8d2c6;
    border-color: #d8d2c6;
    color: #faf9f5;
}
QPushButton[card="true"] {
    background-color: #f1ece1;
    border: 1px solid #e0dcd2;
    border-radius: 10px;
    font-size: 15px;
}
QPushButton[card="true"]:hover {
    border-color: #d97757;
    background-color: #f7f0ec;
}
QPushButton#settingsButton {
    background-color: #ebe6da;
    border: 1px solid #e0dcd2;
    color: #141413;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
    text-align: left;
}
QPushButton#settingsButton:hover {
    background-color: #e8e4d8;
    border-color: #c4bdb0;
}
QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #d8d2c6;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: rgba(217, 119, 87, 70);
    selection-color: #141413;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #d97757;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 30px;
    margin-left: 4px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox {
    padding: 8px 32px 8px 12px;
}
QSpinBox {
    padding: 6px 28px 6px 10px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #e0dcd2;
    border-radius: 12px;
    padding: 4px;
    outline: none;
    selection-background-color: #ebe6da;
    selection-color: #141413;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 6px 10px;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #ebe6da;
    color: #141413;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 24px;
    border: none;
    background: transparent;
    border-radius: 6px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #ebe6da;
}
QSpinBox::up-arrow, QSpinBox::down-arrow {
    image: none;
    width: 12px;
    height: 6px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #73726c;
}
QSpinBox::down-arrow {
    border-bottom: none;
    border-top: 5px solid #73726c;
}
QRadioButton {
    spacing: 8px;
    color: #141413;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid #c4bdb0;
    background-color: #ffffff;
}
QRadioButton::indicator:hover {
    border-color: #d97757;
}
QRadioButton::indicator:checked {
    border-color: #d97757;
    background-color: #d97757;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #e0dcd2;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
    color: #141413;
}
QMenu::item:selected {
    background-color: #ebe6da;
}
QMenu::item:disabled {
    color: #a5a49d;
}
QMenu::separator {
    height: 1px;
    background-color: #ebe6da;
    margin: 6px 10px;
}
QLineEdit, QTextEdit {
    placeholder-text-color: #a5a49d;
}
QGroupBox {
    background-color: #f1ece1;
    border: 1px solid #e0dcd2;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #141413;
}
QTabWidget {
    background-color: #f6f2e9;
}
QTabWidget::pane {
    border: 1px solid #e0dcd2;
    background-color: #f6f2e9;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 11px 18px;
    color: #73726c;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #141413;
    border-bottom: 2px solid #d97757;
}
QTabBar::tab:hover {
    color: #141413;
}
QProgressBar {
    background-color: #ebe6da;
    border: none;
    border-radius: 6px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar#generationProgress {
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk {
    background-color: #d97757;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c4bdb0;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #a5a49d;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #c4bdb0;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #a5a49d;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QToolTip {
    background-color: #1f1e1d;
    color: #faf9f5;
    border: none;
    padding: 8px 10px;
}
QLabel#chatHeader {
    font-size: 16px;
    font-weight: 600;
    color: #141413;
}
QLabel#mutedLabel {
    color: #73726c;
    font-size: 13px;
}
QLabel#chatPlaceholder {
    color: #a5a49d;
    font-size: 14px;
}
QLabel#quizStatusLabel {
    color: #c9562b;
    font-size: 13px;
    padding: 4px 0;
}
QLabel#chatBubbleUser {
    background-color: #d97757;
    color: #ffffff;
    border-radius: 14px;
    padding: 11px 16px;
}
QLabel#chatBubbleAssistant {
    background-color: #ebe6da;
    color: #141413;
    border-radius: 14px;
    padding: 11px 16px;
}
QScrollArea#chatScroll, QScrollArea#settingsScroll {
    background: transparent;
    border: none;
}
QFrame#chatInputContainer {
    background-color: #ffffff;
    border: 1px solid #d8d2c6;
    border-radius: 14px;
}
QTextEdit#chatInputField {
    background: transparent;
    border: none;
    padding: 8px 6px;
}
QPushButton#chatSendButton {
    background-color: #1f1e1d;
    color: #ffffff;
    border: none;
    border-radius: 17px;
    font-size: 18px;
    font-weight: 600;
}
QPushButton#chatSendButton:hover {
    background-color: #3d3d3a;
}
QPushButton#chatSendButton:pressed {
    background-color: #5a5959;
}
QListWidget#historyList {
    background-color: #f6f2e9;
    border: 1px solid #e0dcd2;
    border-radius: 8px;
    padding: 5px;
}
QListWidget#historyList::item {
    padding: 9px;
    border-bottom: 1px solid #ebe6da;
}
QListWidget#historyList::item:selected {
    background-color: #ebe6da;
    color: #141413;
}
QListWidget#historyList::item:hover {
    background-color: #f1ece1;
}
QTextBrowser#answerBrowser {
    background-color: #f1ece1;
    border: 1px solid #e8e4d8;
    border-radius: 12px;
    padding: 12px 14px;
    color: #141413;
}
"""

APP_STYLE_SHEET_DARK = """
QMainWindow {
    background-color: #262624;
}
QWidget#titleBar {
    background-color: #262624;
    border-bottom: 1px solid #3b3b37;
}
QWidget#mainContent {
    background-color: #262624;
}
QWidget {
    color: #faf9f5;
    font-size: 14px;
    font-family: "Anthropic Sans Web Text", "LXGW Neo XiHei", "Microsoft YaHei UI";
}
QLabel#windowTitleLabel {
    color: #faf9f5;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#windowButton, QPushButton#windowButtonClose {
    background: transparent;
    color: #faf9f5;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: 17px;
    font-weight: 500;
}
QPushButton#windowButton:hover {
    background-color: #3a3a37;
}
QPushButton#windowButton:pressed {
    background-color: #4b4b46;
}
QPushButton#windowButtonClose:hover {
    background-color: #c9562b;
    color: #ffffff;
}
QPushButton#windowButtonClose:pressed {
    background-color: #a94f2d;
    color: #ffffff;
}
QWidget#sidebar {
    background-color: #1f1e1d;
    border-right: 1px solid #3b3b37;
}
QStackedWidget {
    background-color: #262624;
}
QLabel {
    background: transparent;
}
QPushButton {
    background-color: #30302e;
    color: #faf9f5;
    border: 1px solid #4b4b46;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #3a3a37;
    border-color: #6d6d65;
}
QPushButton:pressed {
    background-color: #4b4b46;
}
QPushButton:disabled {
    color: #6f6f68;
    background-color: #2a2a28;
    border-color: #3b3b37;
}
QPushButton#primaryButton {
    background-color: #d97757;
    color: #1f1e1d;
    border: 1px solid #d97757;
    border-radius: 8px;
    padding: 9px 22px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #e28469;
    border-color: #e28469;
}
QPushButton#primaryButton:pressed {
    background-color: #c46543;
}
QPushButton#primaryButton:disabled {
    background-color: #3b3b37;
    border-color: #3b3b37;
    color: #6f6f68;
}
QPushButton[card="true"] {
    background-color: #30302e;
    border: 1px solid #3b3b37;
    border-radius: 10px;
    font-size: 15px;
}
QPushButton[card="true"]:hover {
    border-color: #e28469;
    background-color: #332b28;
}
QPushButton#settingsButton {
    background-color: #30302e;
    border: 1px solid #4b4b46;
    color: #faf9f5;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
    text-align: left;
}
QPushButton#settingsButton:hover {
    background-color: #3a3a37;
    border-color: #6d6d65;
}
QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {
    background-color: #1f1e1d;
    border: 1px solid #4b4b46;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: rgba(217, 119, 87, 90);
    selection-color: #faf9f5;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #e28469;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 30px;
    margin-left: 4px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox {
    padding: 8px 32px 8px 12px;
}
QSpinBox {
    padding: 6px 28px 6px 10px;
}
QComboBox QAbstractItemView {
    background-color: #30302e;
    border: 1px solid #4b4b46;
    border-radius: 12px;
    padding: 4px;
    outline: none;
    selection-background-color: #3a3a37;
    selection-color: #faf9f5;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 6px 10px;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #3a3a37;
    color: #faf9f5;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 24px;
    border: none;
    background: transparent;
    border-radius: 6px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #3a3a37;
}
QSpinBox::up-arrow, QSpinBox::down-arrow {
    image: none;
    width: 12px;
    height: 6px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #9a9c92;
}
QSpinBox::down-arrow {
    border-bottom: none;
    border-top: 5px solid #9a9c92;
}
QRadioButton {
    spacing: 8px;
    color: #faf9f5;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid #6d6d65;
    background-color: #1f1e1d;
}
QRadioButton::indicator:hover {
    border-color: #e28469;
}
QRadioButton::indicator:checked {
    border-color: #d97757;
    background-color: #d97757;
}
QMenu {
    background-color: #30302e;
    border: 1px solid #4b4b46;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
    color: #faf9f5;
}
QMenu::item:selected {
    background-color: #3a3a37;
}
QMenu::item:disabled {
    color: #6f6f68;
}
QMenu::separator {
    height: 1px;
    background-color: #3a3a37;
    margin: 6px 10px;
}
QLineEdit, QTextEdit {
    placeholder-text-color: #6f6f68;
}
QGroupBox {
    background-color: #30302e;
    border: 1px solid #3b3b37;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #faf9f5;
}
QTabWidget {
    background-color: #262624;
}
QTabBar {
    background-color: #262624;
}
QTabWidget::pane {
    border: 1px solid #3b3b37;
    background-color: #262624;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 11px 18px;
    color: #9a9c92;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #faf9f5;
    border-bottom: 2px solid #d97757;
}
QTabBar::tab:hover {
    color: #faf9f5;
}
QProgressBar {
    background-color: #3b3b37;
    border: none;
    border-radius: 6px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar#generationProgress {
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk {
    background-color: #d97757;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #5c5b55;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #8a8981;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #5c5b55;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #8a8981;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QToolTip {
    background-color: #30302e;
    color: #faf9f5;
    border: none;
    padding: 8px 10px;
}
QLabel#chatHeader {
    font-size: 16px;
    font-weight: 600;
    color: #faf9f5;
}
QLabel#mutedLabel {
    color: #9a9c92;
    font-size: 13px;
}
QLabel#chatPlaceholder {
    color: #6f6f68;
    font-size: 14px;
}
QLabel#quizStatusLabel {
    color: #e6987d;
    font-size: 13px;
    padding: 4px 0;
}
QLabel#chatBubbleUser {
    background-color: #d97757;
    color: #ffffff;
    border-radius: 14px;
    padding: 11px 16px;
}
QLabel#chatBubbleAssistant {
    background-color: #30302e;
    color: #faf9f5;
    border-radius: 14px;
    padding: 11px 16px;
}
QScrollArea#chatScroll, QScrollArea#settingsScroll {
    background: transparent;
    border: none;
}
QFrame#chatInputContainer {
    background-color: #1f1e1d;
    border: 1px solid #4b4b46;
    border-radius: 14px;
}
QTextEdit#chatInputField {
    background: transparent;
    border: none;
    padding: 8px 6px;
}
QPushButton#chatSendButton {
    background-color: #d97757;
    color: #1f1e1d;
    border: none;
    border-radius: 17px;
    font-size: 18px;
    font-weight: 600;
}
QPushButton#chatSendButton:hover {
    background-color: #e28469;
}
QPushButton#chatSendButton:pressed {
    background-color: #c46543;
}
QListWidget#historyList {
    background-color: #1f1e1d;
    border: 1px solid #3b3b37;
    border-radius: 8px;
    padding: 5px;
}
QListWidget#historyList::item {
    padding: 9px;
    border-bottom: 1px solid #30302e;
}
QListWidget#historyList::item:selected {
    background-color: #3a3a37;
    color: #faf9f5;
}
QListWidget#historyList::item:hover {
    background-color: #30302e;
}
QTextBrowser#answerBrowser {
    background-color: #30302e;
    border: 1px solid #3b3b37;
    border-radius: 12px;
    padding: 12px 14px;
    color: #faf9f5;
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


class DarkModeSwitch(QCheckBox):
    """A custom toggle switch styled like the web slider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("深色模式")
        self._progress = 1.0 if self.isChecked() else 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_animation_value)
        self.toggled.connect(self._start_animation)

    def _start_animation(self, checked: bool):
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _on_animation_value(self, value):
        self._progress = float(value)
        self.update()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        width = self.width()
        height = self.height()
        track = QRectF(0.5, 0.5, width - 1, height - 1)

        off = QColor("#d9d2c6")
        on = QColor("#d97757")
        track_color = QColor(
            int(off.red() + (on.red() - off.red()) * self._progress),
            int(off.green() + (on.green() - off.green()) * self._progress),
            int(off.blue() + (on.blue() - off.blue()) * self._progress),
        )
        knob_diameter = height - 8
        knob_x = 4 + self._progress * (width - height)

        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, height / 2, height / 2)

        knob_rect = QRectF(knob_x, 4, knob_diameter, knob_diameter)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob_rect)
        painter.end()


class AnimatedSendButton(QPushButton):
    """Pill-shaped send button with an expanding hover fill."""

    def __init__(self, parent=None):
        super().__init__("发送", parent)
        self.setFixedHeight(42)
        self.setMinimumWidth(104)
        self.setCursor(Qt.PointingHandCursor)
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_animation_value)

    def enterEvent(self, event):
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_to(0.0)
        super().leaveEvent(event)

    def _animate_to(self, target: float):
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def _on_animation_value(self, value):
        self._progress = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        width = rect.width()
        height = rect.height()
        border_color = self.palette().color(QPalette.ColorRole.WindowText)
        window_color = self.palette().color(QPalette.ColorRole.Window)
        radius = height / 2

        pill = QPainterPath()
        pill.addRoundedRect(
            QRectF(1, 1, width - 2, height - 2), radius, radius
        )
        painter.setClipPath(pill)
        painter.setClipping(True)

        painter.setPen(QPen(border_color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            QRectF(1, 1, width - 2, height - 2), radius, radius
        )

        if self._progress > 0:
            center = QPointF(width / 2, height / 2)
            max_radius = (width ** 2 + height ** 2) ** 0.5 / 2
            painter.setPen(Qt.NoPen)
            painter.setBrush(border_color)
            painter.drawEllipse(
                center, max_radius * self._progress, max_radius * self._progress
            )

        font = self.font()
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        painter.setFont(font)
        painter.setPen(window_color if self._progress >= 0.5 else border_color)
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()


class ChatInputEdit(QTextEdit):
    """Input that sends on Enter and inserts a newline on Shift+Enter."""

    sendRequested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.sendRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


# ────────────────────────────────────────────
#  Custom frameless window title bar
# ────────────────────────────────────────────

class TitleBarWidget(QWidget):
    """Draggable title bar with minimize, maximize, and close controls."""

    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(38)
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        title_label = QLabel("AI 学习助手")
        title_label.setObjectName("windowTitleLabel")
        layout.addWidget(title_label)
        layout.addStretch(1)

        self.min_button = self._build_window_button("—", "最小化")
        self.max_button = self._build_window_button("□", "最大化/还原")
        self.close_button = self._build_window_button("×", "关闭", close=True)

        layout.addWidget(self.min_button)
        layout.addWidget(self.max_button)
        layout.addWidget(self.close_button)

        self.min_button.clicked.connect(self.minimizeRequested.emit)
        self.max_button.clicked.connect(self.maximizeRequested.emit)
        self.close_button.clicked.connect(self.closeRequested.emit)

    @staticmethod
    def _build_window_button(text: str, tooltip: str, close: bool = False):
        button = QPushButton(text)
        button.setObjectName("windowButtonClose" if close else "windowButton")
        button.setToolTip(tooltip)
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(46, 38)
        return button

    def set_maximized(self, maximized: bool):
        self.max_button.setToolTip("还原" if maximized else "最大化")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if isinstance(window, QWidget):
                self._drag_offset = (
                    event.globalPosition().toPoint()
                    - window.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        window = self.window()
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and isinstance(window, QWidget)
            and not window.isMaximized()
        ):
            window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximizeRequested.emit()
        super().mouseDoubleClickEvent(event)


# ────────────────────────────────────────────
#  Sidebar settings pane (always visible)
# ────────────────────────────────────────────

class SidebarWidget(QWidget):
    """Provider / model / API key settings, always visible on the left."""

    providerChanged = Signal(str)
    apiKeyChanged   = Signal(str, str)   # provider, key
    themeChanged    = Signal(bool)
    historySelected = Signal(dict)
    newPlanRequested = Signal()
    demoRequested = Signal()

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
        title_font = QFont("Anthropic Serif Web Text", 15)
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

        self.provider_combo = RoundedComboBox()
        self.provider_combo.addItems(["deepseek", "groq", "openai"])
        self.provider_combo.setToolTip(
            "DeepSeek 性价比高、推理能力强。Groq 免费且快速。OpenAI 需要付费 API 密钥。"
        )
        settings_layout.addWidget(self.provider_combo)

        settings_layout.addWidget(QLabel("选择模型"))

        self.model_combo = RoundedComboBox()
        self._update_model_options("deepseek")
        settings_layout.addWidget(self.model_combo)

        settings_layout.addWidget(QLabel("API 密钥"))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("在此粘贴你的 API 密钥")
        self.api_key_edit.setToolTip("输入所选提供商的 API 密钥。")
        settings_layout.addWidget(self.api_key_edit)

        dark_row = QHBoxLayout()
        dark_label = QLabel("深色模式")
        dark_row.addWidget(dark_label)
        dark_row.addStretch(1)

        self.dark_mode_check = DarkModeSwitch()
        self.dark_mode_check.setChecked(_load_settings().get("dark_mode", False))
        dark_row.addWidget(self.dark_mode_check)
        settings_layout.addLayout(dark_row)

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

        self.demo_btn = QPushButton("打开离线示例项目")
        self.demo_btn.setToolTip(
            "无需 API 密钥，展示完整的智能体学习闭环。"
        )
        layout.addWidget(self.demo_btn)

        self.new_plan_btn = QPushButton("开始新的学习计划")
        self.new_plan_btn.setObjectName("primaryButton")
        layout.addWidget(self.new_plan_btn)

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
        self.new_plan_btn.clicked.connect(self.newPlanRequested.emit)
        self.demo_btn.clicked.connect(self.demoRequested.emit)

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
        hf = QFont("Anthropic Serif Web Text", 18)
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
        hf = QFont("Anthropic Serif Web Text", 18)
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

        self.knowledge_combo = RoundedComboBox()
        levels = ConfigManager().get_all_knowledge_levels()
        level_map = {"beginner": "入门", "intermediate": "中级",
                      "advanced": "高级", "expert": "专家"}
        for lv in levels:
            self.knowledge_combo.addItem(level_map.get(lv, lv.title()), lv)
        self.knowledge_combo.currentIndexChanged.connect(self._on_knowledge_changed)
        left_layout.addRow("你当前的知识水平是？", self.knowledge_combo)

        self.level_info_label = QLabel()
        self.level_info_label.setWordWrap(True)
        self.level_info_label.setStyleSheet("color: #8f8a83;")
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

        self.time_combo = RoundedComboBox()
        for t in ["每周 1-2 小时", "每周 3-5 小时", "每周 6-10 小时",
                   "每周 10+ 小时", "全职（每周 30+ 小时）"]:
            self.time_combo.addItem(t)
        right_layout.addRow("你每周能投入多少时间？", self.time_combo)

        self.style_combo = RoundedComboBox()
        styles = ConfigManager().get_all_learning_styles()
        for s in styles:
            self.style_combo.addItem(s.replace("_", " ").title(), s)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        right_layout.addRow("What's your preferred learning style?", self.style_combo)

        self.style_info_label = QLabel()
        self.style_info_label.setWordWrap(True)
        self.style_info_label.setStyleSheet("color: #8f8a83;")
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
        self._stage_index = 0
        self._trace_lines: list[str] = []
        self._trace_queue = Queue()
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_status)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(120)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_start_value = 0
        self._progress_target = 0
        self._progress_started_at = time.monotonic()
        self._progress_duration = 12000
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
        hf = QFont("Anthropic Serif Web Text", 18)
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
        self.progress_bar.setObjectName("generationProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(430)

        progress_row = QHBoxLayout()
        progress_row.addStretch(1)
        progress_row.addWidget(self.progress_bar)
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("mutedLabel")
        self.progress_percent_label.setAlignment(Qt.AlignCenter)
        self.progress_percent_label.setMinimumWidth(54)
        progress_row.addWidget(self.progress_percent_label)
        progress_row.addStretch(1)
        layout.addLayout(progress_row)

        self.status_label = QLabel("准备中...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.stage_hint_label = QLabel(
            "智能体将依次完成学习分析、路线规划和资源检索"
        )
        self.stage_hint_label.setObjectName("mutedLabel")
        self.stage_hint_label.setAlignment(Qt.AlignCenter)
        self.stage_hint_label.setWordWrap(True)
        self.stage_hint_label.setMaximumWidth(620)
        layout.addWidget(self.stage_hint_label)

        self.trace_browser = QTextBrowser()
        self.trace_browser.setMaximumHeight(118)
        self.trace_browser.setPlaceholderText(
            "这里会显示当前 Agent 的任务理解和流程编排过程。"
        )
        layout.addWidget(self.trace_browser)
        self._trace_poll_timer = QTimer(self)
        self._trace_poll_timer.setInterval(100)
        self._trace_poll_timer.timeout.connect(self._drain_trace_queue)
        self._trace_poll_timer.start()
        layout.addStretch()

    def start_generation(self, handler: StudyAssistantHandler):
        """Start the 3-step generation sequence in background threads."""
        self._handler = handler
        self._results = {}
        self._trace_lines = []
        self._progress_timer.stop()
        self._set_progress(0)
        while True:
            try:
                self._trace_queue.get_nowait()
            except Empty:
                break
        self.trace_browser.clear()
        self._handler.set_trace_callback(self._on_trace)
        self._run_analysis()

    def _on_trace(self, stage: str, detail: str):
        self._trace_queue.put((stage, detail))

    def _drain_trace_queue(self):
        while True:
            try:
                stage, detail = self._trace_queue.get_nowait()
            except Empty:
                break
            self._append_trace(stage, detail)

    def _append_trace(self, stage: str, detail: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {stage}  {detail}"
        self._trace_lines.append(line)
        self.trace_browser.setPlainText("\n".join(self._trace_lines[-20:]))

    def _run_analysis(self):
        self._begin_stage(
            1,
            "正在分析学习需求",
            34,
            "智能体正在理解学习目标、当前水平和知识盲区",
        )
        self._worker = WorkerThread(self._handler.analyze_student)
        self._worker.signals.finished.connect(self._on_analysis_done)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_analysis_done(self, result: str):
        self._results["analysis"] = result
        self._complete_stage(34)
        self._begin_stage(
            2,
            "分析完成 · 正在创建学习路线",
            67,
            "智能体正在编排学习阶段、里程碑和复习节点",
        )
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
        self._complete_stage(67)
        self._begin_stage(
            3,
            "路线已生成 · 正在查找学习资源",
            100,
            "智能体正在调用国内搜索工具并校验课程与练习资源",
        )
        self._run_resources()

    def _run_resources(self):
        worker = WorkerThread(self._handler.find_resources)
        worker.signals.finished.connect(self._on_resources_done)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _on_resources_done(self, result: str):
        self._results["resources"] = result
        self._complete_stage(100)
        self._stop_status_animation()
        self.status_label.setText("全部完成！")
        self.stage_hint_label.setText("学习分析、路线图和资源列表已生成并交付")
        self.generationComplete.emit(self._results)

    def _on_error(self, msg: str):
        self._progress_timer.stop()
        self._stop_status_animation()
        self.stage_hint_label.setText("生成失败，请检查模型配置后重试")
        self.generationError.emit(msg)

    def _begin_stage(self, stage_index, base_text, target, hint):
        self._stage_index = stage_index
        self.stage_hint_label.setText(hint)
        self._start_status_animation(base_text)
        self._animate_progress_to(target - 4, duration=4500)

    def _complete_stage(self, target):
        self._progress_timer.stop()
        self._set_progress(target)

    def _set_progress(self, value):
        self.progress_bar.setValue(int(value))
        self.progress_percent_label.setText(f"{int(value)}%")

    def _animate_progress_to(self, target, duration=12000):
        self._progress_timer.stop()
        self._progress_start_value = self.progress_bar.value()
        self._progress_target = max(self.progress_bar.value(), target)
        self._progress_started_at = time.monotonic()
        self._progress_duration = duration
        self._progress_timer.start()

    def _tick_progress(self):
        elapsed_ms = (
            time.monotonic() - self._progress_started_at
        ) * 1000
        ratio = min(max(elapsed_ms / self._progress_duration, 0.0), 1.0)
        value = self._progress_start_value + (
            self._progress_target - self._progress_start_value
        ) * ratio
        self._set_progress(value)
        if ratio >= 1.0:
            self._progress_timer.stop()

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
        percent = self.progress_bar.value()
        self.status_label.setText(
            f"阶段 {self._stage_index}/3 · "
            f"{self._status_base}{suffix} · {percent}%"
        )


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
        self._quiz_data = None
        self._quiz_answer_widgets = {}
        self._trace_lines: list[str] = []
        self._trace_queue = Queue()
        self._thinking_row = None
        self._thinking_timer = None
        self._thinking_label = None
        self._thinking_started = 0.0
        self._quiz_timer = None
        self._quiz_started = 0.0
        self._build_ui()
        self._trace_poll_timer = QTimer(self)
        self._trace_poll_timer.setInterval(100)
        self._trace_poll_timer.timeout.connect(self._drain_trace_queue)
        self._trace_poll_timer.start()
        self._handler.set_trace_callback(self._on_trace)
        if quiz:
            self.quiz_browser.setMarkdown(quiz)
            self.quiz_browser.setVisible(True)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(8)

        # heading
        heading = QLabel("🎯 学习仪表盘")
        hf = QFont("Anthropic Serif Web Text", 18)
        hf.setPointSize(18)
        hf.setBold(True)
        heading.setFont(hf)
        outer.addWidget(heading)

        # Always-visible agent orchestration trace.
        trace_header = QHBoxLayout()
        trace_title = QLabel("Agent 执行轨迹")
        trace_title.setObjectName("mutedLabel")
        trace_header.addWidget(trace_title)
        trace_header.addStretch()
        clear_trace_btn = QPushButton("清空轨迹")
        clear_trace_btn.setFlat(True)
        clear_trace_btn.clicked.connect(self._clear_trace)
        trace_header.addWidget(clear_trace_btn)
        outer.addLayout(trace_header)
        self.trace_browser = QTextBrowser()
        self.trace_browser.setMaximumHeight(118)
        self.trace_browser.setPlaceholderText(
            "智能体的任务理解、工具调用和结果交付过程会在这里显示。"
        )
        outer.addWidget(self.trace_browser)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_roadmap_tab(), " 学习路线")
        tabs.addTab(self._build_resources_tab(), " 学习资源")
        tabs.addTab(self._build_tasks_tab(), " 任务清单")
        tabs.addTab(self._build_quiz_tab(), " 生成测验")
        tabs.addTab(self._build_tutor_tab(), " AI 辅导")
        tabs.addTab(self._build_rag_tab(), " 文档问答 (RAG)")
        outer.addWidget(tabs)

        self._task_key = f"{self._handler.topic}|{self._handler.learning_goal}"
        self._restore_tasks()

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

    # ── Tab 2.5: Execution checklist ──
    def _build_tasks_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QLabel("任务清单")
        header.setObjectName("chatHeader")
        layout.addWidget(header)

        input_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("例如：完成 Python 环境配置")
        self.task_input.returnPressed.connect(self._add_task)
        input_row.addWidget(self.task_input, 1)
        add_btn = QPushButton("添加任务")
        add_btn.clicked.connect(self._add_task)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

        self.task_list = QListWidget()
        self.task_list.itemChanged.connect(self._update_task_progress)
        layout.addWidget(self.task_list, 1)

        progress_row = QHBoxLayout()
        self.task_progress = QProgressBar()
        self.task_progress.setRange(0, 1)
        self.task_progress.setValue(0)
        progress_row.addWidget(self.task_progress, 1)
        self.task_progress_label = QLabel("0/0")
        self.task_progress_label.setObjectName("mutedLabel")
        progress_row.addWidget(self.task_progress_label)
        layout.addLayout(progress_row)

        clear_btn = QPushButton("清除已完成")
        clear_btn.clicked.connect(self._clear_completed_tasks)
        layout.addWidget(clear_btn, 0, Qt.AlignRight)
        return w

    def _tasks_path(self):
        return os.path.join(_app_data_dir(), "study_tasks.json")

    def _load_tasks_for_current_plan(self):
        try:
            with open(self._tasks_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            return data.get(self._task_key, [])
        except Exception:
            return []

    def _save_tasks(self):
        try:
            path = self._tasks_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
            data[self._task_key] = [
                {"text": item.text(), "done": item.checkState() == Qt.Checked}
                for item in self.task_list.findItems("*", Qt.MatchWildcard)
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            _log_error(traceback.format_exc())

    def _restore_tasks(self):
        for item_data in self._load_tasks_for_current_plan():
            if not isinstance(item_data, dict):
                continue
            item = QListWidgetItem(item_data.get("text", ""))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if item_data.get("done") else Qt.Unchecked
            )
            self.task_list.addItem(item)
        self._update_task_progress()

    def _add_task(self):
        text = self.task_input.text().strip()
        if not text:
            return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        self.task_list.addItem(item)
        self.task_input.clear()
        self._update_task_progress()

    def _update_task_progress(self):
        total = self.task_list.count()
        done = sum(
            1
            for index in range(total)
            if self.task_list.item(index).checkState() == Qt.Checked
        )
        self.task_progress.setRange(0, max(total, 1))
        self.task_progress.setValue(done)
        self.task_progress_label.setText(f"{done}/{total}")
        self._save_tasks()

    def _clear_completed_tasks(self):
        for index in range(self.task_list.count() - 1, -1, -1):
            item = self.task_list.item(index)
            if item.checkState() == Qt.Checked:
                self.task_list.takeItem(index)
        self._update_task_progress()

    # ── Tab 3: Quiz Generator ──
    def _build_quiz_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        form_row = QHBoxLayout()

        # Difficulty
        form_row.addWidget(QLabel("难度等级"))
        self.difficulty_combo = RoundedComboBox()
        self.difficulty_combo.addItems(["入门", "中级", "高级"])
        self.difficulty_combo.setCurrentIndex(1)
        form_row.addWidget(self.difficulty_combo)

        # Num questions
        form_row.addWidget(QLabel("题目数量"))
        self.num_spin = QSpinBox()
        self.num_spin.setRange(1, 20)
        self.num_spin.setValue(3)
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

        self.quiz_status_label = QLabel("正在为您生成测试 0 秒")
        self.quiz_status_label.setObjectName("quizStatusLabel")
        self.quiz_status_label.setVisible(False)
        layout.addWidget(self.quiz_status_label)

        self.quiz_browser = QTextBrowser()
        self.quiz_browser.setVisible(False)
        layout.addWidget(self.quiz_browser, 1)

        self.quiz_scroll = QScrollArea()
        self.quiz_scroll.setObjectName("quizScroll")
        self.quiz_scroll.setWidgetResizable(True)
        self.quiz_scroll.setFrameShape(QFrame.NoFrame)
        self.quiz_scroll.setVisible(False)
        self.quiz_content = QWidget()
        self.quiz_content_layout = QVBoxLayout(self.quiz_content)
        self.quiz_content_layout.setContentsMargins(4, 4, 4, 4)
        self.quiz_content_layout.setSpacing(10)
        self.quiz_scroll.setWidget(self.quiz_content)
        layout.addWidget(self.quiz_scroll, 1)

        download_btn = QPushButton(" 下载测验")
        download_btn.clicked.connect(self._download_quiz)
        layout.addWidget(download_btn)

        return w

    def _generate_quiz(self):
        diff_map = {"入门": "beginner", "中级": "intermediate", "高级": "advanced"}
        difficulty = diff_map[self.difficulty_combo.currentText()]
        focus = self.focus_edit.text().strip() or "general"
        num = self.num_spin.value()
        if self._workers:
            QMessageBox.information(self, "请稍候", "上一个任务仍在运行，请稍候再试。")
            return
        self._start_quiz_status()
        self._run_worker(
            self._handler.generate_quiz_structured, difficulty, focus, num,
            callback=self._on_quiz_generated
        )

    def _on_quiz_generated(self, result):
        self._stop_quiz_status()
        if isinstance(result, dict) and result.get("questions"):
            self._quiz_data = result
            self._current_quiz = self._quiz_data_to_markdown(result)
            self.quiz_browser.setVisible(False)
            self.quiz_scroll.setVisible(True)
            self._render_quiz(result)
        else:
            raw = result.get("raw", "") if isinstance(result, dict) else str(result)
            self._quiz_data = None
            self._current_quiz = raw
            self.quiz_scroll.setVisible(False)
            self.quiz_browser.setVisible(True)
            self.quiz_browser.setMarkdown(raw)
        _save_plan_state(
            self._handler,
            self._analysis,
            self._roadmap,
            self._resources,
            self._current_quiz,
        )

    def _clear_quiz_layout(self):
        for answer_widget in self._quiz_answer_widgets.values():
            group = answer_widget.get("group")
            if isinstance(group, QButtonGroup):
                group.deleteLater()
        self._quiz_answer_widgets = {}
        while self.quiz_content_layout.count():
            item = self.quiz_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _render_quiz(self, data):
        self._clear_quiz_layout()
        questions = data.get("questions", [])
        for index, question in enumerate(questions):
            card = QGroupBox(f"第 {index + 1} 题")
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(8)

            question_label = QLabel(question.get("question", ""))
            question_label.setWordWrap(True)
            card_layout.addWidget(question_label)

            question_type = question.get("question_type", "short_answer")
            answer_data = {"type": question_type}
            if question_type == "single_choice":
                group = QButtonGroup(self)
                for option_index, option in enumerate(
                    question.get("options", [])
                ):
                    radio = QRadioButton(
                        f"{chr(65 + option_index)}) {option}"
                    )
                    radio.setSizePolicy(
                        QSizePolicy.Expanding, QSizePolicy.Preferred
                    )
                    radio.setToolTip(option)
                    group.addButton(radio)
                    card_layout.addWidget(radio)
                answer_data["group"] = group
            elif question_type == "true_false":
                group = QButtonGroup(self)
                for label in ("正确", "错误"):
                    radio = QRadioButton(label)
                    group.addButton(radio)
                    card_layout.addWidget(radio)
                answer_data["group"] = group
            else:
                edit = QTextEdit()
                edit.setMaximumHeight(90)
                edit.setPlaceholderText("写下你的推导或解释")
                card_layout.addWidget(edit)
                answer_data["edit"] = edit

            self._quiz_answer_widgets[index] = answer_data
            self.quiz_content_layout.addWidget(card)

        submit_btn = QPushButton("提交测验")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit_quiz)
        self.quiz_content_layout.addWidget(submit_btn, 0, Qt.AlignRight)

        self._quiz_result_label = QLabel()
        self._quiz_result_label.setWordWrap(True)
        self._quiz_result_label.setVisible(False)
        self.quiz_content_layout.addWidget(self._quiz_result_label)
        self.quiz_content_layout.addStretch(1)

    def _submit_quiz(self):
        if not self._quiz_data:
            return
        questions = self._quiz_data.get("questions", [])
        answers = {}
        for index, question in enumerate(questions):
            answer_data = self._quiz_answer_widgets.get(index)
            if not answer_data:
                continue
            if answer_data["type"] in {"single_choice", "true_false"}:
                button = answer_data["group"].checkedButton()
                answers[index] = button.text() if button else ""
                for radio in answer_data["group"].buttons():
                    radio.setEnabled(False)
            else:
                edit = answer_data["edit"]
                answers[index] = edit.toPlainText().strip()
                edit.setReadOnly(True)

        correct_count, graded_count, results = grade_quiz(questions, answers)
        short_answer_count = len(questions) - graded_count
        lines = [
            f"自动判分：{correct_count}/{graded_count}",
        ]
        if short_answer_count:
            lines.append(
                f"另有 {short_answer_count} 道简答题，请对照参考答案自行复盘。"
            )
        lines.append("")
        for result in results:
            question = questions[result["index"]]
            if result["question_type"] == "short_answer":
                status = "参考答案"
            elif result["is_correct"]:
                status = "正确"
            else:
                status = "待订正"
            lines.append(
                f"第 {result['index'] + 1} 题 [{status}] "
                f"正确答案：{question.get('answer', '')}"
            )
            if question.get("explanation"):
                lines.append(f"解析：{question['explanation']}")
            lines.append("")
        self._quiz_result_label.setText("\n".join(lines))
        self._quiz_result_label.setVisible(True)

    @staticmethod
    def _quiz_data_to_markdown(data):
        lines = ["# 结构化测验", ""]
        for index, question in enumerate(data.get("questions", []), start=1):
            lines.append(f"## 第 {index} 题：{question.get('question', '')}")
            question_type = question.get("question_type", "short_answer")
            lines.append(f"题型：{question_type}")
            if question.get("options"):
                for option_index, option in enumerate(question["options"]):
                    lines.append(f"{chr(65 + option_index)}) {option}")
            lines.append(f"正确答案：{question.get('answer', '')}")
            if question.get("explanation"):
                lines.append(f"解析：{question['explanation']}")
            if question.get("core_concept"):
                lines.append(f"核心概念：{question['core_concept']}")
            lines.append("")
        return "\n".join(lines)

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

        header_row = QHBoxLayout()
        header_row.setContentsMargins(18, 14, 18, 6)
        header = QLabel("AI 辅导")
        header.setObjectName("chatHeader")
        header_row.addWidget(header)
        header_row.addStretch()
        new_chat_btn = QPushButton("新对话")
        new_chat_btn.setFlat(True)
        new_chat_btn.clicked.connect(self._clear_tutor_conversation)
        header_row.addWidget(new_chat_btn)
        layout.addLayout(header_row)

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

        input_container = QFrame()
        input_container.setObjectName("chatInputContainer")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 8, 8, 8)
        input_layout.setSpacing(8)

        self.tutor_question = ChatInputEdit()
        self.tutor_question.setObjectName("chatInputField")
        self.tutor_question.setPlaceholderText("有问题，随便问")
        self.tutor_question.setMaximumHeight(84)
        self.tutor_question.sendRequested.connect(self._ask_tutor)
        input_layout.addWidget(self.tutor_question, 1)

        ask_btn = AnimatedSendButton()
        ask_btn.clicked.connect(self._ask_tutor)
        input_layout.addWidget(ask_btn, 0, Qt.AlignBottom)
        layout.addWidget(input_container)

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
        self._stop_thinking_status()
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

    def _start_thinking_status(self):
        self._stop_thinking_status()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._thinking_label = QLabel("思考中 0 秒")
        self._thinking_label.setObjectName("chatBubbleAssistant")
        row.addWidget(self._thinking_label, 0, Qt.AlignLeft)
        row.addStretch(1)
        self._thinking_row = row
        self.tutor_chat_layout.insertLayout(
            max(0, self.tutor_chat_layout.count() - 1), row
        )
        self._thinking_started = time.monotonic()
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(1000)
        self._thinking_timer.timeout.connect(self._update_thinking_label)
        self._thinking_timer.start()
        self._update_thinking_label()
        QTimer.singleShot(0, self._scroll_tutor_to_bottom)

    def _update_thinking_label(self):
        if self._thinking_label is None:
            return
        elapsed = int(time.monotonic() - self._thinking_started)
        self._thinking_label.setText(f"思考中 {elapsed} 秒")

    def _stop_thinking_status(self):
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer.deleteLater()
            self._thinking_timer = None
        if self._thinking_row is not None and hasattr(self, "tutor_chat_layout"):
            for i in range(self.tutor_chat_layout.count()):
                if self.tutor_chat_layout.itemAt(i) is self._thinking_row:
                    item = self.tutor_chat_layout.takeAt(i)
                    while item.layout().count():
                        child = item.layout().takeAt(0)
                        widget = child.widget()
                        if widget:
                            widget.deleteLater()
                    break
        self._thinking_row = None
        self._thinking_label = None

    def _start_quiz_status(self):
        self._stop_quiz_status()
        self.quiz_status_label.setVisible(True)
        self.quiz_status_label.setText("正在为您生成测试 0 秒")
        self._quiz_started = time.monotonic()
        self._quiz_timer = QTimer(self)
        self._quiz_timer.setInterval(1000)
        self._quiz_timer.timeout.connect(self._update_quiz_status)
        self._quiz_timer.start()
        self._update_quiz_status()

    def _update_quiz_status(self):
        if not getattr(self, "quiz_status_label", None):
            return
        elapsed = int(time.monotonic() - self._quiz_started)
        self.quiz_status_label.setText(f"正在为您生成测试 {elapsed} 秒")

    def _stop_quiz_status(self):
        if self._quiz_timer is not None:
            self._quiz_timer.stop()
            self._quiz_timer.deleteLater()
            self._quiz_timer = None
        if getattr(self, "quiz_status_label", None) is not None:
            self.quiz_status_label.setVisible(False)

    def _ask_tutor(self):
        question = self.tutor_question.toPlainText().strip()
        if not question:
            return
        if self._workers:
            QMessageBox.information(self, "请稍候", "上一个任务仍在运行，请稍候再试。")
            return
        context = self.tutor_context.text().strip()
        self._append_chat_message("user", question)
        self.tutor_question.clear()
        self._start_thinking_status()
        self._run_worker(
            self._handler.get_tutoring, question, context,
            callback=self._on_tutor_response
        )

    def _on_tutor_response(self, result):
        self._stop_thinking_status()
        self._tutor_response = result
        self._append_chat_message("assistant", result)

    def _clear_tutor_conversation(self):
        self._handler.clear_tutoring_memory()
        self._stop_thinking_status()
        self._chat_messages.clear()
        while self.tutor_chat_layout.count() > 2:
            item = self.tutor_chat_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self._tutor_placeholder.setVisible(True)

    # ── Tab 5: Document Q&A (RAG) ──
    def _build_rag_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QLabel("文档问答 (RAG)")
        header.setObjectName("chatHeader")
        layout.addWidget(header)

        desc = QLabel("上传 PDF 或文本文件，由本地中文向量模型完成文档检索")
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

    # ── Agent execution trace ──
    def _on_trace(self, stage: str, detail: str):
        self._trace_queue.put((stage, detail))

    def _drain_trace_queue(self):
        while True:
            try:
                stage, detail = self._trace_queue.get_nowait()
            except Empty:
                break
            self._append_trace(stage, detail)

    def _append_trace(self, stage: str, detail: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {stage}  {detail}"
        self._trace_lines.append(line)
        self.trace_browser.setPlainText("\n".join(self._trace_lines[-30:]))

    def _clear_trace(self):
        self._trace_lines.clear()
        self.trace_browser.clear()

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
        self._stop_thinking_status()
        self._stop_quiz_status()
        QMessageBox.critical(self, "错误", f"操作执行失败：\n{msg}")


# ────────────────────────────────────────────
#  Main Window
# ────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setWindowTitle(" 多智能体 AI 学习助手")
        self.resize(1100, 720)

        # ── state (replaces st.session_state) ──
        self._category = ""
        self._handler: Optional[StudyAssistantHandler] = None
        self.step4 = None

        # ── central layout: sidebar | stacked widget ──
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBarWidget()
        root.addWidget(self.title_bar)

        content = QWidget()
        content.setObjectName("mainContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        content_root = QHBoxLayout(content)
        content_root.setContentsMargins(0, 0, 0, 0)
        content_root.setSpacing(0)

        # Sidebar
        self.sidebar = SidebarWidget()
        content_root.addWidget(self.sidebar)

        # Separator
        vsep = QFrame()
        vsep.setFrameShape(QFrame.VLine)
        content_root.addWidget(vsep)

        # Stacked pages
        self.stack = QStackedWidget()
        content_root.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.raise_()

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
        self.title_bar.minimizeRequested.connect(self.showMinimized)
        self.title_bar.maximizeRequested.connect(self._toggle_maximize)
        self.title_bar.closeRequested.connect(self.close)
        self._connect_signals()

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
        self.sidebar.newPlanRequested.connect(self._reset_all)
        self.sidebar.demoRequested.connect(self._open_demo)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())
            self.size_grip.setVisible(not self.isMaximized())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_grip.move(
            self.width() - self.size_grip.width(),
            self.height() - self.size_grip.height(),
        )
        self.size_grip.raise_()

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

    def _open_demo(self):
        handler = DemoStudyAssistantHandler(
            topic="Python 数据分析",
            subject_category="programming",
            knowledge_level="beginner",
            learning_goal="完成一个数据分析作品集",
            time_available="每周 3-5 小时",
            learning_style="visual",
            model_name="demo-offline",
            provider="demo",
        )
        self._category = "programming"
        self._handler = handler
        dashboard = DashboardWidget(
            handler,
            handler.analyze_student(),
            handler.create_roadmap(""),
            handler.find_resources(),
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
        old_step2 = self.stack.widget(1)
        old_step3 = self.stack.widget(2)
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

        for old_widget in (old_step2, old_step3):
            if old_widget is not None:
                self.stack.removeWidget(old_widget)
                old_widget.deleteLater()
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
    app.setFont(_load_app_font())
    dark = bool(_load_settings().get("dark_mode", False))
    _apply_theme(dark)
    app.installEventFilter(ChineseContextMenuFilter(app))
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    if "--demo" in sys.argv:
        QTimer.singleShot(0, window._open_demo)
    if window.windowHandle() is not None:
        window.windowHandle().setIcon(icon)
    _apply_titlebar_theme(window, dark)
    QTimer.singleShot(50, lambda: _apply_titlebar_theme(window, dark))
    app.setWindowIcon(icon)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

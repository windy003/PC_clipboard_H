from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget,
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu,
                           QHBoxLayout, QStackedWidget, QLabel, QTextEdit, QDialog, QLineEdit, QMessageBox, QComboBox, QInputDialog, QFrame, QScrollArea, QCheckBox,
                           QStyledItemDelegate, QStyle, QStyleOptionViewItem, QListView)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QRect, QSize, QAbstractNativeEventFilter
from PyQt6.QtGui import QClipboard, QIcon, QKeyEvent, QKeySequence, QShortcut, QColor, QPen, QPalette
import sys
import json
import os
import keyboard
import time
import re
import traceback
import ctypes
from ctypes import wintypes
from pynput.keyboard import Key, Controller

from d1_storage import D1Storage, load_env_file

import keyboard
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


# ===== 全局热键：使用 Windows 原生 RegisterHotKey =====
# Windows 修饰键标志
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MOD_MAP = {
    'ctrl': MOD_CONTROL, 'control': MOD_CONTROL,
    'alt': MOD_ALT,
    'shift': MOD_SHIFT,
    'win': MOD_WIN, 'windows': MOD_WIN, 'super': MOD_WIN, 'meta': MOD_WIN,
}


def parse_hotkey(hotkey_str):
    """将 'ctrl+windows+a' 这样的字符串解析为 (modifiers, vk)"""
    modifiers = 0
    vk = None
    for part in hotkey_str.lower().replace(' ', '').split('+'):
        if not part:
            continue
        if part in _MOD_MAP:
            modifiers |= _MOD_MAP[part]
        else:
            vk = _key_to_vk(part)
    return modifiers, vk


def _key_to_vk(key):
    """将单个按键名转换为 Windows 虚拟键码"""
    if len(key) == 1:
        ch = key.upper()
        # 字母 A-Z 与数字 0-9 的虚拟键码等于其 ASCII 值
        if ('A' <= ch <= 'Z') or ('0' <= ch <= '9'):
            return ord(ch)
    # 其它字符尝试用系统接口转换
    return ctypes.windll.user32.VkKeyScanW(ord(key[0])) & 0xFF


class GlobalHotkeyManager(QAbstractNativeEventFilter):
    """使用 Windows 原生 RegisterHotKey 注册全局热键。

    热键消息(WM_HOTKEY)直接由 Qt 主线程的事件循环分发，通过本事件
    过滤器接收并派发，无需独立线程与底层键盘钩子，稳定可靠。
    """

    def __init__(self):
        super().__init__()
        self._user32 = ctypes.windll.user32
        self._callbacks = {}   # hotkey_id -> callback
        self._registry = {}    # name -> (hotkey_id, hotkey_str, callback)
        self._next_id = 1

    def register(self, name, hotkey_str, callback):
        """注册一个全局热键；name 作为唯一标识，便于后续更新/注销。返回是否成功。"""
        # 先清理同名旧热键，避免重复注册
        self.unregister(name)

        modifiers, vk = parse_hotkey(hotkey_str)
        if vk is None:
            print(f"无效的热键: {hotkey_str}")
            return False

        hotkey_id = self._next_id
        self._next_id += 1

        # MOD_NOREPEAT 避免长按时重复触发
        if not self._user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
            print(f"注册热键失败: {hotkey_str} (可能已被其它程序占用)")
            return False

        self._callbacks[hotkey_id] = callback
        self._registry[name] = (hotkey_id, hotkey_str, callback)
        print(f"已注册全局热键: {name} -> {hotkey_str}")
        return True

    def unregister(self, name):
        """注销指定名称的热键"""
        info = self._registry.pop(name, None)
        if info:
            hotkey_id = info[0]
            self._user32.UnregisterHotKey(None, hotkey_id)
            self._callbacks.pop(hotkey_id, None)

    def unregister_all(self):
        """注销全部热键"""
        for hotkey_id in list(self._callbacks):
            self._user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()
        self._registry.clear()

    def nativeEventFilter(self, eventType, message):
        """拦截 WM_HOTKEY 消息并派发到对应回调"""
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(msg.wParam)
                if callback:
                    callback()
                    return True, 0
        return False, 0

class HotkeySettingDialog(QDialog):
    """热键设置对话框"""
    def __init__(self, parent=None, current_hotkey="ctrl+windows+a"):
        super().__init__(parent)
        self.setWindowTitle("设置快捷键")
        self.setFixedSize(300, 150)
        
        layout = QVBoxLayout(self)
        
        # 更新说明标签
        label = QLabel("请按下新的快捷键组合\n(支持: Ctrl, Alt, Shift, Win + 字母/数字)")
        layout.addWidget(label)
        
        # 显示当前热键
        self.hotkey_display = QLineEdit(current_hotkey)
        self.hotkey_display.setReadOnly(True)
        layout.addWidget(self.hotkey_display)
        
        # 确认按钮
        self.confirm_button = QPushButton("确认")
        self.confirm_button.clicked.connect(self.accept)
        layout.addWidget(self.confirm_button)
        
        self.new_hotkey = current_hotkey
        self.key_combination = set()
        
    def keyPressEvent(self, event):
        """处理按键事件"""
        # 特殊键映射
        special_keys = {
            Qt.Key.Key_Control: 'ctrl',
            Qt.Key.Key_Alt: 'alt',
            Qt.Key.Key_Shift: 'shift',
            Qt.Key.Key_Meta: 'windows',
        }
        
        # 获取按键
        key = event.key()
        
        # 收集修饰键
        modifiers = event.modifiers()
        current_keys = set()
        
        # 添加修饰键
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            current_keys.add('ctrl')
        if modifiers & Qt.KeyboardModifier.AltModifier:
            current_keys.add('alt')
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            current_keys.add('shift')
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            current_keys.add('windows')
        
        # 处理特殊键
        if key in special_keys:
            key_name = special_keys[key]
            if key_name not in current_keys:
                current_keys.add(key_name)
        # 处理字母和数字键
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            # 将 Key 值转换为小写字母
            key_char = chr(key).lower()
            current_keys.add(key_char)
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            # 将 Key 值转换为数字字符
            key_char = chr(key - Qt.Key.Key_0 + ord('0'))
            current_keys.add(key_char)
            
        # 更新显示
        if current_keys:
            self.key_combination = current_keys
            self.new_hotkey = '+'.join(sorted(current_keys))
            self.hotkey_display.setText(self.new_hotkey)
            
    def keyReleaseEvent(self, event):
        """处理按键释放事件"""
        if not event.modifiers():
            if self.key_combination:
                self.new_hotkey = '+'.join(sorted(self.key_combination))
                self.hotkey_display.setText(self.new_hotkey)

class DescriptionDialog(QDialog):
    """描述对话框，用于编辑内容和描述"""
    def __init__(self, parent=None, text="", description=""):
        super().__init__(parent)
        self.setWindowTitle("编辑内容和描述")
        self.resize(900, 600)  # 增加窗口尺寸
        
        layout = QVBoxLayout(self)
        
        # 内容标签
        content_label = QLabel("内容(&C):")  # 添加快捷键 Alt+C
        content_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(content_label)
        
        # 内容编辑框
        self.content_edit = QTextEdit()
        self.content_edit.setPlainText(text)
        self.content_edit.setMinimumHeight(250)
        content_label.setBuddy(self.content_edit)  # 将标签与编辑框关联
        layout.addWidget(self.content_edit)
        
        # 描述标签
        description_label = QLabel("描述(&D):")  # 添加快捷键 Alt+D
        description_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(description_label)
        
        # 描述编辑框
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(description)
        self.description_edit.setMinimumHeight(150)
        description_label.setBuddy(self.description_edit)  # 将标签与编辑框关联
        layout.addWidget(self.description_edit)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 全屏切换按钮
        self.fullscreen_button = QPushButton("全屏切换(&F)")  # 添加快捷键 Alt+F
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        button_layout.addWidget(self.fullscreen_button)
        
        # 清空内容按钮
        self.clear_content_button = QPushButton("清空内容(&L)")  # 添加快捷键 Alt+L
        self.clear_content_button.clicked.connect(self.clear_content)
        button_layout.addWidget(self.clear_content_button)
        
        # 清空描述按钮
        self.clear_desc_button = QPushButton("清空描述(&R)")  # 添加快捷键 Alt+R
        self.clear_desc_button.clicked.connect(self.clear_description)
        button_layout.addWidget(self.clear_desc_button)
        
        # 添加弹性空间
        button_layout.addStretch()
        
        # 确定按钮
        self.ok_button = QPushButton("确定(&O)")  # 添加快捷键 Alt+O
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        
        # 取消按钮
        self.cancel_button = QPushButton("取消(&X)")  # 添加快捷键 Alt+X
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # 添加快捷键提示标签
        shortcut_label = QLabel("快捷键: Alt+C=内容 Alt+D=描述 Alt+F=全屏 Alt+L=清空内容 Alt+R=清空描述 Alt+O=确定 Alt+X=取消")
        shortcut_label.setStyleSheet("color: gray; font-style: italic; font-size: 12px;")
        layout.addWidget(shortcut_label)
        
        # 设置窗口样式
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            QTextEdit {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                line-height: 1.5;
            }
            QPushButton {
                background-color: #4a86e8;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a76d8;
            }
            QPushButton:pressed {
                background-color: #2a66c8;
            }
            QPushButton#cancel_button {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ddd;
            }
            QPushButton#cancel_button:hover {
                background-color: #e0e0e0;
            }
        """)
        
        # 设置确定和取消按钮的对象名，用于样式表
        self.ok_button.setObjectName("ok_button")
        self.cancel_button.setObjectName("cancel_button")
        
        # 设置窗口标志，使其保持在最前面
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint
        )
        
        # 设置初始焦点到内容编辑框
        self.content_edit.setFocus()
    
    def toggle_fullscreen(self):
        """切换全屏模式"""
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText("全屏切换(&F)")
        else:
            self.showFullScreen()
            self.fullscreen_button.setText("退出全屏(&F)")
    
    def clear_content(self):
        """清空内容编辑框"""
        self.content_edit.clear()
        self.content_edit.setFocus()
    
    def clear_description(self):
        """清空描述编辑框"""
        self.description_edit.clear()
        self.description_edit.setFocus()
    
    def keyPressEvent(self, event):
        """处理按键事件"""
        # 处理 Ctrl+Enter 快捷键 (确定)
        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.accept()
        # 处理 Escape 键 (取消)
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
    
    def get_content(self):
        """获取内容文本"""
        return self.content_edit.toPlainText()
    
    def get_description(self):
        """获取描述文本"""
        return self.description_edit.toPlainText()

class PreviewWindow(QWidget):
    """悬浮预览窗口"""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
            QTextEdit {
                border: none;
                background-color: transparent;
                padding: 5px;
            }
            QLabel {
                color: #666;
                padding: 5px;
            }
            QFrame#line {
                background-color: #ccc;
            }
            QPushButton#close_button {
                background-color: #ff4444;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: bold;
                font-size: 12px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton#close_button:hover {
                background-color: #ff6666;
            }
            QPushButton#close_button:pressed {
                background-color: #cc3333;
            }
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #ccc;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #f0f0f0;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #ccc;
                border-radius: 5px;
                min-width: 20px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)
        
        # 创建标题栏布局（包含关闭按钮）
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)

        # 标题标签
        title_label = QLabel("预览窗口")
        title_label.setStyleSheet("font-weight: bold; color: #333; font-size: 14px;")
        title_layout.addWidget(title_label)

        # 弹性空间
        title_layout.addStretch()

        # 关闭按钮
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("close_button")
        self.close_button.setToolTip("关闭预览窗口 (Esc)")
        self.close_button.clicked.connect(self.hide)
        title_layout.addWidget(self.close_button)

        main_layout.addLayout(title_layout)
        
        # 创建一个滚动区域
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建一个容器widget来放置所有内容
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)
        
        # 描述信息显示
        self.description_label = QLabel("描述:")
        container_layout.addWidget(self.description_label)
        self.description_edit = QTextEdit()
        self.description_edit.setReadOnly(True)
        self.description_edit.setMaximumHeight(100)
        self.description_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.description_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        container_layout.addWidget(self.description_edit)
        
        # 添加分界线
        self.separator = QFrame()
        self.separator.setObjectName("line")
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.separator.setFixedHeight(2)
        container_layout.addWidget(self.separator)
        
        # 内容标题和显示
        self.content_label = QLabel("内容信息:")
        container_layout.addWidget(self.content_label)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        container_layout.addWidget(self.text_edit)
        
        # 设置弹性空间
        container_layout.addStretch()
        
        # 将容器放入滚动区域
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)
        
        self.setMinimumSize(300, 200)
        self.setMaximumSize(400, 600)  # 增加最大高度
        
        # 设置窗口属性，使其能够独立存在
        self.setWindowFlags(
            Qt.WindowType.Tool | 
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
    
    def set_content(self, text, description=""):
        self.text_edit.setPlainText(text)
        if description:
            self.description_label.show()
            self.description_edit.show()
            self.description_edit.setPlainText(description)
            self.separator.show()
        else:
            self.description_label.hide()
            self.description_edit.hide()
            self.separator.hide()
    
    def keyPressEvent(self, event):
        """处理按键事件"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)
    
    

class ToastNotification(QWidget):
    """短暂提示窗口：显示一段文字后，在指定毫秒数后自动消失。

    用于「移动到记忆夹成功」这类轻量反馈，不抢占焦点、置顶显示。
    """
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool |
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        # 背景透明以呈现圆角；显示时不激活窗口，避免抢走当前焦点
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 用内部 QFrame 承载背景样式（顶层窗口透明时背景样式不直接生效）
        self.frame = QFrame()
        self.frame.setObjectName("toast_frame")
        self.frame.setStyleSheet("""
            QFrame#toast_frame {
                background-color: rgba(50, 50, 50, 235);
                border-radius: 10px;
            }
            QLabel {
                color: white;
                font-size: 15px;
                font-weight: bold;
            }
        """)
        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(28, 16, 28, 16)
        self.label = QLabel("")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(self.label)
        outer.addWidget(self.frame)

        # 单次定时器，到点自动隐藏
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, duration=2000, anchor=None):
        """显示提示文字，duration 毫秒后自动消失。

        anchor 为定位参照窗口（居中其上）；若 anchor 为 None 或不可见，则居中到
        鼠标当前所在的屏幕——这样在主窗口隐藏（全局热键触发）时也能正常显示。
        """
        self.label.setText(text)
        self.adjustSize()

        if anchor is not None and anchor.isVisible():
            geo = anchor.geometry()
            x = geo.center().x() - self.width() // 2
            y = geo.center().y() - self.height() // 2
            self.move(x, y)
        else:
            # 居中到鼠标所在屏幕（多屏时定位更准确）
            from PyQt6.QtGui import QCursor
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            geo = screen.geometry()
            x = geo.center().x() - self.width() // 2
            y = geo.center().y() - self.height() // 2
            self.move(x, y)

        self.show()
        self.raise_()
        self._timer.start(duration)


class EditItemDialog(QDialog):
    """编辑条目对话框"""
    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self.setWindowTitle("编辑条目")
        self.setFixedSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # 文本编辑框
        self.text_edit = QTextEdit()
        self.text_edit.setText(text)
        layout.addWidget(self.text_edit)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 确认按钮 - 使用 Alt+O (O for OK)
        self.confirm_button = QPushButton("确认(&O)")
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)
        
        # 取消按钮 - 使用 Alt+C (C for Cancel)
        self.cancel_button = QPushButton("取消(&C)")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def get_text(self):
        """获取编辑后的文本"""
        return self.text_edit.toPlainText()

class SearchDialog(QDialog):
    """搜索对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("搜索")
        self.resize(500, 400)  # 增加对话框尺寸以容纳搜索结果
        self.parent_app = parent
        
        # 设置对话框属性，确保能够正常接收输入
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        layout = QVBoxLayout(self)
        
        # 搜索框
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入搜索关键词(&D)")  # 添加Alt+D快捷键提示
        self.search_input.textChanged.connect(self.on_search_text_changed)  # 连接文本变化信号
        # 确保搜索框是启用状态
        self.search_input.setEnabled(True)
        self.search_input.setReadOnly(False)
        # 设置焦点策略
        self.search_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 为搜索框添加按键事件过滤器
        self.search_input.installEventFilter(self)
        search_layout.addWidget(self.search_input)
        
        layout.addLayout(search_layout)
        
        # 搜索选项布局
        options_layout = QHBoxLayout()
        
        # 正则表达式选项 - Alt+R
        self.regex_checkbox = QCheckBox("使用正则表达式(&R)")
        self.regex_checkbox.stateChanged.connect(self.on_search_option_changed)
        options_layout.addWidget(self.regex_checkbox)
        
        # 区分大小写选项 - Alt+C
        self.case_sensitive_checkbox = QCheckBox("区分大小写(&C)")
        self.case_sensitive_checkbox.stateChanged.connect(self.on_search_option_changed)
        options_layout.addWidget(self.case_sensitive_checkbox)
        
        # 全字匹配选项 - Alt+W
        self.whole_word_checkbox = QCheckBox("全字匹配(&W)")
        self.whole_word_checkbox.stateChanged.connect(self.on_search_option_changed)
        options_layout.addWidget(self.whole_word_checkbox)
        
        layout.addLayout(options_layout)
        
        # 搜索范围选项 - Alt+X
        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("搜索范围:"))

        # 隐藏的combo用于存储当前选中的范围值
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["全部", "历史记录", "当前收藏夹", "所有收藏夹"])
        self.scope_combo.currentIndexChanged.connect(self.on_search_option_changed)
        self.scope_combo.hide()

        # 下拉菜单按钮
        self.scope_menu_button = QPushButton("全部(&X)")
        scope_menu = QMenu(self)
        for scope in ["全部", "历史记录", "当前收藏夹", "所有收藏夹"]:
            action = scope_menu.addAction(scope)
            action.triggered.connect(lambda checked, s=scope: self._set_scope(s))
        # 指定收藏夹 - 子菜单
        if hasattr(self.parent_app, 'favorites') and self.parent_app.favorites:
            submenu = scope_menu.addMenu("指定收藏夹")
            for folder_name in sorted(self.parent_app.favorites.keys()):
                action = submenu.addAction(folder_name)
                action.triggered.connect(lambda checked, fn=folder_name: self._set_folder_scope(fn))
        self.scope_menu_button.setMenu(scope_menu)
        scope_layout.addWidget(self.scope_menu_button)

        layout.addLayout(scope_layout)
        
        # 创建水平分割布局
        split_layout = QHBoxLayout()
        
        # 结果列表
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.use_selected)
        self.results_list.currentItemChanged.connect(self.show_preview)
        # 设置右键菜单
        self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self.show_results_context_menu)
        split_layout.addWidget(self.results_list)
        
        layout.addLayout(split_layout)
        
        # 存储搜索结果
        self.results = []  # 确保初始化 results 列表
        
        # 创建预览窗口但不显示
        self.preview_window = PreviewWindow()
        self.preview_window.hide()  # 确保预览窗口不会干扰焦点

        
        # 设置窗口标志，使其保持在最前面（必须在设置焦点前调用）
        # 暂时移除WindowStaysOnTopHint，它可能导致焦点问题
        # self.setWindowFlags(
        #     Qt.WindowType.Window |
        #     Qt.WindowType.WindowStaysOnTopHint
        # )
        
        # 添加提示标签
        hint_label = QLabel("提示: 选中条目后按E键或右键可编辑内容和描述")
        hint_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(hint_label)
        
        # 设置焦点到搜索框（必须在setWindowFlags之后调用）
        self.search_input.setFocus()
    
    def showEvent(self, event):
        """重写showEvent确保搜索框获得焦点"""
        super().showEvent(event)
        # 确保对话框激活并设置焦点
        self.raise_()
        self.activateWindow()
        # 延迟设置焦点，确保窗口完全显示后再设置
        QTimer.singleShot(100, self._set_focus_delayed)
    
    def _set_focus_delayed(self):
        """延迟设置焦点"""
        self.search_input.setFocus()
        self.search_input.selectAll()  # 选中所有文本（如果有的话）

    def _set_scope(self, scope_name):
        """设置搜索范围（基本选项）"""
        index = self.scope_combo.findText(scope_name)
        if index != -1:
            self.scope_combo.setCurrentIndex(index)
        self.scope_menu_button.setText(f"{scope_name}(&X)")
        self.perform_search()

    def _set_folder_scope(self, folder_name):
        """设置特定收藏夹作为搜索范围"""
        folder_scope = f"收藏夹-{folder_name}"
        index = self.scope_combo.findText(folder_scope)
        if index == -1:
            self.scope_combo.addItem(folder_scope)
            index = self.scope_combo.count() - 1
        self.scope_combo.setCurrentIndex(index)
        self.scope_menu_button.setText(f"{folder_scope}(&X)")
        self.perform_search()
    

    def show_results_context_menu(self, position):
        """显示搜索结果的右键菜单"""
        menu = QMenu()
        current_item = self.results_list.currentItem()
        
        if current_item:
            index = self.results_list.currentRow()
            if 0 <= index < len(self.results):
                # 使用元组解包，并为可能缺失的值提供默认值
                source, text, description = (*self.results[index], "", "", "")[:3]

                # 添加编辑选项
                edit_action = menu.addAction("编辑内容和描述(&E)")  # Alt+E
                delete_action = menu.addAction("删除(&D)")  # Alt+D
                
                # 添加"移动到收藏夹"选项
                move_to_favorites_menu = menu.addMenu("移动到收藏夹(&M)")  # Alt+M
                for folder in self.parent_app.favorites.keys():
                    move_action = move_to_favorites_menu.addAction(folder)
                    # 修复闭包问题：使用偏函数来正确捕获变量值
                    def make_move_handler(folder_name, item_index):
                        return lambda checked: self.move_to_folder_from_results(item_index, folder_name)
                    move_action.triggered.connect(make_move_handler(folder, index))
                
                # 获取当前条目的矩形区域
                item_rect = self.results_list.visualItemRect(current_item)
                # 将条目的位置转换为全局坐标，并稍微向下偏移
                global_pos = self.results_list.mapToGlobal(item_rect.bottomLeft())
                # 调整菜单显示位置，使其紧贴条目下方
                global_pos.setY(global_pos.y() + 5)
                
                action = menu.exec(global_pos)
                
                if action == edit_action:
                    self.edit_selected_item()
                elif action == delete_action:
                    self.delete_selected_item()

    def move_to_folder_from_results(self, index, target_folder):
        """将搜索结果中的条目移动到指定收藏夹"""
        if 0 <= index < len(self.results):
            source, text, description = (*self.results[index], "", "", "")[:3]

            # 确保目标收藏夹存在
            if target_folder not in self.parent_app.favorites:
                self.parent_app.favorites[target_folder] = []
            
            # 创建新的收藏项
            new_item = {"text": text, "description": description}
            
            # 添加到目标收藏夹
            self.parent_app.favorites[target_folder].append(new_item)
            
            # 如果源是收藏夹，从原收藏夹中移除
            if source.startswith("收藏夹-"):
                original_folder = source[4:]  # 去掉"收藏夹-"前缀
                if original_folder in self.parent_app.favorites:
                    for i, item in enumerate(self.parent_app.favorites[original_folder]):
                        if isinstance(item, dict) and item["text"] == text:
                            self.parent_app.favorites[original_folder].pop(i)
                            break
            # 如果源是历史记录，从历史记录中移除
            elif source == "历史记录":
                if text in self.parent_app.clipboard_history:
                    self.parent_app.clipboard_history.remove(text)
                    self.parent_app.save_history()
            
            # 保存更改
            self.parent_app.save_favorites()
            
            # 更新显示
            if self.parent_app.current_folder == target_folder:
                truncated_text = self.parent_app.truncate_text(text)
                self.parent_app.favorites_list.addItem(f"{len(self.parent_app.favorites[target_folder])}. {truncated_text}")
            
            QMessageBox.information(self, "移动成功", f"已移动到收藏夹: {target_folder}")
    

    def delete_selected_item(self):
        """删除选中的搜索结果项，并从原始数据源中删除"""
        index = self.results_list.currentRow()
        if 0 <= index < len(self.results):
            source, text, description = self.results[index]
            
            # 截断显示的文本
            truncated_text = text[:50] + ('...' if len(text) > 50 else '')
            
            # 确认删除 - 使用正确的按钮类型
            reply = QMessageBox.question(
                self, "确认删除", 
                f"确定要从{source}中删除此项？\n{truncated_text}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 从搜索结果中删除
                self.results.pop(index)
                self.fill_results()
                
                # 从数据源中删除
                parent = self.parent()
                if source.startswith("收藏夹-"):
                    # 提取收藏夹名称
                    folder_name = source[4:]  # 去掉"收藏夹-"前缀
                    
                    # 检查收藏夹是否存在
                    if folder_name in parent.favorites:
                        # 遍历收藏夹中的项目
                        for i, item in enumerate(parent.favorites[folder_name]):
                            if isinstance(item, dict) and item["text"] == text:
                                # 从收藏夹数据中删除
                                parent.favorites[folder_name].pop(i)
                                parent.save_favorites()
                                
                                # 如果当前显示的是该收藏夹，更新 UI
                                if parent.current_folder == folder_name:
                                    parent.favorites_list.takeItem(i)
                                    parent.update_list_numbers(parent.favorites_list)
                                break
                elif source == "历史记录":
                    # 在历史记录中查找并删除
                    for i, history_text in enumerate(parent.clipboard_history):
                        if history_text == text:
                            # 从历史记录中删除
                            deleted_item = parent.clipboard_history.pop(i)
                            parent.delete_history.append(deleted_item)
                            parent.update_history_list()
                            parent.save_history()
                            break
                
                print(f"已从{source}中删除项目")

    def edit_selected_item(self):
        """编辑选中的搜索结果项"""
        index = self.results_list.currentRow()
        if 0 <= index < len(self.results):
            # 解包三个值
            source, text, description = self.results[index]
            
            # 创建编辑对话框
            dialog = DescriptionDialog(self, text=text, description=description)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_description = dialog.get_description()
                new_content = dialog.get_content()
                
                print(f"编辑项目: 源={source}, 索引={index}")
                print(f"原内容: {text}")
                print(f"原描述: {description}")
                print(f"新内容: {new_content}")
                print(f"新描述: {new_description}")
                
                # 更新内容
                if source == "历史记录":
                    # 更新历史记录
                    self.parent_app.clipboard_history[index] = new_content
                    self.parent_app.save_history()
                    
                    # 更新显示
                    truncated_text = self.parent_app.truncate_text(new_content)
                    self.parent_app.history_list.item(index).setText(f"{index+1}. {truncated_text}")
                    
                    # 更新搜索结果
                    self.results[index] = (source, new_content, "")
                    
                elif source.startswith("收藏夹-"):
                    folder_name = source[4:]  # 提取收藏夹名称
                    
                    if folder_name in self.parent_app.favorites:
                        # 检查是否已存在相同内容的项目
                        existing_items = self.parent_app.favorites[folder_name]
                        found_index = None
                        
                        # 查找原始项目的索引
                        for i, item in enumerate(existing_items):
                            if isinstance(item, dict) and item["text"] == text:
                                found_index = i
                                break
                        
                        if found_index is not None:
                            # 更新现有项目
                            new_item = {
                                "text": new_content,
                                "description": new_description
                            }
                            self.parent_app.favorites[folder_name][found_index] = new_item
                            
                            # 如果当前显示的是该收藏夹，更新显示
                            if self.parent_app.current_folder == folder_name:
                                truncated_text = self.parent_app.truncate_text(new_content)
                                self.parent_app.favorites_list.item(found_index).setText(f"{found_index+1}. {truncated_text}")
                            
                            # 更新搜索结果
                            self.results[index] = (source, new_content, new_description)
                            
                            # 立即保存更改
                            self.parent_app.save_favorites()
                            
                            # 更新搜索结果显示
                            self.fill_results()
    

            
    def keyPressEvent(self, event):
        """处理按键事件"""
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # 如果按下回车键，并且有选中的项目，则执行粘贴操作
            if self.results_list.currentRow() >= 0:
                index = self.results_list.currentRow()
                if 0 <= index < len(self.results):
                    # 修改这里：只解包三个值
                    source, text, description = self.results[index]
                    try:
                        
                        # 设置新的剪贴板内容
                        QApplication.clipboard().setText(text)
                        
                        # 隐藏对话框
                        self.hide()
                        
                        # 等待一小段时间确保对话框已关闭
                        QTimer.singleShot(50, lambda: self._do_paste(text))
                        
                    except Exception as e:
                        print(f"粘贴时出错: {e}")
                    
                    self.accept()  # 关闭对话框
        elif event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # 如果按下 Ctrl+C，并且有选中的项目，则执行复制操作
            if self.results_list.currentRow() >= 0:
                self.copy_selected()
        elif event.key() == Qt.Key.Key_D and event.modifiers() == Qt.KeyboardModifier.AltModifier:
            # 如果按下 Alt+D，聚焦到搜索框
            self.search_input.setFocus()
            self.search_input.selectAll()  # 选中所有文本以便直接输入
        else:
            super().keyPressEvent(event)
    
    def copy_selected(self):
        """复制选中项到剪贴板"""
        index = self.results_list.currentRow()
        if 0 <= index < len(self.results):
            # 修改这里：只解包三个值
            source, text, description = self.results[index]
            QApplication.clipboard().setText(text)
            # 显示复制成功提示
            QMessageBox.information(self, "复制成功", "文本已复制到剪贴板")
    
    def on_search_text_changed(self):
        """搜索文本变化时触发搜索"""
        self.perform_search()
    
    def on_search_option_changed(self):
        """搜索选项变化时触发搜索"""
        self.perform_search()
    
    def perform_search(self):
        """执行搜索"""
        search_text = self.search_input.text()
        use_regex = self.regex_checkbox.isChecked()
        case_sensitive = self.case_sensitive_checkbox.isChecked()
        whole_word = self.whole_word_checkbox.isChecked()
        scope = self.scope_combo.currentText()
        
        # 如果搜索文本为空，清空结果
        if not search_text:
            self.results = []
            self.fill_results()
            return
        
        # 执行搜索
        try:
            self.results = self.parent_app.search_items(
                search_text, use_regex, scope, case_sensitive, whole_word
            )
            self.fill_results()
        except Exception as e:
            QMessageBox.warning(self, "搜索错误", f"搜索时发生错误: {str(e)}")
    
    def fill_results(self):
        """填充搜索结果列表"""
        self.results_list.clear()
        
        for i, (source, text, description) in enumerate(self.results):
            # 构建显示文本
            display_text = f"{i+1}. [{source}] {text}"
            if description:
                display_text += " [有描述]"
            
            # 添加到结果列表
            self.results_list.addItem(display_text)
        
        # 如果有结果，选中第一项
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
    
    def use_selected(self):
        """使用选中的搜索结果"""
        index = self.results_list.currentRow()
        if 0 <= index < len(self.results):
            text = self.results[index][0]
            QApplication.clipboard().setText(text)
            self.accept()  # 关闭对话框
    
    def closeEvent(self, event):
        """关闭事件处理"""
        self.preview_window.hide()
        event.accept()
    
    def reject(self):
        """取消对话框"""
        self.preview_window.hide()
        super().reject()
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理搜索框的按键事件"""
        if obj is self.search_input and event.type() == event.Type.KeyPress:
            # 处理向下箭头键，将焦点移到结果列表
            if event.key() == Qt.Key.Key_Down:
                if self.results_list.count() > 0:
                    self.results_list.setFocus()
                    self.results_list.setCurrentRow(0)
                return True
            # 处理向上箭头键，如果搜索框有文本，则清空
            elif event.key() == Qt.Key.Key_Up and self.search_input.text():
                self.search_input.clear()
                return True
        
        return super().eventFilter(obj, event)

    def paste_selected(self):
        """将选中的项目粘贴到当前活动窗口"""
        index = self.results_list.currentRow()
        if 0 <= index < len(self.results):
            # 修改这里：只解包三个值
            source, text, description = self.results[index]
            print(f"index: {index}")
            print(f"self.results[index]: {self.results[index]}")
            print(f"source: {source}, text: {text}, description: {description}")    
            try:
                # 保存当前剪贴板内容
                old_clipboard = QApplication.clipboard().text()
                
                # 设置新的剪贴板内容
                QApplication.clipboard().setText(text)
                
                # 隐藏对话框
                self.hide()
                
                # 等待一小段时间确保对话框已关闭
                QTimer.singleShot(50, lambda: self._do_paste(old_clipboard))
                
            except Exception as e:
                print(f"粘贴时出错: {e}")

    def _do_paste(self, old_clipboard):
        """执行实际的粘贴操作并恢复剪贴板"""
        try:
            # 模拟按下 Ctrl+V
            keyboard.press_and_release('ctrl+v')
            
            # 短暂延迟后恢复原剪贴板内容
            QTimer.singleShot(100, lambda: QApplication.clipboard().setText(old_clipboard))
            
        except Exception as e:
            print(f"执行粘贴操作时出错: {e}")


    def show_preview(self, current, previous):
        """显示选中搜索结果的预览"""
        if not current:
            self.preview_window.hide()
            return
        
        # 只有当搜索对话框可见时才显示预览窗口
        if not self.isVisible():
            return
        
        current_row = self.results_list.currentRow()
        
        try:
            if 0 <= current_row < len(self.results):
                # 从搜索结果中获取数据
                source, text, description = self.results[current_row]
                
                # 显示预览窗口
                self.preview_window.set_content(text, description)
                
                # 计算预览窗口的位置
                screen = QApplication.primaryScreen().geometry()
                preview_width = self.preview_window.width()
                
                # 计算预览窗口的理想x坐标
                ideal_x = self.x() + self.width() + 10
                
                # 如果预览窗口会超出屏幕右边界，则将其放在对话框左侧
                if ideal_x + preview_width > screen.right():
                    preview_x = self.x() - preview_width - 10
                else:
                    preview_x = ideal_x
                
                preview_y = self.y()
                
                self.preview_window.move(preview_x, preview_y)
                self.preview_window.show()
        except Exception as e:
            print(f"搜索预览显示错误: {e}")
            self.preview_window.hide()
    


class FullWidthListWidget(QListWidget):
    """条目始终占满视口宽度的列表。

    QListWidget 默认按内容宽度排布条目，且在窗口显示/缩放后不会主动重新向
    delegate 查询 sizeHint，导致 delegate 返回的“视口宽度”无法生效（本程序
    窗口初始 hide() 且列表位于 QStackedWidget 中，初次布局时视口宽度还不正
    确）。这里直接给每个 QListWidgetItem 设置宽度——条目自身 sizeHint 的宽度
    一定会被视图采纳，最为可靠——并在显示/缩放/新增条目时刷新。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 新增条目后，把新行也撑满宽度
        self.model().rowsInserted.connect(self._on_rows_inserted)

    def showEvent(self, event):
        super().showEvent(event)
        self._stretch_all()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._stretch_all()

    def _row_height(self, item):
        h = item.sizeHint().height()
        return h if h > 0 else 28

    def _stretch_all(self):
        w = self.viewport().width()
        if w <= 0:
            return
        for i in range(self.count()):
            item = self.item(i)
            if item is not None and item.sizeHint().width() != w:
                item.setSizeHint(QSize(w, self._row_height(item)))

    def _on_rows_inserted(self, parent, first, last):
        w = self.viewport().width()
        if w <= 0:
            return
        for i in range(first, last + 1):
            item = self.item(i)
            if item is not None:
                item.setSizeHint(QSize(w, self._row_height(item)))


class ListItemDelegate(QStyledItemDelegate):
    """列表项代理：
    - show_description=True：左半边显示内容，右半边显示描述（收藏面板）
    - show_description=False：内容占满整行宽度（历史记录面板）
    """
    def __init__(self, app, parent=None, show_description=True):
        super().__init__(parent)
        self.app = app  # 主窗口引用，用于按行号读取描述
        self.show_description = show_description

    def _get_description(self, row):
        """按行号从当前收藏夹数据中读取描述"""
        try:
            items = self.app.favorites.get(self.app.current_folder, [])
            if 0 <= row < len(items):
                item = items[row]
                if isinstance(item, dict):
                    desc = item.get("description", "") or ""
                    return desc.replace('\n', ' ').replace('\r', '')
        except Exception:
            pass
        return ""

    def paint(self, painter, option, index):
        painter.save()

        # 用基类样式绘制背景（含选中/悬停效果），但清空文本由我们自己绘制
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        rect = option.rect
        padding = 6

        # 文字颜色与列表样式表保持一致（选中背景为浅蓝 #e3f2fd）
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected:
            text_color = QColor("#1976d2")
            desc_color = QColor("#1976d2")
        else:
            text_color = QColor("#212121")
            desc_color = QColor("#666666")

        fm = painter.fontMetrics()
        content = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if not self.show_description:
            # 历史记录：内容占满整行宽度
            full_rect = QRect(rect.left() + padding, rect.top(),
                              rect.width() - padding * 2, rect.height())
            elided_content = fm.elidedText(content, Qt.TextElideMode.ElideRight, full_rect.width())
            painter.setPen(text_color)
            painter.drawText(full_rect,
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             elided_content)
            painter.restore()
            return

        # 收藏面板：左半边内容，右半边描述
        mid = rect.left() + rect.width() // 2

        # 左半边：内容（DisplayRole 已包含编号前缀）
        left_rect = QRect(rect.left() + padding, rect.top(),
                          mid - rect.left() - padding * 2, rect.height())
        elided_content = fm.elidedText(content, Qt.TextElideMode.ElideRight, left_rect.width())
        painter.setPen(text_color)
        painter.drawText(left_rect,
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         elided_content)

        # 中间分隔线
        painter.setPen(QPen(QColor("#d0d0d0")))
        painter.drawLine(mid, rect.top() + 4, mid, rect.bottom() - 4)

        # 右半边：描述
        description = self._get_description(index.row())
        right_rect = QRect(mid + padding, rect.top(),
                           rect.right() - mid - padding * 2, rect.height())
        elided_desc = fm.elidedText(description, Qt.TextElideMode.ElideRight, right_rect.width())
        painter.setPen(desc_color)
        painter.drawText(right_rect,
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         elided_desc)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if size.height() < 28:
            size.setHeight(28)
        # 让条目占满列表视口宽度（QListWidget 默认只用文本宽度作为条目宽度）
        view = self.parent()
        if view is not None:
            try:
                vw = view.viewport().width()
                if vw > 0:
                    size.setWidth(vw)
            except Exception:
                pass
        return size


class LoginDialog(QDialog):
    """云端账号登录对话框（账号注册改由命令行调用 Worker /register 完成）。"""
    def __init__(self, parent, storage):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("登录云端同步")
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("账号:"))
        self.username_edit = QLineEdit()
        self.username_edit.setText(storage.username or "")
        layout.addWidget(self.username_edit)

        layout.addWidget(QLabel("密码:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.returnPressed.connect(self.do_login)
        layout.addWidget(self.password_edit)

        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("登录(&L)")
        self.login_btn.setDefault(True)
        self.login_btn.clicked.connect(self.do_login)
        btn_layout.addWidget(self.login_btn)

        self.skip_btn = QPushButton("跳过(&S)")
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)
        layout.addLayout(btn_layout)

        hint_label = QLabel("跳过则本次仅使用本地数据")
        hint_label.setStyleSheet("color: gray; font-size: 12px;")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.username_edit.setFocus()

    def _creds(self):
        return self.username_edit.text().strip(), self.password_edit.text()

    def do_login(self):
        u, p = self._creds()
        if not u or not p:
            QMessageBox.warning(self, "提示", "请输入账号和密码")
            return
        try:
            self.storage.login(u, p)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "登录失败", str(e))


class ClipboardHistoryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("剪贴板历史")
        
        # 设置窗口图标 (任务栏会显示此图标)
        self.setWindowIcon(get_app_icon())
        
        # 创建主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建顶部标签布局
        top_layout = QHBoxLayout()
        layout.insertLayout(0, top_layout)  # 将顶部布局添加到主布局的最上方
        
        # 添加标题栏显示当前面板
        self.panel_label = QLabel("历史记录")
        top_layout.addWidget(self.panel_label)
        
        # 添加提示文字
        hint_label = QLabel("(按左右方向键以切换历史和收藏面板)")
        hint_label.setStyleSheet("color: gray;")  # 使提示文字颜色变淡
        top_layout.addWidget(hint_label)
        
        top_layout.addStretch()  # 添加弹性空间，使标签靠左对齐
        
        # 创建堆叠式窗口部件
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)
        
        # 创建历史记录列表
        self.history_list = FullWidthListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        self.history_list.keyPressEvent = self.list_key_press
        # 添加样式
        self.history_list.setStyleSheet("""
            QListWidget {
                padding: 5px;
            }
            QListWidget::item {
                padding: 2px;
                margin: 2px 0px;
                border-radius: 4px;
                background-color: #f8f9fa;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        # 使用自定义代理：内容占满整行宽度（无描述列）
        self.history_list.setItemDelegate(ListItemDelegate(self, self.history_list, show_description=False))
        self.history_list.setResizeMode(QListView.ResizeMode.Adjust)  # 视口变化时重新布局，使条目宽度跟随
        self.stacked_widget.addWidget(self.history_list)

        # 创建收藏列表
        self.favorites_list = FullWidthListWidget()
        self.favorites_list.keyPressEvent = self.list_key_press
        self.favorites_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.favorites_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.favorites_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        # 添加相同的样式
        self.favorites_list.setStyleSheet("""
            QListWidget {
                padding: 5px;
            }
            QListWidget::item {
                padding: 2px;
                margin: 2px 0px;
                border-radius: 4px;
                background-color: #f8f9fa;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        self.favorites_list.model().rowsMoved.connect(self.on_favorites_reordered)  # 连接重排序信号
        # 使用自定义代理：左半边显示内容，右半边显示描述
        self.favorites_list.setItemDelegate(ListItemDelegate(self, self.favorites_list, show_description=True))
        self.favorites_list.setResizeMode(QListView.ResizeMode.Adjust)  # 视口变化时重新布局，使条目宽度跟随
        self.stacked_widget.addWidget(self.favorites_list)
        
        # 为收藏列表添加右键菜单
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.customContextMenuRequested.connect(self.show_favorites_context_menu)
        
        # 添加按钮布局
        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)
        
        # 清空历史按钮
        clear_button = QPushButton("清空历史")
        clear_button.clicked.connect(self.clear_history)
        button_layout.addWidget(clear_button)
        
        # 修改收藏夹数据结构
        self.favorites = {
            "默认收藏夹": []  # 默认收藏夹
        }
        self.current_folder = "默认收藏夹"
        
        # 创建收藏夹下拉菜单
        self.folder_combo = QComboBox()
        self.folder_combo.currentTextChanged.connect(self.change_folder)
        
        # 修改收藏夹布局
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_combo)
        
        # 更换按钮 - 移动到下拉菜单和重命名之间
        self.change_folder_btn = QPushButton("更换(&C)")
        self.change_folder_btn.clicked.connect(lambda: self.folder_combo.showPopup())
        self.change_folder_btn.setFixedWidth(60)
        
        # 重命名按钮
        self.rename_folder_btn = QPushButton("重命名(&R)")
        self.rename_folder_btn.clicked.connect(self.rename_current_folder)
        self.rename_folder_btn.setFixedWidth(60)
        
        # 删除按钮
        self.delete_folder_btn = QPushButton("删除收藏文件夹(&D)")
        self.delete_folder_btn.clicked.connect(self.delete_current_folder)
        self.delete_folder_btn.setFixedWidth(110)
        
        # 按新顺序添加按钮
        folder_layout.addWidget(self.change_folder_btn)
        folder_layout.addWidget(self.rename_folder_btn)
        folder_layout.addWidget(self.delete_folder_btn)
        top_layout.addLayout(folder_layout)
        
        # 存储收藏夹数据
        self.favorites_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.clipboard_favorites.json')

        # 初始化云端收藏夹同步（经 Cloudflare Worker；配置从同目录 .env 或系统环境变量读取）
        load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
        self.d1 = D1Storage.from_env()
        if self.d1.enabled:
            print("已启用云端收藏夹同步（Worker）")
            self._ensure_cloud_login()
        else:
            print("未配置 Worker，收藏夹仅保存在本地文件")

        # 加载收藏记录
        self.load_favorites()
        
        # 存储剪贴板历史
        self.clipboard_history = []
        
        # 获取系统剪贴板
        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.on_clipboard_change)
        
        # 设置定时器检查剪贴板变化
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_clipboard)
        self.timer.start(500)  # 每500毫秒检查一次
        
        self.last_text = self.clipboard.text()
        
        # 设置保存文件的路径
        self.history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.clipboard_history.json')
        
        # 加载历史记录
        self.load_history()
        
        # 加载配置
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.clipboard_config.json')
        self.load_config()
        
        # 创建系统托盘图标 (只调用一次)
        self.create_tray_icon()

        # 创建全局热键管理器（使用 Windows 原生 RegisterHotKey，稳定可靠）
        self.hotkey_manager = GlobalHotkeyManager()
        QApplication.instance().installNativeEventFilter(self.hotkey_manager)
        QApplication.instance().aboutToQuit.connect(self.hotkey_manager.unregister_all)
        self.register_hotkeys()
        
        # 设置窗口标志，移除关闭按钮
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint
        )
        
        # 安装事件过滤器来处理窗口事件
        self.installEventFilter(self)
        
        # 为列表控件启用按键事件
        self.history_list.keyPressEvent = self.list_key_press
        
        # 双击列表项也触发粘贴
        self.history_list.itemDoubleClicked.connect(self.paste_selected)
        self.favorites_list.itemDoubleClicked.connect(self.paste_selected)
        
        
        # 创建预览窗口
        self.preview_window = PreviewWindow()
        
        # 为两个列表添加选择变化事件
        self.history_list.currentItemChanged.connect(self.show_preview)
        self.favorites_list.currentItemChanged.connect(self.show_preview)
        
        # 用于处理编号输入的变量
        self.number_input_buffer = ""
        self.number_input_timer = QTimer()
        self.number_input_timer.setSingleShot(True)
        self.number_input_timer.timeout.connect(self.clear_number_input)
        self.number_input_timer.setInterval(2000)  # 2秒后清空输入缓冲
        
    def register_hotkeys(self):
        """注册/重新注册所有全局热键"""
        main_hotkey = self.config.get('hotkey', 'ctrl+windows+a')
        search_hotkey = self.config.get('search_hotkey', 'ctrl+alt+a')
        memory_hotkey = self.config.get('memory_hotkey', 'alt+y')
        ok_main = self.hotkey_manager.register('main', main_hotkey, self.toggle_window)
        ok_search = self.hotkey_manager.register('search', search_hotkey, self.show_search_dialog)
        # Alt+Y：全局热键，任何窗口下都可把最近一条剪贴板移动到「记忆」收藏夹
        self.hotkey_manager.register('memory', memory_hotkey, self.move_latest_clipboard_to_memory)
        if (not ok_main or not ok_search) and hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "热键注册失败",
                "部分全局热键注册失败，可能被其它程序占用，请在托盘菜单中重新设置。",
                QSystemTrayIcon.MessageIcon.Warning, 5000)
        return ok_main and ok_search

    def show_preview(self, current, previous):
        """显示选中条目的完整内容"""
        if not current:
            self.preview_window.hide()
            return
        
        # 只有当主窗口可见时才显示预览窗口
        if not self.isVisible():
            return
        
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_row = current_list.currentRow()
        
        try:
            if self.stacked_widget.currentIndex() == 0:
                # 历史记录面板
                data_list = self.clipboard_history
                original_text = data_list[current_row]
                description = ""
            else:
                # 收藏夹面板
                data_list = self.favorites[self.current_folder]
                item = data_list[current_row]
                # 处理新旧格式数据
                if isinstance(item, str):
                    original_text = item
                    description = ""
                else:
                    original_text = item["text"]
                    description = item.get("description", "")
            
            if 0 <= current_row < len(data_list):
                # 移除条件判断，总是显示预览窗口
                self.preview_window.set_content(original_text, description)
                
                # 计算预览窗口的位置
                screen = QApplication.primaryScreen().geometry()
                preview_width = self.preview_window.width()
                
                # 计算预览窗口的理想x坐标
                ideal_x = self.x() + self.width() + 10
                
                # 如果预览窗口会超出屏幕右边界，则将其放在主窗口左侧
                if ideal_x + preview_width > screen.right():
                    preview_x = self.x() - preview_width - 10
                else:
                    preview_x = ideal_x
                
                preview_y = self.y()
                
                self.preview_window.move(preview_x, preview_y)
                self.preview_window.show()
        except Exception as e:
            print(f"预览显示错误: {e}")
            self.preview_window.hide()
    


    def check_clipboard(self):
        current_text = self.clipboard.text()
        if current_text != self.last_text:
            self.on_clipboard_change()
            self.last_text = current_text

    def on_clipboard_change(self):
        text = self.clipboard.text()
        if text:
            print(f"原始文本: {text}")  # 调试输出
            # 检查是否已存在于历史记录中
            if text in self.clipboard_history:
                # 如果已存在，从原位置移除
                index = self.clipboard_history.index(text)
                self.clipboard_history.pop(index)
                self.history_list.takeItem(index)
            
            # 添加新条目到历史记录开头
            self.clipboard_history.insert(0, text)
            # 显示截断后的文本
            truncated_text = self.truncate_text(text)
            print(f"截断后文本: {truncated_text}")  # 调试输出
            self.history_list.insertItem(0, truncated_text)
            
            # 如果历史记录超过30个，删除多余的条目
            while len(self.clipboard_history) > 30:
                self.clipboard_history.pop()
                self.history_list.takeItem(self.history_list.count() - 1)
            
            # 更新编号
            self.update_list_numbers(self.history_list)
            # 保存历史记录
            self.save_history()

    def copy_selected(self):
        """复制选中项"""
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_item = current_list.currentItem()
        if current_item:
            # 使用原始文本而不是截断的文本
            original_text = (self.clipboard_history if self.stacked_widget.currentIndex() == 0 
                            else self.favorites[self.current_folder])[current_list.currentRow()]
            self.clipboard.setText(original_text)

    def clear_history(self):
        self.clipboard_history.clear()
        self.history_list.clear()
        # 清空后保存状态
        self.save_history()

    def load_history(self):
        """从文件加载历史记录"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.clipboard_history = json.load(f)
                    self.history_list.clear()
                    for text in self.clipboard_history:
                        truncated_text = self.truncate_text(text)
                        self.history_list.addItem(truncated_text)
                    # 更新编号
                    self.update_list_numbers(self.history_list)
        except Exception as e:
            print(f"加载历史记录时出错: {e}")
            self.clipboard_history = []

    def save_history(self):
        """保存历史记录到文件"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.clipboard_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史记录时出错: {e}")

    def create_tray_icon(self):
        """创建系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self)
        
        # 使用资源路径获取图标 (icon.ico 优先, 回退到 icon.png)
        icon = get_app_icon()
        if not icon.isNull():
            self.tray_icon.setIcon(icon)
        else:
            # 如果找不到图标文件，使用默认图标
            self.tray_icon.setIcon(self.create_default_icon())
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        # 重新设置唤出快捷键
        main_hotkey_action = tray_menu.addAction("重新设置唤出快捷键")
        main_hotkey_action.triggered.connect(self.show_settings)

        # 重新设置搜索快捷键
        search_hotkey_action = tray_menu.addAction("重新设置搜索快捷键")
        search_hotkey_action.triggered.connect(self.show_search_hotkey_settings)

        self.delete_history = []

        # 添加分隔线
        tray_menu.addSeparator()

        # 添加退出动作
        quit_action = tray_menu.addAction("退出(&X)")
        quit_action.triggered.connect(QApplication.quit)
        
        # 设置托盘菜单
        self.tray_icon.setContextMenu(tray_menu)
        
        # 显示托盘图标
        self.tray_icon.show()
        
        # 双击托盘图标显示窗口
        self.tray_icon.activated.connect(self.tray_icon_activated)

    def create_default_icon(self):
        """创建一个简单的默认图标"""
        from PyQt6.QtGui import QPixmap, QPainter, QColor
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(0, 120, 212))  # 使用蓝色
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 32, 32)
        painter.end()
        return QIcon(pixmap)

    def tray_icon_activated(self, reason):
        """处理托盘图标的点击事件"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.isHidden():
                self.show_window()
            else:
                self.hide()

    def closeEvent(self, event):
        """重写关闭事件，确保预览窗口也被关闭"""
        self.preview_window.hide()
        super().closeEvent(event)

    def list_key_press(self, event: QKeyEvent):
        """处理列表的按键事件"""
        # 首先检查是否在编号输入模式
        if self.number_input_buffer:
            if self.handle_number_input(event.key()):
                return  # 已处理，直接返回
        
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.paste_selected()
        elif event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key.Key_Right and self.stacked_widget.currentIndex() == 0:
            # 切换到收藏面板
            self.stacked_widget.setCurrentIndex(1)
            self.panel_label.setText("收藏夹")
            self.favorites_list.setFocus()
            # 确保显示当前收藏夹的内容
            self.change_folder(self.current_folder)
        elif event.key() == Qt.Key.Key_Left and self.stacked_widget.currentIndex() == 1:
            self.stacked_widget.setCurrentIndex(0)
            self.panel_label.setText("历史记录")
            self.history_list.setFocus()
        elif event.key() == Qt.Key.Key_Delete:
            if self.stacked_widget.currentIndex() == 1:
                self.delete_favorite()
            else:
                self.delete_history_item()
        elif (event.key() == Qt.Key.Key_Z and 
              event.modifiers() & Qt.KeyboardModifier.ControlModifier and 
              self.stacked_widget.currentIndex() == 1):
            self.undo_delete()
        # 处理 Ctrl+C
        elif event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
            current_row = current_list.currentRow()
            if current_row >= 0:
                if self.stacked_widget.currentIndex() == 0:
                    # 从历史记录获取完整文本
                    original_text = self.clipboard_history[current_row]
                    # 从原位置移除
                    self.clipboard_history.pop(current_row)
                    self.history_list.takeItem(current_row)
                    # 插入到顶部
                    self.clipboard_history.insert(0, original_text)
                    truncated_text = self.truncate_text(original_text)
                    self.history_list.insertItem(0, truncated_text)
                    # 更新编号
                    self.update_list_numbers(self.history_list)
                    # 保存历史记录
                    self.save_history()
                else:
                    # 从收藏夹获取完整文本
                    item = self.favorites[self.current_folder][current_row]
                    original_text = item["text"] if isinstance(item, dict) else str(item)
                # 复制到剪贴板
                self.clipboard.setText(original_text)
                # 复制成功后隐藏窗口，回退到系统托盘
                self.hide()
        # 修改为 Alt+C 快捷键
        elif (event.modifiers() == Qt.KeyboardModifier.AltModifier and 
              event.key() == Qt.Key.Key_C and 
              self.stacked_widget.currentIndex() == 1):
            # 打开收藏夹下拉菜单
            self.folder_combo.showPopup()
        # Alt+J：在历史记录面板，将高亮选中的条目移动到「记忆」收藏夹
        elif (event.modifiers() == Qt.KeyboardModifier.AltModifier and
              event.key() == Qt.Key.Key_J and
              self.stacked_widget.currentIndex() == 0):
            self.move_history_to_memory()
        elif (event.modifiers() == Qt.KeyboardModifier.AltModifier and
              self.stacked_widget.currentIndex() == 1):
            if event.key() == Qt.Key.Key_Up:
                self.move_favorite_item(-1)
            elif event.key() == Qt.Key.Key_Down:
                self.move_favorite_item(1)
        # 处理数字键 1-9
        elif Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_9:
            index = event.key() - Qt.Key.Key_1  # 将键值转换为0-8的索引
            current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
            if index < current_list.count():
                current_list.setCurrentRow(index)
                self.paste_selected()
        # 处理点号键，开始输入编号
        elif event.key() == Qt.Key.Key_Period:
            self.start_number_input()
        # 处理数字键 0（在编号输入模式之外）
        elif event.key() == Qt.Key.Key_0:
            # 数字0只在编号输入模式中有效，这里不做处理
            pass
        else:
            # 保持其他按键的默认行为
            QListWidget.keyPressEvent(self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list, event)

    def move_favorite_item(self, direction):
        """移动收藏条目"""
        current_row = self.favorites_list.currentRow()
        if current_row < 0:
            return
        
        new_row = current_row + direction
        if 0 <= new_row < self.favorites_list.count():
            # 从列表控件中移动项目
            item = self.favorites_list.takeItem(current_row)
            self.favorites_list.insertItem(new_row, item)
            self.favorites_list.setCurrentRow(new_row)
            
            # 从收藏夹数据中移动项目
            current_folder_items = self.favorites[self.current_folder]
            item_text = current_folder_items.pop(current_row)
            current_folder_items.insert(new_row, item_text)
            
            # 更新编号
            self.update_list_numbers(self.favorites_list)
            # 保存更改
            self.save_favorites()

    def delete_favorite(self):
        """删除选中的收藏项"""
        current_row = self.favorites_list.currentRow()
        if current_row >= 0:  # 确保有选中的项目
            # 保存删除信息用于撤销
            deleted_item = {
                'folder': self.current_folder,
                'item': self.favorites[self.current_folder][current_row],
                'position': current_row
            }
            self.delete_history.append(deleted_item)
            
            # 从数据中删除
            self.favorites[self.current_folder].pop(current_row)
            # 从列表控件中删除
            self.favorites_list.takeItem(current_row)
            # 更新编号
            self.update_list_numbers(self.favorites_list)
            # 保存更改
            self.save_favorites()
            
            # 如果当前收藏夹为空且不是默认收藏夹，询问是否删除该收藏夹
            if not self.favorites[self.current_folder] and self.current_folder != "默认收藏夹":
                reply = QMessageBox.question(
                    self,
                    "删除收藏夹",
                    f"收藏夹 '{self.current_folder}' 已空，是否删除该收藏夹？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    # 删除空收藏夹
                    del self.favorites[self.current_folder]
                    # 更新下拉菜单
                    self.folder_combo.removeItem(self.folder_combo.findText(self.current_folder))
                    # 切换到默认收藏夹
                    self.current_folder = "默认收藏夹"
                    self.folder_combo.setCurrentText("默认收藏夹")
                    self.change_folder("默认收藏夹")
                    self.save_favorites()

    def undo_delete(self):
        """撤销删除操作"""
        if self.delete_history:
            # 获取最后一次删除的信息
            deleted_item = self.delete_history.pop()
            folder = deleted_item['folder']
            item = deleted_item['item']
            position = deleted_item['position']
            
            # 确保文件夹存在
            if folder not in self.favorites:
                self.favorites[folder] = []
                self.folder_combo.addItem(folder)
            
            # 如果不在对应的收藏夹，先切换过去
            if self.current_folder != folder:
                self.current_folder = folder
                self.folder_combo.setCurrentText(folder)
                self.change_folder(folder)
            
            # 恢复删除的项目
            self.favorites[folder].insert(position, item)
            truncated_text = self.truncate_text(item['text'])
            self.favorites_list.insertItem(position, truncated_text)
            
            # 更新编号
            self.update_list_numbers(self.favorites_list)
            # 保存更改
            self.save_favorites()
            
            # 选中恢复的项目
            self.favorites_list.setCurrentRow(position)

    def paste_selected(self):
        """复制选中项并模拟粘贴操作"""
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_item = current_list.currentItem()
        if current_item:
            # 使用原始文本而不是截断的文本
            current_row = current_list.currentRow()
            if self.stacked_widget.currentIndex() == 0:
                # 从历史记录中获取
                original_text = self.clipboard_history[current_row]
            else:
                # 从收藏夹中获取
                item = self.favorites[self.current_folder][current_row]
                original_text = item["text"] if isinstance(item, dict) else str(item)
            
            # 无论是从历史记录还是收藏夹，都将内容更新到历史记录顶部
            if original_text in self.clipboard_history:
                # 如果已存在，先移除旧的
                old_index = self.clipboard_history.index(original_text)
                self.clipboard_history.pop(old_index)
                self.history_list.takeItem(old_index)
            
            # 插入到顶部
            self.clipboard_history.insert(0, original_text)
            truncated_text = self.truncate_text(original_text)
            self.history_list.insertItem(0, truncated_text)
            
            # 更新编号
            self.update_list_numbers(self.history_list)
            # 保存历史记录
            self.save_history()
            
            self.clipboard.setText(original_text)
            self.hide()
            QTimer.singleShot(100, lambda: keyboard.send('ctrl+v'))

    def toggle_window(self):
        """切换窗口显示/隐藏状态"""
        if self.isVisible() and self.isActiveWindow():
            print("窗口当前可见且活跃，将隐藏")
            self.hide()
        else:
            print("窗口当前隐藏或不活跃，将显示")
            self.show_window()

    def show_window(self):
        """显示窗口"""
        print("正在显示窗口")  # 调试信息
        
        # 切换到收藏面板
        self.stacked_widget.setCurrentIndex(1)
        self.panel_label.setText("收藏夹")
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        
        # 计算所需的总宽度（主窗口 + 间距 + 预览窗口）
        main_window_width = self.width()
        preview_window_width = 400  # 预览窗口的最大宽度
        spacing = 10  # 窗口之间的间距
        total_width = main_window_width + spacing + preview_window_width
        
        # 计算主窗口的x坐标，使其居中且留出预览窗口的空间
        x = screen.center().x() - total_width // 2
        y = screen.center().y() - self.height() // 2
        
        # 确保窗口不会超出屏幕左边界
        if x < 0:
            x = 0
        
        # 移动主窗口到计算出的位置
        self.move(x, y)
        
        # 临时设置置顶标志
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        
        self.show()
        self.raise_()
        self.activateWindow()
        
        # 强制窗口置顶并获得焦点 - 修复首次运行时的激活问题
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        
        # 在 Windows 上使用额外的方法来确保窗口获得焦点
        import platform
        if platform.system() == "Windows":
            try:
                import ctypes
                from ctypes import wintypes
                
                # 获取窗口句柄
                hwnd = int(self.winId())
                
                # 强制窗口到前台
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetActiveWindow(hwnd)
                
            except ImportError:
                pass  # 如果无法导入 ctypes，使用默认方法
        
        # 记录窗口显示时间，用于防止立即隐藏
        self._window_show_time = time.time()
        
        # 使用定时器延迟设置焦点，确保窗口完全显示后再获得焦点
        QTimer.singleShot(50, lambda: self.favorites_list.setFocus())  # 修改这里，设置焦点到收藏列表
        QTimer.singleShot(100, lambda: self.activateWindow())  # 再次激活窗口

    def _delayed_hide(self):
        """延迟隐藏窗口，只有当窗口真的失去焦点时才隐藏"""
        if not self.isActiveWindow() and not self.favorites_list.hasFocus():
            self.hide()

    def __del__(self):
        """确保程序退出时清理热键"""
        try:
            if hasattr(self, 'hotkey_manager'):
                self.hotkey_manager.unregister_all()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """事件过滤器，处理窗口事件"""
        if event.type() == event.Type.WindowDeactivate:
            # 添加延迟检查，避免窗口刚显示时立即隐藏
            if hasattr(self, '_window_show_time'):
                current_time = time.time()
                # 窗口显示后至少等待500毫秒再允许自动隐藏
                if current_time - self._window_show_time > 0.5:
                    QTimer.singleShot(100, self._delayed_hide)  # 延迟隐藏
            else:
                QTimer.singleShot(100, self._delayed_hide)
        elif event.type() == event.Type.Close:
            # 处理 Alt+F4
            self.hide()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        """处理窗口的按键事件"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def show_history_context_menu(self, position):
        """显示历史记录的右键菜单"""
        print("右键菜单被触发")  # 调试信息
        menu = QMenu()
        current_item = self.history_list.currentItem()
        
        if current_item:
            # 获取原始文本而不是截断的文本
            original_text = self.clipboard_history[self.history_list.currentRow()]
            print(f"当前选中: {original_text}")  # 调试信息
            
            # 添加编辑选项
            edit_action = menu.addAction("编辑(&E)")  # Alt+E
            delete_action = menu.addAction("删除(&D)")  # Alt+D
            
            move_menu = menu.addMenu("移动到收藏夹(&M)")  # Alt+V
            for folder in self.favorites.keys():
                move_menu.addAction(folder)

            action = menu.exec(self.history_list.mapToGlobal(position))
            
            # 检查action是否为None
            if action is not None:
                if action == edit_action:
                    print("选择了编辑选项")  # 调试信息
                    self.edit_history_item(self.history_list.currentRow())
                elif action == delete_action:
                    print("选择了删除选项")  # 调试信息
                    self.delete_history_item()
                elif action.text() in self.favorites:
                    self.move_to_folder_from_history(current_item, action.text())
    

    def _parse_favorites_file(self):
        """从本地文件解析收藏夹数据，返回字典；无文件或出错返回 None。"""
        if not os.path.exists(self.favorites_file):
            return None
        with open(self.favorites_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        favorites = {}
        # 处理旧格式数据（简单列表）
        if isinstance(data, list):
            favorites = {
                "默认收藏夹": [{"text": item, "description": ""} for item in data]
            }
        # 新格式数据（字典格式）
        elif isinstance(data, dict):
            for folder, items in data.items():
                favorites[folder] = []
                for item in items:
                    if isinstance(item, str):
                        favorites[folder].append({"text": item, "description": ""})
                    else:
                        favorites[folder].append(item)
        return favorites

    def _apply_loaded_favorites(self, favorites):
        """把加载到的收藏夹数据应用到界面。"""
        self.favorites = favorites or {}

        # 确保至少有默认收藏夹
        if "默认收藏夹" not in self.favorites:
            self.favorites["默认收藏夹"] = []

        # 更新收藏夹下拉菜单
        self.folder_combo.clear()
        self.folder_combo.addItems(self.favorites.keys())

        # 显示默认收藏夹内容
        self.current_folder = "默认收藏夹"
        self.folder_combo.setCurrentText("默认收藏夹")
        self.favorites_list.clear()
        for item in self.favorites[self.current_folder]:
            text = item["text"] if isinstance(item, dict) else item
            truncated_text = self.truncate_text(text)
            self.favorites_list.addItem(truncated_text)
        self.update_list_numbers(self.favorites_list)

    def load_favorites(self):
        """加载收藏记录。

        优先从 Cloudflare D1 读取（作为数据源）；若 D1 为空但本地有数据，
        则把本地数据迁移上传到 D1；若 D1 未配置或不可用，则回退到本地文件。
        """
        # 1) 尝试从云端读取（需已登录）
        if self.d1.enabled and self.d1.has_valid_token():
            try:
                d1_favorites = self.d1.load()
                if d1_favorites:
                    # D1 已有数据，作为数据源
                    self._apply_loaded_favorites(d1_favorites)
                    # 同步一份到本地文件作为离线缓存
                    self._write_favorites_file()
                    print("已从 Cloudflare D1 加载收藏夹")
                    return
                else:
                    # D1 为空：若本地有数据则迁移上传
                    local_favorites = None
                    try:
                        local_favorites = self._parse_favorites_file()
                    except Exception as e:
                        print(f"读取本地收藏夹失败: {e}")
                    self._apply_loaded_favorites(local_favorites)
                    if any(self.favorites.values()):
                        print("D1 为空，正在迁移本地收藏夹到 D1...")
                        self.d1.save_async(self.favorites)
                    return
            except Exception as e:
                print(f"从 D1 加载失败，回退到本地文件: {e}")

        # 2) 回退：从本地文件加载
        try:
            local_favorites = self._parse_favorites_file()
            self._apply_loaded_favorites(local_favorites)
            # 保存为新格式（仅本地）
            self._write_favorites_file()
        except Exception as e:
            print(f"加载收藏记录时出错: {e}")
            self.favorites = {"默认收藏夹": []}
            self.folder_combo.clear()
            self.folder_combo.addItem("默认收藏夹")

    def _write_favorites_file(self):
        """把收藏夹数据规整为字典格式并写入本地文件（离线缓存）。"""
        # 确保所有收藏夹中的项目都使用字典格式
        for folder_name in self.favorites:
            for i, item in enumerate(self.favorites[folder_name]):
                if not isinstance(item, dict):
                    self.favorites[folder_name][i] = {
                        "text": str(item),
                        "description": ""
                    }

        # 保存到文件
        with open(self.favorites_file, 'w', encoding='utf-8') as f:
            json.dump(self.favorites, f, ensure_ascii=False, indent=2)

    def _ensure_cloud_login(self):
        """确保云端已登录：本地有未过期 token 则直接用，否则弹出登录框。

        用户跳过登录时，本次运行回退为仅使用本地数据。
        """
        if self.d1.has_valid_token():
            print(f"已使用本地登录凭据：{self.d1.username}")
            return
        dialog = LoginDialog(self, self.d1)
        dialog.exec()
        if self.d1.has_valid_token():
            print(f"已登录云端：{self.d1.username}")
        else:
            print("未登录，本次仅使用本地数据")

    def save_favorites(self):
        """保存收藏记录：写入本地文件，并异步同步到云端 Worker。"""
        try:
            # 1) 写入本地文件（快速、作为离线缓存与回退）
            self._write_favorites_file()
            print(f"收藏已保存到本地: {self.favorites_file}")

            # 2) 异步推送到云端（后台线程，不阻塞 UI；需已登录）
            if self.d1.enabled and self.d1.has_valid_token():
                self.d1.save_async(self.favorites)

        except Exception as e:
            print(f"保存收藏记录时出错: {e}")
            traceback.print_exc()

    def truncate_text(self, text, max_length=50):
        """规整列表显示文本：仅去除换行符，不再按固定字符数截断。

        历史/收藏两个列表都使用 ListItemDelegate，由其 elidedText 按视口
        宽度自动省略（溢出时加“…”），因此这里返回整行文本，条目即可占满
        宽度并尽量多显示内容。max_length 参数仅为兼容旧调用，已不再使用。
        """
        return text.replace('\n', ' ').replace('\r', '')


    def hide(self):
        """写hide方法，同时隐藏预览窗口"""
        super().hide()
        self.preview_window.hide()

    def on_favorites_reordered(self, parent, start, end, destination, row):
        """处理收藏列表重排序"""
        # 获取移动的项目
        moved_item = self.favorites[self.current_folder][start]
        # 从原位置删除
        self.favorites[self.current_folder].pop(start)
        # 插入到新位置
        new_position = row if row < start else row - 1
        self.favorites[self.current_folder].insert(new_position, moved_item)
        # 更新列表项编号
        self.update_list_numbers(self.favorites_list)
        # 保存更新后的收藏列表
        self.save_favorites()

    def show_settings(self):
        """设置唤出快捷键"""
        dialog = HotkeySettingDialog(self, self.config.get('hotkey', 'ctrl+windows+a'))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_hotkey = dialog.new_hotkey
            if new_hotkey != self.config.get('hotkey'):
                self.config['hotkey'] = new_hotkey
                self.save_config()
                # 重新注册主热键
                if self.hotkey_manager.register('main', new_hotkey, self.toggle_window):
                    QMessageBox.information(self, "设置成功", f"唤出快捷键已更改为: {new_hotkey}")
                else:
                    QMessageBox.warning(self, "设置失败", f"快捷键 {new_hotkey} 注册失败，可能被其它程序占用，请更换组合。")

    def show_search_hotkey_settings(self):
        """设置搜索快捷键"""
        dialog = HotkeySettingDialog(self, self.config.get('search_hotkey', 'ctrl+alt+a'))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_hotkey = dialog.new_hotkey
            if new_hotkey != self.config.get('search_hotkey', 'ctrl+alt+a'):
                self.config['search_hotkey'] = new_hotkey
                self.save_config()
                # 重新注册搜索热键
                if self.hotkey_manager.register('search', new_hotkey, self.show_search_dialog):
                    QMessageBox.information(self, "设置成功", f"搜索快捷键已更改为: {new_hotkey}")
                else:
                    QMessageBox.warning(self, "设置失败", f"快捷键 {new_hotkey} 注册失败，可能被其它程序占用，请更换组合。")

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = {'hotkey': 'ctrl+windows+a', 'search_hotkey': 'ctrl+alt+a'}
        except Exception as e:
            print(f"加载配置出错: {e}")
            self.config = {'hotkey': 'ctrl+windows+a', 'search_hotkey': 'ctrl+alt+a'}

    def save_config(self):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置出错: {e}")

    def update_list_numbers(self, list_widget):
        """更新列表项的编号"""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            text = item.text()
            # 移除可能存在的旧编号
            # 查找编号模式: 数字., .数字., ..数字., ...数字. 等
            import re
            # 匹配开头的编号模式：可选的点号 + 数字 + 点号 + 空格
            pattern = r'^(\.*\d+\. )'
            match = re.match(pattern, text)
            if match:
                text = text[len(match.group(1)):]
            
            # 生成新编号
            number = i + 1
            if number <= 9:
                # 1-9: 直接数字
                prefix = f"{number}. "
            else:
                # 10及以上: 根据十位数确定点号数量
                # 10-19: 1个点 (.10, .11, ...)
                # 20-29: 2个点 (..20, ..21, ...)
                # 30-39: 3个点 (...30, ...)
                # 以此类推
                dot_count = number // 10
                prefix = f"{'.' * dot_count}{number}. "
            
            item.setText(f"{prefix}{text}")

    def show_favorites_context_menu(self, position):
        """显示收藏夹的右键菜单"""
        menu = QMenu()
        current_item = self.favorites_list.currentItem()
        
        if current_item:
            current_row = self.favorites_list.currentRow()
            favorite_item = self.favorites[self.current_folder][current_row]
            original_text = favorite_item["text"]
            
            edit_action = menu.addAction("编辑内容和描述(&E)")  # Alt+E
            new_folder = menu.addAction("新建收藏夹(&N)...")  # Alt+N
            
            move_menu = menu.addMenu("移动到收藏夹(&M)")  # Alt+V
            for folder in self.favorites.keys():
                if folder != self.current_folder:
                    move_menu.addAction(folder)
            
            delete_action = menu.addAction("删除(&D)")  # Alt+D
            
            action = menu.exec(self.favorites_list.mapToGlobal(position))
            
            if action:
                if action == edit_action:
                    self.edit_favorite_content_and_description(current_row)
                elif action == new_folder:
                    self.create_new_folder(original_text)
                elif action == delete_action:
                    self.delete_favorite()
                elif action.text() in self.favorites:
                    self.move_to_folder_from_favorites(favorite_item, action.text())

    def create_new_folder(self, item_text):
        """创建新收藏夹并移动选中项"""
        folder_name, ok = QInputDialog.getText(self, "创建收藏夹", "请输入收藏夹名称:")
        if ok and folder_name:
            if folder_name not in self.favorites:
                # 确保使用字典格式
                new_item = {"text": item_text, "description": ""}
                self.favorites[folder_name] = [new_item]
                self.folder_combo.addItem(folder_name)
                
                # 从当前收藏夹移除
                current_row = self.favorites_list.currentRow()
                self.favorites[self.current_folder].pop(current_row)
                self.favorites_list.takeItem(current_row)
                
                self.save_favorites()
                self.update_list_numbers(self.favorites_list)
            else:
                QMessageBox.warning(self, "错误", "收藏夹名称已存在!")

    def move_to_folder_from_favorites(self, item, target_folder):
        """移动条目到指定收藏夹"""
        if target_folder in self.favorites:
            # 确保使用字典格式
            if not isinstance(item, dict):
                item = {"text": str(item), "description": ""}
            
            # 添加到目标收藏夹
            self.favorites[target_folder].append(item)
            
            # 从当前收藏夹移除
            current_row = self.favorites_list.currentRow()
            self.favorites[self.current_folder].pop(current_row)
            self.favorites_list.takeItem(current_row)
            
            self.save_favorites()
            self.update_list_numbers(self.favorites_list)

    def move_to_folder_from_history(self, item, target_folder):
        """移动条目到指定收藏夹"""
        if target_folder in self.favorites:
            # 获取历史记录中的实际文本内容
            current_row = self.history_list.currentRow()
            if 0 <= current_row < len(self.clipboard_history):
                text = self.clipboard_history[current_row]
                
                # 确保使用字典格式
                new_item = {"text": text, "description": ""}
                
                # 添加到目标收藏夹
                self.favorites[target_folder].append(new_item)
                
                # 更新显示
                truncated_text = self.truncate_text(text)
                self.favorites_list.insertItem(0, truncated_text)
                
                # 更新编号
                self.update_list_numbers(self.favorites_list)
                
                # 保存更改
                self.save_favorites()

    def show_toast(self, message, duration=2000):
        """弹出一个短暂提示窗口，duration 毫秒后自动消失（居中于主窗口）。"""
        if not hasattr(self, '_toast') or self._toast is None:
            self._toast = ToastNotification(self)
        self._toast.show_message(message, duration, anchor=self)

    def move_history_to_memory(self):
        """将历史记录中高亮选中的条目移动到「记忆」收藏夹，并弹出 2 秒成功提示。"""
        MEMORY_FOLDER = "记忆"

        current_row = self.history_list.currentRow()
        if current_row < 0 or current_row >= len(self.clipboard_history):
            return

        # 确保「记忆」收藏夹存在；不存在则创建并加入下拉菜单
        if MEMORY_FOLDER not in self.favorites:
            self.favorites[MEMORY_FOLDER] = []
            if self.folder_combo.findText(MEMORY_FOLDER) == -1:
                self.folder_combo.addItem(MEMORY_FOLDER)

        # 取出原始文本
        text = self.clipboard_history[current_row]

        # 若记忆夹中已存在相同文本的条目，则提示并放弃移动
        for item in self.favorites[MEMORY_FOLDER]:
            existing_text = item["text"] if isinstance(item, dict) else str(item)
            if existing_text == text:
                self.show_toast("条目已存在,移动失败", 2000)
                return

        # 以字典格式加入记忆夹
        self.favorites[MEMORY_FOLDER].append({"text": text, "description": ""})

        # 若当前正显示「记忆」收藏夹，同步刷新其列表显示
        if self.current_folder == MEMORY_FOLDER:
            truncated_text = self.truncate_text(text)
            self.favorites_list.addItem(truncated_text)
            self.update_list_numbers(self.favorites_list)

        # 保存更改（本地 + 云端同步由 save_favorites 处理）
        self.save_favorites()

        # 弹出 2 秒后自动消失的成功提示
        self.show_toast("成功把条目移动到记忆", 2000)

    def move_latest_clipboard_to_memory(self):
        """全局热键(Alt+Y)回调：把最近一条剪贴板内容移动到「记忆」收藏夹。

        不依赖应用窗口是否聚焦/可见，移动后弹出 1 秒成功提示（居中于鼠标所在屏幕）。
        """
        MEMORY_FOLDER = "记忆"

        # 取最近一条：历史记录开头即最新；为空则回退到当前剪贴板文本
        if self.clipboard_history:
            text = self.clipboard_history[0]
        else:
            text = self.clipboard.text()
        if not text:
            self.show_toast("剪贴板为空，移动失败", 1000)
            return

        # 确保「记忆」收藏夹存在；不存在则创建并加入下拉菜单
        if MEMORY_FOLDER not in self.favorites:
            self.favorites[MEMORY_FOLDER] = []
            if self.folder_combo.findText(MEMORY_FOLDER) == -1:
                self.folder_combo.addItem(MEMORY_FOLDER)

        # 若记忆夹中已存在相同文本的条目，则提示并放弃移动
        for item in self.favorites[MEMORY_FOLDER]:
            existing_text = item["text"] if isinstance(item, dict) else str(item)
            if existing_text == text:
                self.show_toast("条目已存在，移动失败", 1000)
                return

        # 以字典格式加入记忆夹
        self.favorites[MEMORY_FOLDER].append({"text": text, "description": ""})

        # 若当前正显示「记忆」收藏夹，同步刷新其列表显示
        if self.current_folder == MEMORY_FOLDER:
            truncated_text = self.truncate_text(text)
            self.favorites_list.addItem(truncated_text)
            self.update_list_numbers(self.favorites_list)

        # 保存更改（本地 + 云端同步由 save_favorites 处理）
        self.save_favorites()

        # 弹出 1 秒后自动消失的成功提示
        self.show_toast("移动最近一条剪贴板到记忆文件夹成功", 1000)

    def change_folder(self, folder_name):
        """切换当前收藏夹"""
        if folder_name in self.favorites:
            self.current_folder = folder_name
            self.favorites_list.clear()
            for item in self.favorites[folder_name]:
                # 确保使用字典格式
                if isinstance(item, dict):
                    text = item["text"]
                else:
                    # 如果是旧格式，转换为新格式
                    text = str(item)
                    item = {"text": text, "description": ""}
                
                truncated_text = self.truncate_text(text)
                self.favorites_list.addItem(truncated_text)
            self.update_list_numbers(self.favorites_list)

    def edit_favorite_content_and_description(self, row):
        """编辑收藏条目的内容和描述"""
        if 0 <= row < len(self.favorites[self.current_folder]):
            favorite_item = self.favorites[self.current_folder][row]
            dialog = DescriptionDialog(
                self,
                text=favorite_item["text"],
                description=favorite_item.get("description", "")
            )
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_description = dialog.get_description()
                new_content = dialog.get_content()
                
                # 更新收藏夹中的内容
                favorite_item["text"] = new_content
                favorite_item["description"] = new_description
                
                # 更新显示的文本
                truncated_text = self.truncate_text(new_content)
                self.favorites_list.item(row).setText(f"{row+1}. {truncated_text}")
                
                # 保存更改
                self.save_favorites()

    # 添加重命名收藏夹的方法
    def rename_current_folder(self):
        """重命名当前收藏夹"""
        if self.current_folder == "默认收藏夹":
            QMessageBox.warning(self, "警告", "默认收藏夹不能重命名！")
            return
            
        new_name, ok = QInputDialog.getText(
            self, 
            "重命名收藏夹",
            "请输入新的收藏夹名称:",
            text=self.current_folder
        )
        
        if ok and new_name:
            if new_name == "默认收藏夹":
                QMessageBox.warning(self, "错误", "不能使用'默认收藏夹'作为名称！")
                return
                
            if new_name in self.favorites:
                QMessageBox.warning(self, "错误", "收藏夹名称已存在！")
                return
                
            # 更新收藏夹数据
            self.favorites[new_name] = self.favorites.pop(self.current_folder)
            
            # 更新下拉菜单
            current_index = self.folder_combo.currentIndex()
            self.folder_combo.setItemText(current_index, new_name)
            
            # 更新当前收藏夹名称
            self.current_folder = new_name
            
            # 保存更改
            self.save_favorites()
            
            QMessageBox.information(self, "成功", "收藏夹重命名成功！")

    def delete_current_folder(self):
        """删除当前收藏夹"""
        if self.current_folder == "默认收藏夹":
            QMessageBox.warning(self, "警告", "默认收藏夹不能删除！")
            return
            
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除收藏夹 '{self.current_folder}' 吗？\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 删除收藏夹
            del self.favorites[self.current_folder]
            
            # 从下拉菜单中移除
            current_index = self.folder_combo.currentIndex()
            self.folder_combo.removeItem(current_index)
            
            # 切换到默认收藏夹
            self.current_folder = "默认收藏夹"
            self.folder_combo.setCurrentText("默认收藏夹")
            self.change_folder("默认收藏夹")
            
            # 保存更改
            self.save_favorites()
            
            QMessageBox.information(self, "成功", "收藏夹已删除！")

    def set_content(self, text, description=""):
        """设置预览窗口内容"""
        self.preview_window.set_content(text, description)
    
    def start_number_input(self):
        """开始编号输入"""
        self.number_input_buffer = "."
        self.number_input_timer.start()
        print(f"开始编号输入: {self.number_input_buffer}")
    
    def clear_number_input(self):
        """清空编号输入缓冲"""
        self.number_input_buffer = ""
        print("清空编号输入缓冲")
    
    def handle_number_input(self, key):
        """处理编号输入"""
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            digit = str(key - Qt.Key.Key_0)
            self.number_input_buffer += digit
            self.number_input_timer.start()  # 重新开始计时
            print(f"输入数字: {digit}, 当前缓冲: {self.number_input_buffer}")
            
            # 尝试解析并跳转到对应条目
            self.try_jump_to_item()
            return True
        elif key == Qt.Key.Key_Period:
            self.number_input_buffer += "."
            self.number_input_timer.start()
            print(f"输入点号, 当前缓冲: {self.number_input_buffer}")
            return True
        else:
            # 其他键，清空缓冲
            self.clear_number_input()
            return False
    
    def try_jump_to_item(self):
        """尝试跳转到对应的条目"""
        if not self.number_input_buffer:
            return
        
        # 解析输入的编号
        try:
            # 计算点号数量
            dot_count = 0
            number_str = self.number_input_buffer
            while number_str.startswith('.'):
                dot_count += 1
                number_str = number_str[1:]
            
            if not number_str:
                return  # 还没有输入数字
            
            number = int(number_str)
            
            # 根据点号数量和数字计算实际索引
            if dot_count == 0:
                # 直接数字 1-9
                if 1 <= number <= 9:
                    index = number - 1
                else:
                    return
            else:
                # 有点号的情况
                # 验证数字是否在正确的范围内
                expected_range_start = dot_count * 10
                expected_range_end = expected_range_start + 9
                if expected_range_start <= number <= expected_range_end:
                    index = number - 1
                else:
                    return
            
            # 跳转到对应条目
            current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
            if 0 <= index < current_list.count():
                current_list.setCurrentRow(index)
                print(f"跳转到条目 {index + 1}")
                
                # 如果输入完整，立即执行粘贴
                if self.is_complete_number_input(dot_count, number):
                    self.paste_selected()
                    self.clear_number_input()
        
        except ValueError:
            # 数字解析失败
            pass
    
    def is_complete_number_input(self, dot_count, number):
        """判断是否是完整的编号输入"""
        if dot_count == 0:
            return 1 <= number <= 9
        else:
            # 有点号的情况
            expected_range_start = dot_count * 10
            expected_range_end = expected_range_start + 9
            return expected_range_start <= number <= expected_range_end


    def delete_history_item(self):
        """删除选中的历史条目"""
        current_row = self.history_list.currentRow()
        if current_row >= 0:  # 确保有选中的项目
            # 从数据中删除
            self.clipboard_history.pop(current_row)
            # 从列表控件中删除
            self.history_list.takeItem(current_row)
            # 更新编号
            self.update_list_numbers(self.history_list)
            # 保存更改
            self.save_history()

    def edit_history_item(self, row):
        """编辑历史条目的内容"""
        if 0 <= row < len(self.clipboard_history):
            original_text = self.clipboard_history[row]
            dialog = EditItemDialog(self, text=original_text)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_text = dialog.get_text()
                
                # 更新历史记录中的内容
                self.clipboard_history[row] = new_text
                
                # 更新显示的文本
                truncated_text = self.truncate_text(new_text)
                self.history_list.item(row).setText(f"{row+1}. {truncated_text}")
                
                # 保存更改
                self.save_history()

    def show_search_dialog(self):
        """显示/关闭搜索对话框（toggle）"""
        # 如果搜索对话框已存在且可见，则关闭它
        if hasattr(self, '_search_dialog') and self._search_dialog is not None and self._search_dialog.isVisible():
            self._search_dialog.close()
            self._search_dialog = None
            return
        # 创建新的搜索对话框
        self._search_dialog = SearchDialog(self)
        self._search_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._search_dialog.setModal(True)
        self._search_dialog.destroyed.connect(lambda: setattr(self, '_search_dialog', None))
        self._search_dialog.exec()
    
    def search_items(self, search_text, use_regex, scope, case_sensitive=False, whole_word=False):
        """搜索项目"""
        results = []
        print(f"开始搜索: 文本='{search_text}', 范围='{scope}'")  # 调试输出
        
        try:
            # 搜索历史记录
            if scope in ["全部", "历史记录"]:
                print("搜索历史记录...")  # 调试输出
                for i, item in enumerate(self.clipboard_history):
                    text = str(item)  # 确保是字符串
                    
                    if self.match_text(text, "", search_text, use_regex, case_sensitive, whole_word):
                        results.append(("历史记录", text, ""))
            
            # 搜索收藏夹
            if scope in ["全部", "所有收藏夹", "当前收藏夹"] or scope.startswith("收藏夹-"):
                print("搜索收藏夹...")  # 调试输出
                
                # 确定要搜索的收藏夹
                if scope == "当前收藏夹":
                    folders = [self.current_folder]
                elif scope.startswith("收藏夹-"):
                    folder_name = scope[4:]  # 去掉"收藏夹-"前缀
                    folders = [folder_name] if folder_name in self.favorites else []
                else:
                    # "全部"或"所有收藏夹"
                    folders = list(self.favorites.keys())
                
                print(f"要搜索的收藏夹: {folders}")  # 调试输出
                
                for folder in folders:
                    if folder not in self.favorites:
                        print(f"收藏夹 {folder} 不存在")
                        continue
                        
                    print(f"搜索收藏夹 {folder} 中的 {len(self.favorites[folder])} 个项目")
                    for item in self.favorites[folder]:
                        if isinstance(item, dict):
                            text = item.get("text", "")
                            description = item.get("description", "")
                        else:
                            text = str(item)
                            description = ""
                        
                        if self.match_text(text, description, search_text, use_regex, case_sensitive, whole_word):
                            results.append((f"收藏夹-{folder}", text, description))
            
            print(f"搜索完成，找到 {len(results)} 个结果")  # 调试输出
            return results
            
        except Exception as e:
            print(f"搜索出错: {str(e)}")  # 调试输出
            traceback.print_exc()
            raise e
    
    def match_text(self, text, description, pattern, use_regex, case_sensitive, whole_word):
        """匹配文本"""
        if use_regex:
            try:
                # 正则表达式搜索
                flags = 0 if case_sensitive else re.IGNORECASE
                if whole_word:
                    # 全字匹配的正则表达式
                    pattern = r'\b' + pattern + r'\b'
                if bool(re.search(pattern, text, flags)):
                    return True
                elif bool(re.search(pattern, description, flags)):
                    return True
                else:
                    return False
            except re.error:
                # 正则表达式错误，使用普通搜索
                if self.normal_search(text, pattern, case_sensitive, whole_word):
                    return True
                elif self.normal_search(description, pattern, case_sensitive, whole_word):
                    return True
                else:
                    return False
        else:
            # 普通搜索
            if self.normal_search(text, pattern, case_sensitive, whole_word):
                return True
            elif self.normal_search(description, pattern, case_sensitive, whole_word):
                return True
            else:
                return False
    
    def normal_search(self, text, pattern, is_case_sensitive, is_whole_word):
        """执行普通文本搜索"""
        if not is_case_sensitive:
            text = text.lower()
            pattern = pattern.lower()
        
        if is_whole_word:
            # 全字匹配
            words = re.findall(r'\b\w+\b', text)
            return pattern in words
        else:
            # 普通包含匹配
            return pattern in text

def get_resource_path(relative_path):
    """获取资源文件的绝对路径"""
    base_path = os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)

def get_app_icon():
    """优先使用 icon.ico, 回退到 icon.png"""
    for name in ("icon.ico", "icon.png"):
        path = get_resource_path(name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()

def main():
    # 在 Windows 上设置 AppUserModelID, 让任务栏把本应用识别为独立应用,
    # 否则会沿用 python.exe 的图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "PCClipboardH.ClipboardHistory.1"
            )
        except Exception as e:
            print(f"设置 AppUserModelID 失败: {e}")

    app = QApplication(sys.argv)

    # 设置应用级图标, 任务栏会使用这个图标
    app.setWindowIcon(get_app_icon())

    window = ClipboardHistoryApp()
    window.hide()  # 初始隐藏窗口

    # 阻止 Python 解释器退出
    app.setQuitOnLastWindowClosed(False)

    sys.exit(app.exec())

if __name__ == '__main__':
    main() 
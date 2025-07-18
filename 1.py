from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget, 
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu,
                           QHBoxLayout, QStackedWidget, QLabel, QTextEdit, QDialog, QLineEdit, QMessageBox, QComboBox, QInputDialog, QFrame, QScrollArea, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint
from PyQt6.QtGui import QClipboard, QIcon, QKeyEvent, QKeySequence, QShortcut
import sys
import json
import os
import keyboard
import time
import re
import traceback
from pynput.keyboard import Key, Controller

import keyboard
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


# 修改热键线程的实现
class HotkeyThread(QThread):
    triggered = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, hotkey='ctrl+alt+z'):
        super().__init__()
        self.running = True
        self.hotkey = hotkey
        self.current_hotkey = None
        self.retry_count = 0
        self.max_retries = 5  # 增加最大重试次数
        self.last_check_time = 0
        self.check_interval = 15  # 减少检查间隔，更频繁地检查热键状态
        self.last_trigger_time = 0
        self.min_trigger_interval = 0.3  # 减少最小触发间隔
        self.force_restart_count = 0
        self.max_force_restart = 3  # 最大强制重启次数
        
    def run(self):
        while self.running:
            try:
                # 清理旧的热键注册
                self.cleanup_hotkey()
                
                # 重新注册热键
                self.current_hotkey = keyboard.add_hotkey(self.hotkey, self.on_hotkey)
                print(f"热键已注册: {self.hotkey}")
                self.retry_count = 0
                self.last_check_time = time.time()
                
                while self.running:
                    self.msleep(100)
                    
                    # 定期检查热键状态
                    current_time = time.time()
                    if current_time - self.last_check_time > self.check_interval:
                        print("定期检查热键状态...")
                        self.last_check_time = current_time
                        
                        # 检查热键是否仍然有效
                        if not self.is_hotkey_active():
                            print("热键状态异常，准备重新注册")
                            self.error.emit("热键状态检查失败")
                            break
                        
                        # 定期刷新热键注册以确保稳定性
                        try:
                            self.refresh_hotkey()
                        except Exception as e:
                            print(f"热键刷新错误: {e}")
                            self.error.emit(str(e))
                            break
                            
            except Exception as e:
                print(f"热键错误: {e}")
                self.error.emit(str(e))
                self.retry_count += 1
                
                if self.retry_count < self.max_retries:
                    print(f"尝试重新注册热键 (第 {self.retry_count} 次)")
                    self.msleep(1000 * self.retry_count)  # 递增延迟
                    continue
                else:
                    print("热键重试次数已达上限，进入强制重启模式")
                    self.force_restart_count += 1
                    if self.force_restart_count < self.max_force_restart:
                        self.msleep(5000)
                        self.retry_count = 0
                        continue
                    else:
                        print("强制重启次数已达上限，线程将停止")
                        break

    def cleanup_hotkey(self):
        """清理现有的热键注册"""
        try:
            if self.current_hotkey is not None:
                keyboard.remove_hotkey(self.current_hotkey)
                self.current_hotkey = None
                print("已清理旧的热键注册")
        except Exception as e:
            print(f"清理热键时出错: {e}")

    def refresh_hotkey(self):
        """刷新热键注册"""
        try:
            # 先移除再重新注册来测试热键状态
            if self.current_hotkey is not None:
                keyboard.remove_hotkey(self.current_hotkey)
            self.current_hotkey = keyboard.add_hotkey(self.hotkey, self.on_hotkey)
            print(f"热键已刷新: {self.hotkey}")
        except Exception as e:
            raise e

    def on_hotkey(self):
        """热键触发处理"""
        current_time = time.time()
        # 检查是否满足最小触发间隔
        if current_time - self.last_trigger_time >= self.min_trigger_interval:
            print("热键被触发")
            self.last_trigger_time = current_time
            self.triggered.emit()
        else:
            print(f"热键触发被忽略，间隔过短: {current_time - self.last_trigger_time:.2f}s")

    def is_hotkey_active(self):
        """更强健的热键状态检查"""
        try:
            # 方法1: 检查keyboard库的内部状态
            if hasattr(keyboard, '_listener') and keyboard._listener:
                handlers = getattr(keyboard._listener, 'handlers', {})
                if handlers:
                    # 检查我们的热键是否在已注册的处理器中
                    hotkey_found = False
                    for handler_key in handlers.keys():
                        if str(handler_key).find(self.hotkey.replace('+', '')) != -1:
                            hotkey_found = True
                            break
                    
                    if not hotkey_found:
                        print("热键在处理器列表中未找到")
                        return False
            
            # 方法2: 检查当前热键句柄是否有效
            if self.current_hotkey is None:
                print("热键句柄为空")
                return False
            
            # 方法3: 尝试获取热键信息
            try:
                # 尝试访问热键的内部信息
                if hasattr(self.current_hotkey, '__dict__'):
                    return True
            except:
                print("热键句柄无效")
                return False
            
            return True
            
        except Exception as e:
            print(f"检查热键状态时出错: {e}")
            return False

    def stop(self):
        """停止热键线程"""
        print("正在停止热键线程...")
        self.running = False
        self.cleanup_hotkey()
        
        # 确保线程完全停止
        if self.isRunning():
            self.quit()
            if not self.wait(2000):  # 等待2秒
                print("热键线程强制终止")
                self.terminate()
                self.wait()
        
        print("热键线程已停止")

class HotkeySettingDialog(QDialog):
    """热键设置对话框"""
    def __init__(self, parent=None, current_hotkey="ctrl+alt+z"):
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
            Qt.Key.Key_Meta: 'win',
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
            current_keys.add('win')
        
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
        self.resize(800, 600)  # 增加窗口尺寸
        
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
        self.text_edit.setText(text)
        if description:
            self.description_label.show()
            self.description_edit.show()
            self.description_edit.setText(description)
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
    
    def mousePressEvent(self, event):
        """处理鼠标按下事件，用于拖拽窗口"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """处理鼠标移动事件，实现窗口拖拽"""
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def focusOutEvent(self, event):
        """当窗口失去焦点时的处理"""
        # 可以选择在失去焦点时隐藏窗口，但这可能会影响用户体验
        # 所以这里暂时不自动隐藏
        super().focusOutEvent(event)

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
        
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["全部", "历史记录", "当前收藏夹", "所有收藏夹"])
        self.scope_combo.currentIndexChanged.connect(self.on_search_option_changed)
        scope_layout.addWidget(self.scope_combo)
        
        # 设置快捷键 Alt+X 显示下拉菜单
        self.scope_button = QPushButton("选择范围(&X)")
        self.scope_button.clicked.connect(self.show_scope_menu)
        scope_layout.addWidget(self.scope_button)
        
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
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 使用选中项按钮
        self.use_button = QPushButton("使用选中项")
        self.use_button.clicked.connect(self.use_selected)
        button_layout.addWidget(self.use_button)
        
        # 关闭按钮
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        
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
    
    def show_scope_menu(self):
        """显示搜索范围下拉菜单"""
        # 创建菜单
        menu = QMenu(self)
        
        # 添加基本搜索范围选项
        basic_scopes = ["全部", "历史记录", "当前收藏夹", "所有收藏夹"]
        for i, scope in enumerate(basic_scopes):
            action = menu.addAction(scope)
            # 标记当前选中的范围
            if i == self.scope_combo.currentIndex() and self.scope_combo.currentText() == scope:
                action.setIcon(QIcon.fromTheme("dialog-ok"))
            
            # 修复闭包问题：使用偏函数或默认参数来正确捕获变量值
            def make_scope_handler(scope_name, index):
                return lambda checked: self.set_search_scope(scope_name, index)
            
            # 连接动作信号
            action.triggered.connect(make_scope_handler(scope, i))
        
        # 添加分隔线
        menu.addSeparator()
        
        # 添加子收藏夹选项
        if hasattr(self.parent_app, 'favorites') and self.parent_app.favorites:
            submenu = menu.addMenu("指定收藏夹")
            for folder_name in sorted(self.parent_app.favorites.keys()):
                action = submenu.addAction(folder_name)
                # 标记当前选中的收藏夹
                if self.scope_combo.currentText() == f"收藏夹-{folder_name}":
                    action.setIcon(QIcon.fromTheme("dialog-ok"))
                
                # 修复闭包问题：使用偏函数或默认参数来正确捕获变量值
                def make_folder_handler(folder):
                    return lambda checked: self.set_folder_scope(folder)
                
                # 连接动作信号
                action.triggered.connect(make_folder_handler(folder_name))
        
        # 在按钮下方显示菜单
        button_pos = self.scope_button.mapToGlobal(QPoint(0, self.scope_button.height()))
        menu.exec(button_pos)
    
    def set_search_scope(self, scope, index):
        """设置搜索范围"""
        self.scope_combo.setCurrentIndex(index)
        self.perform_search()

    def set_folder_scope(self, folder_name):
        """设置特定收藏夹作为搜索范围"""
        # 修改搜索范围的格式，使其与 search_items 方法中的判断一致
        folder_scope = f"收藏夹-{folder_name}"  # 修改这里，使用连字符而不是冒号
        index = self.scope_combo.findText(folder_scope)
        
        if index == -1:
            # 如果不存在，添加新选项
            self.scope_combo.addItem(folder_scope)
            index = self.scope_combo.count() - 1
        
        # 设置为当前选项
        self.scope_combo.setCurrentIndex(index)
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
            source, text, description = self.results[index]
            
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
                
                # 显示状态信息
                if hasattr(parent, 'statusBar'):
                    parent.statusBar().showMessage(f"已从{source}中删除项目", 3000)
                else:
                    # 如果没有状态栏，可以在控制台打印信息
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
    


class ClipboardHistoryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("剪贴板历史")
        
        # 设置窗口图标
        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
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
        
        # 添加搜索按钮
        self.search_button = QPushButton("搜索(&S)")  # 添加快捷键 Alt+S
        self.search_button.setFixedWidth(60)
        self.search_button.clicked.connect(self.show_panel_search)
        top_layout.addWidget(self.search_button)
        
        top_layout.addStretch()  # 添加弹性空间，使标签靠左对齐
        
        # 创建堆叠式窗口部件
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)
        
        # 创建历史记录列表
        self.history_list = QListWidget()
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
        self.stacked_widget.addWidget(self.history_list)
        
        # 创建收藏列表
        self.favorites_list = QListWidget()
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
        self.stacked_widget.addWidget(self.favorites_list)
        
        # 为收藏列表添加右键菜单
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.customContextMenuRequested.connect(self.show_favorites_context_menu)
        
        # 添加按钮布局
        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)
        
        # 创建"复制选中项"按钮
        copy_button = QPushButton("复制选中项")
        copy_button.clicked.connect(self.copy_selected)
        button_layout.addWidget(copy_button)
        
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
        self.delete_folder_btn = QPushButton("删除(&D)")
        self.delete_folder_btn.clicked.connect(self.delete_current_folder)
        self.delete_folder_btn.setFixedWidth(60)
        
        # 按新顺序添加按钮
        folder_layout.addWidget(self.change_folder_btn)
        folder_layout.addWidget(self.rename_folder_btn)
        folder_layout.addWidget(self.delete_folder_btn)
        top_layout.addLayout(folder_layout)
        
        # 存储收藏夹数据
        self.favorites_file = os.path.join(os.path.expanduser('~'), '.clipboard_favorites.json')
        
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
        self.history_file = os.path.join(os.path.expanduser('~'), '.clipboard_history.json')
        
        # 加载历史记录
        self.load_history()
        
        # 加载配置
        self.config_file = os.path.join(os.path.expanduser('~'), '.clipboard_config.json')
        self.load_config()
        
        # 创建并启动热键线程
        self.hotkey_thread = HotkeyThread(self.config.get('hotkey', 'ctrl+alt+z'))
        self.hotkey_thread.triggered.connect(self.show_window)
        self.hotkey_thread.error.connect(self.handle_hotkey_error)  # 连接错误处理
        self.hotkey_thread.start()
        
        # 创建搜索热键线程
        self.search_hotkey_thread = HotkeyThread('ctrl+alt+a')
        self.search_hotkey_thread.triggered.connect(self.show_search_dialog)
        self.search_hotkey_thread.error.connect(self.handle_search_hotkey_error)
        self.search_hotkey_thread.start()
        
        # 创建系统托盘图标 (只调用一次)
        self.create_tray_icon()
        
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
        
        # 创建热键状态检查定时器
        self.hotkey_check_timer = QTimer()
        self.hotkey_check_timer.timeout.connect(self.check_hotkey_threads)
        self.hotkey_check_timer.start(30000)  # 减少到每30秒检查一次，更及时发现问题
        
        # 用于处理编号输入的变量
        self.number_input_buffer = ""
        self.number_input_timer = QTimer()
        self.number_input_timer.setSingleShot(True)
        self.number_input_timer.timeout.connect(self.clear_number_input)
        self.number_input_timer.setInterval(2000)  # 2秒后清空输入缓冲
        
        # 添加热键重启计数
        self.hotkey_restart_count = 0
        self.search_hotkey_restart_count = 0
        self.max_restart_count = 10  # 最大重启次数
        
    def check_hotkey_threads(self):
        """检查热键线程状态"""
        try:
            # 检查主热键线程
            if not self.hotkey_thread.isRunning():
                print("主热键线程已停止，正在重启...")
                self.restart_main_hotkey()
            elif hasattr(self.hotkey_thread, 'force_restart_count') and self.hotkey_thread.force_restart_count >= 3:
                print("主热键线程强制重启次数过多，完全重建线程...")
                self.restart_main_hotkey()
            
            # 检查搜索热键线程
            if not self.search_hotkey_thread.isRunning():
                print("搜索热键线程已停止，正在重启...")
                self.restart_search_hotkey()
            elif hasattr(self.search_hotkey_thread, 'force_restart_count') and self.search_hotkey_thread.force_restart_count >= 3:
                print("搜索热键线程强制重启次数过多，完全重建线程...")
                self.restart_search_hotkey()
                
        except Exception as e:
            print(f"检查热键线程状态时出错: {e}")

    def restart_main_hotkey(self):
        """重启主热键线程"""
        try:
            if self.hotkey_restart_count >= self.max_restart_count:
                print("主热键重启次数已达上限，停止重启")
                self.tray_icon.showMessage("热键错误", "主热键重启次数过多，请手动重置", QSystemTrayIcon.MessageIcon.Critical, 5000)
                return
            
            self.hotkey_restart_count += 1
            print(f"重启主热键线程 (第 {self.hotkey_restart_count} 次)")
            
            # 完全停止并清理旧线程
            if hasattr(self, 'hotkey_thread'):
                self.hotkey_thread.stop()
                self.hotkey_thread.wait(3000)  # 等待3秒
                if self.hotkey_thread.isRunning():
                    self.hotkey_thread.terminate()
                    self.hotkey_thread.wait()
            
            # 短暂延迟后创建新线程
            QTimer.singleShot(1000, self.create_new_main_hotkey_thread)
            
        except Exception as e:
            print(f"重启主热键线程时出错: {e}")

    def create_new_main_hotkey_thread(self):
        """创建新的主热键线程"""
        try:
            self.hotkey_thread = HotkeyThread(self.config.get('hotkey', 'ctrl+alt+z'))
            self.hotkey_thread.triggered.connect(self.show_window)
            self.hotkey_thread.error.connect(self.handle_hotkey_error)
            self.hotkey_thread.start()
            print("新的主热键线程已创建")
        except Exception as e:
            print(f"创建新主热键线程时出错: {e}")

    def restart_search_hotkey(self):
        """重启搜索热键线程"""
        try:
            if self.search_hotkey_restart_count >= self.max_restart_count:
                print("搜索热键重启次数已达上限，停止重启")
                self.tray_icon.showMessage("热键错误", "搜索热键重启次数过多，请手动重置", QSystemTrayIcon.MessageIcon.Critical, 5000)
                return
            
            self.search_hotkey_restart_count += 1
            print(f"重启搜索热键线程 (第 {self.search_hotkey_restart_count} 次)")
            
            # 完全停止并清理旧线程
            if hasattr(self, 'search_hotkey_thread'):
                self.search_hotkey_thread.stop()
                self.search_hotkey_thread.wait(3000)  # 等待3秒
                if self.search_hotkey_thread.isRunning():
                    self.search_hotkey_thread.terminate()
                    self.search_hotkey_thread.wait()
            
            # 短暂延迟后创建新线程
            QTimer.singleShot(1000, self.create_new_search_hotkey_thread)
            
        except Exception as e:
            print(f"重启搜索热键线程时出错: {e}")

    def create_new_search_hotkey_thread(self):
        """创建新的搜索热键线程"""
        try:
            self.search_hotkey_thread = HotkeyThread('ctrl+alt+a')
            self.search_hotkey_thread.triggered.connect(self.show_search_dialog)
            self.search_hotkey_thread.error.connect(self.handle_search_hotkey_error)
            self.search_hotkey_thread.start()
            print("新的搜索热键线程已创建")
        except Exception as e:
            print(f"创建新搜索热键线程时出错: {e}")

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
        
        # 使用资源路径获取图标
        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            # 如果找不到图标文件，使用默认图标
            self.tray_icon.setIcon(self.create_default_icon())
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        # 添加显示/隐藏动作
        show_action = tray_menu.addAction("显示")
        show_action.triggered.connect(self.show_window)
        
        hide_action = tray_menu.addAction("隐藏")
        hide_action.triggered.connect(self.hide)
        
        # 添加分隔线
        tray_menu.addSeparator()
        
        # 添加设置选项
        settings_action = tray_menu.addAction("设置")
        settings_action.triggered.connect(self.show_settings)
        
        # 添加分隔线
        tray_menu.addSeparator()
        
        # 添加重置热键选项（添加 Alt+C 快捷键）
        reset_hotkey = tray_menu.addAction("重置热键(&C)")  # 添加 &C 来设置 Alt+C 快捷键
        reset_hotkey.triggered.connect(self.handle_hotkey_error)
        
        # 添加完全重置热键选项
        full_reset_hotkey = tray_menu.addAction("完全重置热键(&F)")  # 添加 &F 来设置 Alt+F 快捷键
        full_reset_hotkey.triggered.connect(self.full_reset_hotkeys)
        
        # 添加分隔线
        tray_menu.addSeparator()
        
        # 添加版本信息（禁用点击）
        version_action = tray_menu.addAction("版本: 2025/07/18-01")
        version_action.setEnabled(False)  # 设置为不可点击
        
        # 添加分隔线
        tray_menu.addSeparator()
        
        # 添加搜索选项
        search_action = tray_menu.addAction("搜索(&S)")
        search_action.triggered.connect(self.show_search_dialog)
        
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
        # 修改为 Alt+C 快捷键
        elif (event.modifiers() == Qt.KeyboardModifier.AltModifier and 
              event.key() == Qt.Key.Key_C and 
              self.stacked_widget.currentIndex() == 1):
            # 打开收藏夹下拉菜单
            self.folder_combo.showPopup()
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
        self.favorites_list.setFocus()  # 修改这里，设置焦点到收藏列表

    def __del__(self):
        """确保程序退出时清理热键"""
        if hasattr(self, 'hotkey_thread'):
            self.hotkey_thread.stop()
            self.hotkey_thread.wait()
        if hasattr(self, 'search_hotkey_thread'):
            self.search_hotkey_thread.stop()
            self.search_hotkey_thread.wait()

    def eventFilter(self, obj, event):
        """事件过滤器，处理窗口事件"""
        if event.type() == event.Type.WindowDeactivate:
            # 当窗口失去焦点时隐藏
            self.hide()
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
    

    def load_favorites(self):
        """从文件加载收藏记录"""
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # 处理旧格式数据（简单列表）
                    if isinstance(data, list):
                        self.favorites = {
                            "默认收藏夹": [{"text": item, "description": ""} for item in data]
                        }
                    # 新格式数据（字典格式）
                    elif isinstance(data, dict):
                        self.favorites = {}
                        for folder, items in data.items():
                            self.favorites[folder] = []
                            for item in items:
                                if isinstance(item, str):
                                    self.favorites[folder].append({"text": item, "description": ""})
                                else:
                                    self.favorites[folder].append(item)
                    
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
                    
                    # 保存为新格式
                    self.save_favorites()
                
        except Exception as e:
            print(f"加载收藏记录时出错: {e}")
            self.favorites = {"默认收藏夹": []}
            self.folder_combo.clear()
            self.folder_combo.addItem("默认收藏夹")

    def save_favorites(self):
        """保存收藏记录到文件"""
        try:
            print(f"开始保存收藏夹...")
            print(f"收藏夹文件路径: {self.favorites_file}")
            print(f"收藏夹数量: {len(self.favorites)}")
            
            # 确保所有收藏夹中的项目都使用字典格式
            for folder_name in self.favorites:
                print(f"处理收藏夹: {folder_name}, 项目数: {len(self.favorites[folder_name])}")
                for i, item in enumerate(self.favorites[folder_name]):
                    if not isinstance(item, dict):
                        print(f"  将项目 {i} 转换为字典格式: {item}")
                        self.favorites[folder_name][i] = {
                            "text": str(item),
                            "description": ""
                        }
            
            # 保存到文件
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
            print(f"收藏已成功保存到: {self.favorites_file}")
            
            # 验证文件是否存在
            if os.path.exists(self.favorites_file):
                print(f"文件存在，大小: {os.path.getsize(self.favorites_file)} 字节")
            else:
                print(f"警告: 文件保存后不存在!")
            
            # 尝试重新加载文件以验证
            try:
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    test_data = json.load(f)
                print(f"验证: 成功读取文件，包含 {len(test_data)} 个收藏夹")
            except Exception as e:
                print(f"验证读取失败: {e}")
            
        except Exception as e:
            print(f"保存收藏记录时出错: {e}")
            traceback.print_exc()

    def truncate_text(self, text, max_length=50):
        """截断文本，保留定长度添加省略号"""
        # 移除文本中的换行符
        text = text.replace('\n', ' ').replace('\r', '')
        
        # 确保不会特殊处理以find开头的文本
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text


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
        """显示设置对话框"""
        dialog = HotkeySettingDialog(self, self.config.get('hotkey', 'ctrl+alt+z'))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_hotkey = dialog.new_hotkey
            if new_hotkey != self.config.get('hotkey'):
                self.config['hotkey'] = new_hotkey
                self.save_config()
                # 重启热键线程
                self.hotkey_thread.stop()
                self.hotkey_thread.wait()
                self.hotkey_thread = HotkeyThread(new_hotkey)
                self.hotkey_thread.triggered.connect(self.show_window)
                self.hotkey_thread.start()
                QMessageBox.information(self, "设置成功", f"快捷键已更改为: {new_hotkey}")

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = {'hotkey': 'ctrl+alt+z'}
        except Exception as e:
            print(f"加载配置出错: {e}")
            self.config = {'hotkey': 'ctrl+alt+z'}

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
                dot_count = (number - 1) // 10
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

    def handle_hotkey_error(self, error_msg=""):
        """处理热键错误"""
        print(f"热键错误，正在重新初始化: {error_msg}")
        
        # 重置强制重启计数，给线程重新开始的机会
        if hasattr(self, 'hotkey_thread') and hasattr(self.hotkey_thread, 'force_restart_count'):
            self.hotkey_thread.force_restart_count = 0
        
        # 重新初始化热键线程
        try:
            # 完全停止旧线程
            if hasattr(self, 'hotkey_thread'):
                self.hotkey_thread.stop()
                self.hotkey_thread.wait(3000)  # 等待3秒
                
                # 如果线程仍在运行，强制终止
                if self.hotkey_thread.isRunning():
                    print("强制终止热键线程")
                    self.hotkey_thread.terminate()
                    self.hotkey_thread.wait()
        except Exception as e:
            print(f"停止热键线程时出错: {e}")
        
        # 延迟一段时间后重新创建线程，避免资源冲突
        QTimer.singleShot(1500, self.recreate_main_hotkey_thread)

    def recreate_main_hotkey_thread(self):
        """重新创建主热键线程"""
        try:
            # 创建新的热键线程
            self.hotkey_thread = HotkeyThread(self.config.get('hotkey', 'ctrl+alt+z'))
            self.hotkey_thread.triggered.connect(self.show_window)
            self.hotkey_thread.error.connect(self.handle_hotkey_error)
            self.hotkey_thread.start()
            
            # 显示通知
            self.tray_icon.showMessage("热键已重置", f"快捷键 {self.config.get('hotkey', 'ctrl+alt+z')} 已重新注册", QSystemTrayIcon.MessageIcon.Information, 3000)
            print("主热键线程重新创建完成")
            
        except Exception as e:
            print(f"重新创建主热键线程时出错: {e}")
            # 如果重新创建失败，延迟后再次尝试
            QTimer.singleShot(5000, self.recreate_main_hotkey_thread)

    def handle_search_hotkey_error(self, error_msg=""):
        """处理搜索热键错误"""
        print(f"搜索热键错误，正在重新初始化: {error_msg}")
        
        # 重置强制重启计数
        if hasattr(self, 'search_hotkey_thread') and hasattr(self.search_hotkey_thread, 'force_restart_count'):
            self.search_hotkey_thread.force_restart_count = 0
        
        try:
            # 完全停止旧线程
            if hasattr(self, 'search_hotkey_thread'):
                self.search_hotkey_thread.stop()
                self.search_hotkey_thread.wait(3000)
                
                if self.search_hotkey_thread.isRunning():
                    print("强制终止搜索热键线程")
                    self.search_hotkey_thread.terminate()
                    self.search_hotkey_thread.wait()
        except Exception as e:
            print(f"停止搜索热键线程时出错: {e}")
        
        # 延迟一段时间后重新创建线程
        QTimer.singleShot(1500, self.recreate_search_hotkey_thread)

    def recreate_search_hotkey_thread(self):
        """重新创建搜索热键线程"""
        try:
            # 创建新的热键线程
            self.search_hotkey_thread = HotkeyThread('ctrl+alt+a')
            self.search_hotkey_thread.triggered.connect(self.show_search_dialog)
            self.search_hotkey_thread.error.connect(self.handle_search_hotkey_error)
            self.search_hotkey_thread.start()
            
            # 显示通知
            self.tray_icon.showMessage("搜索热键已重置", "快捷键 ctrl+alt+a 已重新注册", QSystemTrayIcon.MessageIcon.Information, 3000)
            print("搜索热键线程重新创建完成")
            
        except Exception as e:
            print(f"重新创建搜索热键线程时出错: {e}")
            # 如果重新创建失败，延迟后再次尝试
            QTimer.singleShot(5000, self.recreate_search_hotkey_thread)

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

    def show_panel_search(self):
        """显示当前面板的搜索对话框"""
        dialog = SearchDialog(self)
        # 根据当前面板设置搜索范围
        if self.stacked_widget.currentIndex() == 0:
            # 历史记录面板
            dialog.scope_combo.setCurrentText("历史记录")
        else:
            # 收藏面板
            dialog.scope_combo.setCurrentText("当前收藏夹")
        dialog.perform_search()  # 立即执行一次搜索
        dialog.search_input.setFocus()  # 设置焦点到搜索框
        dialog.exec()

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
        """显示搜索对话框"""
        dialog = SearchDialog(self)
        # 设置对话框属性，确保它能获得输入焦点
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setModal(True)
        dialog.exec()
    
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

    def full_reset_hotkeys(self):
        """完全重置热键系统"""
        print("开始完全重置热键系统...")
        
        try:
            # 重置所有计数器
            self.hotkey_restart_count = 0
            self.search_hotkey_restart_count = 0
            
            # 停止主热键线程
            if hasattr(self, 'hotkey_thread'):
                print("停止主热键线程...")
                self.hotkey_thread.stop()
                self.hotkey_thread.wait(5000)  # 等待5秒
                if self.hotkey_thread.isRunning():
                    self.hotkey_thread.terminate()
                    self.hotkey_thread.wait()
            
            # 停止搜索热键线程
            if hasattr(self, 'search_hotkey_thread'):
                print("停止搜索热键线程...")
                self.search_hotkey_thread.stop()
                self.search_hotkey_thread.wait(5000)  # 等待5秒
                if self.search_hotkey_thread.isRunning():
                    self.search_hotkey_thread.terminate()
                    self.search_hotkey_thread.wait()
            
            # 延迟后重新创建热键线程
            QTimer.singleShot(2000, self.recreate_all_hotkey_threads)
            
            # 显示通知
            self.tray_icon.showMessage("热键重置中", "正在完全重置热键系统，请稍候...", QSystemTrayIcon.MessageIcon.Information, 3000)
            
        except Exception as e:
            print(f"完全重置热键时出错: {e}")
            self.tray_icon.showMessage("重置失败", f"热键重置失败: {str(e)}", QSystemTrayIcon.MessageIcon.Critical, 5000)

    def recreate_all_hotkey_threads(self):
        """重新创建所有热键线程"""
        try:
            print("重新创建所有热键线程...")
            
            # 创建主热键线程
            self.hotkey_thread = HotkeyThread(self.config.get('hotkey', 'ctrl+alt+z'))
            self.hotkey_thread.triggered.connect(self.show_window)
            self.hotkey_thread.error.connect(self.handle_hotkey_error)
            self.hotkey_thread.start()
            
            # 创建搜索热键线程
            self.search_hotkey_thread = HotkeyThread('ctrl+alt+a')
            self.search_hotkey_thread.triggered.connect(self.show_search_dialog)
            self.search_hotkey_thread.error.connect(self.handle_search_hotkey_error)
            self.search_hotkey_thread.start()
            
            print("所有热键线程重新创建完成")
            self.tray_icon.showMessage("重置完成", "热键系统已完全重置并重新启动", QSystemTrayIcon.MessageIcon.Information, 3000)
            
        except Exception as e:
            print(f"重新创建热键线程时出错: {e}")
            self.tray_icon.showMessage("重置失败", f"重新创建热键线程失败: {str(e)}", QSystemTrayIcon.MessageIcon.Critical, 5000)

def get_resource_path(relative_path):
    """获取资源文件的绝对路径"""
    try:
        # PyInstaller创建临时文件夹,将路径存储在_MEIPASS中
        base_path = sys._MEIPASS
    except Exception:
        # 如果不是打包的情况,就使用当前文件的路径
        base_path = os.path.dirname(__file__)
    
    return os.path.join(base_path, relative_path)

def main():
    app = QApplication(sys.argv)
    window = ClipboardHistoryApp()
    window.hide()  # 初始隐藏窗口
    
    # 阻止 Python 解释器退出
    app.setQuitOnLastWindowClosed(False)
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 
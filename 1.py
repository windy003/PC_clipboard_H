from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget, 
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu,
                           QHBoxLayout, QStackedWidget, QLabel, QTextEdit, QDialog, QLineEdit, QMessageBox, QComboBox, QInputDialog, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QClipboard, QIcon, QKeyEvent
import sys
import json
import os
import keyboard
import time

# 修改热键线程的实现
class HotkeyThread(QThread):
    triggered = pyqtSignal()
    error = pyqtSignal(str)  # 添加错误信号

    def __init__(self, hotkey='ctrl+alt+z'):
        super().__init__()
        self.running = True
        self.hotkey = hotkey
        self.current_hotkey = None
        self.retry_count = 0
        self.max_retries = 3
        self.last_check_time = 0
        
    def run(self):
        while self.running:
            try:
                if self.current_hotkey:
                    keyboard.remove_hotkey(self.current_hotkey)
                    
                # 重新注册热键
                self.current_hotkey = keyboard.add_hotkey(self.hotkey, self.on_hotkey)
                print(f"热键已注册: {self.hotkey}")
                self.retry_count = 0  # 重置重试计数
                self.last_check_time = time.time()  # 记录注册时间
                
                # 主循环
                while self.running:
                    self.msleep(100)
                    
                    # 定期检查热键是否仍然有效（每60秒检查一次）
                    current_time = time.time()
                    if current_time - self.last_check_time > 60:
                        print("定期检查热键状态...")
                        self.last_check_time = current_time
                        
                        # 尝试重新注册热键以确保其有效
                        try:
                            keyboard.remove_hotkey(self.current_hotkey)
                            self.current_hotkey = keyboard.add_hotkey(self.hotkey, self.on_hotkey)
                            print(f"热键已刷新: {self.hotkey}")
                        except Exception as e:
                            print(f"热键刷新错误: {e}")
                            self.error.emit(str(e))
                            break  # 跳出内循环，进入外循环重试
                    
                    # 如果重试次数达到上限，跳出循环
                    if self.retry_count >= self.max_retries:
                        break
                        
            except Exception as e:
                print(f"热键错误: {e}")
                self.error.emit(str(e))
                self.retry_count += 1
                
                if self.retry_count < self.max_retries:
                    print(f"尝试重新注册热键 (第 {self.retry_count} 次)")
                    self.msleep(1000)  # 等待1秒后重试
                    continue
                else:
                    print("热键重试次数已达上限")
                    self.msleep(5000)  # 等待5秒后重置重试计数
                    self.retry_count = 0

    def on_hotkey(self):
        print("热键被触发")
        self.triggered.emit()

    def stop(self):
        self.running = False
        try:
            if self.current_hotkey:
                keyboard.remove_hotkey(self.current_hotkey)
                self.current_hotkey = None
            print("热键已清理")
        except Exception as e:
            print(f"清理热键时出错: {e}")

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
    """描述信息编辑对话框"""
    def __init__(self, parent=None, text="", description=""):
        super().__init__(parent)
        self.setWindowTitle("编辑内容和描述")
        self.setFixedSize(400, 300)
        self.original_geometry = None  # 存储原始窗口大小和位置
        
        layout = QVBoxLayout(self)
        
        # 描述信息编辑框 - 添加 Alt+D 快捷键
        description_label = QLabel("描述信息(&D):")
        layout.addWidget(description_label)
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(description)
        layout.addWidget(self.description_edit)
        description_label.setBuddy(self.description_edit)
        
        # 内容编辑框 - 添加 Alt+T 快捷键
        content_label = QLabel("条目内容(&T):")
        layout.addWidget(content_label)
        self.content_text = QTextEdit()
        self.content_text.setPlainText(text)
        layout.addWidget(self.content_text)
        content_label.setBuddy(self.content_text)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 全屏按钮
        self.fullscreen_button = QPushButton("全屏(&F)")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        button_layout.addWidget(self.fullscreen_button)
        
        self.confirm_button = QPushButton("确认(&O)")
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("取消(&C)")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.confirm_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
    
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self.original_geometry:
                self.setGeometry(self.original_geometry)
            self.fullscreen_button.setText("全屏(&F)")
        else:
            self.original_geometry = self.geometry()
            self.showFullScreen()
            self.fullscreen_button.setText("退出全屏(&F)")
    
    def get_description(self):
        return self.description_edit.toPlainText()
    
    def get_content(self):
        return self.content_text.toPlainText()

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
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
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
        layout.addWidget(scroll_area)
        
        self.setMinimumSize(300, 200)
        self.setMaximumSize(400, 600)  # 增加最大高度
    
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
        
        top_layout.addStretch()  # 添加弹性空间，使标签靠左对齐
        
        # 创建堆叠式窗口部件
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)
        
        # 创建历史记录列表
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        self.history_list.keyPressEvent = self.list_key_press
        self.stacked_widget.addWidget(self.history_list)
        
        # 创建收藏列表
        self.favorites_list = QListWidget()
        self.favorites_list.keyPressEvent = self.list_key_press
        self.favorites_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)  # 启用内部拖拽
        self.favorites_list.setDefaultDropAction(Qt.DropAction.MoveAction)  # 设置默认拖拽动作为移动
        self.favorites_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)  # 单选模式
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
        
        
        
        # 创建预览窗口
        self.preview_window = PreviewWindow()
        
        # 为两个列表添加选择变化事件
        self.history_list.currentItemChanged.connect(self.show_preview)
        self.favorites_list.currentItemChanged.connect(self.show_preview)
        
        # 设置列表项为单行显示
        self.history_list.setWordWrap(False)  # 禁用自动换行
        self.favorites_list.setWordWrap(False)  # 禁用自动换行
        
        # 设置固定行高
        self.history_list.setStyleSheet("QListWidget::item { height: 25px; }")
        self.favorites_list.setStyleSheet("QListWidget::item { height: 25px; }")
        
        # 修改列表项的显示格式
        self.history_list.setStyleSheet("""
            QListWidget::item { 
                height: 25px;
                padding-left: 5px;
            }
        """)
        self.favorites_list.setStyleSheet("""
            QListWidget::item { 
                height: 25px;
                padding-left: 5px;
            }
        """)

        # 添加删除历史记录
        self.delete_history = []

    def check_clipboard(self):
        current_text = self.clipboard.text()
        if current_text != self.last_text:
            self.on_clipboard_change()
            self.last_text = current_text

    def on_clipboard_change(self):
        text = self.clipboard.text()
        if text:
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
            self.history_list.insertItem(0, truncated_text)
            
            # 如果历史记录超过10个，删除多余的条目
            while len(self.clipboard_history) > 10:
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
        
        # 添加分隔线
        tray_menu.addSeparator()
        
        # 添加版本信息（禁用点击）
        version_action = tray_menu.addAction("版本: 2025/3/4-01")
        version_action.setEnabled(False)  # 设置为不可点击
        
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
        self.preview_window.close()
        super().closeEvent(event)

    def list_key_press(self, event: QKeyEvent):
        """处理列表的按键事件"""
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
            add_to_favorites = menu.addAction("添加到收藏(&A)")  # Alt+A
            delete_action = menu.addAction("删除(&D)")  # Alt+D
            
            action = menu.exec(self.history_list.mapToGlobal(position))
            
            if action == add_to_favorites:
                print("选择了加到收藏选项")  # 调试信息
                self.add_to_favorites(original_text)
            elif action == edit_action:
                print("选择了编辑选项")  # 调试信息
                self.edit_history_item(self.history_list.currentRow())
            elif action == delete_action:
                print("选择了删除选项")  # 调试信息
                self.delete_history_item()

    def add_to_favorites(self, text):
        """添加文本到当前收藏夹"""
        # 创建新的收藏项
        new_item = {
            "text": text,
            "description": ""
        }
        
        # 检查是否已存在
        existing_texts = [item["text"] for item in self.favorites[self.current_folder]]
        if text not in existing_texts:
            self.favorites[self.current_folder].insert(0, new_item)
            truncated_text = self.truncate_text(text)
            self.favorites_list.insertItem(0, truncated_text)
            self.update_list_numbers(self.favorites_list)
            self.save_favorites()

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
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
            print(f"收藏已保存到: {self.favorites_file}")  # 调试信息
        except Exception as e:
            print(f"保存收藏记录时出错: {e}")  # 调试信息

    def truncate_text(self, text, max_length=50):
        """截断文本，保留定长度添加省略号"""
        # 移除文本中的换行符
        text = text.replace('\n', ' ').replace('\r', '')
        
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def show_preview(self, current, previous):
        """显示选中条目的完整内容"""
        if not current:
            self.preview_window.hide()
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
                if '\n' in original_text or len(original_text) > 50 or description:
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
                else:
                    self.preview_window.hide()
        except Exception as e:
            print(f"预览显示错误: {e}")
            self.preview_window.hide()

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
            if '. ' in text:
                text = text.split('. ', 1)[1]
            # 添加新编号
            item.setText(f"{i+1}. {text}")

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
            
            move_menu = menu.addMenu("移动到收藏夹(&V)")  # Alt+V
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
                    self.move_to_folder(favorite_item, action.text())

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

    def move_to_folder(self, item, target_folder):
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
        # 重新初始化热键线程
        try:
            self.hotkey_thread.stop()
            self.hotkey_thread.wait(1000)  # 等待最多1秒
            
            # 如果线程仍在运行，强制终止
            if self.hotkey_thread.isRunning():
                print("强制终止热键线程")
                self.hotkey_thread.terminate()
                self.hotkey_thread.wait()
        except Exception as e:
            print(f"停止热键线程时出错: {e}")
        
        # 创建新的热键线程
        self.hotkey_thread = HotkeyThread(self.config.get('hotkey', 'ctrl+alt+z'))
        self.hotkey_thread.triggered.connect(self.show_window)
        self.hotkey_thread.error.connect(self.handle_hotkey_error)
        self.hotkey_thread.start()
        
        # 显示通知
        self.tray_icon.showMessage("热键已重置", f"快捷键 {self.config.get('hotkey', 'ctrl+alt+z')} 已重新注册", QSystemTrayIcon.MessageIcon.Information, 3000)

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
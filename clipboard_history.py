from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget, 
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu,
                           QHBoxLayout, QStackedWidget, QLabel, QTextEdit, QDialog, QLineEdit, QMessageBox, QComboBox, QInputDialog)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QClipboard, QIcon, QKeyEvent
import sys
import json
import os
import keyboard

# 修改热键线程的实现
class HotkeyThread(QThread):
    triggered = pyqtSignal()

    def __init__(self, hotkey='ctrl+alt+z'):
        super().__init__()
        self.running = True
        self.hotkey = hotkey
        self.current_hotkey = None
        
    def run(self):
        try:
            # 使用 keyboard 库注册热键组合
            self.current_hotkey = keyboard.add_hotkey(self.hotkey, self.on_hotkey)
            print(f"热键已注册: {self.hotkey}")
            
            while self.running:
                self.msleep(100)
                
        except Exception as e:
            print(f"热键注册错误: {e}")

    def on_hotkey(self):
        print("热键被触发")
        self.triggered.emit()

    def stop(self):
        self.running = False
        try:
            if self.current_hotkey:
                keyboard.remove_hotkey(self.current_hotkey)
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
                padding: 5px;  /* 添加内边距 */
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)  # 增加边距
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        
        self.setMinimumSize(300, 200)
        self.setMaximumSize(400, 300)

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
        self.setGeometry(100, 100, 400, 300)
        
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
        
        # 修改快捷键提示为 Alt+F
        folder_layout = QHBoxLayout()
        folder_hint = QLabel("(Alt+F)")
        folder_hint.setStyleSheet("color: gray;")  # 使提示文字颜色变淡
        folder_layout.addWidget(self.folder_combo)
        folder_layout.addWidget(folder_hint)
        top_layout.addLayout(folder_layout)
        
        # 存储收藏夹数据
        self.favorites_file = os.path.join(os.path.expanduser('~'), '.clipboard_favorites.json')
        
        # 加载收藏记录
        self.load_favorites()
        
        # 存储剪贴板历史
        self.clipboard_history = []
        
        # 获取系���剪贴板
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
        
        # 为列表控件添加 ESC 键支持
        self.history_list.keyPressEvent = self.list_key_press
        
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

    def check_clipboard(self):
        current_text = self.clipboard.text()
        if current_text != self.last_text:
            self.on_clipboard_change()
            self.last_text = current_text

    def on_clipboard_change(self):
        text = self.clipboard.text()
        if text and text not in self.clipboard_history:
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
                            else self.favorites)[current_list.currentRow()]
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
        
        # 添加退出动作
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(QApplication.quit)
        
        # 添加设置选项
        settings_action = tray_menu.addAction("设置")
        settings_action.triggered.connect(self.show_settings)
        
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
        elif event.key() == Qt.Key.Key_Delete and self.stacked_widget.currentIndex() == 1:
            self.delete_favorite()
        # 修改为 Alt+F 快捷键
        elif (event.modifiers() == Qt.KeyboardModifier.AltModifier and 
              event.key() == Qt.Key.Key_F and 
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
            item = self.favorites_list.takeItem(current_row)
            self.favorites_list.insertItem(new_row, item)
            self.favorites_list.setCurrentRow(new_row)
            
            item = self.favorites.pop(current_row)
            self.favorites.insert(new_row, item)
            
            # 更新编号
            self.update_list_numbers(self.favorites_list)
            self.save_favorites()

    def delete_favorite(self):
        """删除选中的收藏项"""
        current_row = self.favorites_list.currentRow()
        if current_row >= 0:  # 确保有选中的项目
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

    def paste_selected(self):
        """复制选中项并模拟粘贴操作"""
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_item = current_list.currentItem()
        if current_item:
            # 使用原始文本而不是截断的文本
            current_row = current_list.currentRow()
            original_text = (self.clipboard_history if self.stacked_widget.currentIndex() == 0 
                           else self.favorites[self.current_folder])[current_row]
            
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
        # 确保窗口显示在屏幕中央
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2
        )
        
        # 显示时默认显示历史记录面板
        self.stacked_widget.setCurrentIndex(0)
        self.panel_label.setText("历史记录")
        
        # 临时设置置顶标志
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        
        self.show()
        self.raise_()
        self.activateWindow()
        self.history_list.setFocus()

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
            add_to_favorites = menu.addAction("添加到收藏")
            action = menu.exec(self.history_list.mapToGlobal(position))
            
            if action == add_to_favorites:
                print("选择了加到收藏选项")  # 调试信息
                self.add_to_favorites(original_text)

    def add_to_favorites(self, text):
        """添加文本到当前收藏夹"""
        if text not in self.favorites[self.current_folder]:
            self.favorites[self.current_folder].insert(0, text)
            truncated_text = self.truncate_text(text)
            self.favorites_list.insertItem(0, truncated_text)
            # 更新编号
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
                            "默认收藏夹": data
                        }
                    # 新格式数据（字典格式）
                    elif isinstance(data, dict):
                        self.favorites = data
                    
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
                    for text in self.favorites[self.current_folder]:
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
        
        # 获取原始文本
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_row = current_list.currentRow()
        
        # 根据当前面板选择正确的数据源
        if self.stacked_widget.currentIndex() == 0:
            data_list = self.clipboard_history
        else:
            data_list = self.favorites[self.current_folder]  # 使用当前收藏夹的数据
        
        if 0 <= current_row < len(data_list):
            original_text = data_list[current_row]
            
            # 如果文本包含换行符或长度超过截断长度，才显示预览窗口
            if '\n' in original_text or len(original_text) > 50:
                self.preview_window.text_edit.setText(original_text)
                
                # 计算预览窗口位置
                list_widget = current_list
                item_rect = list_widget.visualItemRect(current)
                global_pos = list_widget.mapToGlobal(item_rect.topRight())
                
                # 调整位置，确保预览窗口在屏幕内
                screen = QApplication.primaryScreen().geometry()
                preview_x = global_pos.x() + 10  # 在列表右侧显示，留出10像素间距
                preview_y = global_pos.y()
                
                # 如果预览窗口超出屏幕右边界，则显示在列表左侧
                if preview_x + self.preview_window.width() > screen.right():
                    preview_x = global_pos.x() - self.preview_window.width() - 10
                
                # 如果预览窗口超出屏幕底部，则向上调整位���
                if preview_y + self.preview_window.height() > screen.bottom():
                    preview_y = screen.bottom() - self.preview_window.height()
                
                self.preview_window.move(preview_x, preview_y)
                self.preview_window.show()
            else:
                self.preview_window.hide()
        else:
            print(f"索引越界: {current_row} >= {len(data_list)}")  # 调试信息
            self.preview_window.hide()

    def hide(self):
        """写hide方法，同时隐藏预览窗口"""
        super().hide()
        self.preview_window.hide()

    def on_favorites_reordered(self, parent, start, end, destination, row):
        """处理收藏列表重排"""
        # 获取移动的项目
        moved_item = self.favorites[start]
        # 从原位置删除
        self.favorites.pop(start)
        # 插入到新位置
        new_position = row if row < start else row - 1
        self.favorites.insert(new_position, moved_item)
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
            # 获取原始文本
            current_row = self.favorites_list.currentRow()
            original_text = self.favorites[self.current_folder][current_row]
            
            # 添加编辑选项
            edit_action = menu.addAction("编辑")
            
            # 新建收藏夹选项
            new_folder = menu.addAction("新建收藏夹...")
            
            # 移动到收藏夹子菜单
            move_menu = menu.addMenu("移动到收藏夹")
            for folder in self.favorites.keys():
                if folder != self.current_folder:  # 不显示当前收藏夹
                    move_menu.addAction(folder)
            
            # 删除选项
            delete_action = menu.addAction("删除")
            
            action = menu.exec(self.favorites_list.mapToGlobal(position))
            
            if action:
                if action == edit_action:
                    self.edit_favorite_item(current_row)
                elif action == new_folder:
                    self.create_new_folder(original_text)
                elif action == delete_action:
                    self.delete_favorite()
                elif action.text() in self.favorites:  # 移动到其他收藏夹
                    self.move_to_folder(original_text, action.text())

    def create_new_folder(self, item_text):
        """创建新收藏夹并移动选中项"""
        folder_name, ok = QInputDialog.getText(self, "创建收藏夹", "请输入收藏夹名称:")
        if ok and folder_name:
            if folder_name not in self.favorites:
                self.favorites[folder_name] = [item_text]
                self.folder_combo.addItem(folder_name)
                
                # 从当前收藏夹移除
                current_row = self.favorites_list.currentRow()
                self.favorites[self.current_folder].pop(current_row)
                self.favorites_list.takeItem(current_row)
                
                self.save_favorites()
                self.update_list_numbers(self.favorites_list)
            else:
                QMessageBox.warning(self, "错误", "收藏夹名称已存在!")

    def move_to_folder(self, item_text, target_folder):
        """移动条目到指定收藏夹"""
        if target_folder in self.favorites:
            # 添加到目标收藏夹
            self.favorites[target_folder].append(item_text)
            
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
            for text in self.favorites[folder_name]:
                truncated_text = self.truncate_text(text)
                self.favorites_list.addItem(truncated_text)
            self.update_list_numbers(self.favorites_list)

    def edit_favorite_item(self, row):
        """编辑收藏条目"""
        if 0 <= row < len(self.favorites[self.current_folder]):
            original_text = self.favorites[self.current_folder][row]
            dialog = EditItemDialog(self, original_text)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_text = dialog.get_text()
                if new_text and new_text != original_text:
                    # 更新收藏夹中的文本
                    self.favorites[self.current_folder][row] = new_text
                    # 更新显示的文本
                    truncated_text = self.truncate_text(new_text)
                    self.favorites_list.item(row).setText(f"{row+1}. {truncated_text}")
                    # 保存更改
                    self.save_favorites()

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
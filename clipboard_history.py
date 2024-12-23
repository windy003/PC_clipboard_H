from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget, 
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu,
                           QHBoxLayout, QStackedWidget, QLabel, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QClipboard, QIcon, QKeyEvent
import sys
import json
import os
import keyboard

# 修改热键线程的实现
class HotkeyThread(QThread):
    triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        try:
            # 确保之前的热键被清除
            keyboard.unhook_all()
            # 直接使用 keyboard.wait 方式
            keyboard.add_hotkey('ctrl+alt+z', self.on_hotkey, suppress=True)
            print("热键已注册: Ctrl+Alt+Z")  # 调试信息
            
            # 保持线程运行
            while self.running:
                self.msleep(100)
                
        except Exception as e:
            print(f"热键注册错误: {e}")  # 调试信息

    def on_hotkey(self):
        print("热键被触��")  # 调试信息
        self.triggered.emit()

    def stop(self):
        self.running = False
        keyboard.unhook_all()
        print("热键已清理")  # 调试信息

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
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        
        self.setMinimumSize(300, 200)
        self.setMaximumSize(400, 300)

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
        self.stacked_widget.addWidget(self.favorites_list)
        
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
        
        # 存储收藏夹数据
        self.favorites = []
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
        
        # 创建系统托盘图标
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
        
        # 创建并启动热键线程
        self.hotkey_thread = HotkeyThread()
        self.hotkey_thread.triggered.connect(self.show_window)
        self.hotkey_thread.start()
        
        # 为列表控件添加 ESC 键支持
        self.history_list.keyPressEvent = self.list_key_press
        
        # 创建预览窗口
        self.preview_window = PreviewWindow()
        
        # 为两个列表添加选择变化事件
        self.history_list.currentItemChanged.connect(self.show_preview)
        self.favorites_list.currentItemChanged.connect(self.show_preview)

    def check_clipboard(self):
        current_text = self.clipboard.text()
        if current_text != self.last_text:
            self.on_clipboard_change()
            self.last_text = current_text

    def on_clipboard_change(self):
        text = self.clipboard.text()
        if text and text not in self.clipboard_history:
            self.clipboard_history.insert(0, text)
            # 显示截断后的文本
            truncated_text = self.truncate_text(text)
            self.history_list.insertItem(0, truncated_text)
            # 每次更新后保存历史记录
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
        # 清空后也保存状态
        self.save_history()

    def load_history(self):
        """从文件加载历史记录"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.clipboard_history = json.load(f)
                    # 将历史记录显示到列表中，使用截断的文本
                    self.history_list.clear()  # 清空列表
                    for text in self.clipboard_history:
                        truncated_text = self.truncate_text(text)
                        self.history_list.addItem(truncated_text)  # 使用 addItem 而不是 insertItem
        except Exception as e:
            print(f"加载历史记录时出错: {e}")
            self.clipboard_history = []

    def save_history(self):
        """保存历史记录到文件"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.clipboard_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史记录时出���: {e}")

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
        elif event.key() == Qt.Key.Key_Left and self.stacked_widget.currentIndex() == 1:
            # 切换到历史记录面板
            self.stacked_widget.setCurrentIndex(0)
            self.panel_label.setText("历史记录")
            self.history_list.setFocus()
        elif event.key() == Qt.Key.Key_Delete and self.stacked_widget.currentIndex() == 1:
            # 在收藏面板中删除选中项
            self.delete_favorite()
        else:
            # 保持其他按键的默认行为
            QListWidget.keyPressEvent(self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list, event)

    def delete_favorite(self):
        """删除选中的收藏条目"""
        current_row = self.favorites_list.currentRow()
        if current_row >= 0:
            # 从列表控件中移除
            self.favorites_list.takeItem(current_row)
            # 从数据列表中移除
            self.favorites.pop(current_row)
            # 保存更改
            self.save_favorites()

    def paste_selected(self):
        """复制选中项并模拟粘贴操作"""
        current_list = self.history_list if self.stacked_widget.currentIndex() == 0 else self.favorites_list
        current_item = current_list.currentItem()
        if current_item:
            # 使用原始文本而不是截断的文本
            original_text = (self.clipboard_history if self.stacked_widget.currentIndex() == 0 
                            else self.favorites)[current_list.currentRow()]
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
            print(f"当前选中项: {original_text}")  # 调试信息
            add_to_favorites = menu.addAction("添加到收藏")
            action = menu.exec(self.history_list.mapToGlobal(position))
            
            if action == add_to_favorites:
                print("选择了添加到收藏选项")  # 调试信息
                self.add_to_favorites(original_text)

    def add_to_favorites(self, text):
        """添加文本到收藏夹"""
        print(f"尝试添加到收藏: {text}")  # 调试信息
        if text not in self.favorites:
            print("添加新收藏项")  # 调试信息
            # 在列表开头插入新项目
            self.favorites.insert(0, text)
            # 在收藏列表控件的顶部插入截断的文本
            truncated_text = self.truncate_text(text)
            self.favorites_list.insertItem(0, truncated_text)
            self.save_favorites()
        else:
            print("该项目已在收藏中")  # 调试信息

    def load_favorites(self):
        """从文件加载收藏记录"""
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    self.favorites = json.load(f)
                    # 清空列表并重新加载
                    self.favorites_list.clear()
                    for text in self.favorites:
                        truncated_text = self.truncate_text(text)
                        self.favorites_list.addItem(truncated_text)  # 使用 addItem
        except Exception as e:
            print(f"加载收藏记录时出错: {e}")
            self.favorites = []

    def save_favorites(self):
        """保存收藏记录到文件"""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
            print(f"收藏已保存到: {self.favorites_file}")  # 调试信息
        except Exception as e:
            print(f"保存收藏记录时出错: {e}")  # 调试信息

    def truncate_text(self, text, max_length=50):
        """截断文本，保留指定长度，添加省略号"""
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
        data_list = self.clipboard_history if self.stacked_widget.currentIndex() == 0 else self.favorites
        
        print(f"当前行号: {current_row}")  # 调试信息
        print(f"当前面板: {'历史记录' if self.stacked_widget.currentIndex() == 0 else '收藏夹'}")  # 调试信息
        print(f"列表项文本: {current.text()}")  # 调试信息
        
        if 0 <= current_row < len(data_list):
            original_text = data_list[current_row]
            print(f"原始文本: {original_text}")  # 调试信息
            
            # 如果文本长度超过截断长度，才显示预览窗口
            if len(original_text) > 50:  # 根据 truncate_text 的 max_length 参数调整
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
                
                # 如果预览窗口超出屏幕底部，则向上调���位置
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
        """重写hide方法，同时隐藏预览窗口"""
        super().hide()
        self.preview_window.hide()

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
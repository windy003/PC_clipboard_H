from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget, 
                           QVBoxLayout, QPushButton, QWidget, QSystemTrayIcon, QMenu)
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
        print("热键被触发")  # 调试信息
        self.triggered.emit()

    def stop(self):
        self.running = False
        keyboard.unhook_all()
        print("热键已清理")  # 调试信息

class ClipboardHistoryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("剪贴板历史")
        self.setGeometry(100, 100, 400, 300)
        
        # 创建主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建列表控件来显示剪贴板历史
        self.history_list = QListWidget()
        layout.addWidget(self.history_list)
        
        # 创建"复制选中项"按钮
        copy_button = QPushButton("复制选中项")
        copy_button.clicked.connect(self.copy_selected)
        layout.addWidget(copy_button)
        
        # 清空历史按钮
        clear_button = QPushButton("清空历史")
        clear_button.clicked.connect(self.clear_history)
        layout.addWidget(clear_button)
        
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

    def check_clipboard(self):
        current_text = self.clipboard.text()
        if current_text != self.last_text:
            self.on_clipboard_change()
            self.last_text = current_text

    def on_clipboard_change(self):
        text = self.clipboard.text()
        if text and text not in self.clipboard_history:
            self.clipboard_history.insert(0, text)
            self.history_list.insertItem(0, text)
            # 每次更新后保存历史记录
            self.save_history()

    def copy_selected(self):
        current_item = self.history_list.currentItem()
        if current_item:
            self.clipboard.setText(current_item.text())

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
                    # 将历史记录显示到列表中
                    for text in self.clipboard_history:
                        self.history_list.insertItem(0, text)
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
        
        # 使用项目目录下的图标文件
        icon_path = os.path.join(os.path.dirname(__file__), "icon.ico")
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
        """重写关闭事件，阻止窗口关闭"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "剪贴板历史",
            "按下 Ctrl+Alt+Z 可以重新打开窗口",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def list_key_press(self, event: QKeyEvent):
        """处理列表的按键事件"""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.paste_selected()
        elif event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            # 保持其他按键的默认行为
            QListWidget.keyPressEvent(self.history_list, event)

    def paste_selected(self):
        """复制选中项并模拟粘贴操作"""
        current_item = self.history_list.currentItem()
        if current_item:
            # 复制选中的文本到剪贴板
            self.clipboard.setText(current_item.text())
            
            # ��藏窗口
            self.hide()
            
            # 短暂延迟后模拟 Ctrl+V 按键
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

def main():
    app = QApplication(sys.argv)
    window = ClipboardHistoryApp()
    window.hide()  # 初始隐藏窗口
    
    # 阻止 Python 解释器退出
    app.setQuitOnLastWindowClosed(False)
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 
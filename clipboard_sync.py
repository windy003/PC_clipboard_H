import subprocess
import os
import logging
import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# 配置日志
log_dir = os.path.join(os.path.expanduser("~"), ".clipboard_sync", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"clipboard_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# 源文件路径
source_path = os.path.join(os.path.expanduser("~"), ".clipboard_favorites.json")

    
# 目标路径
destination_path = 'gdrive:/sync/x13y/pc_clipboard_sync/'

def sync_clipboard_to_gdrive():
    """
    使用rclone将剪贴板收藏夹文件同步到Google Drive
    """
    # 检查源文件是否存在
    if not os.path.exists(source_path):
        logging.error(f"源文件不存在: {source_path}")
        return False
    
    # 构建rclone命令
    rclone_command = [
        'rclone', 
        'sync', 
        source_path, 
        destination_path,
        '--progress'  # 显示进度
    ]
    
    try:
        # 执行命令
        logging.info(f"开始同步: {source_path} -> {destination_path}")
        process = subprocess.run(
            rclone_command, 
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW  # 添加这行来隐藏控制台窗口
        )
        
        # 记录输出
        logging.info(f"同步成功完成")
        logging.debug(f"命令输出: {process.stdout}")
        return True
        
    except subprocess.CalledProcessError as e:
        # 处理错误
        logging.error(f"同步失败: {e}")
        logging.error(f"错误输出: {e.stderr}")
        return False

class ClipboardFileHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_sync_time = 0
        self.sync_cooldown = 2  # 2秒冷却时间，防止重复触发
    
    def on_modified(self, event):
        # 检查是否是我们要监控的文件
        if not event.is_directory and os.path.abspath(event.src_path) == os.path.abspath(source_path):
            # 防抖处理：避免短时间内多次触发
            current_time = time.time()
            if current_time - self.last_sync_time < self.sync_cooldown:
                return
            
            self.last_sync_time = current_time
            logging.info(f"检测到文件变化: {source_path}")
            start_time = datetime.now()
            result = sync_clipboard_to_gdrive()
            end_time = datetime.now()
            duration = end_time - start_time
            
            if result:
                logging.info(f"同步任务完成，耗时: {duration}")
            else:
                logging.error(f"同步任务失败，耗时: {duration}")

def watch_file():
    # 创建观察者
    observer = Observer()
    event_handler = ClipboardFileHandler()
    
    # 监控文件所在的目录（而不是文件本身）
    watch_directory = os.path.dirname(source_path)
    observer.schedule(event_handler, watch_directory, recursive=False)
    
    # 启动观察者
    observer.start()
    logging.info(f"开始监控文件: {source_path}")
    logging.info(f"监控目录: {watch_directory}")
    
    try:
        # 保持程序运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("监控停止")
    
    observer.join()

if __name__ == "__main__":
    logging.info(f"===== 启动自动同步服务 =====")
    
    # 先进行一次初始同步
    sync_clipboard_to_gdrive()
    
    # 开始监控文件变化
    watch_file()
    
    logging.info(f"===== 同步服务结束 =====\n")
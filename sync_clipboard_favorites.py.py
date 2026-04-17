import os
import shutil
import logging
import time
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, '.env'))

SOURCE_FILE = os.path.join(SCRIPT_DIR, '.clipboard_favorites.json')
SOURCE_NAME = '.clipboard_favorites.json'
DEST_DIR = os.environ['SYNC_FAVORITES_DIR']
DEST_FILE = os.path.join(DEST_DIR, SOURCE_NAME)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class FavoritesHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        if os.path.basename(event.src_path) == SOURCE_NAME:
            try:
                shutil.copy2(SOURCE_FILE, DEST_FILE)
                logging.info(f"已同步到 {DEST_FILE}")
            except Exception as e:
                logging.error(f"同步失败: {e}")

if __name__ == '__main__':
    os.makedirs(DEST_DIR, exist_ok=True)
    observer = Observer()
    observer.schedule(FavoritesHandler(), SCRIPT_DIR, recursive=False)
    observer.start()
    logging.info(f"开始监控: {SOURCE_FILE}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

import os
import logging
import queue
import threading
import time
from colorama import init, Fore, Style
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

from config import SOURCE_DIR, DEST_BASE_DIR, DELETE_SOURCE_FILES, PROCESS_DELAY
from utils import wait_for_stability
from processor import process_bundle, process_single_file

# --- CUSTOM LOGGING FORMATTER FOR COLORED OUTPUT ---
class ColoredFormatter(logging.Formatter):
    """A custom logging formatter to add colors to log messages."""
    LOG_COLORS = {
        logging.DEBUG: Style.DIM + Fore.WHITE,
        logging.INFO: Fore.WHITE,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        """Applies color to the log message."""
        color = self.LOG_COLORS.get(record.levelno)
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}" if color else message

# --- DIRECTORY WATCHER AND QUEUE MANAGER ---
class ChangeHandler(FileSystemEventHandler):
    """
    A Watchdog event handler that debounces events and adds items (files or bundles)
    to a processing queue.
    """
    def __init__(self, processing_queue):
        super().__init__()
        self.queue = processing_queue
        self.timers = {}
        self.lock = threading.Lock()

    def on_any_event(self, event):
        """Called for any file system event in the watched directory."""
        if event.is_directory or not os.path.exists(event.src_path): return
        try:
            relative_path = os.path.relpath(event.src_path, SOURCE_DIR)
            if relative_path.startswith('..'): return

            if os.path.sep in relative_path:
                bundle_name = relative_path.split(os.path.sep)[0]
                item_path = os.path.join(SOURCE_DIR, bundle_name)
            else:
                item_path = event.src_path

            with self.lock:
                if item_path in self.timers: self.timers[item_path].cancel()
                timer = threading.Timer(PROCESS_DELAY, self.queue_item, [item_path])
                self.timers[item_path] = timer
                timer.start()
        except Exception:
            pass

    def queue_item(self, item_path):
        """Called by a timer to add an item to the processing queue."""
        with self.lock:
            if os.path.exists(item_path) and item_path not in list(self.queue.queue):
                logging.info(Fore.CYAN + f"Queueing item for processing: {os.path.basename(item_path)}")
                self.queue.put(item_path)
            self.timers.pop(item_path, None)

def worker(processing_queue):
    """
    The worker thread function that pulls items from the queue, confirms
    their stability, and then processes them.
    """
    while True:
        item_path = processing_queue.get()
        if item_path is None: break
        try:
            if wait_for_stability(item_path):
                if os.path.isdir(item_path):
                    process_bundle(item_path)
                elif os.path.isfile(item_path):
                    process_single_file(item_path)
            else:
                logging.error(f"Skipping '{os.path.basename(item_path)}' due to stability check timeout.")
        except Exception as e:
            logging.error(f"CRITICAL: Unhandled exception processing '{os.path.basename(item_path)}'.", exc_info=True)
        finally:
            processing_queue.task_done()

def main():
    """Main function to set up logging, the watcher, and the processing queue."""
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.INFO)

    logging.info(f"Starting Orzy Media Watcher (v1.0.0)")
    logging.info(f"Source Directory: {SOURCE_DIR}")
    if DELETE_SOURCE_FILES: logging.warning("DELETE_SOURCE_FILES is enabled.")

    if not os.path.isdir(SOURCE_DIR): os.makedirs(SOURCE_DIR)
    if not os.path.isdir(DEST_BASE_DIR): os.makedirs(DEST_BASE_DIR)

    processing_queue = queue.Queue()
    worker_thread = threading.Thread(target=worker, args=(processing_queue,))
    worker_thread.daemon = True
    worker_thread.start()

    event_handler = ChangeHandler(processing_queue)
    observer = Observer()
    observer.schedule(event_handler, SOURCE_DIR, recursive=True)
    observer.start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        observer.stop()
        processing_queue.put(None)

    observer.join()
    worker_thread.join()
    logging.info("Shutdown complete.")

if __name__ == "__main__":
    main()

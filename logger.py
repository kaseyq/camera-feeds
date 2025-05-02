import logging
import uuid
import os
import queue
from datetime import datetime

class Logger:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.logger = logging.getLogger(f"logger_{uuid.uuid4()}")
        self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        # Ensure logs directory exists
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(log_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)

        # Rename existing log.txt to log_prev.txt if it exists
        self.log_file_path = os.path.join(log_dir, "log.txt")
        prev_log_file_path = os.path.join(log_dir, "log_prev.txt")
        if os.path.exists(self.log_file_path):
            if os.path.exists(prev_log_file_path):
                os.remove(prev_log_file_path)  # Remove previous backup
            os.rename(self.log_file_path, prev_log_file_path)

        # File handler for logging to file
        file_handler = logging.FileHandler(self.log_file_path, mode='w')  # Use 'w' to overwrite
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_formatter = logging.Formatter('%(asctime)s,%(msecs)03d %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def log(self, message, level=logging.INFO):
        if level == logging.INFO:
            self.logger.info(message)
        elif level == logging.ERROR:
            self.logger.error(message)
        elif level == logging.DEBUG:
            self.logger.debug(message)

    def log_to_file(self, message, level=logging.INFO):
        self.log(message, level)

    def log_stderr(self, stderr_queue):
        try:
            while True:
                message = stderr_queue.get_nowait()
                self.log(message, level=logging.ERROR)
        except queue.Empty:
            pass
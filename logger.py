import os
import time
import datetime

class Logger:
    def __init__(self, log_dir="logs", log_file_prefix="log"):
        self.log_dir = log_dir
        self.log_file_prefix = log_file_prefix
        self.log_file = None
        self._ensure_log_directory()
        self._open_log_file()

    def _ensure_log_directory(self):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

    def _open_log_file(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{self.log_file_prefix}_{timestamp}.txt"
        log_path = os.path.join(self.log_dir, log_filename)
        self.log_file = open(log_path, "a", buffering=1)  # Line buffering

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        log_line = f"{timestamp} {message}\n"
        print(log_line, end="")
        if self.log_file:
            self.log_file.write(log_line)
            self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None


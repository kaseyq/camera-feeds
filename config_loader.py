import json
import sys

class ConfigLoader:
    def __init__(self, system_config_path="system_config.json", camera_config_path="camera_config.json"):
        self.system_config_path = system_config_path
        self.camera_config_path = camera_config_path
        self.system_config = None
        self.camera_config = None

    def load_config(self):
        try:
            with open(self.system_config_path, "r") as f:
                self.system_config = json.load(f)
        except Exception as e:
            print(f"Error loading system_config.json: {e}")
            sys.exit(1)

        try:
            with open(self.camera_config_path, "r") as f:
                self.camera_config = json.load(f)
        except Exception as e:
            print(f"Error loading camera_config.json: {e}")
            sys.exit(1)

        return self.system_config


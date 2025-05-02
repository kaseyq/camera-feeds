import json
import os
import sys

class ConfigLoader:
    def __init__(self, camera_config_path="camera_config.json", system_config_path="system_config.json"):
        self.camera_config_path = camera_config_path
        self.system_config_path = system_config_path
        self.config = {}

    def load_config(self):
        # Load camera_config.json
        if not os.path.exists(self.camera_config_path):
            self._create_default_camera_config()
        try:
            with open(self.camera_config_path, "r") as config_file:
                camera_config = json.load(config_file)
        except FileNotFoundError:
            print(f"Error: camera_config.json not found at {self.camera_config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in camera_config.json: {e}")
            sys.exit(1)

        # Load system_config.json
        if not os.path.exists(self.system_config_path):
            self._create_default_system_config()
        try:
            with open(self.system_config_path, "r") as config_file:
                system_config = json.load(config_file)
        except FileNotFoundError:
            print(f"Error: system_config.json not found at {self.system_config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in system_config.json: {e}")
            sys.exit(1)

        # Merge configs
        self.config = camera_config
        self.config.update(system_config)

        self._validate_config()
        return self.config

    def _create_default_camera_config(self):
        default_config = {
            "starting_position": "top-left",
            "grid_cols": 2,
            "grid_rows": 1,
            "window_width": 640,
            "window_height": 390,
            "toolbar_height_adjustment": 37,
            "width_offset": 4,
            "x_spacing": 2,
            "y_spacing": 70,
            "cameras": [
                {
                    "camera_num": 1,
                    "stream_url": "rtsp://user:pass@placeholder:554/cam1",
                    "features": {
                        "basic_motion_detection": {
                            "enabled": False,  # Changed to False to isolate overlay issues
                            "sensitivity": 50,
                            "outline_enabled": False,
                            "outline_color": "#FF0000",
                            "outline_weight": 1
                        }
                    }
                },
                {
                    "camera_num": 2,
                    "stream_url": "http://placeholder:80/cam2.m3u8",
                    "features": {
                        "basic_motion_detection": {
                            "enabled": False,  # Changed to False to isolate overlay issues
                            "sensitivity": 50,
                            "outline_enabled": False,
                            "outline_color": "#FF0000",
                            "outline_weight": 1
                        }
                    }
                }
            ]
        }
        with open(self.camera_config_path, "w") as config_file:
            json.dump(default_config, config_file, indent=2)
        print(f"Created default camera_config.json at {self.camera_config_path}")

    def _create_default_system_config(self):
        default_config = {
            "camera_management": {
                "restart_delay_seconds": 120
            },
            "motion_detection": {
                "motion_frame_skip": 5,
                "motion_downsample_factor": 2,
                "outline_persistence_seconds": 1
            }
        }
        with open(self.system_config_path, "w") as config_file:
            json.dump(default_config, config_file, indent=2)
        print(f"Created default system_config.json at {self.system_config_path}")

    def _validate_config(self):
        # Validate camera_config.json
        if "starting_position" not in self.config:
            print("Error: 'starting_position' missing in camera_config.json")
            sys.exit(1)
        starting_position = self.config["starting_position"]
        valid_positions = ["top-left", "top-right", "bottom-right", "bottom-left"]
        if starting_position not in valid_positions:
            print(f"Error: Invalid starting_position '{starting_position}'; must be one of {valid_positions}")
            sys.exit(1)

        if "grid_cols" not in self.config:
            print("Error: 'grid_cols' missing in camera_config.json")
            sys.exit(1)
        if "grid_rows" not in self.config:
            print("Error: 'grid_rows' missing in camera_config.json")
            sys.exit(1)
        grid_cols = self.config["grid_cols"]
        grid_rows = self.config["grid_rows"]
        if not isinstance(grid_cols, int) or grid_cols < 1:
            print(f"Error: grid_cols must be a positive integer, got {grid_cols}")
            sys.exit(1)
        if not isinstance(grid_rows, int) or grid_rows < 1:
            print(f"Error: grid_rows must be a positive integer, got {grid_rows}")
            sys.exit(1)

        if "window_width" not in self.config:
            print("Error: 'window_width' missing in camera_config.json")
            sys.exit(1)
        if "window_height" not in self.config:
            print("Error: 'window_height' missing in camera_config.json")
            sys.exit(1)
        window_width = self.config["window_width"]
        window_height = self.config["window_height"]
        if not isinstance(window_width, int) or window_width < 1:
            print(f"Error: window_width must be a positive integer, got {window_width}")
            sys.exit(1)
        if not isinstance(window_height, int) or window_height < 1:
            print(f"Error: window_height must be a positive integer, got {window_height}")
            sys.exit(1)

        if "toolbar_height_adjustment" not in self.config:
            print("Error: 'toolbar_height_adjustment' missing in camera_config.json")
            sys.exit(1)
        if "width_offset" not in self.config:
            print("Error: 'width_offset' missing in camera_config.json")
            sys.exit(1)
        if "x_spacing" not in self.config:
            print("Error: 'x_spacing' missing in camera_config.json")
            sys.exit(1)
        if "y_spacing" not in self.config:
            print("Error: 'y_spacing' missing in camera_config.json")
            sys.exit(1)
        toolbar_height_adjustment = self.config["toolbar_height_adjustment"]
        width_offset = self.config["width_offset"]
        x_spacing = self.config["x_spacing"]
        y_spacing = self.config["y_spacing"]
        if not isinstance(toolbar_height_adjustment, int) or toolbar_height_adjustment < 0:
            print(f"Error: toolbar_height_adjustment must be a non-negative integer, got {toolbar_height_adjustment}")
            sys.exit(1)
        if not isinstance(width_offset, int) or width_offset < 0:
            print(f"Error: width_offset must be a non-negative integer, got {width_offset}")
            sys.exit(1)
        if not isinstance(x_spacing, int) or x_spacing < 0:
            print(f"Error: x_spacing must be a non-negative integer, got {x_spacing}")
            sys.exit(1)
        if not isinstance(y_spacing, int) or y_spacing < 0:
            print(f"Error: y_spacing must be a non-negative integer, got {y_spacing}")
            sys.exit(1)

        if "cameras" not in self.config:
            print("Error: 'cameras' section missing in camera_config.json")
            sys.exit(1)
        cameras_config = self.config["cameras"]
        num_cameras = len(cameras_config)

        if grid_cols * grid_rows < num_cameras:
            print(f"Error: Grid size ({grid_cols}x{grid_rows}) too small for {num_cameras} cameras; need at least {num_cameras} slots")
            sys.exit(1)

        camera_urls = {}
        for camera in cameras_config:
            if "camera_num" not in camera or "stream_url" not in camera:
                print("Error: Each camera entry must have 'camera_num' and 'stream_url'")
                sys.exit(1)
            camera_num = camera["camera_num"]
            if not isinstance(camera_num, int) or camera_num < 1 or camera_num > num_cameras:
                print(f"Error: Invalid camera_num {camera_num}; must be between 1 and {num_cameras}")
                sys.exit(1)
            camera_urls[camera_num] = camera["stream_url"]

            if "features" not in camera:
                camera["features"] = {
                    "basic_motion_detection": {
                        "enabled": False,
                        "sensitivity": 50,
                        "outline_enabled": False,
                        "outline_color": "#FF0000",
                        "outline_weight": 1
                    }
                }

        for i in range(1, num_cameras + 1):
            if i not in camera_urls:
                print(f"Error: Missing configuration for camera number {i}")
                sys.exit(1)

        # Validate system_config.json
        if "camera_management" not in self.config:
            print("Error: 'camera_management' section missing in system_config.json")
            sys.exit(1)
        if "restart_delay_seconds" not in self.config["camera_management"]:
            print("Error: 'restart_delay_seconds' missing in system_config.json camera_management section")
            sys.exit(1)
        restart_delay_seconds = self.config["camera_management"]["restart_delay_seconds"]
        if not isinstance(restart_delay_seconds, int) or restart_delay_seconds < 0:
            print(f"Error: restart_delay_seconds must be a non-negative integer, got {restart_delay_seconds}")
            sys.exit(1)

        if "motion_detection" not in self.config:
            print("Error: 'motion_detection' section missing in system_config.json")
            sys.exit(1)
        motion_config = self.config["motion_detection"]
        if "motion_frame_skip" not in motion_config:
            print("Error: 'motion_frame_skip' missing in system_config.json motion_detection section")
            sys.exit(1)
        if "motion_downsample_factor" not in motion_config:
            print("Error: 'motion_downsample_factor' missing in system_config.json motion_detection section")
            sys.exit(1)
        if "outline_persistence_seconds" not in motion_config:
            print("Error: 'outline_persistence_seconds' missing in system_config.json motion_detection section")
            sys.exit(1)

        motion_frame_skip = motion_config["motion_frame_skip"]
        motion_downsample_factor = motion_config["motion_downsample_factor"]
        outline_persistence_seconds = motion_config["outline_persistence_seconds"]

        if not isinstance(motion_frame_skip, int) or motion_frame_skip < 1:
            print(f"Error: motion_frame_skip must be a positive integer, got {motion_frame_skip}")
            sys.exit(1)
        if not isinstance(motion_downsample_factor, int) or motion_downsample_factor < 1:
            print(f"Error: motion_downsample_factor must be a positive integer, got {motion_downsample_factor}")
            sys.exit(1)
        if not isinstance(outline_persistence_seconds, (int, float)) or outline_persistence_seconds < 0:
            print(f"Error: outline_persistence_seconds must be a non-negative number, got {outline_persistence_seconds}")
            sys.exit(1)
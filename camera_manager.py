import cv2
import threading
import queue
import time
import os
import subprocess
import sys
import platform
import psutil
import json

class CameraManager:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.cameras = []
        self.window_title = "Camera Feeds"
        self.grid = None
        self.grid_lock = threading.Lock()
        self.running = threading.Event()
        self.window_geometry = {}
        self.is_wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        self.window_manager = None
        self.window_manager_thread = None
        self.stderr_queue = queue.Queue()
        self.stderr_thread = None

    def start(self):
        self.running.set()
        from camera import Camera

        try:
            with open("camera_config.json", "r") as f:
                camera_config = json.load(f)
        except Exception as e:
            self.logger.log(f"Error loading camera_config.json: {e}")
            sys.exit(1)

        starting_position = camera_config.get("starting_position", "top-left")
        grid_cols = camera_config.get("grid_cols", 4)
        grid_rows = camera_config.get("grid_rows", 2)
        window_width = camera_config.get("window_width", 720)
        window_height = camera_config.get("window_height", 480)
        toolbar_height_adjustment = camera_config.get("toolbar_height_adjustment", 37)
        width_offset = camera_config.get("width_offset", 4)
        x_spacing = camera_config.get("x_spacing", 2)
        y_spacing = camera_config.get("y_spacing", 70)

        camera_configs = camera_config.get("cameras", [])
        if not camera_configs:
            self.logger.log("No cameras specified in camera_config.json. Exiting.")
            sys.exit(1)

        if grid_cols * grid_rows < len(camera_configs):
            self.logger.log(f"Grid size ({grid_cols}x{grid_rows}) is too small for {len(camera_configs)} cameras. Exiting.")
            sys.exit(1)

        grid_width = grid_cols * window_width
        grid_height = grid_rows * window_height
        self.logger.log(f"Grid dimensions: {grid_width}x{grid_height}, cell size: {window_width}x{window_height}")

        if self.is_wayland:
            self.window_geometry = {
                "original": {"x": 0, "y": 0, "w": grid_width + width_offset, "h": grid_height + y_spacing},
                "current": {"x": 0, "y": 0, "w": grid_width + width_offset, "h": grid_height + y_spacing},
                "expanded": False
            }
        else:
            self.window_geometry = {
                "original": {"x": 0, "y": 0, "w": grid_width + width_offset, "h": grid_height + toolbar_height_adjustment},
                "current": {"x": 0, "y": 0, "w": grid_width + width_offset, "h": grid_height + toolbar_height_adjustment},
                "expanded": False
            }

        cv2.namedWindow(self.window_title, cv2.WINDOW_FULLSCREEN)
        cv2.setWindowProperty(self.window_title, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self.logger.log(f"Created OpenCV window: {self.window_title} with type WINDOW_FULLSCREEN")
        cv2.moveWindow(self.window_title, 0, 0)
        cv2.resizeWindow(self.window_title, self.window_geometry["original"]["w"], self.window_geometry["original"]["h"])
        self.logger.log(f"Positioned window {self.window_title} at (0, 0) with size {self.window_geometry['original']['w']}x{self.window_geometry['original']['h']}")

        self.grid = np.zeros((grid_height * 2, grid_width, 3), dtype=np.uint8)

        for i, cam_config in enumerate(camera_configs):
            camera_num = cam_config.get("camera_num", i + 1)
            stream_url = cam_config.get("stream_url", "")

            if not stream_url:
                self.logger.log(f"No stream URL provided for Camera{camera_num}. Skipping.")
                continue

            row = i // grid_cols
            col = i % grid_cols

            x_pos = col * window_width
            y_pos = row * window_height

            camera = Camera(
                camera_num=camera_num,
                stream_url=stream_url,
                config=self.config,
                camera_config=cam_config,
                x_pos=x_pos,
                y_pos=y_pos,
                stderr_queue=self.stderr_queue,
                logger=self.logger,
                window_manager=self
            )

            if camera.test_connectivity():
                camera_thread = threading.Thread(target=camera.start, daemon=True)
                camera_thread.start()
                self.cameras.append(camera)
            else:
                self.logger.log(f"Skipping Camera{camera_num} due to connectivity issues.")

        self.logger.log(f"Launched {len(self.cameras)} camera feeds.")

        self.stderr_thread = threading.Thread(target=self._monitor_stderr, daemon=True)
        self.stderr_thread.start()

    def _monitor_stderr(self):
        while self.running.is_set():
            try:
                line = self.stderr_queue.get(timeout=1)
                self.logger.log(f"STDERR: {line}")
            except queue.Empty:
                continue

    def get_camera(self, camera_num):
        for camera in self.cameras:
            if camera.camera_num == camera_num:
                return camera
        return None

    def get_window_geometry(self, camera_num):
        camera = self.get_camera(camera_num)
        if camera:
            return camera.get_window_geometry()
        return None

    def set_window_geometry(self, camera_num, geometry):
        camera = self.get_camera(camera_num)
        if camera:
            camera.window_geometry = geometry

    def run(self):
        health_border_thickness = self.config.get("health_border_thickness", 2)
        healthy_border_color = tuple(int(self.config.get("healthy_border_color", "#00FF00").lstrip('#')[i:i+2], 16) for i in (0, 2, 4))[::-1]  # Convert hex to BGR
        stalled_border_color = tuple(int(self.config.get("stalled_border_color", "#FF0000").lstrip('#')[i:i+2], 16) for i in (0, 2, 4))[::-1]
        healthy_threshold = self.config.get("healthy_threshold", 1)
        stalled_threshold = self.config.get("stalled_threshold", 10)

        grid_cols = self.grid.shape[1] // self.config.get("window_width", 720)
        grid_rows = self.grid.shape[0] // self.config.get("window_height", 480) // 2

        expanded_camera = None
        last_expansion_time = time.time()
        expansion_cooldown = 0.5

        while self.running.is_set():
            frames_rendered = 0

            with self.grid_lock:
                self.grid.fill(0)

                for camera in self.cameras:
                    frame = camera.get_frame()
                    last_frame_time = camera.get_last_frame_time()
                    current_time = time.time()

                    if frame is None:
                        continue

                    frames_rendered += 1

                    window_geometry = camera.get_window_geometry()
                    x_pos = window_geometry["current"]["x"]
                    y_pos = window_geometry["current"]["y"]
                    window_width = window_geometry["current"]["w"]
                    window_height = window_geometry["current"]["h"]

                    if window_geometry["expanded"]:
                        expanded_camera = camera
                        last_expansion_time = current_time

                    frame_resized = cv2.resize(frame, (window_width, window_height), interpolation=cv2.INTER_AREA)

                    if current_time - last_frame_time < healthy_threshold:
                        border_color = healthy_border_color
                    elif current_time - last_frame_time > stalled_threshold:
                        border_color = stalled_border_color
                    else:
                        border_color = (0, 0, 0)

                    cv2.rectangle(frame_resized, (0, 0), (window_width - 1, window_height - 1), border_color, health_border_thickness)

                    while not camera.bounding_box_queue.empty():
                        rect = camera.bounding_box_queue.get()
                        x1, y1, x2, y2 = rect
                        outline_color = tuple(int(camera.camera_config["features"]["basic_motion_detection"]["outline_color"].lstrip('#')[i:i+2], 16) for i in (0, 2, 4))[::-1]
                        outline_weight = camera.camera_config["features"]["basic_motion_detection"]["outline_weight"]
                        cv2.rectangle(frame_resized, (x1, y1), (x2, y2), outline_color, outline_weight)

                    self.grid[y_pos:y_pos + window_height, x_pos:x_pos + window_width] = frame_resized

                    frame_rate = camera.get_frame_rate()
                    cv2.putText(frame_resized, f"FPS: {frame_rate:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                if expanded_camera and current_time - last_expansion_time > 5:
                    expanded_camera_geometry = expanded_camera.get_window_geometry()
                    expanded_camera_geometry["current"]["x"] = expanded_camera_geometry["original"]["x"]
                    expanded_camera_geometry["current"]["y"] = expanded_camera_geometry["original"]["y"]
                    expanded_camera_geometry["current"]["w"] = expanded_camera_geometry["original"]["w"]
                    expanded_camera_geometry["current"]["h"] = expanded_camera_geometry["original"]["h"]
                    expanded_camera_geometry["expanded"] = False
                    expanded_camera.set_window_geometry(expanded_camera_geometry)
                    expanded_camera = None

            self.logger.log(f"Rendered {frames_rendered} frames in grid")

            cv2.imshow(self.window_title, self.grid)
            key = cv2.waitKey(1)

            if key == 27:  # ESC key to exit
                self.logger.log(f"{self.window_title} window closed by user. Exiting.")
                break
            elif key == -1:
                self.logger.log("No keypress detected (cv2.waitKey returned -1).")
            elif key == ord('1') and current_time - last_expansion_time > expansion_cooldown:
                camera = self.get_camera(1)
                if camera:
                    geometry = camera.get_window_geometry()
                    if not geometry["expanded"]:
                        geometry["current"]["x"] = 0
                        geometry["current"]["y"] = grid_rows * window_height
                        geometry["current"]["w"] = grid_cols * window_width
                        geometry["current"]["h"] = grid_rows * window_height
                        geometry["expanded"] = True
                        camera.set_window_geometry(geometry)
                        last_expansion_time = current_time
            elif key == ord('2') and current_time - last_expansion_time > expansion_cooldown:
                camera = self.get_camera(2)
                if camera:
                    geometry = camera.get_window_geometry()
                    if not geometry["expanded"]:
                        geometry["current"]["x"] = 0
                        geometry["current"]["y"] = grid_rows * window_height
                        geometry["current"]["w"] = grid_cols * window_width
                        geometry["current"]["h"] = grid_rows * window_height
                        geometry["expanded"] = True
                        camera.set_window_geometry(geometry)
                        last_expansion_time = current_time

            time.sleep(0.01)

    def shutdown(self):
        self.logger.log("Shutdown initiated")
        self.running.clear()
        for camera in self.cameras:
            camera.stop()
        cv2.destroyAllWindows()
        for camera in self.cameras:
            camera_thread = threading.Thread(target=camera.stop, daemon=True)
            camera_thread.start()
            camera_thread.join(timeout=5)


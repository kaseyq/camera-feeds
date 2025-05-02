import screeninfo
import psutil
import time
import queue
import threading
import cv2
import numpy as np
import os
import signal
import sys
import json
from camera import Camera
from logger import Logger

class CameraManager:
    def __init__(self, config, verbose=False):
        self.config = config
        self.verbose = verbose
        self.logger = Logger(verbose)
        self.cameras = {}
        self.stderr_queue = queue.Queue()
        self.start_x = 0
        self.start_y = 0
        self.running = threading.Event()
        self.shutting_down = False  # Flag to prevent multiple shutdown attempts
        self.last_warning_time = 0
        self.warning_interval = 5
        self.camera_timeouts = {}
        self.enlarged_feed = None  # None for no feed selected, camera_num for selected feed
        self.window_name = "Camera Feeds"
        self.cols = 4  # Derived from config if available
        self.rows = 2
        self.health_status = {}  # camera_num -> health value (0 to 1)
        self.health_thread = None

        # Set up signal handler for Ctrl+C
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, sig, frame):
        if self.shutting_down:
            self.logger.log("Shutdown already in progress, ignoring additional Ctrl+C")
            return
        self.logger.log("Received Ctrl+C, initiating shutdown...")
        self.shutdown()
        sys.exit(0)

    def start(self):
        # Check and log dependency versions using dependency_check.json
        self._check_and_log_dependencies()

        self._close_existing_ffplay()
        self._launch_cameras()
        self.logger.log(f"Launched {len(self.cameras)} camera feeds.")
        self._start_health_monitoring()
        self._display_feeds()

    def _check_and_log_dependencies(self):
        # Define the path for dependency_check.json
        dependency_file = "dependency_check.json"

        # Ensure dependency_check.json exists
        if not os.path.exists(dependency_file):
            self.logger.log("dependency_check.json not found, creating an empty one...")
            dependency_data = {}
            try:
                with open(dependency_file, 'w') as f:
                    json.dump(dependency_data, f, indent=4)
                self.logger.log("Successfully created dependency_check.json")
            except Exception as e:
                self.logger.log(f"Error creating dependency_check.json: {e}")
                return

        # Read dependency_check.json
        try:
            with open(dependency_file, 'r') as f:
                dependency_data = json.load(f)
        except Exception as e:
            self.logger.log(f"Error reading dependency_check.json: {e}")
            return

        # Update dependency_check.json with OpenCV's FFmpeg build info if missing
        if "opencv_ffmpeg_build_info" not in dependency_data:
            build_info = cv2.getBuildInformation()
            ffmpeg_info = [line.strip() for line in build_info.split('\n') if 'FFmpeg' in line or 'Video I/O' in line]
            dependency_data["opencv_ffmpeg_build_info"] = ffmpeg_info
            try:
                with open(dependency_file, 'w') as f:
                    json.dump(dependency_data, f, indent=4)
                self.logger.log("Updated dependency_check.json with OpenCV FFmpeg build information")
            except Exception as e:
                self.logger.log(f"Error updating dependency_check.json: {e}")

        # Log the contents of dependency_check.json
        self.logger.log("Dependency versions from dependency_check.json:")
        for dep, info in dependency_data.items():
            if dep == "opencv_ffmpeg_build_info":
                self.logger.log("FFmpeg build information from OpenCV:")
                for line in info:
                    self.logger.log(line)
            else:
                self.logger.log(f"{dep}: {info.get('version', 'Unknown')}")

    def _close_existing_ffplay(self):
        self.logger.log("Closing existing ffplay processes...")
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'].lower() == 'ffplay':
                    proc.terminate()
                    proc.wait(timeout=3)
                    self.logger.log(f"Terminated ffplay process (PID: {proc.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                continue

    def _launch_cameras(self):
        launch_threads = []
        connectivity_results = [None] * len(self.config["cameras"])
        connectivity_threads = []

        for i, camera_config in enumerate(self.config["cameras"]):
            camera = Camera(
                camera_config["camera_num"],
                camera_config["stream_url"],
                self.config,
                camera_config,
                0, 0,
                self.stderr_queue,
                self.logger,
                None
            )
            self.cameras[camera_config["camera_num"]] = camera
            thread = threading.Thread(target=lambda idx, cam: connectivity_results.__setitem__(idx, cam.test_connectivity()), args=(i, camera))
            connectivity_threads.append(thread)
            thread.start()

        for thread in connectivity_threads:
            thread.join()

        for i, camera_config in enumerate(self.config["cameras"]):
            camera = self.cameras[camera_config["camera_num"]]
            if not connectivity_results[i]:
                self.logger.log(f"Skipping Camera{camera.camera_num} due to failed connectivity test")
                continue
            self.camera_timeouts[camera_config["camera_num"]] = time.time()
            thread = threading.Thread(target=camera.start)
            launch_threads.append(thread)
            thread.start()

        self.launch_threads = launch_threads

    def _start_health_monitoring(self):
        self.health_thread = threading.Thread(target=self._monitor_health, daemon=True)
        self.health_thread.start()

    def _monitor_health(self):
        update_interval = self.config.get("health_update_interval", 1)
        healthy_threshold = self.config.get("healthy_threshold", 1)
        stalled_threshold = self.config.get("stalled_threshold", 10)
        while self.running.is_set():
            current_time = time.time()
            for camera_num, camera in self.cameras.items():
                last_update = camera.get_last_frame_time()
                time_since_update = current_time - last_update
                # Normalize health to 0-1
                if time_since_update <= healthy_threshold:
                    health = 1.0
                elif time_since_update >= stalled_threshold:
                    health = 0.0
                else:
                    health = 1.0 - (time_since_update - healthy_threshold) / (stalled_threshold - healthy_threshold)
                self.health_status[camera_num] = health
            time.sleep(update_interval)

    def _create_window(self, window_name, width, height, x, y):
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_FULLSCREEN)
            self.logger.log(f"Created OpenCV window: {window_name} with type WINDOW_FULLSCREEN")
            cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.resizeWindow(window_name, width, height)
            cv2.moveWindow(window_name, x, y)
            self.logger.log(f"Positioned window {window_name} at ({x}, {y}) with size {width}x{height}")
            return True
        except Exception as e:
            self.logger.log(f"Error creating OpenCV window: {e}")
            return False

    def _hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _interpolate_color(self, color1, color2, t):
        # color1 and color2 are RGB tuples, t is a float between 0 and 1
        return tuple(int(c1 * t + c2 * (1 - t)) for c1, c2 in zip(color1, color2))

    def _on_mouse(self, event, x, y, flags, param):
        # Use single click for selecting the feed
        if event != cv2.EVENT_LBUTTONDOWN:
            return

        # Only handle clicks in the grid region (top half of the window)
        if y >= param["grid_height"]:
            return

        # Determine which feed was clicked in the grid
        cell_width = param["scaled_width"] // self.cols
        cell_height = param["scaled_height"] // self.rows
        col = x // cell_width
        row = y // cell_height
        if col >= self.cols or row >= self.rows:
            self.logger.log(f"Click outside grid: col={col}, row={row}")
            return
        feed_index = row * self.cols + col + 1  # 1-based camera numbers
        if feed_index not in self.cameras:
            self.logger.log(f"Invalid feed index: {feed_index}")
            return
        # Check if a frame is available before updating
        camera = self.cameras[feed_index]
        frame = camera.get_frame()
        if frame is None:
            self.logger.log(f"No frame available for Camera {feed_index}, delaying update")
            return
        self.logger.log(f"Updating enlarged feed to: {feed_index}")
        self.enlarged_feed = feed_index

    def _display_feeds(self):
        self.running.set()
        frame_width = 720
        frame_height = 480
        grid_width = frame_width * self.cols
        grid_height = frame_height * self.rows

        self.logger.log(f"Grid dimensions: {grid_width}x{grid_height}, cell size: {frame_width}x{frame_height}")

        display_width = 1720
        scale = display_width / grid_width
        scaled_width = display_width
        scaled_height = int(grid_height * scale)
        grid_display_height = scaled_height  # Height of the grid region
        enlarged_display_height = scaled_height  # Height of the enlarged region
        total_display_height = grid_display_height + enlarged_display_height  # Total height of the combined window

        # Create a single window for both grid and enlarged feeds
        if not self._create_window(self.window_name, display_width, total_display_height, 0, 0):
            self.running.clear()
            return

        # Set mouse callback on the single window
        param = {
            "scaled_width": scaled_width,
            "scaled_height": scaled_height,
            "display_width": display_width,
            "grid_height": grid_display_height,
            "total_height": total_display_height
        }
        cv2.setMouseCallback(self.window_name, self._on_mouse, param=param)

        timeout_seconds = 5
        frame_interval = 1/30

        while self.running.is_set():
            # Create a single frame for both grid and enlarged regions
            combined_frame = np.zeros((total_display_height, display_width, 3), dtype=np.uint8)

            # Grid window rendering (top half)
            grid_frame = np.zeros((grid_height, grid_width, 3), dtype=np.uint8)
            frames_rendered = 0
            current_time = time.time()

            for camera_num, camera in self.cameras.items():
                if (current_time - self.camera_timeouts[camera_num] > timeout_seconds) and camera.get_frame() is None:
                    self.logger.log(f"Camera{camera_num} timed out after {timeout_seconds} seconds.")
                    continue

                frame = camera.get_frame()
                if frame is None:
                    continue
                frames_rendered += 1

                row = (camera_num - 1) // self.cols
                col = (camera_num - 1) % self.cols
                y_start = row * frame_height
                x_start = col * frame_width
                y_end = y_start + frame_height
                x_end = x_start + frame_width

                slice_shape = (y_end - y_start, x_end - x_start, 3)
                self.logger.log(f"Camera{camera_num} slice: [{y_start}:{y_end}, {x_start}:{x_end}], slice shape: {slice_shape}, frame shape: {frame.shape}")
                if slice_shape[:2] != frame.shape[:2]:
                    self.logger.log(f"Dimension mismatch: slice shape {slice_shape[:2]} does not match frame shape {frame.shape[:2]}")
                    continue

                # Draw health border for grid
                health = self.health_status.get(camera_num, 1.0)
                healthy_color = self._hex_to_rgb(self.config.get("healthy_border_color", "#00FF00"))
                stalled_color = self._hex_to_rgb(self.config.get("stalled_border_color", "#FF0000"))
                border_color = self._interpolate_color(healthy_color, stalled_color, health)
                border_thickness = self.config.get("health_border_thickness", 2)
                cv2.rectangle(frame, (0, 0), (frame_width - 1, frame_height - 1), border_color, border_thickness)

                # Draw motion detection rectangles for grid
                if camera.camera_config["features"]["basic_motion_detection"]["enabled"]:
                    outline_color = self._hex_to_rgb(camera.camera_config["features"]["basic_motion_detection"]["outline_color"])
                    outline_weight = camera.camera_config["features"]["basic_motion_detection"]["outline_weight"]
                    motion_rects = []
                    while not camera.bounding_box_queue.empty():
                        rect = camera.bounding_box_queue.get()
                        motion_rects.append(rect)
                        (x1, y1, x2, y2) = rect
                        cv2.rectangle(frame, (x1, y1), (x2, y2), outline_color, outline_weight)
                    if motion_rects:
                        self.logger.log(f"Camera{camera_num}: Drawing {len(motion_rects)} motion rectangles in grid")

                grid_frame[y_start:y_end, x_start:x_end] = frame

            self.logger.log(f"Rendered {frames_rendered} frames in grid")
            grid_display_frame = cv2.resize(grid_frame, (scaled_width, scaled_height), interpolation=cv2.INTER_AREA)
            combined_frame[0:grid_display_height, 0:display_width] = grid_display_frame

            # Enlarged window rendering (bottom half)
            if self.enlarged_feed is not None:
                camera = self.cameras.get(self.enlarged_feed)
                if camera:
                    frame = camera.get_frame()
                    if frame is None:
                        self.logger.log(f"No frame available for Camera {self.enlarged_feed} in enlarged window")
                        # Display a placeholder
                        final_frame = np.zeros((enlarged_display_height, display_width, 3), dtype=np.uint8)
                        cv2.putText(final_frame, "No Frame Available", (display_width//4, enlarged_display_height//2), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                    else:
                        # Scale to fit window height
                        frame_height, frame_width = frame.shape[:2]
                        scale = enlarged_display_height / frame_height  # 573 / 480 ≈ 1.19375
                        enlarged_width = int(frame_width * scale)  # 720 * 1.19375 ≈ 859
                        enlarged_height = enlarged_display_height  # 573
                        self.logger.log(f"Enlarged frame dimensions: {enlarged_width}x{enlarged_height}")
                        enlarged_frame = cv2.resize(frame, (enlarged_width, enlarged_height), interpolation=cv2.INTER_AREA)
                        self.logger.log(f"After resize, enlarged frame shape: {enlarged_frame.shape}")

                        # Center the frame with letterboxing
                        final_frame = np.zeros((enlarged_display_height, display_width, 3), dtype=np.uint8)
                        x_offset = (display_width - enlarged_width) // 2  # (1720 - 859) // 2 ≈ 430
                        self.logger.log(f"Placing frame at x_offset: {x_offset}")
                        final_frame[:, x_offset:x_offset + enlarged_width] = enlarged_frame
                        self.logger.log(f"Final frame shape: {final_frame.shape}")

                        # Draw health border for enlarged feed
                        health = self.health_status.get(self.enlarged_feed, 1.0)
                        healthy_color = self._hex_to_rgb(self.config.get("healthy_border_color", "#00FF00"))
                        stalled_color = self._hex_to_rgb(self.config.get("stalled_border_color", "#FF0000"))
                        border_color = self._interpolate_color(healthy_color, stalled_color, health)
                        border_thickness = self.config.get("health_border_thickness", 2)
                        cv2.rectangle(final_frame, (x_offset, 0), (x_offset + enlarged_width - 1, enlarged_height - 1), border_color, border_thickness)

                        # Draw motion detection rectangles for enlarged feed
                        if camera.camera_config["features"]["basic_motion_detection"]["enabled"]:
                            outline_color = self._hex_to_rgb(camera.camera_config["features"]["basic_motion_detection"]["outline_color"])
                            outline_weight = camera.camera_config["features"]["basic_motion_detection"]["outline_weight"]
                            scaled_outline_weight = int(outline_weight * scale)
                            motion_rects = []  # Define motion_rects here
                            while not camera.bounding_box_queue.empty():
                                rect = camera.bounding_box_queue.get()
                                motion_rects.append(rect)
                                (x1, y1, x2, y2) = rect
                                scaled_x1 = int(x1 * scale) + x_offset
                                scaled_y1 = int(y1 * scale)
                                scaled_x2 = int(x2 * scale) + x_offset
                                scaled_y2 = int(y2 * scale)
                                cv2.rectangle(final_frame, (scaled_x1, scaled_y1), (scaled_x2, scaled_y2), outline_color, scaled_outline_weight)
                            if motion_rects:
                                self.logger.log(f"Camera{self.enlarged_feed}: Drawing {len(motion_rects)} motion rectangles in enlarged feed")
                else:
                    self.logger.log(f"Camera {self.enlarged_feed} not found for enlarged window")
                    self.enlarged_feed = None
                    final_frame = np.zeros((enlarged_display_height, display_width, 3), dtype=np.uint8)
                    cv2.putText(final_frame, "Select a Feed to Enlarge", (display_width//4, enlarged_display_height//2), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            else:
                # Display a placeholder if no feed is selected
                final_frame = np.zeros((enlarged_display_height, display_width, 3), dtype=np.uint8)
                cv2.putText(final_frame, "Select a Feed to Enlarge", (display_width//4, enlarged_display_height//2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            combined_frame[grid_display_height:total_display_height, 0:display_width] = final_frame

            # Display the combined frame in the single window
            cv2.imshow(self.window_name, combined_frame)

            key = cv2.waitKey(1)  # Reduced delay for better responsiveness
            cv2.pollKey()
            if key == 27:
                self.logger.log("ESC key pressed, initiating shutdown")
                self.running.clear()
                break
            elif key == -1:
                current_time = time.time()
                if current_time - self.last_warning_time >= self.warning_interval:
                    self.logger.log("No keypress detected (cv2.waitKey returned -1).")
                    self.last_warning_time = current_time

            try:
                if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                    self.logger.log(f"{self.window_name} window closed by user. Exiting.")
                    self.running.clear()
                    break
            except Exception as e:
                self.logger.log(f"Error checking window visibility: {e}")
                self.running.clear()
                break

            time.sleep(frame_interval)

        self.shutdown()

    def shutdown(self):
        if self.shutting_down:
            self.logger.log("Shutdown already in progress, skipping")
            return
        self.shutting_down = True
        self.running.clear()
        self.logger.log("Shutdown initiated")

        # Stop all cameras and wait for threads to terminate
        for camera in self.cameras.values():
            camera.stop()

        # Wait for camera threads to join with a longer timeout
        for thread in getattr(self, 'launch_threads', []):
            if thread.is_alive():
                thread.join(timeout=10)  # Increased timeout to 10 seconds
                if thread.is_alive():
                    self.logger.log(f"Thread for camera failed to join within timeout")

        # Add a small delay to ensure all threads have stopped
        time.sleep(0.5)

        # Clean up OpenCV windows
        try:
            cv2.destroyAllWindows()
        except Exception as e:
            self.logger.log(f"Error during OpenCV cleanup: {e}")

        self.logger.log("Shutdown complete.")
        self.shutting_down = False

    def log_stderr(self):
        self.logger.log_stderr(self.stderr_queue)
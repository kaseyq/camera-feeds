import cv2
import threading
import queue
import time
import urllib.parse
import socket
import os
import numpy as np

class MotionDetector:
    def __init__(self, camera_config, logger, bounding_box_queue, config):
        self.camera_config = camera_config  # From camera_config.json
        self.logger = logger
        self.bounding_box_queue = bounding_box_queue
        self.config = config  # From system_config.json
        self.running = threading.Event()
        self.prev_frame = None
        self.min_lifespan = None  # Will be set by Camera
        self.detected_rectangles = []  # List of (rect, timestamp)
        self.frame_counter = 0  # For frame skipping
        # Get motion_frame_skip and motion_downsample_factor from system_config.json
        self.motion_frame_skip = self.config.get("motion_detection", {}).get("motion_frame_skip", 5)
        self.motion_downsample_factor = self.config.get("motion_detection", {}).get("motion_downsample_factor", 2)

    def start(self, cap, running, min_lifespan):
        self.running = running
        self.min_lifespan = min_lifespan
        while self.running.is_set():
            try:
                ret, frame = cap.read()
                if not ret or frame is None:
                    self.logger.log("MotionDetector: No frame available for processing")
                    time.sleep(0.01)
                    continue

                self.frame_counter += 1
                if self.frame_counter % self.motion_frame_skip != 0:
                    time.sleep(0.01)
                    continue  # Skip processing this frame to reduce load

                # Downsample the frame to reduce processing load
                if self.motion_downsample_factor > 1:
                    height, width = frame.shape[:2]
                    new_height = height // self.motion_downsample_factor
                    new_width = width // self.motion_downsample_factor
                    frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if self.prev_frame is None:
                    self.prev_frame = gray
                    time.sleep(0.01)
                    continue

                # Compute frame difference
                frame_delta = cv2.absdiff(self.prev_frame, gray)
                sensitivity = self.camera_config["features"]["basic_motion_detection"]["sensitivity"]
                # Map sensitivity (0-99) to threshold (0-255)
                thresh_value = int((sensitivity / 99) * 255)
                thresh = cv2.threshold(frame_delta, thresh_value, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)

                # Find contours
                contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                current_time = time.time()
                new_rectangles = []

                for contour in contours:
                    if cv2.contourArea(contour) < 200:  # Reduced minimum area to detect smaller movements
                        continue
                    (x, y, w, h) = cv2.boundingRect(contour)
                    # Scale bounding box coordinates back to original frame size
                    x = x * self.motion_downsample_factor
                    y = y * self.motion_downsample_factor
                    w = w * self.motion_downsample_factor
                    h = h * self.motion_downsample_factor
                    new_rectangles.append(((x, y, x + w, y + h), current_time))
                    self.logger.log(f"Motion detected: rectangle at ({x}, {y}, {x+w}, {y+h})")

                # Update detected rectangles, removing expired ones
                self.detected_rectangles = [(rect, t) for rect, t in self.detected_rectangles if current_time - t < self.min_lifespan]
                self.detected_rectangles.extend(new_rectangles)

                # Add to queue for rendering
                while not self.bounding_box_queue.empty():
                    self.bounding_box_queue.get()
                for rect, _ in self.detected_rectangles:
                    self.bounding_box_queue.put(rect)

                self.prev_frame = gray
                self.logger.log(f"MotionDetector: Processed frame {self.frame_counter}, detected {len(new_rectangles)} motion rectangles")
                time.sleep(0.01)
            except Exception as e:
                self.logger.log(f"MotionDetector error: {e}")
                time.sleep(0.01)
                continue

    def stop(self):
        self.running.clear()

class Camera:
    def __init__(self, camera_num, stream_url, config, camera_config, x_pos, y_pos, stderr_queue, logger, window_manager):
        self.camera_num = camera_num
        self.stream_url = stream_url
        self.config = config  # system_config.json
        self.camera_config = camera_config  # camera_config.json
        self.x_pos = x_pos
        self.y_pos = y_pos
        self.stderr_queue = stderr_queue
        self.logger = logger
        self.window_manager = window_manager
        self.cap = None
        self.restart_event = threading.Event()
        self.running = threading.Event()
        self.start_time = [time.time()]
        self.window_title = f"Camera{self.camera_num}"
        self.bounding_box_queue = queue.Queue()
        self.motion_detector = None
        self.overlay_manager = None
        self.motion_thread = None
        self.is_wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        self.frame = None
        self.frame_lock = threading.Lock()
        # Frame rate monitoring
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.frame_rate = 0
        self.frame_rate_lock = threading.Lock()
        self.frame_rate_thread = None

    def test_connectivity(self):
        try:
            parsed_url = urllib.parse.urlparse(self.stream_url)
            scheme = parsed_url.scheme.lower()
            self.logger.log(f"Parsed stream URL scheme: {scheme} for {self.stream_url}")

            if scheme in ["rtsp", "http", "https"]:
                netloc = parsed_url.netloc
                if '@' in netloc:
                    netloc = netloc.split('@')[1]
                host = netloc.split(':')[0]
                port = parsed_url.port

                if port is None:
                    if scheme == "rtsp":
                        port = 554
                    elif scheme == "http":
                        port = 80
                    elif scheme == "https":
                        port = 443

                self.logger.log(f"Testing connectivity to {host}:{port} for {scheme} stream")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                if result != 0:
                    self.logger.log(f"Connectivity test failed for {host}:{port} (error code: {result})")
                return result == 0
            else:
                self.logger.log(f"Skipping connectivity test for unsupported scheme: {scheme}")
                return True
        except Exception as e:
            self.logger.log(f"Connectivity test error for {self.stream_url}: {e}")
            return False

    def start(self):
        if self.is_wayland:
            self.logger.log(f"Running on Wayland. Using a single OpenCV window for consistent layout.")

        try:
            import cv2
            MOTION_DETECTION_AVAILABLE = True
        except ImportError as e:
            self.logger.log(f"Warning: Motion detection disabled due to missing OpenCV: {e}")
            MOTION_DETECTION_AVAILABLE = False

        motion_enabled = MOTION_DETECTION_AVAILABLE and self.camera_config["features"]["basic_motion_detection"]["enabled"]
        outline_enabled = motion_enabled and self.camera_config["features"]["basic_motion_detection"]["outline_enabled"]

        try:
            self.running.set()
            # Determine the backend from system_config.json
            backend = self.config.get("stream_backend", "ffmpeg").lower()
            self.logger.log(f"Using stream backend: {backend}")

            # Initialize video capture based on backend
            self.cap = None
            if backend == "gstreamer":
                # Escape special characters in the RTSP URL
                escaped_url = self.stream_url.replace("$", "\\$")
                pipeline = (
                    f"rtspsrc location={escaped_url} latency=0 protocols=tcp ! "
                    "rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! appsink sync=false"
                )
                self.logger.log(f"Attempting to open GStreamer pipeline: {pipeline}")
                self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if not self.cap.isOpened():
                    self.logger.log("GStreamer pipeline failed to open. Falling back to FFmpeg.")
                    backend = "ffmpeg"
                    self.cap.release()
                    self.cap = None  # Ensure we start fresh with FFmpeg

            # Use FFmpeg if GStreamer fails or if FFmpeg was selected
            if backend == "ffmpeg" or self.cap is None:
                self.logger.log(f"Attempting to open FFmpeg stream: {self.stream_url}")
                self.cap = cv2.VideoCapture(self.stream_url)

            # Final check to ensure the stream opened successfully
            if not self.cap.isOpened():
                self.logger.log(f"Failed to open video stream for Camera{self.camera_num} using {backend}: {self.stream_url}")
                self.running.clear()
                return

            self.logger.log(f"Successfully opened stream for Camera{self.camera_num} using {backend}")
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.logger.log(f"Started capturing for Camera{self.camera_num} (PID: {os.getpid()})")

            # Start motion detection if enabled
            if motion_enabled:
                self.motion_detector = MotionDetector(self.camera_config, self.logger, self.bounding_box_queue, self.config)
                min_lifespan = self.config.get("motion_detection", {}).get("outline_persistence_seconds", 1.0)
                self.motion_thread = threading.Thread(
                    target=self.motion_detector.start,
                    args=(self.cap, self.running, min_lifespan),
                    daemon=True
                )
                self.motion_thread.start()

            # Start frame rate monitoring
            self.frame_rate_thread = threading.Thread(target=self._monitor_frame_rate, daemon=True)
            self.frame_rate_thread.start()

            self._start_monitoring()
            self._capture_frames()

        except Exception as e:
            self.logger.log(f"Error starting Camera{self.camera_num}: {e}")
        finally:
            self.stop()

    def _monitor_frame_rate(self):
        while self.running.is_set():
            start_time = time.time()
            initial_count = self.frame_count
            time.sleep(1)  # Measure over 1-second intervals
            elapsed = time.time() - start_time
            frames = self.frame_count - initial_count
            with self.frame_rate_lock:
                self.frame_rate = frames / elapsed if elapsed > 0 else 0
            time.sleep(0.1)

    def get_frame_rate(self):
        with self.frame_rate_lock:
            return self.frame_rate

    def _capture_frames(self):
        retry_attempts = 3
        retry_delay = 5  # Seconds
        attempt = 0

        while self.running.is_set():
            start_time = time.time()
            timeout = 0.5
            ret, frame = False, None
            while self.running.is_set() and time.time() - start_time < timeout:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    break
                time.sleep(0.005)

            if not ret or frame is None:
                if not self.running.is_set():
                    break  # Exit if shutdown is initiated
                attempt += 1
                if attempt <= retry_attempts:
                    self.logger.log(f"Failed to read frame from {self.stream_url}, retrying ({attempt}/{retry_attempts})...")
                    time.sleep(retry_delay)
                    self.cap.release()
                    backend = self.config.get("stream_backend", "ffmpeg").lower()
                    if backend == "gstreamer":
                        escaped_url = self.stream_url.replace("$", "\\$")
                        pipeline = (
                            f"rtspsrc location={escaped_url} latency=0 protocols=tcp ! "
                            "rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! appsink sync=false"
                        )
                        self.logger.log(f"Retrying GStreamer pipeline: {pipeline}")
                        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                        if not self.cap.isOpened():
                            self.logger.log("GStreamer pipeline failed on retry. Falling back to FFmpeg.")
                            backend = "ffmpeg"
                            self.cap.release()
                            self.cap = None
                    if backend == "ffmpeg" or self.cap is None:
                        self.cap = cv2.VideoCapture(self.stream_url)

                    if not self.cap.isOpened():
                        self.logger.log(f"Failed to reopen video stream for Camera{self.camera_num}")
                        break
                    continue
                self.logger.log(f"Failed to read frame from {self.stream_url} after {retry_attempts} retries, triggering restart...")
                self.restart_event.set()
                break
            with self.frame_lock:
                self.frame = frame
                self.last_frame_time = time.time()
                self.frame_count += 1
            attempt = 0
            time.sleep(0.01)

    def get_frame(self):
        with self.frame_lock:
            if self.frame is None:
                self.logger.log(f"Camera{self.camera_num}: No frame available")
                return None
            if not isinstance(self.frame, np.ndarray):
                self.logger.log(f"Camera{self.camera_num}: Invalid frame type: {type(self.frame)}")
                return None
            if self.frame.size == 0:
                self.logger.log(f"Camera{self.camera_num}: Empty frame")
                return None
            self.logger.log(f"Camera{self.camera_num}: Returning frame with shape {self.frame.shape}")
            return self.frame.copy()

    def get_last_frame_time(self):
        with self.frame_lock:
            return self.last_frame_time

    def stop(self):
        self.running.clear()
        if self.cap:
            try:
                self.cap.release()
                self.logger.log(f"Camera{self.camera_num}: Released video capture")
            except Exception as e:
                self.logger.log(f"Camera{self.camera_num}: Error releasing video capture: {e}")
        if self.motion_detector:
            self.motion_detector.stop()
        if self.overlay_manager:
            self.overlay_manager.stop()

    def _run_motion_detection(self):
        if self.overlay_manager:
            self.overlay_manager.start()
        else:
            self.motion_detector.start()

    def _start_monitoring(self):
        process_thread = threading.Thread(
            target=self._monitor_process,
            daemon=True
        )
        process_thread.start()
        stall_thread = threading.Thread(
            target=self._monitor_stall,
            daemon=True
        )
        stall_thread.start()

    def _monitor_process(self):
        last_restart = 0
        while self.running.is_set():
            if self.restart_event.is_set():
                if time.time() - last_restart > self.config["camera_management"]["restart_delay_seconds"]:
                    if self.motion_detector:
                        self.motion_detector.stop()
                    if self.overlay_manager:
                        self.overlay_manager.stop()

                    self.running.clear()
                    if self.cap:
                        self.cap.release()

                    self.running.set()
                    backend = self.config.get("stream_backend", "ffmpeg").lower()
                    if backend == "gstreamer":
                        escaped_url = self.stream_url.replace("$", "\\$")
                        pipeline = (
                            f"rtspsrc location={escaped_url} latency=0 protocols=tcp ! "
                            "rtph265depay ! h265parse ! avdec_h265 ! videoconvert ! appsink sync=false"
                        )
                        self.logger.log(f"Restarting GStreamer pipeline: {pipeline}")
                        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                        if not self.cap.isOpened():
                            self.logger.log("GStreamer pipeline failed on restart. Falling back to FFmpeg.")
                            backend = "ffmpeg"
                            self.cap.release()
                            self.cap = None
                    if backend == "ffmpeg" or self.cap is None:
                        self.cap = cv2.VideoCapture(self.stream_url)

                    if not self.cap.isOpened():
                        self.logger.log(f"Camera{self.camera_num} failed to restart, stopping monitoring")
                        self.running.clear()
                        return
                    last_restart = time.time()
                    self.start_time[0] = time.time()
                    self.logger.log(f"Camera{self.camera_num} restarted successfully")
                    self._start_motion_detection_after_restart()
                    self._capture_frames()
                else:
                    remaining = self.config["camera_management"]["restart_delay_seconds"] - (time.time() - last_restart)
                    self.logger.log(f"Camera{self.camera_num} restart delayed for {remaining:.1f} seconds")
                    time.sleep(remaining)
                    continue

                self.restart_event.clear()
            time.sleep(0.1)

    def _start_motion_detection_after_restart(self):
        if self.motion_detector:
            self.motion_detector = MotionDetector(self.camera_config, self.logger, self.bounding_box_queue, self.config)
            self.motion_thread = threading.Thread(target=self._run_motion_detection, daemon=True)
            self.motion_thread.start()

    def _monitor_stall(self):
        stall_keywords = ["connection timeout", "connection closed"]
        timeout_interval = 30
        while self.running.is_set():
            if self.restart_event.is_set():
                self.restart_event.wait()
                continue

            with self.frame_lock:
                if self.frame is None and time.time() - self.start_time[0] > timeout_interval:
                    self.logger.log(f"Camera{self.camera_num} stall detected (no frames read)")
                    self.restart_event.set()
                    self.restart_event.wait()
            time.sleep(0.05)

    def get_window_geometry(self):
        return {
            "original": {"x": self.x_pos, "y": self.y_pos, "w": self.config["window_width"], "h": self.config["window_height"]},
            "current": {"x": self.x_pos, "y": self.y_pos, "w": self.config["window_width"], "h": self.config["window_height"]},
            "expanded": False
        }


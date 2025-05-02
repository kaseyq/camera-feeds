import subprocess
import sys
import json
import importlib
import cv2
import time
import os
import platform
from camera_manager import CameraManager
from config_loader import ConfigLoader
from logger import Logger

# Debug logging to confirm script execution
logger = Logger()
logger.log(f"Executing __main__.py at path: {os.path.abspath(__file__)}")
logger.log(f"Python version: {platform.python_version()}")
logger.log(f"sys.path: {sys.path}")
logger.log(f"Environment variables: {os.environ}")

# Version identifier with timestamp for debugging
SCRIPT_VERSION = f"1.0.3-{int(time.time())}"

def load_dependency_check(logger):
    """Load dependency_check.json or create it if it doesn't exist."""
    dependency_file = "dependency_check.json"
    logger.log(f"Starting load_dependency_check function...")
    try:
        logger.log(f"Attempting to open {dependency_file}...")
        with open(dependency_file, "r") as f:
            logger.log(f"Loading {dependency_file}...")
            deps = json.load(f)
            logger.log(f"Loaded dependency versions: {deps}")
            return deps
    except FileNotFoundError:
        logger.log(f"{dependency_file} not found. Creating default dependency check file...")
        default_deps = {
            "ffmpeg": {"version": "unknown"},
            "psutil": {"version": "unknown"},
            "screeninfo": {"version": "unknown"},
            "pynput": {"version": "unknown"},
            "opencv-python": {"version": "unknown"},
            "opencv_ffmpeg_build_info": ["Video I/O:"],
            "gstreamer1.0-tools": {"version": "unknown"},
            "gstreamer1.0-plugins-good": {"version": "unknown"},
            "gstreamer1.0-plugins-bad": {"version": "unknown"},
            "gstreamer1.0-plugins-ugly": {"version": "unknown"},
            "gstreamer1.0-libav": {"version": "unknown"},
            "opencv_gstreamer_support": "unknown"
        }
        logger.log(f"Writing default dependency file...")
        with open(dependency_file, "w") as f:
            json.dump(default_deps, f, indent=4)
        logger.log(f"Created default {dependency_file} with versions: {default_deps}")
        return default_deps
    except Exception as e:
        logger.log(f"Failed to load {dependency_file}: {e}")
        raise
    finally:
        logger.log("Exiting load_dependency_check function.")

def save_dependency_check(deps, logger):
    """Save updated dependency_check.json."""
    logger.log("Starting save_dependency_check function...")
    try:
        logger.log("Writing dependency_check.json...")
        with open("dependency_check.json", "w") as f:
            json.dump(deps, f, indent=4)
        logger.log("Updated dependency_check.json with current dependency versions.")
    except Exception as e:
        logger.log(f"Failed to update dependency_check.json: {e}")
        raise
    finally:
        logger.log("Exiting save_dependency_check function.")

def check_and_install_apt_package(package, logger, deps):
    """Check if an apt package is installed and install it if missing or outdated."""
    logger.log(f"Starting check_and_install_apt_package for {package}...")
    current_version = deps.get(package, {}).get("version", "unknown")
    if current_version != "unknown":
        logger.log(f"{package} already installed (version: {current_version}). Skipping installation.")
        return

    logger.log(f"Checking for {package} installation...")
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package],
            capture_output=True, text=True, check=True
        )
        version = result.stdout.strip()
        if version:
            logger.log(f"{package} is installed (version: {version}).")
            deps[package] = {"version": version}
            save_dependency_check(deps, logger)
            return
    except subprocess.CalledProcessError:
        logger.log(f"{package} is not installed. Installing...")

    try:
        logger.log("Running sudo apt update...")
        subprocess.run(
            ["sudo", "apt", "update"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        logger.log(f"Installing {package} with sudo apt install...")
        subprocess.run(
            ["sudo", "apt", "install", "-y", package],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        logger.log(f"Verifying {package} installation...")
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package],
            capture_output=True, text=True, check=True
        )
        version = result.stdout.strip()
        logger.log(f"Successfully installed {package} (version: {version}).")
        deps[package] = {"version": version}
        save_dependency_check(deps, logger)
    except subprocess.CalledProcessError as e:
        logger.log(f"Failed to install {package}: {e.stderr}")
        raise
    except Exception as e:
        logger.log(f"Unexpected error installing {package}: {e}")
        raise
    finally:
        logger.log(f"Exiting check_and_install_apt_package for {package}.")

def check_and_install_pip_package(package, expected_version, logger, deps):
    """Check if a pip package is installed and matches the expected version."""
    logger.log(f"Starting check_and_install_pip_package for {package}...")
    current_version = deps.get(package, {}).get("version", "unknown")
    if current_version == expected_version:
        logger.log(f"{package} already installed with version {current_version}. Skipping installation.")
        return

    logger.log(f"Checking for {package} installation (expected version: {expected_version})...")
    try:
        result = subprocess.run(
            ["pip", "show", package],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("Version:"):
                version = line.split(":")[1].strip()
                if version == expected_version:
                    logger.log(f"{package} is installed with version {version}.")
                    deps[package] = {"version": version}
                    save_dependency_check(deps, logger)
                    return
                else:
                    logger.log(f"{package} version {version} does not match expected version {expected_version}. Reinstalling...")
    except subprocess.CalledProcessError:
        logger.log(f"{package} is not installed. Installing...")

    try:
        logger.log(f"Running pip install for {package}...")
        subprocess.run(
            ["pip", "install", "--upgrade", f"{package}=={expected_version}", "--user", "--break-system-packages"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        logger.log(f"Successfully installed {package} version {expected_version}.")
        deps[package] = {"version": expected_version}
        save_dependency_check(deps, logger)
    except subprocess.CalledProcessError as e:
        logger.log(f"Failed to install {package}: {e.stderr}")
        raise
    except Exception as e:
        logger.log(f"Unexpected error installing {package}: {e}")
        raise
    finally:
        logger.log(f"Exiting check_and_install_pip_package for {package}.")

def verify_opencv_gstreamer_support(logger, deps):
    """Verify if OpenCV has GStreamer support and attempt to fix if missing."""
    logger.log("Starting verify_opencv_gstreamer_support function...")
    if deps.get("opencv_gstreamer_support") == "YES":
        logger.log("OpenCV GStreamer support already verified. Skipping check.")
        return

    logger.log("Checking OpenCV GStreamer support...")
    try:
        build_info = cv2.getBuildInformation()
        gstreamer_support = "YES" if "GStreamer: YES" in build_info else "NO"
        logger.log(f"OpenCV GStreamer support: {gstreamer_support}")

        if gstreamer_support == "NO":
            logger.log("OpenCV lacks GStreamer support. Attempting to install opencv-python-headless...")
            try:
                subprocess.run(
                    ["pip", "install", "--upgrade", "opencv-python-headless==4.11.0.86", "--user", "--break-system-packages"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                logger.log("Installed opencv-python-headless. Reloading cv2 module...")
                try:
                    importlib.reload(cv2)
                    build_info = cv2.getBuildInformation()
                    gstreamer_support = "YES" if "GStreamer: YES" in build_info else "NO"
                    logger.log(f"OpenCV GStreamer support after reinstall: {gstreamer_support}")
                    if gstreamer_support == "NO":
                        logger.log("OpenCV still lacks GStreamer support. Using FFmpeg as backend.")
                except Exception as e:
                    logger.log(f"Failed to reload cv2 module after installing opencv-python-headless: {e}")
                    logger.log("Proceeding with FFmpeg backend.")
                    gstreamer_support = "NO"
            except subprocess.CalledProcessError as e:
                logger.log(f"Failed to install opencv-python-headless: {e.stderr}")
                logger.log("Proceeding with FFmpeg backend.")
                gstreamer_support = "NO"

        deps["opencv_gstreamer_support"] = gstreamer_support
        save_dependency_check(deps, logger)
    except Exception as e:
        logger.log(f"Error verifying OpenCV GStreamer support: {e}")
        deps["opencv_gstreamer_support"] = "NO"
        save_dependency_check(deps, logger)
    finally:
        logger.log("Exiting verify_opencv_gstreamer_support function.")

def install_dependencies(logger):
    """Install all required dependencies using dependency_check.json."""
    logger.log("Entering install_dependencies function...")
    logger.log("Note: This script requires sudo privileges for apt installations. Ensure you have the necessary permissions.")
    deps = load_dependency_check(logger)

    # Install apt dependencies
    logger.log("Installing apt dependencies...")
    apt_packages = [
        "ffmpeg",
        "gstreamer1.0-tools",
        "gstreamer1.0-plugins-good",
        "gstreamer1.0-plugins-bad",
        "gstreamer1.0-plugins-ugly",
        "gstreamer1.0-libav"
    ]
    for package in apt_packages:
        logger.log(f"Processing apt package: {package}")
        try:
            check_and_install_apt_package(package, logger, deps)
        except Exception as e:
            logger.log(f"Failed to check/install apt package {package}: {e}")
            raise

    # Install pip dependencies
    logger.log("Installing pip dependencies...")
    pip_packages = {
        "psutil": "7.0.0",
        "screeninfo": "0.8.1",
        "pynput": "1.8.1",
        "opencv-python": "4.11.0.86"
    }
    for package, version in pip_packages.items():
        logger.log(f"Processing pip package: {package}")
        try:
            check_and_install_pip_package(package, version, logger, deps)
        except Exception as e:
            logger.log(f"Failed to check/install pip package {package}: {e}")
            raise

    # Verify OpenCV GStreamer support
    logger.log("Verifying OpenCV GStreamer support...")
    try:
        verify_opencv_gstreamer_support(logger, deps)
    except Exception as e:
        logger.log(f"Failed to verify OpenCV GStreamer support: {e}")
        raise

    logger.log("Completed install_dependencies function.")

def main():
    # Initialize logger
    logger = Logger()
    logger.log(f"Starting application (version {SCRIPT_VERSION})...")

    # Install dependencies and verify GStreamer support
    try:
        install_dependencies(logger)
    except Exception as e:
        logger.log(f"Failed to install dependencies: {e}")
        sys.exit(1)

    # Load configuration
    logger.log("Loading configuration...")
    config_loader = ConfigLoader()
    try:
        config = config_loader.load_config()
        logger.log("Configuration loaded successfully.")
    except Exception as e:
        logger.log(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Initialize camera manager
    logger.log("Initializing camera manager...")
    try:
        camera_manager = CameraManager(config, logger)
        logger.log("Camera manager initialized. Starting camera feeds...")
        camera_manager.start()
    except Exception as e:
        logger.log(f"Failed to initialize or start camera manager: {e}")
        sys.exit(1)

    # Run the application
    logger.log("Running camera manager...")
    try:
        camera_manager.run()
    except KeyboardInterrupt:
        logger.log("Shutdown initiated by user (Ctrl+C).")
    except Exception as e:
        logger.log(f"Error during camera manager run: {e}")
    finally:
        logger.log("Shutting down camera manager...")
        try:
            camera_manager.shutdown()
            logger.log("Shutdown complete.")
        except Exception as e:
            logger.log(f"Error during shutdown: {e}")
            sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger = Logger()
        logger.log(f"Unhandled exception in main: {e}")
        sys.exit(1)


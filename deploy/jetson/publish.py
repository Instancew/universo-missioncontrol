#!/usr/bin/env python3
"""Supervised, shell-free GStreamer publisher. No package installation or downloads."""
import argparse
import os
import shutil
import subprocess
import sys


def integer(env, key, default, minimum, maximum):
    value = int(env.get(key, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be {minimum}..{maximum}")
    return value


def pipeline(env, has_plugin):
    width = integer(env, "WIDTH", 640, 160, 3840)
    height = integer(env, "HEIGHT", 360, 120, 2160)
    fps = integer(env, "FPS", 15, 1, 120)
    bitrate = integer(env, "BITRATE_KBPS", 700, 100, 30000)
    keyframes = integer(env, "KEYFRAME_SECONDS", 1, 1, 10) * fps
    mode = env.get("ENCODER", "auto")
    source = env.get("SOURCE", "camera")
    if mode not in ("auto", "hardware", "software") or source not in ("camera", "test"):
        raise ValueError("ENCODER=auto|hardware|software; SOURCE=camera|test")
    model = env.get("JETSON_MODEL", "")
    # Orin Nano has no NVENC even if an encoder plugin happens to be installed.
    hardware = "orin nano" not in model.lower() and all(has_plugin(p) for p in ("nvv4l2h264enc", "nvvidconv"))
    if mode == "hardware" and not hardware:
        raise RuntimeError("Hardware encoder unavailable; select ENCODER=software and verify CPU load")
    use_hw = hardware and mode != "software"
    required = ["videoconvert", "videoscale", "videorate", "queue", "h264parse", "rtspclientsink", "watchdog"]
    if source == "test":
        required += ["videotestsrc", "timeoverlay"]
        capture = ["videotestsrc", "is-live=true", "pattern=ball", "!", "timeoverlay"]
    else:
        device = env.get("VIDEO_DEVICE", "/dev/video0")
        if not device.startswith("/dev/"):
            raise ValueError("VIDEO_DEVICE must be a V4L2 /dev path")
        capture = ["v4l2src", f"device={device}", "do-timestamp=true"]
        required += ["v4l2src"]
        camera_format = env.get("CAMERA_FORMAT", "raw")
        if camera_format == "mjpeg":
            required += ["jpegdec"]
            capture += ["!", f"image/jpeg,width={width},height={height},framerate={fps}/1", "!", "jpegdec"]
        elif camera_format != "raw":
            raise ValueError("CAMERA_FORMAT must be raw or mjpeg")
    required += ["nvv4l2h264enc", "nvvidconv"] if use_hw else ["x264enc"]
    missing = [p for p in required if not has_plugin(p)]
    if missing:
        raise RuntimeError("Missing GStreamer plugins: " + ", ".join(missing))
    caps = f"video/x-raw,format=I420,width={width},height={height},framerate={fps}/1"
    encoder = (["nvvidconv", "!", "video/x-raw(memory:NVMM),format=NV12", "!",
                "nvv4l2h264enc", f"bitrate={bitrate * 1000}", f"iframeinterval={keyframes}",
                f"idrinterval={keyframes}", "insert-sps-pps=true", "num-B-Frames=0", "profile=0", "control-rate=1"]
               if use_hw else ["x264enc", "tune=zerolatency", "speed-preset=ultrafast", "bframes=0",
                               f"bitrate={bitrate}", f"key-int-max={keyframes}", "byte-stream=true"])
    # RTSP/TCP is confined to the same Jetson. Wireless transport is WebRTC/UDP.
    return ["gst-launch-1.0", "-e"] + capture + ["!", "videoconvert", "!", "videoscale", "!", "videorate", "!", caps,
        "!", "queue", "leaky=downstream", "max-size-buffers=2", "max-size-bytes=0", "max-size-time=0",
        "!"] + encoder + ["!", "video/x-h264,profile=baseline", "!", "h264parse", "config-interval=-1",
        "!", "watchdog", "timeout=5000", "!", "rtspclientsink", "location=rtsp://127.0.0.1:8554/rovercam",
        "protocols=tcp", "latency=0"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check plugins and print command; do not capture")
    args = parser.parse_args()
    if not shutil.which("gst-inspect-1.0") or not shutil.which("gst-launch-1.0"):
        raise RuntimeError("GStreamer executables are not on PATH")
    env = dict(os.environ)
    try:
        with open("/proc/device-tree/model") as model:
            env["JETSON_MODEL"] = model.read().strip("\x00\n")
    except FileNotFoundError:
        pass
    def installed(name):
        return subprocess.run(["gst-inspect-1.0", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    command = pipeline(env, installed)
    print("Publisher:", " ".join(command), flush=True)
    if not args.check:
        os.execvp(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Publisher startup failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)

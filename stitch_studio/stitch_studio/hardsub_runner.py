from __future__ import annotations

import argparse
import multiprocessing
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VideoInfo:
    frame_count: float
    fps: float
    width: int
    height: int


@dataclass(frozen=True)
class SubtitleArea:
    ymin: int
    ymax: int
    xmin: int
    xmax: int


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _milliseconds_from_parts(parts: list[str]) -> int:
    hour, minute, second, millisecond = [int(value) for value in parts[:4]]
    return ((hour * 60 + minute) * 60 + second) * 1000 + millisecond


def _image_start_ms(path: Path) -> int | None:
    match = re.match(r"^(\d+_\d+_\d+_\d+)__", path.name)
    if not match:
        return None
    return _milliseconds_from_parts(match.group(1).split("_"))


def _resolve_vsf_executable(root: Path) -> Path:
    system = platform.system()
    if system == "Windows":
        candidates = [
            root / "VideoSubFinderWXW.exe",
            root / "windows" / "VideoSubFinderWXW.exe",
            root / "backend" / "subfinder" / "windows" / "VideoSubFinderWXW.exe",
        ]
    elif system == "Darwin":
        candidates = [
            root / "VideoSubFinderCli",
            root / "macos" / "VideoSubFinderCli",
            root / "backend" / "subfinder" / "macos" / "VideoSubFinderCli",
        ]
    else:
        candidates = [
            root / "VideoSubFinderCli.run",
            root / "linux" / "VideoSubFinderCli.run",
            root / "backend" / "subfinder" / "linux" / "VideoSubFinderCli.run",
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(f"VideoSubFinder executable not found under: {root}")


def _probe_video(video_path: Path) -> VideoInfo:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    try:
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if frame_count <= 0 or fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"Could not inspect video for VideoSubFinder: {video_path}")
    return VideoInfo(frame_count=frame_count, fps=fps, width=width, height=height)


def _run_video_subfinder(video_path: Path, output_dir: Path, area: SubtitleArea, info: VideoInfo, root: Path) -> None:
    vsf = _resolve_vsf_executable(root)
    subtitle_dir = output_dir / "subtitle"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    raw_vsf_srt = subtitle_dir / "raw_vsf.srt"

    top_end = 1 - area.ymin / info.height
    bottom_end = 1 - area.ymax / info.height
    left_end = area.xmin / info.width
    right_end = area.xmax / info.width
    cpu_count = max(multiprocessing.cpu_count() - 2, 1)

    cmd = [
        str(vsf),
        "-c",
        "-r",
        "-i",
        str(video_path),
        "-o",
        str(output_dir),
        "-ces",
        str(raw_vsf_srt),
        "-te",
        str(top_end),
        "-be",
        str(bottom_end),
        "-le",
        str(left_end),
        "-re",
        str(right_end),
        "-nthr",
        str(cpu_count),
        "-nocrthr",
        str(cpu_count),
        "--open_video_opencv",
    ]
    if platform.system() == "Windows":
        cmd.insert(1, "--use_cuda")

    print("Running VideoSubFinder...", flush=True)
    duration_ms = max(1, int((info.frame_count / info.fps) * 1000))
    rgb_dir = output_dir / "RGBImages"
    proc = subprocess.Popen(
        cmd,
        cwd=str(vsf.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    last_progress = -1
    while proc.poll() is None:
        latest_ms = 0
        if rgb_dir.exists():
            for image_path in rgb_dir.glob("*"):
                image_ms = _image_start_ms(image_path)
                if image_ms is not None and image_ms > latest_ms:
                    latest_ms = image_ms
        progress = min(99, int(latest_ms * 100 / duration_ms))
        if progress >= last_progress + 2:
            print(f"VSF progress: {progress}%", flush=True)
            last_progress = progress
        time.sleep(1)

    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()[-1200:]
        frame_count = len([path for path in rgb_dir.glob("*") if path.is_file()]) if rgb_dir.exists() else 0
        if frame_count == 0:
            raise RuntimeError(f"VideoSubFinder failed: {detail or f'exit code {proc.returncode}'}")
        print(
            f"VideoSubFinder returned exit code {proc.returncode}, "
            f"but {frame_count} frame(s) were extracted; continuing.",
            flush=True,
        )
    print("VSF progress: 100%", flush=True)


def _ocr_vsf_images(vsf_output_dir: Path, output_srt: Path, mode: str) -> None:
    from rapid_videocr import RapidVideOCR, RapidVideOCRInput

    rgb_dir = vsf_output_dir / "RGBImages"
    images = sorted(path for path in rgb_dir.glob("*") if path.is_file())
    if not images:
        raise RuntimeError(f"VideoSubFinder did not create OCR frames under: {rgb_dir}")

    save_dir = output_srt.parent
    save_name = output_srt.stem
    if output_srt.exists():
        output_srt.unlink()
    input_args = RapidVideOCRInput(
        is_batch_rec=mode in {"fast", "auto"},
        batch_size=10,
        out_format="srt",
    )
    print(f"OCR {len(images)} hard-sub frame(s) with RapidVideOCR...", flush=True)
    extractor_ocr = RapidVideOCR(input_args)
    extractor_ocr(rgb_dir, save_dir, save_name=save_name)
    print(f"OCR progress: {len(images)}/{len(images)}", flush=True)
    if not output_srt.exists() or output_srt.stat().st_size == 0:
        raise RuntimeError("RapidVideOCR finished but did not create a readable SRT.")


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run hard-sub extraction with VideoSubFinder + RapidVideOCR.")
    parser.add_argument("--subfinder-root")
    parser.add_argument("--vse-root", help="Backward-compatible alias for a VSE checkout that contains subfinder.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--mode", default="fast", choices=["fast", "auto", "accurate"])
    parser.add_argument("--ymin", type=int, required=True)
    parser.add_argument("--ymax", type=int, required=True)
    parser.add_argument("--xmin", type=int, required=True)
    parser.add_argument("--xmax", type=int, required=True)
    args = parser.parse_args()
    del args.language

    root_value = args.subfinder_root or args.vse_root
    if not root_value:
        raise SystemExit("Set --subfinder-root, or pass --vse-root for a legacy VSE checkout.")
    subfinder_root = Path(root_value).resolve()
    video_path = Path(args.video).resolve()
    output_dir = video_path.parent / "videosubfinder_output"
    output_srt = video_path.with_suffix(".srt")
    area = SubtitleArea(args.ymin, args.ymax, args.xmin, args.xmax)

    temp_dir = video_path.parent / ".hardsub-temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMP"] = str(temp_dir)

    info = _probe_video(video_path)
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    _run_video_subfinder(video_path, output_dir, area, info, subfinder_root)
    _ocr_vsf_images(output_dir, output_srt, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

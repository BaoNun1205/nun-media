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
from pathlib import Path


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _set_vse_config(vse_config, name: str, value) -> None:
    item = getattr(vse_config.config, name, None)
    if item is None:
        return
    try:
        vse_config.qconfig.set(item, value)
        return
    except Exception:
        pass
    try:
        item.value = value
    except Exception:
        return


def _vse_language(value: str) -> str:
    aliases = {
        "zh": "ch",
        "zh-cn": "ch",
        "zh-hans": "ch",
        "zh-tw": "chinese_cht",
        "zh-hant": "chinese_cht",
        "ja": "japan",
        "jp": "japan",
        "ko": "korean",
        "kr": "korean",
        "vi": "vi",
        "en": "en",
    }
    normalized = (value or "ch").strip().lower()
    return aliases.get(normalized, normalized)


def _patch_vse_runtime() -> None:
    from backend.tools.process_manager import ProcessManager

    ProcessManager.add_process = lambda self, process, name=None: None
    ProcessManager.add_pid = lambda self, pid, name=None: None


def _milliseconds_from_parts(parts: list[str]) -> int:
    hour, minute, second, millisecond = [int(value) for value in parts[:4]]
    return ((hour * 60 + minute) * 60 + second) * 1000 + millisecond


def _image_start_ms(path: Path) -> int | None:
    match = re.match(r"^(\d+_\d+_\d+_\d+)__", path.name)
    if not match:
        return None
    return _milliseconds_from_parts(match.group(1).split("_"))


def _run_video_subfinder(extractor, vse_root: Path) -> None:
    import backend.config as vse_config

    if platform.system() == "Windows":
        vsf = vse_root / "backend" / "subfinder" / "windows" / "VideoSubFinderWXW.exe"
    elif platform.system() == "Darwin":
        vsf = vse_root / "backend" / "subfinder" / "macos" / "VideoSubFinderCli"
    else:
        vsf = vse_root / "backend" / "subfinder" / "linux" / "VideoSubFinderCli.run"
    if not vsf.exists():
        raise RuntimeError(f"VideoSubFinder executable not found: {vsf}")

    subtitle_dir = Path(extractor.subtitle_output_dir)
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    top_end = 1 - extractor.sub_area.ymin / extractor.frame_height
    bottom_end = 1 - extractor.sub_area.ymax / extractor.frame_height
    left_end = extractor.sub_area.xmin / extractor.frame_width
    right_end = extractor.sub_area.xmax / extractor.frame_width
    cpu_count = max(multiprocessing.cpu_count() - 2, 1)
    cores = getattr(vse_config.config, "videoSubFinderCpuCores", None)
    if cores is not None and getattr(cores, "value", 0) > 0:
        cpu_count = cores.value
    decoder = getattr(getattr(vse_config.config, "videoSubFinderDecoder", None), "value", None)
    decoder_name = getattr(decoder, "value", "opencv").lower()

    cmd = [
        str(vsf),
        "-c",
        "-r",
        "-i",
        extractor.video_path,
        "-o",
        extractor.temp_output_dir,
        "-ces",
        extractor.vsf_subtitle,
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
        f"--open_video_{decoder_name}",
    ]
    if platform.system() == "Windows" or extractor.hardware_accelerator.has_accelerator():
        cmd.insert(1, "--use_cuda")

    print("Running VideoSubFinder...", flush=True)
    duration_ms = max(1, int((extractor.frame_count / extractor.fps) * 1000))
    rgb_dir = Path(extractor.temp_output_dir) / "RGBImages"
    proc = subprocess.Popen(
        cmd,
        cwd=str(vse_root),
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


def _ocr_vsf_images(extractor, output_srt: Path, mode: str) -> None:
    from rapid_videocr import RapidVideOCR, RapidVideOCRInput

    rgb_dir = Path(extractor.temp_output_dir) / "RGBImages"
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
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run VSE hardsub extraction non-interactively.")
    parser.add_argument("--vse-root", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--mode", default="fast", choices=["fast", "auto", "accurate"])
    parser.add_argument("--ymin", type=int, required=True)
    parser.add_argument("--ymax", type=int, required=True)
    parser.add_argument("--xmin", type=int, required=True)
    parser.add_argument("--xmax", type=int, required=True)
    args = parser.parse_args()

    vse_root = Path(args.vse_root).resolve()
    if not (vse_root / "backend" / "main.py").exists():
        raise SystemExit(f"VSE backend not found under: {vse_root}")

    cache_dir = vse_root / ".paddlex-cache"
    temp_dir = cache_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_dir)
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HOME"] = str(cache_dir)
    os.environ["USERPROFILE"] = str(cache_dir)
    os.environ["XDG_CACHE_HOME"] = str(cache_dir / ".cache")
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMP"] = str(temp_dir)

    sys.path.insert(0, str(vse_root))
    from backend import config as vse_config
    from backend.bean.subtitle_area import SubtitleArea
    from backend.main import SubtitleExtractor
    _patch_vse_runtime()
    SubtitleExtractor.manage_process = staticmethod(lambda pid: None)

    _set_vse_config(vse_config, "language", _vse_language(args.language))
    _set_vse_config(vse_config, "mode", args.mode)
    _set_vse_config(vse_config, "generateTxt", False)

    extractor = SubtitleExtractor(str(Path(args.video).resolve()))
    extractor.sub_area = SubtitleArea(args.ymin, args.ymax, args.xmin, args.xmax)
    if extractor.video_cap:
        extractor.video_cap.release()
        extractor.video_cap = None
    shutil.rmtree(extractor.temp_output_dir, ignore_errors=True)
    Path(extractor.temp_output_dir).mkdir(parents=True, exist_ok=True)
    _run_video_subfinder(extractor, vse_root)
    _ocr_vsf_images(extractor, Path(args.video).with_suffix(".srt"), args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

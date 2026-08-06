from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .models import AssetItem, VideoItem
from .storage import Storage


Progress = Callable[[str], None]

AUDIO_SEPARATOR_MODEL = "UVR-MDX-NET-Inst_HQ_3.onnx"
AUDIO_SEPARATOR_MODEL_LABEL = "UVR-MDX-NET Inst HQ 3"
AUDIO_MIX_VERSION = "instrumental_mix_95_05_limiter_v2"
INSTRUMENTAL_MIX_GAIN = 0.95
ORIGINAL_MIX_GAIN = 0.05
AUDIO_MODE_ORIGINAL = "original"
AUDIO_MODE_REMOVE_VOCALS = "remove_vocals"
AUDIO_MODE_REMOVE_MUSIC = "remove_music"
AUDIO_MODES = {
    AUDIO_MODE_ORIGINAL,
    AUDIO_MODE_REMOVE_VOCALS,
    AUDIO_MODE_REMOVE_MUSIC,
}

_SEPARATOR_LOCK = threading.Lock()
_TQDM_PERCENT = re.compile(r"(?<!\d)(\d{1,3})%\|")
_CHUNK_PROGRESS = re.compile(r"processing chunk\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)


class AudioSeparationService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage

    def source_fingerprint(self, video: VideoItem) -> str:
        try:
            stat = video.path.stat()
        except OSError:
            return ""
        payload = "|".join(
            (
                str(video.path.resolve()),
                str(stat.st_size),
                str(stat.st_mtime_ns),
                AUDIO_SEPARATOR_MODEL,
                AUDIO_MIX_VERSION,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def cached_stems(self, video: VideoItem) -> dict[str, AssetItem]:
        fingerprint = self.source_fingerprint(video)
        if not fingerprint:
            return {}
        stems: dict[str, AssetItem] = {}
        for asset in self.storage.list_assets(video.id):
            if asset.kind not in {"audio_stem_vocals", "audio_stem_instrumental"}:
                continue
            metadata = asset.metadata or {}
            if metadata.get("source_fingerprint") != fingerprint:
                continue
            if metadata.get("model") != AUDIO_SEPARATOR_MODEL or not asset.path.exists():
                continue
            stem = "vocals" if asset.kind.endswith("vocals") else "instrumental"
            stems.setdefault(stem, asset)
        return stems

    def separate(self, video: VideoItem, progress: Progress) -> dict[str, object]:
        if not video.path.exists():
            raise RuntimeError(f"Source video not found: {video.path}")
        cached = self.cached_stems(video)
        if {"vocals", "instrumental"}.issubset(cached):
            progress("Audio separation cache ready")
            return self._result(cached, reused=True)

        executable = self._separator_executable()
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required for audio separation")

        fingerprint = self.source_fingerprint(video)
        output_root = self.config.outputs_dir / f"video_{video.id}" / "audio_separation"
        output_dir = output_root / fingerprint[:16]
        output_dir.mkdir(parents=True, exist_ok=True)
        input_wav = output_dir / "source.wav"
        vocals_path = output_dir / "vocals.wav"
        raw_instrumental_path = output_dir / "instrumental_raw.wav"
        instrumental_path = output_dir / "instrumental.wav"

        progress("Preparing audio separation (3%)")
        extract = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-vn",
                "-map",
                "0:a:0",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                str(input_wav),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=_no_window_flags(),
        )
        if extract.returncode != 0 or not input_wav.exists() or input_wav.stat().st_size <= 44:
            raise RuntimeError(f"Could not extract source audio: {(extract.stderr or extract.stdout)[-1200:]}")

        custom_names = json.dumps({"Vocals": "vocals", "Instrumental": "instrumental_raw"})
        command = [
            str(executable),
            "--debug",
            "--model_filename",
            AUDIO_SEPARATOR_MODEL,
            "--model_file_dir",
            str(self.config.models_dir / "audio-separator"),
            "--output_dir",
            str(output_dir),
            "--output_format",
            "WAV",
            "--sample_rate",
            "44100",
            "--use_soundfile",
            "--use_directml",
            "--custom_output_names",
            custom_names,
            str(input_wav),
        ]

        try:
            reusable = self._find_reusable_raw_stems(video, output_root, output_dir)
            if reusable:
                progress("Reusing existing HQ3 stems (90%)")
                shutil.copy2(reusable[0], vocals_path)
                shutil.copy2(reusable[1], raw_instrumental_path)
            else:
                progress("Waiting for audio separator (5%)")
                with _SEPARATOR_LOCK:
                    progress("Loading audio separation model (10%)")
                    self._run_separator(command, progress)
                vocals_path = self._find_stem(output_dir, "vocals", vocals_path)
                raw_instrumental_path = self._find_stem(output_dir, "instrumental", raw_instrumental_path)
            if not vocals_path or not raw_instrumental_path:
                found = ", ".join(path.name for path in output_dir.glob("*") if path.is_file())
                raise RuntimeError(f"Audio separator did not create both stems. Files found: {found or 'none'}")

            progress("Audio separation mix: instrumental 95% + original 5% (97%)")
            self._mix_instrumental(ffmpeg, raw_instrumental_path, input_wav, instrumental_path)
        finally:
            input_wav.unlink(missing_ok=True)

        metadata = {
            "model": AUDIO_SEPARATOR_MODEL,
            "source_fingerprint": fingerprint,
            "source_video_path": str(video.path),
            "sample_rate": 44100,
            "instrumental_mix": {
                "instrumental": INSTRUMENTAL_MIX_GAIN,
                "original": ORIGINAL_MIX_GAIN,
                "version": AUDIO_MIX_VERSION,
            },
        }
        vocal_asset_id = self.storage.add_asset(
            video_id=video.id,
            kind="audio_stem_vocals",
            path=vocals_path,
            engine=f"audio-separator:{AUDIO_SEPARATOR_MODEL_LABEL}",
            metadata={**metadata, "stem": "vocals"},
        )
        instrumental_asset_id = self.storage.add_asset(
            video_id=video.id,
            kind="audio_stem_instrumental",
            path=instrumental_path,
            engine=f"audio-separator:{AUDIO_SEPARATOR_MODEL_LABEL}",
            metadata={**metadata, "stem": "instrumental"},
        )
        manifest = {
            **metadata,
            "vocals": str(vocals_path),
            "instrumental_raw": str(raw_instrumental_path),
            "instrumental": str(instrumental_path),
            "vocal_asset_id": vocal_asset_id,
            "instrumental_asset_id": instrumental_asset_id,
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress("Audio separation complete (99%)")
        stems = self.cached_stems(video)
        return self._result(stems, reused=False)

    def stem_for_mode(self, video: VideoItem, mode: str) -> Path | None:
        stems = self.cached_stems(video)
        if mode == AUDIO_MODE_REMOVE_VOCALS:
            asset = stems.get("instrumental")
        elif mode == AUDIO_MODE_REMOVE_MUSIC:
            asset = stems.get("vocals")
        else:
            return None
        return asset.path if asset and asset.path.exists() else None

    def _separator_executable(self) -> Path:
        configured = Path(os.environ.get("STITCH_AUDIO_SEPARATOR_EXE") or self.config.audio_separator_exe)
        if configured.exists():
            return configured
        discovered = shutil.which("audio-separator")
        if discovered:
            return Path(discovered)
        raise RuntimeError(
            "Audio Separator is not installed. Run "
            f"{self.config.audio_separator_root.parent / 'setup_audio_separator.ps1'} first."
        )

    @staticmethod
    def _mix_instrumental(ffmpeg: str, instrumental_path: Path, original_path: Path, output_path: Path) -> None:
        filter_graph = (
            f"[0:a]volume={INSTRUMENTAL_MIX_GAIN}[instrumental];"
            f"[1:a]volume={ORIGINAL_MIX_GAIN}[original];"
            "[instrumental][original]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixed];"
            "[mixed]alimiter=limit=0.98:attack=5:release=50[mix]"
        )
        mixed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(instrumental_path),
                "-i",
                str(original_path),
                "-filter_complex",
                filter_graph,
                "-map",
                "[mix]",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=_no_window_flags(),
        )
        if mixed.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 44:
            raise RuntimeError(f"Could not mix instrumental and original audio: {(mixed.stderr or mixed.stdout)[-1200:]}")

    @staticmethod
    def _find_stem(output_dir: Path, stem: str, preferred: Path) -> Path | None:
        if preferred.exists() and preferred.stat().st_size > 44:
            return preferred
        candidates = sorted(output_dir.glob("*.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            name = path.stem.lower()
            if stem == "vocals" and "vocal" in name and "no_vocal" not in name:
                return path
            if stem == "instrumental" and any(token in name for token in ("instrumental", "no_vocal", "karaoke")):
                return path
        return None

    @staticmethod
    def _find_reusable_raw_stems(video: VideoItem, output_root: Path, current_dir: Path) -> tuple[Path, Path] | None:
        try:
            source_path = video.path.resolve()
            source_mtime = video.path.stat().st_mtime_ns
        except OSError:
            return None
        manifests = sorted(
            output_root.glob("*/manifest.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for manifest_path in manifests:
            if manifest_path.parent == current_dir:
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("model") != AUDIO_SEPARATOR_MODEL:
                    continue
                if Path(str(manifest.get("source_video_path") or "")).resolve() != source_path:
                    continue
                vocals = Path(str(manifest.get("vocals") or ""))
                instrumental_raw = Path(str(manifest.get("instrumental_raw") or ""))
                if not vocals.is_file() or not instrumental_raw.is_file():
                    continue
                if vocals.stat().st_size <= 44 or instrumental_raw.stat().st_size <= 44:
                    continue
                if min(vocals.stat().st_mtime_ns, instrumental_raw.stat().st_mtime_ns) < source_mtime:
                    continue
                return vocals, instrumental_raw
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    @staticmethod
    def _run_separator(command: list[str], progress: Progress) -> None:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
            creationflags=_no_window_flags(),
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("Could not read Audio Separator output")

        recent: deque[str] = deque(maxlen=80)
        buffer = ""
        state = {"phase": "setup"}
        try:
            while True:
                char = process.stdout.read(1)
                if char == "":
                    if buffer.strip():
                        recent.append(buffer.strip())
                        AudioSeparationService._report_progress(buffer, progress, state)
                    break
                if char in {"\r", "\n"}:
                    line = buffer.strip()
                    buffer = ""
                    if line:
                        recent.append(line)
                        AudioSeparationService._report_progress(line, progress, state)
                    continue
                buffer += char
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise

        return_code = process.wait()
        if return_code != 0:
            detail = "\n".join(recent)[-4000:]
            raise RuntimeError(f"Audio Separator failed ({return_code}): {detail}")

    @staticmethod
    def _report_progress(line: str, progress: Progress, state: dict[str, str]) -> None:
        low = line.lower()
        if "downloading file" in low or "downloading model" in low:
            state["phase"] = "download"
        elif "starting separation process" in low:
            state["phase"] = "separate"
        percent_match = _TQDM_PERCENT.search(line)
        if percent_match:
            raw = min(100, int(percent_match.group(1)))
            value = 10 + round(raw * 0.08) if state.get("phase") == "download" else 20 + round(raw * 0.68)
            progress(f"Audio separation progress: {value}%")
            return
        chunk_match = _CHUNK_PROGRESS.search(line)
        if chunk_match:
            current = int(chunk_match.group(1))
            total = max(1, int(chunk_match.group(2)))
            value = 20 + round(min(current / total, 1.0) * 68)
            progress(f"Audio separation progress: {value}%")
            return
        if "downloading file" in low or "downloading model" in low:
            progress("Downloading audio separation model (12%)")
        elif "loading model" in low:
            progress("Loading audio separation model (16%)")
        elif "starting separation process" in low:
            progress("Separating vocals and music (20%)")
        elif "saving instrumental" in low:
            progress("Saving instrumental stem (91%)")
        elif "saving vocals" in low:
            progress("Saving vocal stem (95%)")

    @staticmethod
    def _result(stems: dict[str, AssetItem], *, reused: bool) -> dict[str, object]:
        return {
            "model": AUDIO_SEPARATOR_MODEL,
            "reused": reused,
            "vocalsAssetId": stems.get("vocals").id if stems.get("vocals") else None,
            "instrumentalAssetId": stems.get("instrumental").id if stems.get("instrumental") else None,
            "outputPath": str(stems.get("instrumental").path) if stems.get("instrumental") else "",
        }


def _no_window_flags() -> int:
    if sys.platform.startswith("win"):
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0

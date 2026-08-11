from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from .config import AppConfig
from .models import SubtitleSegment, VideoItem
from .srt import read_srt, write_srt
from .storage import Storage
from .subtitle_timeline_scaler import AdaptiveTimelineError, DEFAULT_SLOT_MAX_SPEED, process_adaptive_timeline, process_srt_slot_timeline

Progress = Callable[[str], None]

HTTP_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
MEDIA_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES


def extract_video_url(text: str) -> str:
    value = text.strip()
    match = HTTP_URL_RE.search(value)
    url = (match.group(0) if match else value).rstrip(".,;:!?)]}'\"")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("No valid http(s) video URL found in pasted text.")
    return url


def _rename_download_with_timestamp(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    micros = (time.time_ns() // 1_000) % 1_000_000
    suffix = path.suffix.lower() or ".mp4"
    candidate = path.with_name(f"{stamp}_{micros:06d}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{stamp}_{micros:06d}_{counter}{suffix}")
        counter += 1
    path.replace(candidate)
    return candidate


class DownloaderService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage

    def download_url(self, url: str, progress: Optional[Progress] = None) -> list[int]:
        url = extract_video_url(url)
        if _is_douyin_url(url):
            return self._download_with_douyin_downloader(url, progress)

        if not self.config.lazy_downloader_cli.exists():
            raise RuntimeError(f"Lazy-downloader CLI not found: {self.config.lazy_downloader_cli}")

        _emit(progress, "Downloading with Lazy-downloader...")
        cmd = [
            "node",
            str(self.config.lazy_downloader_cli),
            url,
            "-P",
            str(self.config.downloads_dir),
            "--all",
            "--timeout",
            "120",
            "--retries",
            "2",
            "--write-json",
            "--output-file",
            "lazy_result",
            "--quiet",
            "--no-print-json",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(self.config.lazy_downloader_cli.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
        if proc.returncode != 0:
            lazy_error = (proc.stderr or proc.stdout or "Lazy-downloader failed").strip()
            if _should_fallback_to_ytdlp(lazy_error):
                if _is_douyin_url(url):
                    try:
                        _emit(progress, f"Lazy-downloader blocked ({lazy_error}). Falling back to Lux...")
                        return self._download_with_lux(url, progress)
                    except Exception as exc:
                        _emit(progress, f"Lux failed ({exc}). Falling back to yt-dlp...")
                else:
                    _emit(progress, f"Lazy-downloader blocked ({lazy_error}). Falling back to yt-dlp...")
                return self._download_with_ytdlp(url, progress)
            raise RuntimeError(_friendly_lazy_error(lazy_error))

        payload = _load_lazy_payload(proc.stdout)
        json_path = payload.get("jsonPath")
        if json_path and Path(json_path).exists():
            payload = json.loads(Path(json_path).read_text(encoding="utf-8"))

        ids: list[int] = []
        for media in payload.get("medias", []):
            saved = media.get("savedPath") or media.get("localPath")
            if not saved:
                continue
            path = Path(saved)
            if not path.exists():
                continue
            original_title = media.get("title") or payload.get("json", {}).get("title") or path.stem
            path = _rename_download_with_timestamp(path)
            ids.append(
                self.storage.upsert_video(
                    title=path.stem,
                    source_url=media.get("webpage_url") or url,
                    source=media.get("source") or payload.get("json", {}).get("source") or "",
                    path=path,
                    media_type=media.get("type") or "video",
                    duration_ms=_duration_to_ms(media.get("duration") or payload.get("json", {}).get("duration")) or _probe_video_duration_ms(path),
                    size_bytes=media.get("filesize") or (path.stat().st_size if path.exists() else None),
                    metadata={**media, "original_title": original_title},
                )
            )

        if not ids:
            paths = [Path(p) for p in payload.get("paths", [])]
            for source_path in paths:
                if not source_path.exists():
                    continue
                path = _rename_download_with_timestamp(source_path)
                ids.append(
                    self.storage.upsert_video(
                        title=path.stem,
                        source_url=url,
                        source="lazy-downloader",
                        path=path,
                        media_type="audio" if path.suffix.lower() in AUDIO_SUFFIXES else "video",
                        duration_ms=_probe_video_duration_ms(path),
                        size_bytes=path.stat().st_size,
                        metadata={"downloader": "lazy-downloader", "original_title": source_path.stem},
                    )
                )
        _emit(progress, f"Downloaded {len(ids)} media file(s).")
        return ids

    def _download_with_douyin_downloader(self, url: str, progress: Optional[Progress] = None) -> list[int]:
        python = self.config.douyin_downloader_python
        run_py = self.config.douyin_downloader_root / "run.py"
        if not python.exists() or not run_py.exists():
            raise RuntimeError(
                "Douyin downloader is not installed. Expected "
                f"{python} and {run_py}."
            )

        self.config.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.config.douyin_downloader_config_path.parent.mkdir(parents=True, exist_ok=True)
        cookies = _parse_cookie_header(_read_cookie_file(self.config.douyin_cookie_path))
        missing_cookies = _missing_required_douyin_cookies(cookies)
        if missing_cookies:
            raise RuntimeError(
                "No valid Douyin cookie is saved yet. Open Settings, paste a fresh Cookie header "
                "from www.douyin.com, then retry. Missing cookie key(s): "
                f"{', '.join(missing_cookies)}"
            )
        self.config.douyin_downloader_config_path.write_text(
            json.dumps(
                _douyin_downloader_config(
                    url=url,
                    downloads_dir=self.config.downloads_dir,
                    cookies=cookies,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        before = _media_files(self.config.downloads_dir)
        env = _without_proxy_env()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["TEMP"] = str(self.config.douyin_downloader_config_path.parent / ".tmp")
        env["TMP"] = env["TEMP"]
        Path(env["TEMP"]).mkdir(parents=True, exist_ok=True)

        cmd = [
            str(python),
            str(run_py),
            "--config",
            str(self.config.douyin_downloader_config_path),
            "--path",
            str(self.config.downloads_dir),
            "--thread",
            "1",
            "--show-warnings",
        ]

        _emit(progress, "Downloading Douyin video with douyin-downloader (highest quality)...")
        proc = subprocess.run(
            cmd,
            cwd=str(self.config.douyin_downloader_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
            env=env,
        )
        after = _media_files(self.config.downloads_dir)
        new_paths = sorted(after - before, key=lambda path: path.stat().st_mtime)

        if proc.returncode != 0 or not new_paths:
            detail = _strip_ansi((proc.stderr or proc.stdout or "").strip())
            if not detail and not new_paths:
                detail = "douyin-downloader finished but no downloaded media file was found."
            raise RuntimeError(_friendly_douyin_downloader_error(detail))

        ids: list[int] = []
        for source_path in new_paths:
            path = _rename_download_with_timestamp(source_path)
            ids.append(
                self.storage.upsert_video(
                    title=path.stem,
                    source_url=url,
                    source="douyin-downloader",
                    path=path,
                    media_type="audio" if path.suffix.lower() in AUDIO_SUFFIXES else "video",
                    duration_ms=_probe_video_duration_ms(path),
                    size_bytes=path.stat().st_size,
                    metadata={"downloader": "douyin-downloader", "video_quality": "highest", "original_title": source_path.stem},
                )
            )
        _emit(progress, f"Downloaded {len(ids)} media file(s) with douyin-downloader.")
        return ids

    def _download_with_lux(self, url: str, progress: Optional[Progress] = None) -> list[int]:
        lux = str(self.config.lux_cli) if self.config.lux_cli.exists() else shutil.which("lux")
        if not lux:
            raise RuntimeError("Lux CLI is not installed.")

        self.config.downloads_dir.mkdir(parents=True, exist_ok=True)
        manual_cookie = _read_cookie_file(self.config.douyin_cookie_path)
        attempts = []
        if manual_cookie:
            attempts.append(("Lux with manual cookies", ["--cookie", manual_cookie]))
        attempts.append(("Lux", []))

        last_error = "Lux failed."
        new_paths: list[Path] = []
        for label, extra_args in attempts:
            before = _media_files(self.config.downloads_dir)
            cmd = [
                lux,
                "--output-path",
                str(self.config.downloads_dir),
                "--retry",
                "3",
                *extra_args,
                url,
            ]

            _emit(progress, f"Downloading with {label}...")
            proc = subprocess.run(
                cmd,
                cwd=str(self.config.downloads_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                check=False,
                env=_without_proxy_env(),
            )
            after = _media_files(self.config.downloads_dir)
            new_paths = sorted(after - before, key=lambda path: path.stat().st_mtime)
            if new_paths:
                break
            last_error = (proc.stderr or proc.stdout or f"{label} failed").strip()
            if label != attempts[-1][0]:
                _emit(progress, f"{label} did not produce a media file. Trying next method...")

        if not new_paths:
            raise RuntimeError(last_error[-1000:] or "Lux finished but no downloaded media file was found.")

        ids: list[int] = []
        for source_path in new_paths:
            path = _rename_download_with_timestamp(source_path)
            ids.append(
                self.storage.upsert_video(
                    title=path.stem,
                    source_url=url,
                    source="lux:douyin",
                    path=path,
                    media_type="audio" if path.suffix.lower() in AUDIO_SUFFIXES else "video",
                    duration_ms=_probe_video_duration_ms(path),
                    size_bytes=path.stat().st_size,
                    metadata={"downloader": "lux", "original_title": source_path.stem},
                )
            )
        _emit(progress, f"Downloaded {len(ids)} media file(s) with Lux.")
        return ids

    def _download_with_f2(self, url: str, progress: Optional[Progress] = None) -> list[int]:
        f2 = shutil.which("f2")
        if not f2:
            raise RuntimeError("F2 CLI is not installed.")

        self.config.downloads_dir.mkdir(parents=True, exist_ok=True)
        env = _without_proxy_env()
        env.setdefault("PYTHONIOENCODING", "utf-8")

        attempts = []
        manual_cookie = _read_cookie_file(self.config.douyin_cookie_path)
        if manual_cookie:
            attempts.append(("F2 with manual cookies", ["--cookie", manual_cookie]))
        attempts.extend(
            [
                ("F2", []),
                ("F2 with Chrome cookies", ["--auto-cookie", "chrome"]),
                ("F2 with Edge cookies", ["--auto-cookie", "edge"]),
            ]
        )
        last_error = "F2 failed."
        new_paths: list[Path] = []
        for label, extra_args in attempts:
            before = _media_files(self.config.downloads_dir)
            cmd = [
                f2,
                "dy",
                "--url",
                url,
                "--path",
                str(self.config.downloads_dir),
                "--mode",
                "one",
                "--languages",
                "en_US",
                *extra_args,
            ]

            _emit(progress, f"Downloading with {label}...")
            proc = subprocess.run(
                cmd,
                cwd=str(self.config.downloads_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                check=False,
                env=env,
            )
            after = _media_files(self.config.downloads_dir)
            new_paths = sorted(after - before, key=lambda path: path.stat().st_mtime)
            if new_paths:
                break
            last_error = (proc.stderr or proc.stdout or f"{label} failed").strip()
            if label != attempts[-1][0]:
                _emit(progress, f"{label} did not produce a media file. Trying next method...")
        if not new_paths:
            raise RuntimeError(last_error[-1000:] or "F2 finished but no downloaded media file was found.")

        ids: list[int] = []
        for source_path in new_paths:
            path = _rename_download_with_timestamp(source_path)
            ids.append(
                self.storage.upsert_video(
                    title=path.stem,
                    source_url=url,
                    source="f2:douyin",
                    path=path,
                    media_type="audio" if path.suffix.lower() in AUDIO_SUFFIXES else "video",
                    duration_ms=_probe_video_duration_ms(path),
                    size_bytes=path.stat().st_size,
                    metadata={"downloader": "f2", "original_title": source_path.stem},
                )
            )
        _emit(progress, f"Downloaded {len(ids)} media file(s) with F2.")
        return ids

    def _download_with_ytdlp(self, url: str, progress: Optional[Progress] = None) -> list[int]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise RuntimeError(
                "Lazy-downloader was blocked and yt-dlp is not installed. "
                "Install it with: py -3.11 -m pip install yt-dlp"
            ) from exc

        self.config.downloads_dir.mkdir(parents=True, exist_ok=True)

        def hook(data: dict) -> None:
            status = data.get("status")
            if status == "downloading":
                percent = data.get("_percent_str", "").strip()
                speed = data.get("_speed_str", "").strip()
                eta = data.get("_eta_str", "").strip()
                _emit(progress, f"yt-dlp downloading {percent} {speed} ETA {eta}".strip())
            elif status == "finished":
                _emit(progress, "yt-dlp download finished; finalizing...")

        base_ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": str(self.config.downloads_dir / "%(title).180B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [hook],
            "windowsfilenames": True,
        }

        attempts = [("yt-dlp", {})]
        if "douyin.com" in url.lower():
            manual_cookie = _read_cookie_file(self.config.douyin_cookie_path)
            if manual_cookie:
                attempts.append(("yt-dlp with manual cookies", {"http_headers": {"Cookie": manual_cookie}}))
            attempts.extend(_browser_cookie_attempts())

        last_error: Exception | None = None
        info = None
        ydl = None
        for label, extra_opts in attempts:
            _emit(progress, f"Downloading with {label}...")
            try:
                with YoutubeDL({**base_ydl_opts, **extra_opts}) as active_ydl:
                    info = active_ydl.extract_info(url, download=True)
                    ydl = active_ydl
                break
            except Exception as exc:
                last_error = exc
                if label != attempts[-1][0]:
                    _emit(progress, f"{label} failed ({exc}). Trying next method...")

        if info is None or ydl is None:
            raise RuntimeError(str(last_error or "yt-dlp failed."))

        entries = info.get("entries") if isinstance(info, dict) else None
        infos = [item for item in entries if item] if entries else [info]
        ids: list[int] = []
        for item in infos:
            path = _ytdlp_filepath(item, ydl)
            if not path or not path.exists():
                continue
            original_title = item.get("title") or path.stem
            path = _rename_download_with_timestamp(path)
            ids.append(
                self.storage.upsert_video(
                    title=path.stem,
                    source_url=item.get("webpage_url") or url,
                    source=str(item.get("extractor_key") or item.get("extractor") or "yt-dlp").lower(),
                    path=path,
                    media_type="audio" if str(item.get("vcodec")) == "none" else "video",
                    duration_ms=_duration_to_ms(item.get("duration")) or _probe_video_duration_ms(path),
                    size_bytes=path.stat().st_size if path.exists() else item.get("filesize"),
                    metadata={**_compact_ytdlp_metadata(item), "original_title": original_title},
                )
            )

        if not ids:
            raise RuntimeError("yt-dlp finished but no downloaded media file was found.")
        _emit(progress, f"Downloaded {len(ids)} media file(s) with yt-dlp.")
        return ids


class TranscriptionService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._whisper_model: Any | None = None
        self._whisper_model_key: tuple[str, str, str] | None = None
        self._whisper_model_lock = threading.Lock()

    def generate_srt(
        self,
        video: VideoItem,
        *,
        model_name: str = "large-v3",
        device: str = "auto",
        language: str = "vi",
        timeline_speed: float = 1.0,
        progress: Optional[Progress] = None,
    ) -> Path:
        output_dir = self.config.outputs_dir / f"video_{video.id}"
        srt_path = output_dir / f"{video.path.stem}.{model_name}.srt"
        model = self._get_whisper_model(model_name=model_name, device=device, progress=progress)
        _emit(progress, "Transcribing...")
        segments_iter, info = model.transcribe(
            str(video.path),
            language=None if not language or language == "auto" else language,
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        duration_seconds = float(getattr(info, "duration", 0) or 0)
        if duration_seconds <= 0 and video.duration_ms:
            duration_seconds = video.duration_ms / 1000
        timeline_speed = max(0.1, min(80.0, float(timeline_speed)))
        time_scale = 1.0 / timeline_speed
        if abs(timeline_speed - 1.0) > 0.000001:
            _emit(progress, f"Mapping SRT timestamps to {timeline_speed:.2f}x video speed...")

        segments: list[SubtitleSegment] = []
        last_percent = -1
        for index, segment in enumerate(segments_iter, start=1):
            segments.append(
                SubtitleSegment(index=index, start=float(segment.start) * time_scale, end=float(segment.end) * time_scale, text=segment.text.strip())
            )
            if duration_seconds > 0:
                percent = min(99, int((float(segment.end) / duration_seconds) * 100))
                if percent > last_percent:
                    _emit(progress, f"Transcribing progress: {percent}%")
                    last_percent = percent
        write_srt(segments, srt_path)
        self.storage.add_asset(
            video_id=video.id,
            kind="srt",
            path=srt_path,
            engine=f"faster-whisper:{model_name}",
            metadata={
                "language": getattr(info, "language", language),
                "duration": getattr(info, "duration", None),
                "timeline_speed": timeline_speed,
                "timeline_time_scale": time_scale,
            },
        )
        _emit(progress, f"SRT exported: {srt_path}")
        return srt_path

    def transcribe_audio_text(
        self,
        audio_path: Path,
        *,
        model_name: str = "base",
        device: str = "cpu",
        language: str = "auto",
        progress: Optional[Progress] = None,
    ) -> str:
        """Transcribe a short reference recording with Stitch's faster-whisper."""
        if not audio_path.exists():
            raise RuntimeError(f"Reference audio not found: {audio_path}")
        model = self._get_whisper_model(model_name=model_name, device=device, progress=progress)
        _emit(progress, "Transcribing reference voice with faster-whisper...")
        segments_iter, _info = model.transcribe(
            str(audio_path),
            language=None if not language or language == "auto" else language,
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = " ".join(segment.text.strip() for segment in segments_iter if segment.text.strip()).strip()
        if not text:
            raise RuntimeError("faster-whisper could not detect speech in the reference audio.")
        _emit(progress, "Reference voice transcript ready.")
        return text

    def _get_whisper_model(
        self,
        *,
        model_name: str,
        device: str,
        progress: Optional[Progress],
    ):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Missing faster-whisper. Install it to enable local transcription.") from exc
        compute_type = "float16" if device == "cuda" else "int8"
        model_key = (model_name, device, compute_type)
        with self._whisper_model_lock:
            model = self._whisper_model if self._whisper_model_key == model_key else None
            if model is None:
                _emit(progress, f"Loading faster-whisper model {model_name}...")
                try:
                    model = WhisperModel(model_name, device=device, compute_type=compute_type)
                except Exception as exc:
                    detail = str(exc)
                    if "snapshot folder" in detail or "connection" in detail.lower() or "hub" in detail.lower():
                        raise RuntimeError(
                            f"Whisper model '{model_name}' is not fully downloaded on this machine. "
                            "Connect to the internet once to download it, then retry."
                        ) from exc
                    raise
                self._whisper_model = model
                self._whisper_model_key = model_key
                _emit(progress, "Whisper model ready.")
            else:
                _emit(progress, f"Using cached faster-whisper model {model_name}.")
        return model

    def generate_hardsub_srt(
        self,
        video: VideoItem,
        *,
        language: str = "vi",
        mode: str = "fast",
        area: dict | str | None = None,
        timeline_speed: float = 1.0,
        progress: Optional[Progress] = None,
    ) -> dict[str, Any]:
        subfinder_root = Path(
            os.environ.get("VIDEOSUBFINDER_ROOT")
            or os.environ.get("VSE_ROOT")
            or self.config.videosubfinder_root
        )
        hardsub_python = _resolve_hardsub_python(self.config.hardsub_python)
        if not _has_videosubfinder(subfinder_root):
            raise RuntimeError(
                "VideoSubFinder is not installed. Put the standalone VideoSubFinder files under "
                f"{self.config.videosubfinder_root} or set VIDEOSUBFINDER_ROOT."
            )
        if mode not in {"fast", "auto", "accurate"}:
            raise RuntimeError(f"Unsupported VSE mode: {mode}")

        output_dir = self.config.outputs_dir / f"video_{video.id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = output_dir / "vse_hardsub"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_video = staging_dir / f"input{video.path.suffix.lower() or '.mp4'}"
        staging_srt = staging_video.with_suffix(".srt")
        srt_path = output_dir / f"{video.path.stem}.vse-{mode}.srt"

        _emit(progress, "Preparing video for hard-sub OCR...")
        shutil.copy2(video.path, staging_video)
        width, height = _probe_video_size(staging_video)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Could not detect video dimensions for hard-sub OCR: {video.path}")

        ymin, ymax, xmin, xmax = _resolve_subtitle_area(area, width, height)

        runner = Path(__file__).resolve().parent / "hardsub_runner.py"
        cmd = [
            str(hardsub_python),
            str(runner),
            "--subfinder-root",
            str(subfinder_root),
            "--video",
            str(staging_video),
            "--language",
            language or "vi",
            "--mode",
            mode,
            "--ymin",
            str(ymin),
            "--ymax",
            str(ymax),
            "--xmin",
            str(xmin),
            "--xmax",
            str(xmax),
        ]
        _emit(progress, f"Running hard-sub OCR with VideoSubFinder + RapidVideOCR ({mode})...")
        env = os.environ.copy()
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            }
        )
        output_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            cwd=str(subfinder_root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            output_lines.append(line)
            _emit(progress, line)
        return_code = proc.wait()
        if return_code != 0:
            detail = "\n".join(output_lines).strip()[-1200:]
            raise RuntimeError(f"RapidVideOCR hard-sub OCR failed: {detail}")
        if not staging_srt.exists():
            detail = "\n".join(output_lines).strip()[-1200:]
            raise RuntimeError(f"RapidVideOCR finished but did not create an SRT file. {detail}")

        _publish_srt_file(staging_srt, srt_path)
        timeline_speed = max(0.1, min(80.0, float(timeline_speed)))
        time_scale = 1.0 / timeline_speed
        if abs(timeline_speed - 1.0) > 0.000001:
            scaled_segments = [
                SubtitleSegment(segment.index, segment.start * time_scale, segment.end * time_scale, segment.text)
                for segment in read_srt(srt_path)
            ]
            write_srt(scaled_segments, srt_path)
            _emit(progress, f"Mapped hard-sub SRT timestamps to {timeline_speed:.2f}x video speed.")
        self.storage.add_asset(
            video_id=video.id,
            kind="srt",
            path=srt_path,
            engine=f"rapid-videocr:{mode}",
            metadata={
                "language": language,
                "source": "hard-sub-ocr",
                "videosubfinder_root": str(subfinder_root),
                "subtitle_area": {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
                "subtitle_area_ratio": {
                    "xmin": xmin / width,
                    "xmax": xmax / width,
                    "ymin": ymin / height,
                    "ymax": ymax / height,
                },
                "timeline_speed": timeline_speed,
                "timeline_time_scale": time_scale,
            },
        )
        _emit(progress, f"Hard-sub SRT exported: {srt_path}")
        return srt_path


class SubtitleRemovalService:
    AI_MODE_MAP = {
        "fast": "sttn-auto",
        "quality": "lama",
        "bestMotion": "propainter",
        "basic": "opencv",
    }
    FFMPEG_MODES = {"blur", "cover"}
    AUTO_BLUR_MODE = "autoBlur"

    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._lock = threading.Lock()

    def configure_blur_effect(
        self,
        video: VideoItem,
        *,
        mode: str,
        area: dict | str | None = "bottom",
        srt_path: Path | None = None,
        srt_asset_id: int | None = None,
        progress: Optional[Progress] = None,
    ) -> dict[str, Any]:
        if mode not in {"manual", "auto"}:
            raise RuntimeError(f"Unsupported blur effect mode: {mode}")
        width, height = _probe_video_size(video.path)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Could not detect video dimensions: {video.path}")

        longest_segment: SubtitleSegment | None = None
        detection_source = "manual"
        if mode == "manual":
            ymin, ymax, xmin, xmax = _resolve_subtitle_area(area, width, height)
        else:
            if not srt_path or srt_asset_id is None or not srt_path.exists():
                raise RuntimeError("Automatic blur requires an existing SRT file.")
            segments = [segment for segment in read_srt(srt_path) if segment.text.strip()]
            if not segments:
                raise RuntimeError("The selected SRT contains no subtitle text.")
            longest_segment = max(
                segments,
                key=lambda segment: (len(re.sub(r"\s+", "", segment.text)), len(segment.text)),
            )
            fallback = _default_subtitle_area(width, height)
            ymin, ymax, xmin, xmax = fallback
            detection_source = "fallback"
            try:
                detected = self._detect_single_subtitle_box(
                    video,
                    longest_segment,
                    srt_asset_id=srt_asset_id,
                    progress=progress,
                )
                if detected:
                    ymin, ymax, xmin, xmax = detected
                    detection_source = "ocr-longest-srt-line"
            except Exception as exc:
                _emit(progress, f"Auto blur OCR fallback: {exc}")

        effect_area = {
            "xmin": max(0.0, min(1.0, xmin / width)),
            "xmax": max(0.0, min(1.0, xmax / width)),
            "ymin": max(0.0, min(1.0, ymin / height)),
            "ymax": max(0.0, min(1.0, ymax / height)),
        }
        effect = {
            "enabled": True,
            "kind": "subtitle_blur",
            "mode": mode,
            "area": effect_area,
            "source": detection_source,
            "srt_asset_id": srt_asset_id,
            "longest_segment_index": longest_segment.index if longest_segment else None,
            "longest_segment_text": longest_segment.text if longest_segment else None,
            "updated_at": time.time(),
        }
        metadata = dict(video.metadata or {})
        metadata["subtitle_blur_effect"] = effect
        self.storage.update_video_metadata(video.id, metadata)
        _emit(progress, f"Subtitle blur effect ready ({mode})")
        return {"videoId": video.id, "effect": effect}

    def _detect_single_subtitle_box(
        self,
        video: VideoItem,
        segment: SubtitleSegment,
        *,
        srt_asset_id: int,
        progress: Optional[Progress],
    ) -> tuple[int, int, int, int] | None:
        vsr_python = Path(os.environ.get("VSR_PYTHON") or self.config.vsr_python)
        vsr_root = Path(os.environ.get("VSR_ROOT") or self.config.vsr_root)
        model_dir = vsr_root / "backend" / "models" / "V5" / "ch_det_fast"
        runner = Path(__file__).with_name("subtitle_mask_runner.py")
        if not vsr_python.exists() or not model_dir.exists() or not runner.exists():
            raise RuntimeError("OCR runtime or PP-OCRv5 detection model is unavailable")

        output_dir = self.config.outputs_dir / f"video_{video.id}" / "blur_effect"
        temp_dir = output_dir / ".tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        clip_speed = float(((video.metadata or {}).get("clip_settings") or {}).get("videoSpeed") or 1.0)
        source_segment = SubtitleSegment(
            segment.index,
            max(0.0, segment.start * clip_speed),
            max(0.001, segment.end * clip_speed),
            segment.text,
        )
        sample_srt = temp_dir / f"longest_{srt_asset_id}_{segment.index}.srt"
        plan_path = output_dir / f"longest_{srt_asset_id}_{segment.index}.json"
        write_srt([source_segment], sample_srt)

        cache_dir = self.config.models_dir / "vsr_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        env = _vsr_runtime_environment(cache_dir=cache_dir, temp_dir=temp_dir)
        command = [
            str(vsr_python),
            str(runner),
            "--video",
            str(video.path),
            "--srt",
            str(sample_srt),
            "--output",
            str(plan_path),
            "--model-dir",
            str(model_dir),
            "--xmin",
            "0.02",
            "--xmax",
            "0.98",
            "--ymin",
            "0.20",
            "--ymax",
            "0.99",
            "--exact-box",
            "--single-sample",
        ]
        _emit(progress, f"OCR longest SRT line #{segment.index} at its midpoint...")
        proc = subprocess.run(
            command,
            cwd=str(vsr_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not plan_path.exists():
            raise RuntimeError((proc.stderr or proc.stdout or "OCR did not return a subtitle box")[-800:])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        rows = plan.get("segments") or []
        bbox = (rows[0] if rows else {}).get("bbox")
        if not bbox:
            return None
        return int(bbox["ymin"]), int(bbox["ymax"]), int(bbox["xmin"]), int(bbox["xmax"])

    def remove_subtitles(
        self,
        video: VideoItem,
        *,
        mode: str = "blur",
        area: dict | str | None = "bottom",
        srt_path: Path | None = None,
        srt_asset_id: int | None = None,
        progress: Optional[Progress] = None,
    ) -> Path:
        with self._lock:
            return self._remove_subtitles_locked(
                video,
                mode=mode,
                area=area,
                srt_path=srt_path,
                srt_asset_id=srt_asset_id,
                progress=progress,
            )

    def _remove_subtitles_locked(
        self,
        video: VideoItem,
        *,
        mode: str,
        area: dict | str | None,
        srt_path: Path | None,
        srt_asset_id: int | None,
        progress: Optional[Progress],
    ) -> Path:
        if mode == self.AUTO_BLUR_MODE:
            if not srt_path or srt_asset_id is None:
                raise RuntimeError("Automatic timed blur requires an original SRT file.")
            return self._hide_subtitles_from_srt(
                video,
                srt_path=srt_path,
                srt_asset_id=srt_asset_id,
                area=area,
                progress=progress,
            )
        if mode in self.FFMPEG_MODES:
            return self._hide_subtitles_with_ffmpeg(video, mode=mode, area=area, progress=progress)

        vsr_mode = self.AI_MODE_MAP.get(mode)
        if not vsr_mode:
            raise RuntimeError(f"Unsupported subtitle removal mode: {mode}")

        vsr_root = Path(os.environ.get("VSR_ROOT") or self.config.vsr_root)
        vsr_python = Path(os.environ.get("VSR_PYTHON") or self.config.vsr_python)
        vsr_main = vsr_root / "backend" / "main.py"
        if not vsr_root.exists() or not vsr_main.exists():
            raise RuntimeError(
                "Video Subtitle Remover is not installed. Expected "
                f"{vsr_main}. Put YaoFANGUK/video-subtitle-remover under {self.config.vsr_root} "
                "or set VSR_ROOT."
            )
        if not vsr_python.exists():
            raise RuntimeError(
                "Video Subtitle Remover Python env is not installed. Expected "
                f"{vsr_python}. Create the separate runtime under tools/vsr-env or set VSR_PYTHON."
            )

        output_dir = self.config.outputs_dir / f"video_{video.id}" / "removed_subtitles"
        staging_dir = output_dir / "stage"
        temp_dir = output_dir / ".tmp"
        cache_dir = self.config.models_dir / "vsr_cache"
        output_dir.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        _emit(progress, "Preparing subtitle removal...")
        staging_video = staging_dir / f"input{video.path.suffix.lower() or '.mp4'}"
        shutil.copy2(video.path, staging_video)
        width, height = _probe_video_size(staging_video)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Could not detect video dimensions for subtitle removal: {video.path}")

        ymin, ymax, xmin, xmax = _resolve_subtitle_area(area, width, height)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"{video.path.stem}.nosub.{mode}.{stamp}.mp4"
        cmd = [
            str(vsr_python),
            str(vsr_main),
            "-i",
            str(staging_video),
            "-o",
            str(output_path),
            "--subtitle-area-coords",
            str(ymin),
            str(ymax),
            str(xmin),
            str(xmax),
            "--inpaint-mode",
            vsr_mode,
        ]
        env = os.environ.copy()
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "TEMP": str(temp_dir),
                "TMP": str(temp_dir),
                "HOME": str(cache_dir),
                "USERPROFILE": str(cache_dir),
                "XDG_CACHE_HOME": str(cache_dir / ".cache"),
                "HF_HOME": str(cache_dir / "huggingface"),
                "PADDLE_HOME": str(cache_dir / "paddle"),
                "PADDLEOCR_HOME": str(cache_dir / "paddleocr"),
                "PADDLE_PDX_CACHE_HOME": str(cache_dir / "paddlex"),
                "MPLCONFIGDIR": str(cache_dir / "matplotlib"),
                "PYTHONPYCACHEPREFIX": str(cache_dir / "pycache"),
            }
        )
        for value in [
            env["XDG_CACHE_HOME"],
            env["HF_HOME"],
            env["PADDLE_HOME"],
            env["PADDLEOCR_HOME"],
            env["PADDLE_PDX_CACHE_HOME"],
            env["MPLCONFIGDIR"],
            env["PYTHONPYCACHEPREFIX"],
        ]:
            Path(value).mkdir(parents=True, exist_ok=True)

        _emit(progress, f"Removing subtitles with VSR ({vsr_mode})...")
        output_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            cwd=str(vsr_root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        _stream_vsr_output(proc.stdout, output_lines, progress)
        return_code = proc.wait()
        if return_code != 0:
            detail = "\n".join(output_lines).strip()[-1600:]
            raise RuntimeError(f"Video Subtitle Remover failed: {detail or f'exit code {return_code}'}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            detail = "\n".join(output_lines).strip()[-1600:]
            raise RuntimeError(f"Video Subtitle Remover finished but did not create output video. {detail}")

        _emit(progress, "Saving removed-subtitle video...")
        result = self._register_derived_video(
            video,
            output_path,
            title=video.title,
            source="vsr:remove-subtitles",
            engine="video-subtitle-remover",
            mode=mode,
            operation="hide",
            area={"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
            extra_metadata={
                "inpaint_mode": vsr_mode,
                "area_ratio": _area_ratio_from_pixels(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, width=width, height=height),
            },
        )
        _emit(progress, f"Removed-subtitle video exported: {output_path}")
        return result

    def _hide_subtitles_from_srt(
        self,
        video: VideoItem,
        *,
        srt_path: Path,
        srt_asset_id: int,
        area: dict | str | None,
        progress: Optional[Progress],
    ) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for automatic timed subtitle hiding.")
        if not srt_path.exists():
            raise RuntimeError(f"SRT not found: {srt_path}")

        vsr_python = Path(os.environ.get("VSR_PYTHON") or self.config.vsr_python)
        vsr_root = Path(os.environ.get("VSR_ROOT") or self.config.vsr_root)
        model_dir = vsr_root / "backend" / "models" / "V5" / "ch_det_fast"
        runner = Path(__file__).with_name("subtitle_mask_runner.py")
        if not vsr_python.exists():
            raise RuntimeError(f"VSR Python runtime not found: {vsr_python}")
        if not model_dir.exists():
            raise RuntimeError(f"PP-OCRv5 mobile detection model not found: {model_dir}")
        if not runner.exists():
            raise RuntimeError(f"Subtitle mask detector runner not found: {runner}")

        output_dir = self.config.outputs_dir / f"video_{video.id}" / "removed_subtitles"
        mask_dir = output_dir / "subtitle_masks"
        temp_dir = output_dir / ".tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        mask_plan_path = mask_dir / f"srt_{srt_asset_id}.ppocrv5-mobile.json"

        _emit(progress, "Preparing automatic subtitle mask...")
        plan = _load_current_mask_plan(mask_plan_path, video.path, srt_path)
        if plan:
            stats = plan.get("stats") or {}
            _emit(
                progress,
                f"Subtitle mask cache: {stats.get('detected', 0)}/{stats.get('segments', 0)} detected",
            )
        else:
            cache_dir = self.config.models_dir / "vsr_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            env = _vsr_runtime_environment(cache_dir=cache_dir, temp_dir=temp_dir)
            cmd = [
                str(vsr_python),
                str(runner),
                "--video",
                str(video.path),
                "--srt",
                str(srt_path),
                "--output",
                str(mask_plan_path),
                "--model-dir",
                str(model_dir),
                "--xmin",
                "0.04",
                "--xmax",
                "0.96",
                "--ymin",
                "0.30",
                "--ymax",
                "0.99",
            ]
            _emit(progress, "Detecting subtitle positions from SRT samples...")
            output_lines: list[str] = []
            proc = subprocess.Popen(
                cmd,
                cwd=str(vsr_root),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = _strip_ansi(line.strip())
                if not line:
                    continue
                output_lines.append(line)
                match = re.search(r"MASK_PROGRESS\s+(\d+)\s*/\s*(\d+)", line)
                if match:
                    _emit(progress, f"Subtitle mask detection: {match.group(1)}/{match.group(2)}")
            return_code = proc.wait()
            if return_code != 0:
                mask_plan_path.unlink(missing_ok=True)
                detail = "\n".join(output_lines).strip()[-1600:]
                raise RuntimeError(f"Automatic subtitle detection failed: {detail or f'exit code {return_code}'}")
            plan = _load_current_mask_plan(mask_plan_path, video.path, srt_path)
            if not plan:
                raise RuntimeError("Subtitle detector finished without a valid mask plan.")

        width = int(plan.get("width") or 0)
        height = int(plan.get("height") or 0)
        segments = plan.get("segments") or []
        if width <= 0 or height <= 0 or not segments:
            raise RuntimeError("Automatic subtitle mask plan is empty or invalid.")

        # Keep the affected mask around the detected subtitle, while giving
        # the blur kernel enough surrounding pixels to match Manual Area.
        detected_xmin = min(int(item["bbox"]["xmin"]) for item in segments)
        detected_xmax = max(int(item["bbox"]["xmax"]) for item in segments)
        detected_ymin = min(int(item["bbox"]["ymin"]) for item in segments)
        detected_ymax = max(int(item["bbox"]["ymax"]) for item in segments)
        area_ymin, area_ymax, area_xmin, area_xmax = _resolve_subtitle_area(area, width, height)
        manual_width = max(2, area_xmax - area_xmin)
        manual_height = max(2, area_ymax - area_ymin)
        manual_blur_filter = _boxblur_filter(manual_width, manual_height)
        manual_luma_radius, _ = _boxblur_radii(manual_width, manual_height)
        minimum_context = max(2, manual_luma_radius * 2 + 2)

        crop_xmin = _even_floor(max(0, detected_xmin - minimum_context // 2))
        crop_xmax = _even_ceil(min(width, detected_xmax + minimum_context // 2), width)
        crop_ymin = _even_floor(max(0, detected_ymin - minimum_context // 2))
        crop_ymax = _even_ceil(min(height, detected_ymax + minimum_context // 2), height)
        if crop_xmax - crop_xmin < minimum_context:
            crop_xmax = _even_ceil(min(width, crop_xmin + minimum_context), width)
            crop_xmin = _even_floor(max(0, crop_xmax - minimum_context))
        if crop_ymax - crop_ymin < minimum_context:
            crop_ymax = _even_ceil(min(height, crop_ymin + minimum_context), height)
            crop_ymin = _even_floor(max(0, crop_ymax - minimum_context))
        crop_width = max(2, crop_xmax - crop_xmin)
        crop_height = max(2, crop_ymax - crop_ymin)
        blur_filter = manual_blur_filter
        filter_path = temp_dir / f"timed_blur_{srt_asset_id}.fffilter"
        _write_timed_blur_filter(
            filter_path,
            segments=segments,
            crop_x=crop_xmin,
            crop_y=crop_ymin,
            crop_width=crop_width,
            crop_height=crop_height,
            blur_filter=blur_filter,
        )

        duration_ms = video.duration_ms or _probe_video_duration_ms(video.path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"{video.path.stem}.auto-blur.{stamp}.mp4"
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video.path),
            "-/filter_complex",
            str(filter_path),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]

        _emit(progress, "Rendering timed subtitle blur...")
        output_lines = []
        env = os.environ.copy()
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        proc = subprocess.Popen(
            cmd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            output_lines.append(line)
            parsed = _normalize_ffmpeg_progress(line, duration_ms)
            if parsed:
                _emit(progress, parsed.replace("FFmpeg progress", "Timed blur progress"))
        return_code = proc.wait()
        if return_code != 0:
            output_path.unlink(missing_ok=True)
            detail = _ffmpeg_failure_summary(output_lines)
            raise RuntimeError(f"ffmpeg automatic subtitle hiding failed: {detail or f'exit code {return_code}'}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("ffmpeg finished but did not create the automatic blurred video.")

        _emit(progress, "Saving removed-subtitle video...")
        stats = plan.get("stats") or {}
        result = self._register_derived_video(
            video,
            output_path,
            title=video.title,
            source="ffmpeg:timed-blur-subtitles",
            engine="ffmpeg+PP-OCRv5_mobile_det",
            mode=self.AUTO_BLUR_MODE,
            operation="hide",
            area={"xmin": crop_xmin, "xmax": crop_xmax, "ymin": crop_ymin, "ymax": crop_ymax},
            extra_metadata={
                "area_ratio": _area_ratio_from_pixels(
                    xmin=crop_xmin,
                    xmax=crop_xmax,
                    ymin=crop_ymin,
                    ymax=crop_ymax,
                    width=width,
                    height=height,
                ),
                "srt_asset_id": srt_asset_id,
                "subtitle_mask_plan": str(mask_plan_path),
                "subtitle_mask_stats": stats,
                "timed_blur": True,
            },
        )
        _emit(progress, f"Removed-subtitle video exported: {output_path}")
        return result

    def _hide_subtitles_with_ffmpeg(
        self,
        video: VideoItem,
        *,
        mode: str,
        area: dict | str | None,
        progress: Optional[Progress],
    ) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for fast blur/cover subtitle hiding.")

        output_dir = self.config.outputs_dir / f"video_{video.id}" / "removed_subtitles"
        temp_dir = output_dir / ".tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        _emit(progress, "Preparing subtitle removal...")
        width, height = _probe_video_size(video.path)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"Could not detect video dimensions for subtitle removal: {video.path}")
        ymin, ymax, xmin, xmax = _resolve_subtitle_area(area, width, height)
        box_width = max(2, xmax - xmin)
        box_height = max(2, ymax - ymin)
        blur_filter = _boxblur_filter(box_width, box_height)
        duration_ms = video.duration_ms or _probe_video_duration_ms(video.path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"{video.path.stem}.{mode}.{stamp}.mp4"

        if mode == "blur":
            filter_complex = (
                f"[0:v]split[base][tmp];"
                f"[tmp]crop={box_width}:{box_height}:{xmin}:{ymin},{blur_filter}[blurred];"
                f"[base][blurred]overlay={xmin}:{ymin}[v]"
            )
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "0:a?",
            ]
        else:
            vf = f"drawbox=x={xmin}:y={ymin}:w={box_width}:h={box_height}:color=black@0.72:t=fill"
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-vf",
                vf,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]

        _emit(progress, f"Hiding subtitles with ffmpeg ({mode})...")
        output_lines: list[str] = []
        env = os.environ.copy()
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        proc = subprocess.Popen(
            cmd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            output_lines.append(line)
            parsed = _normalize_ffmpeg_progress(line, duration_ms)
            if parsed:
                _emit(progress, parsed)
        return_code = proc.wait()
        if return_code != 0:
            output_path.unlink(missing_ok=True)
            detail = _ffmpeg_failure_summary(output_lines)
            raise RuntimeError(f"ffmpeg subtitle hiding failed: {detail or f'exit code {return_code}'}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            detail = "\n".join(output_lines).strip()[-1600:]
            raise RuntimeError(f"ffmpeg finished but did not create output video. {detail}")

        _emit(progress, "Saving removed-subtitle video...")
        result = self._register_derived_video(
            video,
            output_path,
            title=video.title,
            source=f"ffmpeg:{mode}-subtitles",
            engine="ffmpeg",
            mode=mode,
            operation="hide",
            area={"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
            extra_metadata={
                "area_ratio": _area_ratio_from_pixels(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, width=width, height=height),
            },
        )
        _emit(progress, f"Removed-subtitle video exported: {output_path}")
        return result

    def _register_derived_video(
        self,
        video: VideoItem,
        output_path: Path,
        *,
        title: str,
        source: str,
        engine: str,
        mode: str,
        operation: str,
        area: dict[str, int],
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        processing_state = _video_processing_state(video)
        if operation == "hide":
            processing_state.update({"subtitle_hidden": True, "hide_mode": mode})
        elif operation == "insert":
            processing_state.update({"subtitle_inserted": True, "insert_mode": mode})
            if mode in self.FFMPEG_MODES:
                processing_state.update({"subtitle_hidden": True, "hide_mode": mode})
        processing_state["last_operation"] = operation
        project_id = self.storage.project_id_for(video)
        metadata = {
            "project_id": project_id,
            "source_video_id": video.id,
            "source_video_path": str(video.path),
            "engine": engine,
            "mode": mode,
            "area": area,
            "processing_state": processing_state,
        }
        metadata.update(extra_metadata or {})
        output_video_id = self.storage.upsert_video(
            title=title,
            source_url=video.source_url or str(video.path),
            source=source,
            path=output_path,
            media_type="video",
            duration_ms=video.duration_ms,
            size_bytes=output_path.stat().st_size,
            metadata=metadata,
        )
        inherited_srt_count = self._inherit_srt_assets(video, output_video_id, output_path)
        return {
            "outputPath": str(output_path),
            "videoId": output_video_id,
            "inheritedSrtCount": inherited_srt_count,
            "processingState": processing_state,
            "projectId": project_id,
        }

    def _inherit_srt_assets(self, source_video: VideoItem, output_video_id: int, output_path: Path) -> int:
        source_assets = [
            asset
            for asset in reversed(self.storage.list_assets(source_video.id))
            if asset.kind == "srt" and asset.path.exists()
        ]
        if not source_assets:
            return 0

        subtitle_dir = output_path.parent / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        for asset in source_assets:
            inherited_path = subtitle_dir / f"{asset.path.stem}.source-{asset.id}.srt"
            shutil.copy2(asset.path, inherited_path)
            self.storage.add_asset(
                video_id=output_video_id,
                kind="srt",
                path=inherited_path,
                engine=f"inherited:{asset.engine or 'srt'}",
                metadata={
                    "source": "subtitle-removal",
                    "inherited_from_video_id": source_video.id,
                    "inherited_from_asset_id": asset.id,
                },
            )
        return len(source_assets)

    def replace_subtitles(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        srt_asset_id: int,
        mode: str = "blur",
        area: dict | str | None = "bottom",
        style: Optional[dict[str, Any]] = None,
        progress: Optional[Progress] = None,
    ) -> dict[str, Any]:
        if mode not in self.FFMPEG_MODES | {"none"}:
            raise RuntimeError("Subtitle insertion supports none, blur, or cover mode.")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to render translated subtitles.")
        if not srt_path.exists():
            raise RuntimeError(f"Translated SRT not found: {srt_path}")

        with self._lock:
            output_dir = self.config.outputs_dir / f"video_{video.id}" / "translated_subtitles"
            temp_dir = output_dir / ".tmp"
            output_dir.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

            _emit(progress, "Preparing translated subtitle render...")
            width, height = _probe_video_size(video.path)
            if width <= 0 or height <= 0:
                raise RuntimeError(f"Could not detect video dimensions: {video.path}")
            ymin, ymax, xmin, xmax = _resolve_subtitle_area(area, width, height)
            box_width = max(2, xmax - xmin)
            box_height = max(2, ymax - ymin)
            blur_filter = _boxblur_filter(box_width, box_height)
            duration_ms = video.duration_ms or _probe_video_duration_ms(video.path)

            staged_srt = temp_dir / "translated.srt"
            shutil.copy2(srt_path, staged_srt)
            staged_ass = temp_dir / "translated.ass"
            _write_positioned_ass(
                staged_srt,
                staged_ass,
                width=width,
                height=height,
                xmin=xmin,
                xmax=xmax,
                ymin=ymin,
                ymax=ymax,
                style=style or {},
            )
            if mode == "blur":
                hide_filter = (
                    f"[0:v]split[base][tmp];"
                    f"[tmp]crop={box_width}:{box_height}:{xmin}:{ymin},{blur_filter}[hidden];"
                    f"[base][hidden]overlay={xmin}:{ymin}[clean]"
                )
            elif mode == "cover":
                hide_filter = (
                    f"[0:v]drawbox=x={xmin}:y={ymin}:w={box_width}:h={box_height}:"
                    "color=black@0.78:t=fill[clean]"
                )
            else:
                hide_filter = "[0:v]null[clean]"
            filter_complex = f"{hide_filter};[clean]ass=filename='translated.ass'[v]"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            output_path = output_dir / f"{video.path.stem}.translated.{stamp}.mp4"
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(output_path),
            ]

            _emit(progress, "Rendering translated subtitles...")
            output_lines: list[str] = []
            proc = subprocess.Popen(
                cmd,
                cwd=str(temp_dir),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                output_lines.append(line)
                parsed = _normalize_ffmpeg_progress(line, duration_ms)
                if parsed:
                    _emit(progress, parsed.replace("FFmpeg progress", "Subtitle render progress"))
            return_code = proc.wait()
            if return_code != 0:
                output_path.unlink(missing_ok=True)
                detail = _ffmpeg_failure_summary(output_lines)
                raise RuntimeError(f"Translated subtitle render failed: {detail or f'exit code {return_code}'}")
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError("ffmpeg finished without creating the translated video.")

            _emit(progress, "Saving translated video...")
            result = self._register_derived_video(
                video,
                output_path,
                title=video.title,
                source="ffmpeg:replace-subtitles",
                engine="ffmpeg+libass",
                mode=mode,
                operation="insert",
                area={"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
                extra_metadata={
                    "rendered_srt_asset_id": srt_asset_id,
                    "subtitle_style": style or {},
                    "area_ratio": _area_ratio_from_pixels(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, width=width, height=height),
                },
            )
            _emit(progress, f"Translated video exported: {output_path}")
            return result


class TranslationService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._lock = threading.Lock()
        self._translator = None
        self._tokenizer = None
        self._model_path: Path | None = None
        self._device = ""

    def translate_srt(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        source_language: str = "auto",
        target_language: str = "vi",
        engine: str = "madlad400-ct2",
        device: str = "cpu",
        progress: Optional[Progress] = None,
        register_asset: bool = True,
    ) -> Path:
        del source_language
        if engine not in {"madlad400-ct2", "madlad400-q4", "gemini-3.5-flash-lite"}:
            raise RuntimeError(f"Unsupported translation engine: {engine}")
        if not target_language or target_language == "auto":
            raise RuntimeError("Choose a target language before translating.")

        segments = read_srt(srt_path)
        if not segments:
            raise RuntimeError(f"No subtitle segments found in {srt_path}")

        if engine == "gemini-3.5-flash-lite":
            translated = self._translate_with_gemini(segments, target_language, progress)
        else:
            with self._lock:
                tokenizer, translator = self._get_madlad_ct2(device=device)
                _emit(progress, f"Translating {len(segments)} subtitle segment(s) to {target_language}...")
                texts = [segment.text.strip() for segment in segments]
                translated = self._translate_texts(
                    texts,
                    tokenizer=tokenizer,
                    translator=translator,
                    target_language=target_language,
                    progress=progress,
                )

        output_dir = self.config.outputs_dir / f"video_{video.id}"
        output_path = output_dir / f"{srt_path.stem}.{engine}-{target_language}.srt"
        translated_segments = [
            SubtitleSegment(index=segment.index, start=segment.start, end=segment.end, text=text)
            for segment, text in zip(segments, translated)
        ]
        write_srt(translated_segments, output_path)
        if register_asset:
            self.storage.add_asset(
                video_id=video.id,
                kind="srt",
                path=output_path,
                engine=f"{engine}:{target_language}",
                metadata={
                    "source_srt": str(srt_path),
                    "target_language": target_language,
                    "segments": len(translated_segments),
                },
            )
        _emit(progress, f"Translated SRT exported: {output_path}")
        return output_path

    def _get_madlad_ct2(self, *, device: str):
        try:
            import ctranslate2
            from huggingface_hub import snapshot_download
            from sentencepiece import SentencePieceProcessor
        except ImportError as exc:
            raise RuntimeError(
                "Missing translation dependencies. Install ctranslate2, sentencepiece, and huggingface_hub."
            ) from exc

        local_model_dir = self.config.models_dir / "madlad400-3b-ct2"
        model_ref = os.environ.get(
            "MADLAD_CT2_MODEL",
            str(local_model_dir) if (local_model_dir / "model.bin").exists() else "santhosh/madlad400-3b-ct2",
        )
        resolved = Path(model_ref)
        if not resolved.exists():
            resolved = Path(snapshot_download(model_ref, cache_dir=str(self.config.models_dir)))
        normalized_device = "cuda" if device == "cuda" else "cpu"
        if (
            self._translator is not None
            and self._tokenizer is not None
            and self._model_path == resolved
            and self._device == normalized_device
        ):
            return self._tokenizer, self._translator

        tokenizer = SentencePieceProcessor()
        tokenizer_path = resolved / "sentencepiece.model"
        if not tokenizer_path.exists():
            raise RuntimeError(f"MADLAD sentencepiece model not found: {tokenizer_path}")
        tokenizer.load(str(tokenizer_path))
        compute_type = "int8_float16" if normalized_device == "cuda" else "int8"
        translator = ctranslate2.Translator(str(resolved), device=normalized_device, compute_type=compute_type)
        self._model_path = resolved
        self._device = normalized_device
        self._tokenizer = tokenizer
        self._translator = translator
        return tokenizer, translator

    @staticmethod
    def _translate_texts(
        texts: list[str],
        *,
        tokenizer,
        translator,
        target_language: str,
        progress: Optional[Progress] = None,
    ) -> list[str]:
        translated: list[str] = []
        batch_tokens: list[list[str]] = []
        batch_positions: list[int] = []
        translated_map: dict[int, str] = {}

        for index, text in enumerate(texts):
            if not text:
                translated_map[index] = ""
                continue
            batch_tokens.append(tokenizer.encode(f"<2{target_language}> {text}", out_type=str))
            batch_positions.append(index)
            if len(batch_tokens) >= 16:
                _decode_batch(batch_tokens, batch_positions, translated_map, tokenizer, translator)
                _emit(progress, f"Translation progress: {len(translated_map)}/{len(texts)}")
                batch_tokens = []
                batch_positions = []

        if batch_tokens:
            _decode_batch(batch_tokens, batch_positions, translated_map, tokenizer, translator)
            _emit(progress, f"Translation progress: {len(translated_map)}/{len(texts)}")

        for index in range(len(texts)):
            translated.append(translated_map.get(index, texts[index]))
        return translated


    def _translate_with_gemini(
        self,
        segments: list[SubtitleSegment],
        target_language: str,
        progress: Optional[Progress] = None,
    ) -> list[str]:
        api_key_path = self.config.gemini_api_key_path
        if not api_key_path.exists():
            raise RuntimeError("Gemini API key not found. Please set it in Settings.")
        api_key = api_key_path.read_text(encoding="utf-8").strip()
        if not api_key:
            raise RuntimeError("Gemini API key is empty. Please set it in Settings.")
        
        try:
            from google import genai
        except ImportError:
            raise RuntimeError("google-genai package is missing.")
            
        client = genai.Client(api_key=api_key)

        def translate_chunk(chunk_segments: list[SubtitleSegment]) -> dict[int, str]:
            srt_content = "".join([f"{seg.index}\n{seg.start_label} --> {seg.end_label}\n{seg.text}\n\n" for seg in chunk_segments])
            prompt = f"Translate the following SRT subtitles to {target_language}. Maintain the exact SRT format, including index numbers and timestamps. Only translate the text.\n\n{srt_content}"
            response = client.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=prompt,
            )
            translated_map = {}
            blocks = (response.text or "").strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    try:
                        idx = int(lines[0].strip().replace('\ufeff', ''))
                        text = "\n".join(lines[2:]).strip()
                        translated_map[idx] = text
                    except ValueError:
                        continue
            return translated_map

        _emit(progress, f"Sending FULL-SRT to Gemini 3.5 Flash-Lite...")
        try:
            translated_map = translate_chunk(segments)
        except Exception as e:
            _emit(progress, f"Gemini API request failed: {e}. Falling back to chunking...")
            translated_map = {}

        missing = [seg for seg in segments if seg.index not in translated_map]
        
        if missing and len(missing) < len(segments):
            _emit(progress, f"Gemini output was truncated or incomplete. Translating {len(missing)} missing segments in chunks...")
            
        chunk_size = 50
        for i in range(0, len(missing), chunk_size):
            chunk = missing[i:i+chunk_size]
            _emit(progress, f"Translating chunk {i//chunk_size + 1}...")
            try:
                chunk_map = translate_chunk(chunk)
                translated_map.update(chunk_map)
            except Exception as e:
                _emit(progress, f"Chunk translation failed: {e}")

        results = []
        for seg in segments:
            results.append(translated_map.get(seg.index, seg.text))
        return results

class VieneuTtsService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._engine = None
        self._lock = threading.Lock()

    def list_voices(self) -> list[tuple[str, str]]:
        try:
            voices_path = self.config.vieneu_src / "vieneu" / "assets" / "voices_v3_turbo.json"
            if voices_path.exists():
                data = json.loads(voices_path.read_text(encoding="utf-8"))
                return [
                    (f"{name} - {voice.get('description', '')}".strip(" -"), name)
                    for name, voice in data.get("presets", {}).items()
                ]
        except Exception:
            pass

        engine = self._get_engine()
        try:
            return list(engine.list_preset_voices())
        except Exception as exc:
            raise RuntimeError(f"Could not load VieNeu voices: {exc}") from exc

    def synthesize_srt(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str = "",
        timing_mode: str = "srt_slot",
        timeline_playback_speed: float = 1.0,
        timeline_options: dict[str, float] | None = None,
        progress: Optional[Progress] = None,
    ) -> Path:
        with self._lock:
            return self._synthesize_srt_locked(video, srt_path, voice=voice, timing_mode=timing_mode, timeline_playback_speed=timeline_playback_speed, timeline_options=timeline_options, progress=progress)

    def _synthesize_srt_locked(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str = "",
        timing_mode: str = "srt_slot",
        timeline_playback_speed: float = 1.0,
        timeline_options: dict[str, float] | None = None,
        progress: Optional[Progress] = None,
    ) -> Path:
        segments = read_srt(srt_path)
        if not segments:
            raise RuntimeError(f"No subtitle segments found in {srt_path}")

        engine = self._get_engine()
        output_dir = self.config.outputs_dir / f"video_{video.id}" / "tts_vieneu"
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        generation_signature = _tts_generation_signature(engine="vieneu:v3turbo", voice=voice or "default")
        cached = _load_tts_segment_cache(manifest_path, generation_signature)
        manifest: list[dict] = []
        selected_voice = voice or None
        rendered: list[tuple[SubtitleSegment, Path]] = []

        for segment in segments:
            if not segment.text.strip():
                continue
            cached_row = cached.get(segment.index)
            cached_path = Path(str((cached_row or {}).get("path") or ""))
            if cached_row and cached_row.get("text") == segment.text and cached_path.exists():
                rendered.append((segment, cached_path))
                manifest.append(cached_row)
                _emit(progress, f"Reusing cached TTS segment {segment.index}/{len(segments)}...")
                continue
            _emit(progress, f"TTS segment {segment.index}/{len(segments)}...")
            audio = engine.infer(segment.text, voice=selected_voice)
            wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
            engine.save(audio, wav_path)
            rendered.append((segment, wav_path))
            manifest.append(
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "path": str(wav_path),
                    "generation_signature": generation_signature,
                }
            )

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if _is_plain_tts_request(video, timing_mode):
            timeline_result = process_and_register_plain_tts(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="vieneu",
                source_srt=srt_path,
                sample_rate=getattr(engine, "sample_rate", 48_000),
                progress=progress,
            )
        else:
            timeline_result = process_and_register_srt_slot_timeline(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="vieneu",
                source_srt=srt_path,
                sample_rate=getattr(engine, "sample_rate", 48_000),
                timeline_options=timeline_options,
                progress=progress,
            )
        voiceover_path = Path(timeline_result["voiceover_path"])
        timing_metadata = timeline_result["state"]
        self.storage.add_asset(
            video_id=video.id,
            kind="tts",
            path=voiceover_path,
            engine="vieneu:v3turbo",
            metadata={"voice": selected_voice, "segments": len(manifest), "manifest": str(manifest_path), "timing_mode": timing_metadata.get("timing_mode", timing_mode), "timing": timing_metadata},
        )
        _emit(progress, f"TTS exported {len(manifest)} segment(s): {voiceover_path}")
        return voiceover_path

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        if sys.version_info < (3, 10):
            raise RuntimeError("VieNeu-TTS requires Python 3.10+. Run this app with `py -3.11 app.py`.")
        if self.config.vieneu_src.exists():
            sys.path.insert(0, str(self.config.vieneu_src))
        try:
            from vieneu import Vieneu
        except ImportError as exc:
            raise RuntimeError("Missing VieNeu-TTS. Install vieneu or keep VieNeu-TTS-src in D:/nun-media.") from exc
        self._engine = Vieneu()
        return self._engine


class CapcutTtsService:
    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._lock = threading.Lock()

    def list_voices(self, language: str | None = None) -> list[dict]:
        voices_path = self.config.capcut_tts_root / "Voice.json"
        if not voices_path.exists():
            return []
        voices = json.loads(voices_path.read_text(encoding="utf-8"))
        if language:
            voices = [voice for voice in voices if voice.get("lang") == language]
        return [
            {
                "id": f"capcut:{voice.get('voice_type')}:{voice.get('resource_id')}",
                "label": f"{voice.get('display_name') or voice.get('voice_type')} ({voice.get('lang')})",
                "engine": "capcut",
                "language": voice.get("lang"),
                "voiceType": voice.get("voice_type"),
                "resourceId": voice.get("resource_id"),
            }
            for voice in voices
            if voice.get("voice_type") and voice.get("resource_id")
        ]

    def synthesize_srt(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str = "",
        language: str = "en-US",
        rate: str = "1.0",
        timing_mode: str = "srt_slot",
        timeline_playback_speed: float = 1.0,
        timeline_options: dict[str, float] | None = None,
        progress: Optional[Progress] = None,
    ) -> Path:
        with self._lock:
            return self._synthesize_srt_locked(video, srt_path, voice=voice, language=language, rate=rate, timing_mode=timing_mode, timeline_playback_speed=timeline_playback_speed, timeline_options=timeline_options, progress=progress)

    def _synthesize_srt_locked(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str,
        language: str,
        rate: str,
        timing_mode: str,
        timeline_playback_speed: float,
        timeline_options: dict[str, float] | None,
        progress: Optional[Progress],
    ) -> Path:
        segments = read_srt(srt_path)
        if not segments:
            raise RuntimeError(f"No subtitle segments found in {srt_path}")
        voice_type, resource_id = self._resolve_voice(voice, language)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to convert CapCut TTS mp3 segments.")

        output_dir = self.config.outputs_dir / f"video_{video.id}" / "tts_capcut"
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        generation_signature = _tts_generation_signature(
            engine="capcut:tts",
            voice=voice_type,
            resource_id=resource_id,
            language=language,
            rate=rate,
        )
        cached = _load_tts_segment_cache(manifest_path, generation_signature)
        manifest: list[dict] = []
        rendered: list[tuple[SubtitleSegment, Path]] = []

        for segment in segments:
            cleaned_text = _clean_capcut_tts_text(segment.text)
            if not cleaned_text:
                continue
            cached_row = cached.get(segment.index)
            cached_path = Path(str((cached_row or {}).get("wav") or ""))
            if cached_row and cached_row.get("text") == cleaned_text and cached_path.exists():
                rendered.append((SubtitleSegment(segment.index, segment.start, segment.end, cleaned_text), cached_path))
                manifest.append(cached_row)
                _emit(progress, f"Reusing cached CapCut TTS segment {segment.index}/{len(segments)}...")
                continue
            _emit(progress, f"CapCut TTS segment {segment.index}/{len(segments)}...")
            mp3_path = output_dir / f"segment_{segment.index:04d}_original.mp3"
            wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
            try:
                self._request_segment_mp3(cleaned_text, mp3_path, voice_type=voice_type, resource_id=resource_id, rate=rate)
            except RuntimeError as exc:
                preview = cleaned_text[:160].replace("\n", " ")
                raise RuntimeError(f"CapCut TTS failed at SRT segment {segment.index}: {preview}. {exc}") from exc
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", str(mp3_path), "-ac", "1", "-ar", "48000", str(wav_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode != 0 or not wav_path.exists():
                raise RuntimeError(f"Could not convert CapCut mp3 to wav: {proc.stderr[-800:]}")
            rendered.append((SubtitleSegment(segment.index, segment.start, segment.end, cleaned_text), wav_path))
            manifest.append(
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": cleaned_text,
                    "voice": voice_type,
                    "resource_id": resource_id,
                    "mp3": str(mp3_path),
                    "wav": str(wav_path),
                    "generation_signature": generation_signature,
                }
            )

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if _is_plain_tts_request(video, timing_mode):
            timeline_result = process_and_register_plain_tts(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="capcut",
                source_srt=srt_path,
                sample_rate=48_000,
                progress=progress,
            )
        else:
            timeline_result = process_and_register_srt_slot_timeline(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="capcut",
                source_srt=srt_path,
                sample_rate=48_000,
                timeline_options=timeline_options,
                progress=progress,
            )
        voiceover_path = Path(timeline_result["voiceover_path"])
        timing_metadata = timeline_result["state"]
        self.storage.add_asset(
            video_id=video.id,
            kind="tts",
            path=voiceover_path,
            engine="capcut:tts",
            metadata={
                "voice": voice_type,
                "resource_id": resource_id,
                "language": language,
                "segments": len(manifest),
                "manifest": str(manifest_path),
                "source_srt": str(srt_path),
                "timing_mode": timing_metadata.get("timing_mode", timing_mode),
                "timing": timing_metadata,
            },
        )
        _emit(progress, f"CapCut TTS exported {len(manifest)} segment(s): {voiceover_path}")
        return voiceover_path

    def _resolve_voice(self, voice: str, language: str) -> tuple[str, str]:
        if voice.startswith("capcut:"):
            parts = voice.split(":", 2)
            if len(parts) == 3 and parts[1] and parts[2]:
                return parts[1], parts[2]
        voices = self.list_voices(language)
        if voices:
            first = voices[0]
            return first["voiceType"], first["resourceId"]
        raise RuntimeError(f"No CapCut voice found for language {language}.")

    def _request_segment_mp3(self, text: str, output_path: Path, *, voice_type: str, resource_id: str, rate: str) -> None:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("Missing requests. Install it to use CapCut TTS.") from exc

        client = self._client_module()
        device_json_arg = self._capcut_device_json()
        session = requests.Session()
        session.trust_env = False

        new_data = None
        for attempt in range(2):
            new_args = SimpleNamespace(
                mode="tts-new",
                device_json=device_json_arg,
                text=[text],
                text_file=None,
                voice=voice_type,
                resource_id=resource_id,
                rate=str(rate or "1.0"),
            )
            url, headers, body_text = client.build_request(new_args)
            try:
                new_resp = _capcut_post(session, url, headers, body_text, timeout=60)
            except requests.RequestException as exc:
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                raise RuntimeError(_friendly_capcut_network_error(exc)) from exc
            new_data = client.checked_json_response(new_resp, "CapCut tts-new")
            if str(new_data.get("ret")) == "0":
                break
            if new_data.get("errmsg") == "shark block only" and attempt == 0:
                device_json_arg = self._refresh_capcut_device_json()
                continue
            raise RuntimeError(f"CapCut tts-new failed: {new_data}")
        task = (new_data.get("data", {}).get("tasks") or [{}])[0]
        task_id = task.get("id")
        token = task.get("token")
        if not task_id or not token:
            raise RuntimeError(f"CapCut tts-new did not return task id/token: {new_data}")

        payload = None
        for _ in range(60):
            query_args = SimpleNamespace(mode="tts-query", device_json=device_json_arg, task_id=task_id, token=token, bind_id="")
            url, headers, body_text = client.build_request(query_args)
            try:
                query_resp = _capcut_post(session, url, headers, body_text, timeout=60)
            except requests.RequestException as exc:
                raise RuntimeError(_friendly_capcut_network_error(exc)) from exc
            query_data = client.checked_json_response(query_resp, "CapCut tts-query")
            task = (query_data.get("data", {}).get("tasks") or [{}])[0]
            status = task.get("status")
            if status == "succeed":
                payload = json.loads(task.get("payload") or "{}")
                break
            if status in {"failed", "error"}:
                err_msg = str(task.get("err_msg") or query_data.get("errmsg") or "unknown error")
                err_code = task.get("err_code")
                if err_msg == "TTSInvalidText":
                    raise RuntimeError("CapCut rejected this text as invalid. Shorten it or remove unusual symbols/punctuation.")
                raise RuntimeError(f"CapCut TTS task failed ({err_code}): {err_msg}")
            time.sleep(1.0)
        if payload is None:
            raise RuntimeError("CapCut TTS timed out.")

        audio = (payload.get("audio_subtitles") or [{}])[0]
        speech_url = audio.get("speech_url")
        if not speech_url:
            raise RuntimeError(f"CapCut TTS result did not include speech_url: {payload}")
        try:
            audio_resp = session.get(speech_url, timeout=120)
        except requests.RequestException as exc:
            raise RuntimeError(_friendly_capcut_network_error(exc)) from exc
        if audio_resp.status_code >= 400:
            raise RuntimeError(f"Could not download CapCut speech audio HTTP {audio_resp.status_code}")
        output_path.write_bytes(audio_resp.content)

    def _capcut_device_json(self) -> str | None:
        auto_path = self.config.capcut_tts_root / "device.auto.json"
        if auto_path.exists():
            return str(auto_path)
        device_json = self.config.capcut_tts_root / "device.windows.test.json"
        return str(device_json) if device_json.exists() else None

    def _refresh_capcut_device_json(self) -> str:
        value = str(1_000_000_000_000_000_000 + (uuid.uuid4().int % 8_000_000_000_000_000_000))
        device = {
            "device_platform": "win",
            "device_type": "Windows",
            "device_brand": "Windows",
            "os_version": "10.0.19045",
            "lan": "en-US",
            "loc": "US",
            "region": "US",
            "device_id": value,
            "iid": str(int(value) + 12345),
            "tdid": value,
            "appvr": "8.7.0",
            "version_name": "8.7.0",
            "version_code": "8.7.0",
        }
        auto_path = self.config.capcut_tts_root / "device.auto.json"
        auto_path.write_text(json.dumps(device, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(auto_path)

    def _client_module(self):
        if str(self.config.capcut_tts_root) not in sys.path:
            sys.path.insert(0, str(self.config.capcut_tts_root))
        try:
            import capcut_common_task_client
        except ImportError as exc:
            raise RuntimeError(f"CapCut TTS client not found in {self.config.capcut_tts_root}") from exc
        return capcut_common_task_client


POCKET_TTS_VOICES = [
    ("alba", "Alba"),
    ("anna", "Anna"),
    ("azelma", "Azelma"),
    ("bill_boerst", "Bill Boerst"),
    ("caro_davy", "Caro Davy"),
    ("charles", "Charles"),
    ("cosette", "Cosette"),
    ("eponine", "Eponine"),
    ("eve", "Eve"),
    ("fantine", "Fantine"),
    ("george", "George"),
    ("jane", "Jane"),
    ("jean", "Jean"),
    ("javert", "Javert"),
    ("marius", "Marius"),
    ("mary", "Mary"),
    ("michael", "Michael"),
    ("paul", "Paul"),
    ("peter_yearsley", "Peter Yearsley"),
    ("stuart_bell", "Stuart Bell"),
    ("vera", "Vera"),
]
POCKET_TTS_LANGUAGE_ALIASES = {
    "": "english",
    "auto": "english",
    "en": "english",
    "en-us": "english",
    "en-gb": "english",
    "english": "english",
    "english_2026-01": "english_2026-01",
    "english_2026-04": "english",
    "fr": "french_24l",
    "fr-fr": "french_24l",
    "french": "french_24l",
    "french_24l": "french_24l",
    "de": "german",
    "de-de": "german",
    "german": "german",
    "german_24l": "german_24l",
    "pt": "portuguese",
    "pt-br": "portuguese",
    "portuguese": "portuguese",
    "portuguese_24l": "portuguese_24l",
    "it": "italian",
    "it-it": "italian",
    "italian": "italian",
    "italian_24l": "italian_24l",
    "es": "spanish",
    "es-es": "spanish",
    "spanish": "spanish",
    "spanish_24l": "spanish_24l",
}
POCKET_TTS_DEFAULT_VOICE = {
    "italian": "giovanni",
    "italian_24l": "giovanni",
    "spanish": "lola",
    "spanish_24l": "lola",
    "german": "juergen",
    "german_24l": "juergen",
    "portuguese": "rafael",
    "portuguese_24l": "rafael",
    "french_24l": "estelle",
}


class PocketTtsService:
    """Run Kyutai Pocket TTS and hand every segment to the shared SRT timing pass."""

    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage
        self._lock = threading.Lock()
        self._models: dict[str, Any] = {}
        self._voice_states: dict[tuple[str, str], Any] = {}

    def list_voices(self, language: str | None = None) -> list[dict]:
        normalized = self._normalize_language(language)
        if normalized.startswith("english"):
            return [
                {"id": voice_id, "label": label, "engine": "pocket", "language": normalized}
                for voice_id, label in POCKET_TTS_VOICES
            ]
        default_voice = POCKET_TTS_DEFAULT_VOICE.get(normalized, "alba")
        return [{"id": default_voice, "label": default_voice.replace("_", " ").title(), "engine": "pocket", "language": normalized}]

    def synthesize_srt(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str = "",
        language: str = "english",
        timing_mode: str = "srt_slot",
        timeline_playback_speed: float = 1.0,
        timeline_options: dict[str, float] | None = None,
        progress: Optional[Progress] = None,
    ) -> Path:
        with self._lock:
            return self._synthesize_srt_locked(
                video,
                srt_path,
                voice=voice,
                language=language,
                timing_mode=timing_mode,
                timeline_playback_speed=timeline_playback_speed,
                timeline_options=timeline_options,
                progress=progress,
            )

    def _synthesize_srt_locked(
        self,
        video: VideoItem,
        srt_path: Path,
        *,
        voice: str,
        language: str,
        timing_mode: str,
        timeline_playback_speed: float,
        timeline_options: dict[str, float] | None,
        progress: Optional[Progress],
    ) -> Path:
        segments = [segment for segment in read_srt(srt_path) if segment.text.strip()]
        if not segments:
            raise RuntimeError(f"No subtitle segments found in {srt_path}")

        language = self._normalize_language(language)
        voice = self._normalize_voice(voice, language)
        model = self._get_model(language, progress=progress)
        voice_state = self._get_voice_state(model, language, voice, progress=progress)
        output_dir = self.config.outputs_dir / f"video_{video.id}" / "tts_pocket"
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        generation_signature = _tts_generation_signature(
            engine="pocket-tts",
            language=language,
            voice=voice,
            quantize=os.environ.get("POCKET_TTS_QUANTIZE", "0"),
        )
        cached = _load_tts_segment_cache(manifest_path, generation_signature)
        manifest: list[dict] = []
        rendered: list[tuple[SubtitleSegment, Path]] = []

        for segment in segments:
            cached_row = cached.get(segment.index)
            cached_path = Path(str((cached_row or {}).get("path") or ""))
            if cached_row and cached_row.get("text") == segment.text and cached_path.exists():
                rendered.append((segment, cached_path))
                manifest.append(cached_row)
                _emit(progress, f"Reusing cached Pocket TTS segment {segment.index}/{len(segments)}...")
                continue
            _emit(progress, f"Pocket TTS segment {segment.index}/{len(segments)}...")
            wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
            self._write_segment_audio(model, voice_state, segment.text, wav_path)
            rendered.append((segment, wav_path))
            manifest.append(
                {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "path": str(wav_path),
                    "language": language,
                    "voice": voice,
                    "generation_signature": generation_signature,
                }
            )

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if _is_plain_tts_request(video, timing_mode):
            timeline_result = process_and_register_plain_tts(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="pocket",
                source_srt=srt_path,
                sample_rate=int(model.sample_rate),
                progress=progress,
            )
        else:
            timeline_result = process_and_register_srt_slot_timeline(
                self.storage,
                video,
                rendered,
                output_dir,
                engine="pocket",
                source_srt=srt_path,
                sample_rate=int(model.sample_rate),
                timeline_options=timeline_options,
                progress=progress,
            )
        voiceover_path = Path(timeline_result["voiceover_path"])
        timing_metadata = timeline_result["state"]
        self.storage.add_asset(
            video_id=video.id,
            kind="tts",
            path=voiceover_path,
            engine="pocket-tts",
            metadata={
                "voice": voice,
                "language": language,
                "segments": len(manifest),
                "manifest": str(manifest_path),
                "source_srt": str(srt_path),
                "timing_mode": timing_metadata.get("timing_mode", timing_mode),
                "timing": timing_metadata,
            },
        )
        _emit(progress, f"Pocket TTS exported {len(manifest)} segment(s): {voiceover_path}")
        return voiceover_path

    def render_segment_to_file(
        self,
        segment: SubtitleSegment,
        output_dir: Path,
        *,
        voice: str = "",
        language: str = "english",
        progress: Optional[Progress] = None,
    ) -> tuple[SubtitleSegment, Path, dict[str, Any]]:
        with self._lock:
            language = self._normalize_language(language)
            voice = self._normalize_voice(voice, language)
            model = self._get_model(language, progress=progress)
            voice_state = self._get_voice_state(model, language, voice, progress=progress)
            output_dir.mkdir(parents=True, exist_ok=True)
            rendered_segment = SubtitleSegment(segment.index, segment.start, segment.end, segment.text.strip())
            wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
            _emit(progress, f"Pocket TTS segment {segment.index}...")
            self._write_segment_audio(model, voice_state, rendered_segment.text, wav_path)
            return rendered_segment, wav_path, {
                "index": rendered_segment.index,
                "start": rendered_segment.start,
                "end": rendered_segment.end,
                "text": rendered_segment.text,
                "path": str(wav_path),
                "language": language,
                "voice": voice,
                "generation_signature": _tts_generation_signature(
                    engine="pocket-tts",
                    language=language,
                    voice=voice,
                    quantize=os.environ.get("POCKET_TTS_QUANTIZE", "0"),
                ),
            }

    def _normalize_language(self, language: str | None) -> str:
        key = (language or "english").strip().lower()
        normalized = POCKET_TTS_LANGUAGE_ALIASES.get(key)
        if not normalized:
            raise RuntimeError(f"Pocket TTS does not support language: {language}")
        return normalized

    def _normalize_voice(self, voice: str | None, language: str) -> str:
        value = (voice or "").strip()
        if value in {"", "default"}:
            return POCKET_TTS_DEFAULT_VOICE.get(language, "alba")
        if value.startswith("pocket:"):
            return value.split(":", 1)[1] or POCKET_TTS_DEFAULT_VOICE.get(language, "alba")
        return value

    def _get_model(self, language: str, *, progress: Optional[Progress] = None):
        model = self._models.get(language)
        if model is not None:
            return model
        try:
            from pocket_tts import TTSModel
        except ImportError as exc:
            raise RuntimeError(
                "Pocket TTS is not installed. Install it with `pip install pocket-tts soundfile`, "
                "then generate voiceover again."
            ) from exc
        quantize = os.environ.get("POCKET_TTS_QUANTIZE", "0").lower() in {"1", "true", "yes", "on"}
        _emit(progress, f"Loading Pocket TTS model ({language})...")
        model = TTSModel.load_model(language=language, quantize=quantize)
        self._models[language] = model
        return model

    def _get_voice_state(self, model: Any, language: str, voice: str, *, progress: Optional[Progress] = None):
        cache_key = (language, voice)
        voice_state = self._voice_states.get(cache_key)
        if voice_state is not None:
            return voice_state
        _emit(progress, f"Preparing Pocket TTS voice ({voice})...")
        voice_state = model.get_state_for_audio_prompt(voice)
        self._voice_states[cache_key] = voice_state
        return voice_state

    def _write_segment_audio(self, model: Any, voice_state: Any, text: str, output_path: Path) -> None:
        if not text.strip():
            raise RuntimeError("Pocket TTS segment text is empty")
        try:
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("Missing soundfile. Install it with `pip install soundfile`.") from exc
        audio = model.generate_audio(voice_state, text.strip(), copy_state=True)
        samples = audio.detach().cpu().float().numpy()
        sf.write(str(output_path), samples, int(model.sample_rate))



def process_and_register_adaptive_timeline(
    storage: Storage,
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    engine: str,
    source_srt: Path,
    sample_rate: int,
    manual_working_speed: float | None = None,
    timeline_options: dict[str, float] | None = None,
    progress: Optional[Progress] = None,
) -> dict[str, Any]:
    timeline_options = timeline_options or {}
    try:
        result = process_adaptive_timeline(
            video,
            rendered,
            output_dir,
            sample_rate=sample_rate,
            manual_working_speed=manual_working_speed,
            min_working_speed=timeline_options.get("min_working_speed", 0.7),
            preferred_max_local_speed=timeline_options.get("preferred_max_local_speed", 1.15),
            hard_max_local_speed=timeline_options.get("hard_max_local_speed", 1.30),
            safety_gap=timeline_options.get("safety_gap", 0.12),
            progress=progress,
        )
    except AdaptiveTimelineError as exc:
        metadata = dict(video.metadata or {})
        metadata["tts_timeline"] = exc.state
        storage.update_video_metadata(video.id, metadata)
        common_metadata = {"source_srt": str(source_srt), "timeline": exc.state}
        storage.add_asset(video_id=video.id, kind="tts_working_srt", path=exc.working_srt_path, engine=f"adaptive-timeline:{engine}:invalid", metadata=common_metadata)
        storage.add_asset(video_id=video.id, kind="tts_timeline_manifest", path=exc.manifest_path, engine=f"adaptive-timeline:{engine}:invalid", metadata=common_metadata)
        raise
    register_adaptive_timeline_result(storage, video, result, engine=engine, source_srt=source_srt)
    return result


def _is_plain_tts_request(video: VideoItem, timing_mode: str | None) -> bool:
    metadata = video.metadata or {}
    return timing_mode == "plain" or (
        bool(metadata.get("standalone_tts")) and metadata.get("input_mode") == "text"
    )


def process_and_register_plain_tts(
    storage: Storage,
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    engine: str,
    source_srt: Path,
    sample_rate: int,
    progress: Optional[Progress] = None,
) -> dict[str, Any]:
    if not rendered:
        raise RuntimeError("Plain TTS received no rendered audio segments")
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("numpy and soundfile are required for plain TTS rendering") from exc
    if sample_rate <= 0:
        raise RuntimeError("Plain TTS received an invalid sample rate")

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    audio_segments: list[Any] = []
    current_sample = 0
    working_segments: list[SubtitleSegment] = []

    for segment, path in rendered:
        audio, source_rate = sf.read(str(path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if source_rate != sample_rate:
            try:
                import soxr
            except ImportError as exc:
                raise RuntimeError("soxr is required to resample TTS audio") from exc
            audio = soxr.resample(audio, source_rate, sample_rate)
        audio = np.asarray(audio, dtype=np.float32)
        if len(audio) <= 0:
            continue

        start = current_sample / sample_rate
        duration = len(audio) / sample_rate
        end = start + duration
        rows.append(
            {
                "index": segment.index,
                "text": segment.text,
                "original_start_time": segment.start,
                "original_end_time": segment.end,
                "plain_start_time": start,
                "plain_end_time": end,
                "original_tts_path": str(path),
                "original_tts_duration": duration,
                "processed_tts_path": str(path),
                "processed_tts_duration": duration,
                "segment_status": "PLAIN",
            }
        )
        working_segments.append(SubtitleSegment(segment.index, start, end, segment.text))
        audio_segments.append(audio)
        current_sample += len(audio)

    if not audio_segments:
        raise RuntimeError("Plain TTS rendered no audible audio")

    final_audio_data = np.concatenate(audio_segments).astype(np.float32)
    final_audio = output_dir / "voiceover.wav"
    sf.write(str(final_audio), final_audio_data, sample_rate, subtype="FLOAT")
    working_srt = output_dir / "plain_tts_timeline.srt"
    write_srt(working_segments, working_srt)
    manifest = output_dir / "plain_tts_timeline.json"
    actual_samples = int(sf.info(str(final_audio)).frames)
    actual_duration = actual_samples / sample_rate
    state = {
        "timing_mode": "plain",
        "final_audio_duration": actual_duration,
        "target_samples": actual_samples,
        "actual_samples": actual_samples,
        "counts": {"PLAIN": len(rows)},
    }
    manifest.write_text(json.dumps({"state": state, "segments": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "voiceover_path": final_audio,
        "working_audio_path": final_audio,
        "working_srt_path": working_srt,
        "final_video_path": "",
        "manifest_path": manifest,
        "state": state,
        "segments": rows,
    }
    register_plain_tts_result(storage, video, result, engine=engine, source_srt=source_srt)
    if progress:
        progress(f"Plain TTS exported {len(rows)} segment(s)")
    return result


def register_plain_tts_result(
    storage: Storage,
    video: VideoItem,
    result: dict[str, Any],
    *,
    engine: str,
    source_srt: Path,
) -> None:
    state = dict(result["state"])
    metadata = dict(video.metadata or {})
    metadata["tts_timeline"] = state
    storage.update_video_metadata(video.id, metadata)
    common_metadata = {"source_srt": str(source_srt), "timeline": state}
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_srt",
        path=Path(result["working_srt_path"]),
        engine=f"plain-tts:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_audio",
        path=Path(result["working_audio_path"]),
        engine=f"plain-tts:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_timeline_manifest",
        path=Path(result["manifest_path"]),
        engine=f"plain-tts:{engine}",
        metadata=common_metadata,
    )


def process_and_register_srt_slot_timeline(
    storage: Storage,
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    engine: str,
    source_srt: Path,
    sample_rate: int,
    timeline_options: dict[str, float] | None = None,
    progress: Optional[Progress] = None,
) -> dict[str, Any]:
    timeline_options = timeline_options or {}
    max_speed = float(timeline_options.get("max_speed") or timeline_options.get("hard_max_local_speed") or DEFAULT_SLOT_MAX_SPEED)
    result = process_srt_slot_timeline(
        video,
        rendered,
        output_dir,
        sample_rate=sample_rate,
        max_speed=max_speed,
        progress=progress,
    )
    register_srt_slot_timeline_result(storage, video, result, engine=engine, source_srt=source_srt)
    return result


def register_srt_slot_timeline_result(
    storage: Storage,
    video: VideoItem,
    result: dict[str, Any],
    *,
    engine: str,
    source_srt: Path,
) -> None:
    state = dict(result["state"])
    metadata = dict(video.metadata or {})
    metadata["tts_timeline"] = state
    storage.update_video_metadata(video.id, metadata)
    common_metadata = {"source_srt": str(source_srt), "timeline": state}
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_srt",
        path=Path(result["working_srt_path"]),
        engine=f"srt-slot-timeline:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_audio",
        path=Path(result["working_audio_path"]),
        engine=f"srt-slot-timeline:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_timeline_manifest",
        path=Path(result["manifest_path"]),
        engine=f"srt-slot-timeline:{engine}",
        metadata=common_metadata,
    )
    final_video = Path(result["final_video_path"])
    if final_video.exists():
        storage.add_asset(
            video_id=video.id,
            kind="tts_video",
            path=final_video,
            engine=f"srt-slot-timeline:{engine}",
            metadata=common_metadata,
        )


def register_adaptive_timeline_result(
    storage: Storage,
    video: VideoItem,
    result: dict[str, Any],
    *,
    engine: str,
    source_srt: Path,
) -> None:
    state = dict(result["state"])
    metadata = dict(video.metadata or {})
    metadata["tts_timeline"] = state
    storage.update_video_metadata(video.id, metadata)
    common_metadata = {"source_srt": str(source_srt), "timeline": state}
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_srt",
        path=Path(result["working_srt_path"]),
        engine=f"adaptive-timeline:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_working_audio",
        path=Path(result["working_audio_path"]),
        engine=f"adaptive-timeline:{engine}",
        metadata=common_metadata,
    )
    storage.add_asset(
        video_id=video.id,
        kind="tts_timeline_manifest",
        path=Path(result["manifest_path"]),
        engine=f"adaptive-timeline:{engine}",
        metadata=common_metadata,
    )
    if result.get("final_video_path"):
        storage.add_asset(
            video_id=video.id,
            kind="tts_video",
            path=Path(result["final_video_path"]),
            engine=f"adaptive-timeline:{engine}",
            metadata=common_metadata,
        )


def _tts_generation_signature(**values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _clean_capcut_tts_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\{\\[^}]*\}", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\ufeff", " ").replace("\u200b", " ")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    lines = []
    for line in value.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue
        if re.fullmatch(r"[A-Za-z0-9\s.,:/\\|*#_+\-]{1,12}", clean_line):
            continue
        lines.append(clean_line)
    value = " ".join(lines)
    value = value.replace("|", " ").replace("/", " ")
    value = value.replace("â€¦", "...")
    value = re.sub(r"[*#_=+<>[\]{}]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" \t\r\n-â€“â€”_~")


def _capcut_post(session, url: str, headers: dict, body_text: str, *, timeout: int):
    return session.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=timeout)


def _friendly_capcut_network_error(error: Exception) -> str:
    text = str(error)
    if "SSL" in text or "TLS" in text or "sslv" in text.lower():
        return (
            "CapCut TTS network/TLS connection failed. "
            "The API host may be blocked, unstable, or intercepted by proxy/VPN/antivirus. "
            "Retry once, or switch VPN/network, then run Generate Voiceover again. "
            f"Detail: {text[-500:]}"
        )
    return f"CapCut TTS network request failed: {text[-500:]}"


def _load_tts_segment_cache(manifest_path: Path, signature: str) -> dict[int, dict]:
    if not manifest_path.exists():
        return {}
    try:
        rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            int(row["index"]): row
            for row in rows
            if row.get("generation_signature") == signature and row.get("index") is not None
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _emit(progress: Optional[Progress], message: str) -> None:
    if progress:
        progress(message)


def _subtitle_force_style(style: dict[str, Any], *, height: int, area_bottom: int, area_height: int) -> str:
    font_name = str(style.get("fontFamily") or "Arial").replace("'", "").replace(",", " ").strip() or "Arial"
    font_size = min(48, max(12, int(style.get("fontSize") or 24)))
    outline = min(6, max(0, int(style.get("outline") or 2)))
    margin_v = max(10, height - area_bottom + round(area_height * 0.08))
    primary = _ass_color(str(style.get("fontColor") or "#FFFFFF"))
    outline_color = _ass_color(str(style.get("outlineColor") or "#000000"))
    background = bool(style.get("background"))
    values = [
        f"FontName={font_name}",
        f"FontSize={font_size}",
        f"PrimaryColour={primary}",
        f"OutlineColour={outline_color}",
        "Alignment=2",
        f"MarginV={margin_v}",
        "Shadow=0",
    ]
    if background:
        values.extend(["BorderStyle=3", "Outline=1", "BackColour=&H80000000"])
    else:
        values.extend(["BorderStyle=1", f"Outline={outline}"])
    return ",".join(values)


def _write_positioned_ass(
    srt_path: Path,
    ass_path: Path,
    *,
    width: int,
    height: int,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
    style: dict[str, Any],
) -> None:
    def style_value(*keys: str, default: Any = None) -> Any:
        for key in keys:
            value = style.get(key)
            if value is not None and value != "":
                return value
        return default

    def style_float(*keys: str, default: float = 0.0, minimum: float | None = None, maximum: float | None = None) -> float:
        try:
            value = float(style_value(*keys, default=default))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    font_name = str(style_value("fontFamily", default="Arial")).replace(",", " ").strip() or "Arial"
    scale = max(0.5, height / 720)
    font_size = max(12, int(style_float("fontSize", default=24, minimum=1, maximum=120) * scale))
    outline = max(0, style_float("outlineWidth", "outline", default=2, minimum=0, maximum=24) * scale)
    shadow = max(0, style_float("shadowOffsetX", "shadowOffsetY", default=0, minimum=0, maximum=32) * scale)
    background = bool(style_value("backgroundEnabled", "background", default=False))
    primary_hex = str(style_value("fontColor", "color", default="#FFFFFF"))
    outline_hex = str(style_value("outlineColor", default="#000000"))
    shadow_hex = str(style_value("shadowColor", default="#000000"))
    primary = _ass_color(primary_hex)
    outline_color = _ass_color(outline_hex)
    shadow_color = _ass_color(shadow_hex, alpha=70 if shadow else 0)
    
    weight = style_value("fontWeight", default="normal")
    try:
        font_weight = -1 if float(weight) >= 700 else 0
    except (TypeError, ValueError):
        font_weight = -1 if str(weight).lower() == "bold" else 0
    font_style = 1 if str(style_value("fontStyle", default="normal")).lower() == "italic" else 0
    text_decoration = 1 if style_value("textDecoration", default="none") == "underline" else 0
    spacing = int(style_float("letterSpacing", default=0, minimum=-20, maximum=80))
    
    border_style = 3 if background else 1
    bg_opacity = style_float("backgroundOpacity", default=.55, minimum=0, maximum=1)
    bg_alpha = int(round((1 - bg_opacity) * 255))
    back_color = _ass_color(str(style_value("backgroundColor", default="#000000")), alpha=bg_alpha) if background else shadow_color
    
    text_align = str(style_value("textAlign", default="center")).lower()
    vertical_align = str(style_value("verticalAlign", default="bottom")).lower()
    horizontal_alignment = {"left": 1, "center": 2, "right": 3}.get(text_align, 2)
    vertical_offset = {"bottom": 0, "middle": 3, "top": 6}.get(vertical_align, 0)
    alignment = horizontal_alignment + vertical_offset
    if text_align == "left":
        x = xmin + max(8, int(width * 0.02))
    elif text_align == "right":
        x = xmax - max(8, int(width * 0.02))
    else:
        x = (xmin + xmax) // 2

    inset = max(8, int((ymax - ymin) * 0.07))
    if vertical_align == "top":
        y = ymin + inset
    elif vertical_align == "middle":
        y = (ymin + ymax) // 2
    else:
        y = max(ymin + 8, ymax - max(12, inset))
    glow_enabled = bool(style_value("glowEnabled", default=False))
    glow_hex = str(style_value("glowColor", default=shadow_hex))
    glow_blur = style_float("glowBlur", default=0, minimum=0, maximum=48) * scale
    glow_strength = style_float("glowStrength", default=1, minimum=0, maximum=3)
    static_effect = str(style_value("staticEffect", default="none"))
    secondary_hex = str(style_value("secondaryOutlineColor", default=shadow_hex))
    secondary_width = style_float("secondaryOutlineWidth", default=0, minimum=0, maximum=24) * scale

    def style_line(name: str, *, font_color: str = primary, border_color: str = outline_color, back: str = back_color, border: float = outline, shadow_depth: float = shadow, blur: float = 0.0, border_style_override: int | None = None) -> str:
        return (
            f"Style: {name},{font_name},{font_size},{font_color},&H00000000,{border_color},{back},"
            f"{font_weight},{font_style},{text_decoration},0,100,100,{spacing},0,"
            f"{border_style_override or border_style},{border:.2f},{shadow_depth:.2f},{alignment},0,0,0,1"
        )

    style_lines = [
        style_line("Subtitle"),
    ]
    if secondary_width > 0:
        style_lines.insert(0, style_line("SecondaryOutline", font_color=primary, border_color=_ass_color(secondary_hex), border=secondary_width, shadow_depth=0, border_style_override=1))
    if glow_enabled and glow_blur > 0:
        style_lines.insert(0, style_line("GlowOuter", font_color=_ass_color(glow_hex, alpha=115), border_color=_ass_color(glow_hex, alpha=85), border=max(outline + glow_blur * .65, glow_blur * .75), shadow_depth=0, border_style_override=1))
        style_lines.insert(1, style_line("GlowInner", font_color=_ass_color(glow_hex, alpha=80), border_color=_ass_color(glow_hex, alpha=55), border=max(outline + glow_blur * .28, 1), shadow_depth=0, border_style_override=1))
    if static_effect == "glitch":
        style_lines.insert(0, style_line("GlitchCyan", font_color=_ass_color("#00F5FF", alpha=45), border_color=_ass_color("#001D1F", alpha=80), border=max(1, outline * .55), shadow_depth=0, border_style_override=1))
        style_lines.insert(1, style_line("GlitchMagenta", font_color=_ass_color(secondary_hex or "#FF2F7D", alpha=45), border_color=_ass_color("#21000C", alpha=80), border=max(1, outline * .55), shadow_depth=0, border_style_override=1))
    if static_effect == "duotone":
        style_lines.insert(0, style_line("DuotoneBack", font_color=_ass_color(secondary_hex, alpha=0), border_color=_ass_color(secondary_hex, alpha=0), border=max(secondary_width, outline), shadow_depth=0, border_style_override=1))
    
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "ScaledBorderAndShadow: yes",
            "WrapStyle: 0",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
            *style_lines,
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]
    )
    events = []
    text_case = style_value("textTransform", default="none")
    
    for segment in read_srt(srt_path):
        text = segment.text
        if text_case == "uppercase":
            text = text.upper()
        elif text_case == "lowercase":
            text = text.lower()
        elif text_case == "capitalize":
            text = " ".join(w.capitalize() for w in text.split(" "))
            
        text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        start = _ass_timestamp(segment.start)
        end = _ass_timestamp(segment.end)
        if glow_enabled and glow_blur > 0:
            events.append(f"Dialogue: 0,{start},{end},GlowOuter,,0,0,0,,{{\\pos({x},{y})\\blur{max(1, glow_blur):.1f}}}{text}")
            events.append(f"Dialogue: 1,{start},{end},GlowInner,,0,0,0,,{{\\pos({x},{y})\\blur{max(.5, glow_blur * .45):.1f}}}{text}")
        if static_effect == "glitch":
            offset = max(2, int(3 * scale))
            events.append(f"Dialogue: 0,{start},{end},GlitchCyan,,0,0,0,,{{\\pos({x - offset},{y})}}{text}")
            events.append(f"Dialogue: 1,{start},{end},GlitchMagenta,,0,0,0,,{{\\pos({x + offset},{y + max(1, offset // 2)})}}{text}")
        if static_effect == "duotone":
            offset = max(2, int(4 * scale))
            events.append(f"Dialogue: 0,{start},{end},DuotoneBack,,0,0,0,,{{\\pos({x + offset},{y + max(1, offset // 2)})}}{text}")
        if secondary_width > 0:
            events.append(f"Dialogue: 2,{start},{end},SecondaryOutline,,0,0,0,,{{\\pos({x},{y})}}{text}")
        events.append(f"Dialogue: 3,{start},{end},Subtitle,,0,0,0,,{{\\pos({x},{y})}}{text}")
    ass_path.write_text(f"{header}\n" + "\n".join(events) + "\n", encoding="utf-8-sig")


def _ass_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds_part, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds_part:02d}.{centiseconds:02d}"


def _ass_color(value: str, alpha: int = 0) -> str:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    rgb = match.group(1) if match else "FFFFFF"
    red, green, blue = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{max(0, min(255, int(alpha))):02X}{blue}{green}{red}"


def _boxblur_radii(width: int, height: int) -> tuple[int, int]:
    smallest = max(2, min(width, height))
    # Match the frosted subtitle mask used by the web preview/export: adjusted for a subtler, more transparent blur
    luma_radius = max(8, min(45, max(1, (smallest - 1) // 3)))
    chroma_radius = max(4, min(22, max(1, (smallest - 1) // 6), max(1, luma_radius // 2)))
    return luma_radius, chroma_radius


def _boxblur_filter(width: int, height: int) -> str:
    luma_radius, chroma_radius = _boxblur_radii(width, height)
    return (
        "boxblur="
        f"luma_radius={luma_radius}:luma_power=3:"
        f"chroma_radius={chroma_radius}:chroma_power=2"
    )


def _area_ratio_from_pixels(
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
    width: int,
    height: int,
) -> dict[str, float]:
    width = max(1, width)
    height = max(1, height)
    return {
        "xmin": max(0.0, min(1.0, xmin / width)),
        "xmax": max(0.0, min(1.0, xmax / width)),
        "ymin": max(0.0, min(1.0, ymin / height)),
        "ymax": max(0.0, min(1.0, ymax / height)),
    }


def _load_current_mask_plan(path: Path, video_path: Path, srt_path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mtimes = payload.get("source_mtime_ns") or {}
        if int(mtimes.get("video") or -1) != video_path.stat().st_mtime_ns:
            return None
        if int(mtimes.get("srt") or -1) != srt_path.stat().st_mtime_ns:
            return None
        if payload.get("detector") != "PP-OCRv5_mobile_det" or not payload.get("segments"):
            return None
        return payload
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _vsr_runtime_environment(*, cache_dir: Path, temp_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "KMP_DUPLICATE_LIB_OK": "TRUE",
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "HOME": str(cache_dir),
            "USERPROFILE": str(cache_dir),
            "XDG_CACHE_HOME": str(cache_dir / ".cache"),
            "HF_HOME": str(cache_dir / "huggingface"),
            "PADDLE_HOME": str(cache_dir / "paddle"),
            "PADDLEOCR_HOME": str(cache_dir / "paddleocr"),
            "PADDLE_PDX_CACHE_HOME": str(cache_dir / "paddlex"),
            "MPLCONFIGDIR": str(cache_dir / "matplotlib"),
            "PYTHONPYCACHEPREFIX": str(cache_dir / "pycache"),
        }
    )
    for key in (
        "XDG_CACHE_HOME",
        "HF_HOME",
        "PADDLE_HOME",
        "PADDLEOCR_HOME",
        "PADDLE_PDX_CACHE_HOME",
        "MPLCONFIGDIR",
        "PYTHONPYCACHEPREFIX",
    ):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def _even_floor(value: int) -> int:
    return max(0, value - (value % 2))


def _even_ceil(value: int, limit: int) -> int:
    candidate = value if value % 2 == 0 else value + 1
    if candidate > limit:
        candidate = limit - (limit % 2)
    return max(2, candidate)


def _cluster_timed_masks(
    segments: list[dict[str, Any]],
    *,
    crop_y: int,
    crop_height: int,
) -> list[dict[str, Any]]:
    tolerance = max(3, min(8, int(round(crop_height * 0.04))))
    groups: list[dict[str, Any]] = []
    for segment in segments:
        bbox = segment["bbox"]
        ymin = max(0, int(bbox["ymin"]) - crop_y)
        ymax = min(crop_height, int(bbox["ymax"]) - crop_y)
        if ymax <= ymin:
            continue
        target = next(
            (
                group
                for group in groups
                if abs(group["ymin"] - ymin) <= tolerance and abs(group["ymax"] - ymax) <= tolerance
            ),
            None,
        )
        if target is None:
            target = {"ymin": ymin, "ymax": ymax, "bounds": [], "intervals": []}
            groups.append(target)
        target["bounds"].append((ymin, ymax))
        target["ymin"] = _median_int([item[0] for item in target["bounds"]])
        target["ymax"] = _median_int([item[1] for item in target["bounds"]])
        target["intervals"].append((float(segment["start"]), float(segment["end"])))
    return groups


def _median_int(values: list[int]) -> int:
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return int(round((values[middle - 1] + values[middle]) / 2))


def _write_timed_blur_filter(
    path: Path,
    *,
    segments: list[dict[str, Any]],
    crop_x: int,
    crop_y: int,
    crop_width: int,
    crop_height: int,
    blur_filter: str,
) -> None:
    groups = _cluster_timed_masks(segments, crop_y=crop_y, crop_height=crop_height)
    if not groups:
        raise RuntimeError("No valid timed subtitle masks were generated.")
    lines = [
        "[0:v]split=2[base][region_src]",
        (
            f"[region_src]crop={crop_width}:{crop_height}:{crop_x}:{crop_y},"
            "split=3[region][blur_src][mask_src]"
        ),
        f"[blur_src]{blur_filter}[blurred]",
        "[mask_src]format=gray,geq=lum='0'[mask0]",
    ]
    current_mask = "mask0"
    for index, group in enumerate(groups, start=1):
        intervals = "+".join(
            f"between(t,{start:.3f},{end:.3f})" for start, end in group["intervals"]
        )
        ymin = max(0, int(group["ymin"]))
        box_height = max(2, min(crop_height - ymin, int(group["ymax"]) - ymin))
        next_mask = f"mask{index}"
        lines.append(
            f"[{current_mask}]drawbox=x=0:y={ymin}:w={crop_width}:h={box_height}:"
            f"color=white:t=fill:enable='{intervals}'[{next_mask}]"
        )
        current_mask = next_mask
    lines.extend(
        [
            f"[region][blurred][{current_mask}]maskedmerge[masked]",
            f"[base][masked]overlay={crop_x}:{crop_y}[v]",
        ]
    )
    path.write_text(";\n".join(lines) + "\n", encoding="utf-8")


def _ffmpeg_failure_summary(lines: list[str]) -> str:
    markers = ("invalid", "failed", "error", "could not")
    important = [line for line in lines if any(marker in line.lower() for marker in markers)]
    selected = important[-4:] if important else lines[-4:]
    return "\n".join(selected).strip()[-800:]


def _video_processing_state(video: VideoItem) -> dict[str, Any]:
    state = dict(((video.metadata or {}).get("processing_state") or {}))
    if video.source == "vsr:remove-subtitles" or video.source.startswith("ffmpeg:blur-") or video.source.startswith("ffmpeg:cover-") or video.source == "ffmpeg:timed-blur-subtitles":
        state.setdefault("subtitle_hidden", True)
        state.setdefault("last_operation", "hide")
    if video.source == "ffmpeg:replace-subtitles":
        state.setdefault("subtitle_inserted", True)
        mode = str((video.metadata or {}).get("mode") or "none")
        if mode in {"blur", "cover"}:
            state.setdefault("subtitle_hidden", True)
        state.setdefault("last_operation", "insert")
    return state


def _default_subtitle_area(width: int, height: int) -> tuple[int, int, int, int]:
    xmin = max(0, int(width * 0.04))
    xmax = min(width, int(width * 0.96))
    ymin = max(0, int(height * 0.60))
    ymax = min(height, int(height * 0.98))
    return ymin, ymax, xmin, xmax


def _resolve_subtitle_area(area: dict | str | None, width: int, height: int) -> tuple[int, int, int, int]:
    if not area or area == "bottom":
        return _default_subtitle_area(width, height)
    if not isinstance(area, dict):
        raise RuntimeError(f"Unsupported subtitle area: {area}")

    try:
        xmin_ratio = float(area["xmin"])
        xmax_ratio = float(area["xmax"])
        ymin_ratio = float(area["ymin"])
        ymax_ratio = float(area["ymax"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Subtitle area must include xmin, xmax, ymin, ymax ratios.") from exc

    xmin_ratio = min(max(xmin_ratio, 0.0), 1.0)
    xmax_ratio = min(max(xmax_ratio, 0.0), 1.0)
    ymin_ratio = min(max(ymin_ratio, 0.0), 1.0)
    ymax_ratio = min(max(ymax_ratio, 0.0), 1.0)
    if xmax_ratio - xmin_ratio < 0.01 or ymax_ratio - ymin_ratio < 0.01:
        raise RuntimeError("Subtitle area is too small. Draw a larger rectangle.")

    xmin = max(0, min(width - 1, int(round(width * xmin_ratio))))
    xmax = max(xmin + 2, min(width, int(round(width * xmax_ratio))))
    ymin = max(0, min(height - 1, int(round(height * ymin_ratio))))
    ymax = max(ymin + 2, min(height, int(round(height * ymax_ratio))))
    return ymin, ymax, xmin, xmax


def _normalize_ffmpeg_progress(message: str, duration_ms: int | None) -> str | None:
    if message == "progress=end":
        return "FFmpeg progress: 100%"
    if not duration_ms:
        return None
    match = re.match(r"out_time_ms=(\d+)", message)
    if not match:
        return None
    out_time_ms = int(match.group(1)) // 1000
    percent = min(max(int(out_time_ms * 100 / max(duration_ms, 1)), 0), 99)
    return f"FFmpeg progress: {percent}%"


def _stream_vsr_output(stdout, output_lines: list[str], progress: Optional[Progress]) -> None:
    buffer = ""

    def flush_buffer() -> None:
        nonlocal buffer
        text = _strip_ansi(buffer.strip())
        buffer = ""
        if not text:
            return
        output_lines.append(text)
        _emit(progress, _normalize_vsr_progress(text))

    while True:
        chunk = stdout.read(1)
        if chunk == "":
            break
        if chunk in {"\r", "\n"}:
            flush_buffer()
            continue
        buffer += chunk
        if len(buffer) > 2000:
            flush_buffer()
    flush_buffer()


def _normalize_vsr_progress(message: str) -> str:
    low = message.lower()
    percent_matches = re.findall(r"(\d{1,3})\s*%", message)
    if percent_matches and ("subtitle removing" in low or "frame" in low or "it/s" in low):
        percent = min(max(int(percent_matches[-1]), 0), 100)
        return f"VSR progress: {percent}%"
    if "processing start removing" in low or "removing subtitles" in low:
        return "Removing subtitles / processing frames"
    if "merge" in low or "audio" in low or "ffmpeg" in low:
        return "Encoding output"
    if "finished" in low or "processing time" in low:
        return "Saving video"
    return message


def _publish_srt_file(source: Path, destination: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if source.exists() and source.stat().st_size > 0:
            break
        time.sleep(0.2)
    if not source.exists() or source.stat().st_size == 0:
        raise RuntimeError(f"Hard-sub OCR produced an empty SRT file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f"{destination.name}.tmp")
    tmp_path.write_bytes(source.read_bytes())
    if tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Hard-sub OCR could not publish SRT output: {destination}")
    os.replace(tmp_path, destination)
    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError(f"Hard-sub OCR published an empty SRT file: {destination}")


def _decode_batch(batch_tokens, batch_positions, translated_map, tokenizer, translator) -> None:
    results = translator.translate_batch(
        batch_tokens,
        batch_type="tokens",
        max_batch_size=1024,
        beam_size=1,
        no_repeat_ngram_size=1,
        repetition_penalty=2,
    )
    for position, result in zip(batch_positions, results):
        text = tokenizer.decode(result.hypotheses[0]).strip()
        translated_map[position] = text


def _probe_video_size(path: Path) -> tuple[int, int]:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(path),
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            width_text, height_text = proc.stdout.strip().split("x", 1)
            return int(width_text), int(height_text)
    except Exception:
        pass

    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width > 0 and height > 0:
                return width, height
        finally:
            cap.release()
    except Exception:
        pass

    return 0, 0


def _probe_video_duration_ms(path: Path) -> Optional[int]:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            seconds = float(proc.stdout.strip())
            if seconds > 0:
                return int(seconds * 1000)
    except Exception:
        pass
    return None


def _has_videosubfinder(root: Path) -> bool:
    candidates = [
        root / "VideoSubFinderWXW.exe",
        root / "windows" / "VideoSubFinderWXW.exe",
        root / "backend" / "subfinder" / "windows" / "VideoSubFinderWXW.exe",
        root / "VideoSubFinderCli",
        root / "macos" / "VideoSubFinderCli",
        root / "backend" / "subfinder" / "macos" / "VideoSubFinderCli",
        root / "VideoSubFinderCli.run",
        root / "linux" / "VideoSubFinderCli.run",
        root / "backend" / "subfinder" / "linux" / "VideoSubFinderCli.run",
    ]
    return any(candidate.exists() for candidate in candidates)


def _resolve_hardsub_python(configured_python: Path) -> Path:
    env_python = (
        os.environ.get("HARDSUB_PYTHON")
        or os.environ.get("RAPID_VIDEOOCR_PYTHON")
        or os.environ.get("VSE_PYTHON")
    )
    legacy_vse_root = Path(os.environ.get("VSE_ROOT") or AppConfig().vse_root)
    candidates = [
        Path(env_python) if env_python else None,
        configured_python,
        legacy_vse_root / "videoEnv" / "Scripts" / "python.exe",
        legacy_vse_root / ".venv" / "bin" / "python",
        legacy_vse_root / "videoEnv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return Path(sys.executable)


def _merge_segment_wavs(
    rendered: list[tuple[SubtitleSegment, Path]],
    output_path: Path,
    sample_rate: int,
    *,
    duration_seconds: float | None = None,
) -> None:
    if not rendered:
        raise RuntimeError("VieNeu did not render any audio segments.")
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("Missing numpy/soundfile, required to merge VieNeu voice output.") from exc

    content_end = max(segment.end for segment, _ in rendered)
    duration = max(content_end, duration_seconds or content_end + 1.0)
    timeline = np.zeros(int(duration * sample_rate), dtype=np.float32)
    for segment, wav_path in rendered:
        audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != sample_rate:
            try:
                import soxr

                audio = soxr.resample(audio, sr, sample_rate)
            except ImportError as exc:
                raise RuntimeError("Missing soxr, required to resample VieNeu segment audio.") from exc
        start = max(0, int(segment.start * sample_rate))
        end = min(len(timeline), start + len(audio))
        if end <= start:
            continue
        existing = timeline[start:end]
        timeline[start:end] = np.clip(existing + audio[: end - start], -1.0, 1.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), timeline, sample_rate)


def _load_lazy_payload(stdout: str) -> dict:
    candidates = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(candidates):
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"Could not parse Lazy-downloader output: {stdout[:500]}")


def _duration_to_ms(value) -> Optional[int]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return int(numeric if numeric > 10_000 else numeric * 1000)


def _should_fallback_to_ytdlp(error: str) -> bool:
    text = error.lower()
    return (
        "window_bootstrap_missing" in text
        or "cloudflare" in text
        or "autolink http 500 phase=bootstrap" in text
        or "autolink http 403" in text
        or "fresh cookies" in text
        or "[douyin]" in text
    )


def _friendly_lazy_error(error: str) -> str:
    if _should_fallback_to_ytdlp(error):
        return (
            "Lazy-downloader/J2Download is currently blocked by the source site. "
            "Try again later, use Import Video, or open Douyin in Chrome/Edge so yt-dlp can reuse fresh cookies."
        )
    return error


def _is_douyin_url(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return host == "douyin.com" or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com")


def _douyin_downloader_config(url: str, downloads_dir: Path, cookies: dict[str, str]) -> dict:
    return {
        "link": [url],
        "path": str(downloads_dir),
        "music": False,
        "cover": False,
        "avatar": False,
        "json": False,
        "start_time": "",
        "end_time": "",
        "folderstyle": True,
        "group_by_mode": True,
        "filename_template": "{date}_{title}_{id}",
        "folder_template": "{date}_{title}_{id}",
        "author_dir": "nickname",
        "download_pinned": False,
        "mode": ["post"],
        "number": {
            "post": 0,
            "like": 0,
            "allmix": 0,
            "mix": 0,
            "music": 0,
            "collect": 0,
            "collectmix": 0,
        },
        "increase": {
            "post": False,
            "like": False,
            "allmix": False,
            "mix": False,
            "music": False,
        },
        "thread": 1,
        "retry_times": 3,
        "rate_limit": 2,
        "proxy": "",
        "database": False,
        "database_path": str(downloads_dir / "douyin_downloader.sqlite3"),
        "video_quality": "highest",
        "progress": {"quiet_logs": True},
        "transcript": {
            "enabled": False,
            "model": "gpt-4o-mini-transcribe",
            "output_dir": "",
            "response_formats": ["txt", "json"],
            "api_url": "https://api.openai.com/v1/audio/transcriptions",
            "api_key_env": "OPENAI_API_KEY",
            "api_key": "",
        },
        "browser_fallback": {
            "enabled": False,
            "headless": True,
            "max_scrolls": 0,
            "idle_rounds": 0,
            "wait_timeout_seconds": 30,
        },
        "comments": {
            "enabled": False,
            "include_replies": False,
            "max_comments": 0,
            "page_size": 20,
        },
        "live": {
            "max_duration_seconds": 0,
            "chunk_size": 65536,
            "idle_timeout_seconds": 30,
        },
        "notifications": {
            "enabled": False,
            "on_success": False,
            "on_failure": False,
            "providers": [],
        },
        "cookies": cookies,
    }


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    if not cookie_header:
        return {}

    selected = cookie_header.strip()
    for line in selected.splitlines():
        if line.lower().startswith("cookie:"):
            selected = line.split(":", 1)[1].strip()
            break

    parsed: dict[str, str] = {}
    for item in selected.replace("\r", "\n").replace("\n", ";").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not key or re.search(r"[()<>@,;:\\\"/\[\]?={} \t\r\n]", key):
            continue
        parsed[key] = value.strip()
    return parsed


def _missing_required_douyin_cookies(cookies: dict[str, str]) -> list[str]:
    required = ["ttwid"]
    return [key for key in required if not cookies.get(key)]


def _friendly_douyin_downloader_error(error: str) -> str:
    text = error.lower()
    if (
        "cookie" in text
        or "login" in text
        or "ç™»å½•" in error
        or "æœªç™»å½•" in error
        or "invalid or incomplete" in text
        or "empty" in text
        or "captcha" in text
    ):
        return (
            "Douyin downloader could not fetch this video with the current session. "
            "Save a fresh Douyin Cookie header in Settings, then retry. "
            f"Detail: {error[-800:]}"
        )
    return error[-1000:] or "douyin-downloader failed."


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def _media_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    }


def _read_cookie_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _without_proxy_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
    ]:
        env.pop(key, None)
    return env


def _browser_cookie_attempts() -> list[tuple[str, dict]]:
    attempts: list[tuple[str, dict]] = []
    for browser, root in _chromium_cookie_roots():
        for profile in _chromium_cookie_profiles(root):
            attempts.append(
                (
                    f"yt-dlp with {browser.title()} cookies ({profile})",
                    {"cookiesfrombrowser": (browser, profile, None, None)},
                )
            )
    return attempts


def _chromium_cookie_roots() -> list[tuple[str, Path]]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return []
    base = Path(local_app_data)
    return [
        ("chrome", base / "Google" / "Chrome" / "User Data"),
        ("edge", base / "Microsoft" / "Edge" / "User Data"),
    ]


def _chromium_cookie_profiles(root: Path) -> list[str]:
    if not root.exists():
        return []

    profiles = []
    for profile_dir in root.iterdir():
        if not profile_dir.is_dir():
            continue
        if not (
            (profile_dir / "Network" / "Cookies").exists()
            or (profile_dir / "Cookies").exists()
        ):
            continue
        if profile_dir.name == "Default" or profile_dir.name.startswith("Profile "):
            profiles.append(profile_dir.name)

    def sort_key(profile: str) -> tuple[int, int | str]:
        if profile == "Default":
            return (0, 0)
        suffix = profile.removeprefix("Profile ")
        return (1, int(suffix) if suffix.isdigit() else suffix)

    return sorted(profiles, key=sort_key)


def _ytdlp_filepath(info: dict, ydl) -> Optional[Path]:
    requested = info.get("requested_downloads") or []
    for item in requested:
        filepath = item.get("filepath") or item.get("_filename")
        if filepath:
            return Path(filepath)
    filepath = info.get("filepath") or info.get("_filename")
    if filepath:
        return Path(filepath)
    try:
        return Path(ydl.prepare_filename(info))
    except Exception:
        return None


def _compact_ytdlp_metadata(info: dict) -> dict:
    keys = [
        "id",
        "title",
        "webpage_url",
        "extractor",
        "extractor_key",
        "duration",
        "thumbnail",
        "uploader",
        "channel",
        "ext",
        "format",
        "width",
        "height",
        "resolution",
        "filesize",
        "filesize_approx",
    ]
    return {key: info.get(key) for key in keys if info.get(key) is not None}


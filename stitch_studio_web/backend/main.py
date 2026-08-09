from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
STITCH_ROOT = ROOT / "stitch_studio"
if str(STITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(STITCH_ROOT))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from stitch_studio.config import AppConfig, ensure_dirs  # noqa: E402
from stitch_studio.audio_separation import AUDIO_MODE_ORIGINAL, AUDIO_MODE_REMOVE_MUSIC, AUDIO_MODE_REMOVE_VOCALS, AUDIO_MODES, AUDIO_SEPARATOR_MODEL, AudioSeparationService  # noqa: E402
from stitch_studio.models import SubtitleSegment, VideoItem  # noqa: E402
from stitch_studio.services import CapcutTtsService, DownloaderService, PocketTtsService, SubtitleRemovalService, TranslationService, TranscriptionService, VieneuTtsService, _clean_capcut_tts_text, _probe_video_duration_ms, _probe_video_size, _tts_generation_signature, extract_video_url, process_and_register_adaptive_timeline, process_and_register_srt_slot_timeline  # noqa: E402
from stitch_studio.srt import read_srt, seconds_to_srt_time, write_srt  # noqa: E402
from stitch_studio.storage import Storage  # noqa: E402


app = FastAPI(title="Nun Studio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config = AppConfig()
ensure_dirs(config)
storage = Storage(config.db_path)
downloader = DownloaderService(config, storage)
transcriber = TranscriptionService(config, storage)
translator = TranslationService(config, storage)
tts = VieneuTtsService(config, storage)
capcut_tts = CapcutTtsService(config, storage)
pocket_tts = PocketTtsService(config, storage)
subtitle_remover = SubtitleRemovalService(config, storage)
audio_separator = AudioSeparationService(config, storage)

jobs: dict[int, dict[str, Any]] = {}
next_job_id = 1
jobs_lock = threading.Lock()


class JobCancelled(RuntimeError):
    pass


class DownloadRequest(BaseModel):
    url: str


class SrtGenerateRequest(BaseModel):
    source: str = "audio"
    model: str = "tiny"
    device: str = "cpu"
    language: str = "auto"
    hardsubMode: str = "fast"
    ocrArea: Any = None
    timelineSpeed: float | None = None


class SrtSaveRequest(BaseModel):
    content: str


class TtsRequest(BaseModel):
    voice: str = ""
    srtAssetId: int | None = None
    engine: str = "vieneu"
    language: str = "vi-VN"
    rate: str = "1.0"
    timingMode: str = "srt_slot"
    minWorkingSpeed: float = 0.7
    preferredMaxLocalSpeed: float = 1.15
    hardMaxLocalSpeed: float = 1.50
    safetyGap: float = 0.12


class StandaloneTtsRequest(TtsRequest):
    content: str
    inputMode: str = "text"
    title: str = "Text To Speech"


class TimelineRemapRequest(BaseModel):
    srtAssetId: int | None = None
    minWorkingSpeed: float = 0.7
    preferredMaxLocalSpeed: float = 1.15
    hardMaxLocalSpeed: float = 1.30
    safetyGap: float = 0.12


class TtsSegmentRequest(TtsRequest):
    pass


class SubtitleRemoveRequest(BaseModel):
    mode: str = "blur"
    area: Any = "bottom"
    srtAssetId: int | None = None


class SubtitleReplaceRequest(BaseModel):
    srtAssetId: int
    mode: str = "none"
    area: Any = "bottom"
    style: dict[str, Any] | None = None


class SrtTranslateRequest(BaseModel):
    srtAssetId: int | None = None
    sourceLanguage: str = "auto"
    targetLanguage: str = "vi"
    engine: str = "madlad400-ct2"
    device: str = "cpu"


class SettingsRequest(BaseModel):
    douyinCookie: str | None = None


class YoutubeChannelUpdateRequest(BaseModel):
    name: str | None = None
    references_json: str | None = None


class YoutubePromptRequest(BaseModel):
    name: str
    content: str


class VideoRenameRequest(BaseModel):
    title: str


class ProjectCreateRequest(BaseModel):
    title: str = "Untitled Project"
    videoIds: list[int] = []


class ProjectAttachVideosRequest(BaseModel):
    videoIds: list[int] = []


class ProjectAttachAssetsRequest(BaseModel):
    assetIds: list[int] = []


class ProjectTimelineRequest(BaseModel):
    items: list[dict[str, Any]] = []
    timelineState: dict[str, Any] | None = None


class ProjectCleanupDeleteRequest(BaseModel):
    itemIds: list[str] = []


class ClipSettingsRequest(BaseModel):
    videoScale: float | None = None
    videoVolumeDb: float | None = None
    videoSpeed: float | None = None
    voiceVolumeDb: float | None = None
    voiceSpeed: float | None = None


class SubtitleEditorSettingsRequest(BaseModel):
    area: Any
    blurEffectArea: Any = None
    style: Any = None


class SubtitleUndoRequest(BaseModel):
    operation: str


class AudioModeRequest(BaseModel):
    mode: str = AUDIO_MODE_ORIGINAL


def _new_job(kind: str, title: str, video_id: int | None = None) -> int:
    global next_job_id
    with jobs_lock:
        job_id = next_job_id
        next_job_id += 1
        jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "title": title,
            "status": "queued",
            "progress": 0.0,
            "detail": "Queued",
            "createdAt": time.time(),
            "videoId": video_id,
        }
    return job_id


def _active_job(kind: str, video_id: int) -> dict[str, Any] | None:
    with jobs_lock:
        for job in sorted(jobs.values(), key=lambda item: item["createdAt"], reverse=True):
            if job.get("kind") == kind and job.get("videoId") == video_id and job.get("status") in {"queued", "running"}:
                return job
    return None


def _update_job(job_id: int, **changes: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(changes)


def _job_progress(job_id: int) -> float:
    with jobs_lock:
        return float(jobs.get(job_id, {}).get("progress") or 0.0)


def _job_cancelled(job_id: int) -> bool:
    with jobs_lock:
        return bool(jobs.get(job_id, {}).get("cancelRequested") or jobs.get(job_id, {}).get("status") == "cancelled")


def _timeline_options(payload: TtsRequest | TimelineRemapRequest) -> dict[str, float]:
    min_speed = max(0.5, min(float(payload.minWorkingSpeed), 1.0))
    preferred_speed = max(1.0, min(float(payload.preferredMaxLocalSpeed), 1.6))
    hard_speed = max(preferred_speed, min(float(payload.hardMaxLocalSpeed), 2.0))
    safety_gap = max(0.02, min(float(payload.safetyGap), 0.3))
    return {
        "min_working_speed": min_speed,
        "preferred_max_local_speed": preferred_speed,
        "hard_max_local_speed": hard_speed,
        "max_speed": hard_speed,
        "safety_gap": safety_gap,
    }


def _srt_timeline_speed(video, payload: SrtGenerateRequest) -> float:
    stored = ((video.metadata or {}).get("clip_settings") or {}).get("videoSpeed")
    requested = payload.timelineSpeed if payload.timelineSpeed is not None else stored
    try:
        speed = float(requested if requested is not None else 1.0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid video speed for SRT generation") from exc
    if speed != speed or speed in (float("inf"), float("-inf")):
        raise HTTPException(400, "Invalid video speed for SRT generation")
    return max(0.1, min(80.0, speed))


def _split_plain_text_chunks(text: str, max_words: int = 90) -> list[str]:
    chunks: list[str] = []
    pending: list[str] = []
    pending_words = 0

    def flush() -> None:
        nonlocal pending, pending_words
        if pending:
            chunks.append(" ".join(pending).strip())
            pending = []
            pending_words = 0

    paragraphs = [block.strip() for block in re.split(r"\n+", text) if block.strip()]
    for paragraph in paragraphs:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        for sentence in sentences or [paragraph]:
            words = re.findall(r"\S+", sentence)
            if not words:
                continue
            if len(words) > max_words:
                flush()
                for index in range(0, len(words), max_words):
                    chunks.append(" ".join(words[index:index + max_words]))
                continue
            if pending_words and pending_words + len(words) > max_words:
                flush()
            pending.append(sentence)
            pending_words += len(words)
    flush()
    return chunks


def _plain_text_to_srt(content: str) -> list[SubtitleSegment]:
    lines = [line.strip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    text = "\n".join(lines).strip()
    if not text:
        raise HTTPException(400, "Text content is empty")
    segments: list[SubtitleSegment] = []
    cursor = 0.0
    for index, chunk in enumerate(_split_plain_text_chunks(text), start=1):
        words = re.findall(r"\S+", chunk)
        duration = max(1.0, min(180.0, len(words) / 2.6))
        segments.append(SubtitleSegment(index=index, start=cursor, end=cursor + duration, text=chunk))
        cursor += duration
    return segments


def _content_to_standalone_srt(payload: StandaloneTtsRequest, output_dir: Path) -> Path:
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "TTS content is empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "source.srt"
    if payload.inputMode == "srt":
        raw_path = output_dir / "source_input.srt"
        raw_path.write_text(content, encoding="utf-8")
        segments = read_srt(raw_path)
        if not segments:
            raise HTTPException(400, "SRT content does not contain readable subtitle segments")
        write_srt(segments, srt_path)
        return srt_path
    if payload.inputMode != "text":
        raise HTTPException(400, f"Unsupported TTS input mode: {payload.inputMode}")
    write_srt(_plain_text_to_srt(content), srt_path)
    return srt_path


def _standalone_tts_video(payload: StandaloneTtsRequest, output_dir: Path, srt_path: Path):
    marker_path = output_dir / "standalone_tts_source.txt"
    marker_path.write_text(payload.content.strip(), encoding="utf-8")
    title = payload.title.strip()[:160] or "Text To Speech"
    segments = read_srt(srt_path)
    duration_ms = int((max((segment.end for segment in segments), default=0.0) + 1.0) * 1000)
    video_id = storage.upsert_video(
        title=title,
        source_url="standalone:tts",
        source="standalone:tts",
        path=marker_path,
        media_type="audio",
        duration_ms=max(duration_ms, 1000),
        size_bytes=marker_path.stat().st_size,
        metadata={
            "hidden": True,
            "standalone_tts": True,
            "input_mode": payload.inputMode,
            "source_srt": str(srt_path),
        },
    )
    video = storage.get_video(video_id)
    if not video:
        raise HTTPException(500, "Could not create standalone TTS workspace")
    return video


def _synthesize_tts_for_video(video, srt_path: Path, payload: TtsRequest, progress: Callable[[str], None]) -> Path:
    engine = payload.engine or "vieneu"
    if engine not in {"vieneu", "capcut", "pocket"}:
        raise HTTPException(400, f"Unsupported TTS engine: {engine}")
    requested_timing_mode = payload.timingMode or "srt_slot"
    if (video.metadata or {}).get("standalone_tts") and (video.metadata or {}).get("input_mode") == "text":
        requested_timing_mode = "plain"
    if requested_timing_mode not in {"adaptive", "manual", "srt_slot", "plain"}:
        raise HTTPException(400, f"Unsupported TTS timing mode: {requested_timing_mode}")
    timing_mode = "plain" if requested_timing_mode == "plain" else "srt_slot"
    timeline_playback_speed = 1.0
    voice = "" if payload.voice == "default" else payload.voice
    timeline_options = _timeline_options(payload)
    if engine == "capcut":
        return capcut_tts.synthesize_srt(
            video,
            srt_path,
            voice=voice,
            language=payload.language,
            rate=payload.rate,
            timing_mode=timing_mode,
            timeline_playback_speed=timeline_playback_speed,
            timeline_options=timeline_options,
            progress=progress,
        )
    if engine == "pocket":
        return pocket_tts.synthesize_srt(
            video,
            srt_path,
            voice=voice,
            language=payload.language,
            timing_mode=timing_mode,
            timeline_playback_speed=timeline_playback_speed,
            timeline_options=timeline_options,
            progress=progress,
        )
    return tts.synthesize_srt(
        video,
        srt_path,
        voice=voice,
        timing_mode=timing_mode,
        timeline_playback_speed=timeline_playback_speed,
        timeline_options=timeline_options,
        progress=progress,
    )


def _hardsub_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"vsf progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.05 + 0.70 * (percent / 100), f"Extracting subtitle frames ({percent}%)"

    match = re.search(r"ocr progress:\s*(\d+)\s*/\s*(\d+)", low)
    if match:
        done = int(match.group(1))
        total = max(1, int(match.group(2)))
        ratio = min(done / total, 1.0)
        return 0.76 + 0.19 * ratio, f"Recognizing subtitle text ({done}/{total})"

    match = re.search(r"ocr\s+(\d+)\s+hard-sub frame", low)
    if match:
        return 0.76, f"Recognizing subtitle text ({match.group(1)} frames)"

    if "preparing video for hard-sub ocr" in low:
        return 0.03, "Preparing video for OCR"
    if "running hard-sub ocr" in low or "running videosubfinder" in low:
        return 0.05, "Extracting subtitle frames"
    if "hard-sub srt exported" in low:
        return 0.98, "Saving SRT"
    return None


def _tts_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"reusing cached (?:capcut\s+|pocket\s+)?tts segment\s+(\d+)\s*/\s*(\d+)", low)
    if match:
        current = int(match.group(1))
        total = max(1, int(match.group(2)))
        ratio = min(max(current, 0) / total, 1.0)
        return 0.05 + 0.80 * ratio, f"Reusing cached voice segment {current}/{total}"

    match = re.search(r"(?:capcut\s+|pocket\s+)?tts segment\s+(\d+)\s*/\s*(\d+)", low)
    if match:
        current = int(match.group(1))
        total = max(1, int(match.group(2)))
        ratio = min(max(current - 1, 0) / total, 1.0)
        return 0.05 + 0.80 * ratio, f"Generating voice segment {current}/{total}"
    if "tts exported" in low or "capcut tts exported" in low:
        return 0.98, "Saving voiceover"
    return None


def _subtitle_remove_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"subtitle mask detection:\s*(\d+)\s*/\s*(\d+)", low)
    if match:
        current = int(match.group(1))
        total = max(1, int(match.group(2)))
        ratio = min(max(current, 0) / total, 1.0)
        return 0.08 + 0.27 * ratio, f"Detecting subtitle positions ({current}/{total})"
    match = re.search(r"timed blur progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.38 + 0.57 * (percent / 100), f"Blurring subtitle intervals ({percent}%)"
    match = re.search(r"ffmpeg progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.10 + 0.85 * (percent / 100), f"Hiding subtitles ({percent}%)"
    match = re.search(r"vsr progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.10 + 0.70 * (percent / 100), f"Removing subtitles / processing frames ({percent}%)"
    if "preparing subtitle removal" in low:
        return 0.05, "Preparing"
    if "preparing automatic subtitle mask" in low:
        return 0.05, "Preparing automatic subtitle mask"
    if "detecting subtitle positions" in low:
        return 0.08, "Loading PP-OCRv5 detector"
    if "subtitle mask cache" in low:
        return 0.35, "Using cached subtitle positions"
    if "rendering timed subtitle blur" in low:
        return 0.38, "Blurring subtitle intervals"
    if "hiding subtitles with ffmpeg" in low:
        return 0.10, "Hiding subtitles"
    if "removing subtitles with vsr" in low or "removing subtitles / processing frames" in low:
        return 0.10, "Removing subtitles / processing frames"
    if "encoding output" in low:
        return 0.85, "Encoding output"
    if "saving removed-subtitle video" in low or "saving video" in low:
        return 0.95, "Saving video"
    if "removed-subtitle video exported" in low:
        return 0.98, "Saving video"
    return None


def _subtitle_replace_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"subtitle render progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.10 + 0.85 * (percent / 100), f"Rendering translated subtitles ({percent}%)"
    if "preparing translated subtitle render" in low:
        return 0.05, "Preparing video"
    if "rendering translated subtitles" in low:
        return 0.10, "Rendering translated subtitles"
    if "saving translated video" in low or "translated video exported" in low:
        return 0.97, "Saving translated video"
    return None


def _transcription_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"transcribing progress:\s*(\d+)\s*%", low)
    if match:
        percent = min(max(int(match.group(1)), 0), 100)
        return 0.05 + 0.90 * (percent / 100), f"Transcribing ({percent}%)"
    if "loading faster-whisper model" in low:
        return 0.02, "Loading Whisper model"
    if "using cached faster-whisper model" in low:
        return 0.04, "Using cached Whisper model"
    if "whisper model ready" in low:
        return 0.05, "Whisper model ready"
    if "srt exported" in low:
        return 0.98, "Saving SRT"
    if "transcribing" in low:
        return 0.05, "Transcribing"
    return None


def _translation_progress(message: str, low: str) -> tuple[float, str] | None:
    match = re.search(r"translation progress:\s*(\d+)\s*/\s*(\d+)", low)
    if match:
        done = int(match.group(1))
        total = max(1, int(match.group(2)))
        ratio = min(max(done, 0) / total, 1.0)
        return 0.10 + 0.85 * ratio, f"Translating subtitles ({done}/{total})"
    if "translating" in low:
        return 0.08, "Loading translation model"
    return None


def _audio_separation_progress(message: str, low: str) -> tuple[float, str] | None:
    if "audio separation" not in low and "separating vocals and music" not in low and "saving instrumental stem" not in low and "saving vocal stem" not in low:
        return None
    match = re.search(r"\((\d+)%\)", message)
    if not match:
        match = re.search(r"audio separation progress:\s*(\d+)%", low)
    value = min(99, max(1, int(match.group(1)))) / 100 if match else 0.02
    detail = re.sub(r"\s*\(\d+%\)\s*$", "", message).strip()
    if low.startswith("audio separation progress"):
        detail = f"Separating vocals and music ({round(value * 100)}%)"
    return value, detail or "Separating vocals and music"


def _run_job(job_id: int, fn: Callable[[Callable[[str], None]], Any]) -> None:
    def progress(message: str) -> None:
        if _job_cancelled(job_id):
            raise JobCancelled("Job cancelled")
        low = message.lower()
        parsed = _audio_separation_progress(message, low) or _hardsub_progress(message, low) or _tts_progress(message, low) or _subtitle_replace_progress(message, low) or _subtitle_remove_progress(message, low) or _transcription_progress(message, low) or _translation_progress(message, low)
        if parsed:
            value, detail = parsed
            value = max(_job_progress(job_id), value)
            _update_job(job_id, status="running", progress=value, detail=detail)
            return

        value = 0.02
        detail = message
        match = re.search(r"ocr progress:\s*(\d+)\s*/\s*(\d+)", low)
        if match:
            done = int(match.group(1))
            total = max(1, int(match.group(2)))
            value = 0.45 + 0.45 * min(done / total, 1.0)
        elif "ocr " in low and "frame" in low:
            value = 0.45
        if "export" in low or "downloaded" in low:
            value = 0.9
        value = max(_job_progress(job_id), value)
        _update_job(job_id, status="running", progress=value, detail=detail)

    def runner() -> None:
        _update_job(job_id, status="running", progress=0.01, detail="Starting")
        try:
            if _job_cancelled(job_id):
                raise JobCancelled("Job cancelled")
            result = fn(progress)
            if _job_cancelled(job_id):
                raise JobCancelled("Job cancelled")
            result_value = result
            if not isinstance(result, (dict, list, str, int, float, bool, type(None))):
                result_value = str(result)
            result_detail = result.get("outputPath", "Completed") if isinstance(result, dict) else str(result)
            _update_job(job_id, status="completed", progress=1.0, detail=result_detail, result=result_value)
        except JobCancelled:
            _update_job(job_id, status="cancelled", detail="Cancelled", cancelRequested=True)
        except Exception as exc:
            if _job_cancelled(job_id):
                _update_job(job_id, status="cancelled", detail="Cancelled", cancelRequested=True)
            else:
                _update_job(job_id, status="error", progress=0.0, detail=str(exc))

    threading.Thread(target=runner, daemon=True).start()


MEDIA_DURATION_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def _metadata_duration_ms(metadata: dict[str, Any]) -> int:
    for key in ("duration_ms", "durationMs", "audio_duration_ms"):
        try:
            value = int(float(metadata.get(key) or 0))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    try:
        seconds = float(metadata.get("duration_seconds") or metadata.get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return int(seconds * 1000) if seconds > 0 else 0


def _metadata_with_media_duration(metadata: dict[str, Any] | None, path: Path) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    if _metadata_duration_ms(next_metadata) > 0:
        return next_metadata
    if path.exists() and path.suffix.lower() in MEDIA_DURATION_SUFFIXES:
        duration_ms = _probe_video_duration_ms(path) or 0
        if duration_ms > 0:
            next_metadata["duration_ms"] = duration_ms
    return next_metadata


def _asset_belongs_to_video(asset, video) -> bool:
    if asset.video_id == video.id:
        return True
        
    for workspace in storage.list_projects():
        video_in_workspace = False
        for p_asset in storage.list_project_assets(workspace.id):
            if p_asset.source_video_id == video.id:
                video_in_workspace = True
                break
                
        if video_in_workspace:
            if storage.project_asset_for_asset(workspace.id, asset.id):
                return True
            if asset.video_id == workspace.id:
                return True
            asset_video = storage.get_video(asset.video_id)
            if asset_video and asset_video.metadata and asset_video.metadata.get("workspace_id") == workspace.id:
                return True

    return False


def _asset_payload(asset) -> dict[str, Any]:
    metadata = _metadata_with_media_duration(asset.metadata or {}, asset.path)
    if metadata != (asset.metadata or {}):
        storage.update_asset_metadata(asset.id, metadata)
    return {
        "id": asset.id,
        "videoId": asset.video_id,
        "kind": asset.kind,
        "path": str(asset.path),
        "name": asset.path.name,
        "engine": asset.engine,
        "status": asset.status,
        "createdAt": asset.created_at,
        "metadata": metadata,
    }


def _project_asset_payload(asset, include_linked: bool = True) -> dict[str, Any]:
    metadata = _metadata_with_media_duration(asset.metadata or {}, asset.path)
    if asset.source_video_id:
        video = storage.get_video(asset.source_video_id)
        if video and video.duration_ms and _metadata_duration_ms(metadata) <= 0:
            metadata["duration_ms"] = video.duration_ms
    if asset.source_asset_id:
        linked = storage.get_asset(asset.source_asset_id)
        if linked:
            linked_metadata = _metadata_with_media_duration(linked.metadata or {}, linked.path)
            if linked_metadata != (linked.metadata or {}):
                storage.update_asset_metadata(linked.id, linked_metadata)
            if _metadata_duration_ms(metadata) <= 0 and _metadata_duration_ms(linked_metadata) > 0:
                metadata["duration_ms"] = _metadata_duration_ms(linked_metadata)
    payload = {
        "id": asset.id,
        "projectId": asset.project_id,
        "kind": asset.kind,
        "path": str(asset.path),
        "name": asset.name,
        "status": asset.status,
        "createdAt": asset.created_at,
        "sourceVideoId": asset.source_video_id,
        "sourceAssetId": asset.source_asset_id,
        "metadata": metadata,
    }
    if include_linked and asset.source_video_id:
        video = storage.get_video(asset.source_video_id)
        if video:
            payload["video"] = _video_payload(video)
    if include_linked and asset.source_asset_id:
        linked = storage.get_asset(asset.source_asset_id)
        if linked:
            payload["asset"] = _asset_payload(linked)
    return payload


def _workspace_project_payload(project) -> dict[str, Any]:
    assets = storage.list_project_assets(project.id)
    videos = [storage.get_video(item.source_video_id) for item in assets if item.kind == "video" and item.source_video_id]
    video_payloads = [_video_payload(video, include_workspace_assets=False) for video in videos if video]
    primary = storage.get_video(project.primary_video_id) if project.primary_video_id else (videos[0] if videos else None)
    metadata = project.metadata or {}
    timeline = metadata.get("timeline") or []
    timeline_state = metadata.get("timeline_state") or None
    timeline_duration_ms = max(
        [
            int((float(item.get("start") or 0) + float(item.get("duration") or 0)) * 1000)
            for item in timeline
            if isinstance(item, dict)
        ] or [0],
    )
    total_size = sum(int((item.metadata or {}).get("size_bytes") or (item.path.stat().st_size if item.path.exists() else 0)) for item in assets)
    latest_created = max([project.created_at, *[item.created_at for item in assets]], default=project.created_at)
    return {
        "id": project.id,
        "title": project.title,
        "primaryVideoId": primary.id if primary else None,
        "primaryVideo": _video_payload(primary, include_workspace_assets=False) if primary else None,
        "projectId": f"workspace-{project.id}",
        "createdAt": latest_created,
        "durationMs": timeline_duration_ms or max([int(video.duration_ms or 0) for video in videos if video] or [0]),
        "sizeBytes": total_size,
        "videos": video_payloads,
        "assets": [_project_asset_payload(asset, include_linked=False) for asset in assets],
        "timeline": timeline,
        "timelineState": timeline_state,
        "metadata": metadata,
    }


def _owned_file_roots() -> tuple[Path, Path]:
    return (config.downloads_dir.resolve(), config.outputs_dir.resolve())


def _is_owned_file(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in _owned_file_roots())


def _cleanup_item_payload(
    *,
    item_id: str,
    kind: str,
    path: Path,
    name: str | None = None,
    source: str,
    project_asset_id: int | None = None,
    source_video_id: int | None = None,
    source_asset_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    exists = path.is_file()
    size_bytes = 0
    if exists:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
    else:
        try:
            size_bytes = int(metadata.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
    owned = _is_owned_file(path)
    return {
        "id": item_id,
        "kind": kind,
        "name": name or path.name,
        "path": str(path),
        "source": source,
        "exists": exists,
        "canDelete": owned and exists,
        "sizeBytes": size_bytes,
        "projectAssetId": project_asset_id,
        "sourceVideoId": source_video_id,
        "sourceAssetId": source_asset_id,
        "metadata": metadata,
    }


def _project_cleanup_items(project) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_item(payload: dict[str, Any]) -> None:
        key = str(Path(payload["path"]).resolve()).lower()
        if key in seen_paths:
            return
        seen_paths.add(key)
        items.append(payload)

    for project_asset in storage.list_project_assets(project.id):
        metadata = project_asset.metadata or {}
        if project_asset.source_video_id:
            video = storage.get_video(project_asset.source_video_id)
            if video:
                add_item(_cleanup_item_payload(
                    item_id=f"video:{video.id}",
                    kind="video",
                    path=video.path,
                    name=project_asset.name or video.path.name,
                    source="downloaded video",
                    project_asset_id=project_asset.id,
                    source_video_id=video.id,
                    metadata={"title": video.title, "duration_ms": video.duration_ms, "size_bytes": video.size_bytes},
                ))
                for linked_asset in storage.list_assets(video.id):
                    add_item(_cleanup_item_payload(
                        item_id=f"asset:{linked_asset.id}",
                        kind=linked_asset.kind,
                        path=linked_asset.path,
                        source="video asset",
                        source_video_id=video.id,
                        source_asset_id=linked_asset.id,
                        metadata=linked_asset.metadata or {},
                    ))
                continue
        if project_asset.source_asset_id:
            linked_asset = storage.get_asset(project_asset.source_asset_id)
            if linked_asset:
                add_item(_cleanup_item_payload(
                    item_id=f"asset:{linked_asset.id}",
                    kind=project_asset.kind,
                    path=linked_asset.path,
                    name=project_asset.name or linked_asset.path.name,
                    source="project asset",
                    project_asset_id=project_asset.id,
                    source_asset_id=linked_asset.id,
                    metadata=linked_asset.metadata or metadata,
                ))
                continue
        add_item(_cleanup_item_payload(
            item_id=f"project_asset:{project_asset.id}",
            kind=project_asset.kind,
            path=project_asset.path,
            name=project_asset.name,
            source="project upload",
            project_asset_id=project_asset.id,
            metadata=metadata,
        ))
    return items


def _delete_owned_path_if_unreferenced(path: Path) -> bool:
    if not _is_owned_file(path) or not path.is_file():
        return False
    if storage.path_is_referenced(path):
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _video_has_active_job(video_id: int) -> bool:
    with jobs_lock:
        return any(
            job.get("videoId") == video_id and job.get("status") in {"queued", "running"}
            for job in jobs.values()
        )


def _delete_video_and_owned_files(video) -> dict[str, Any]:
    if _video_has_active_job(video.id):
        raise HTTPException(409, "Stop active jobs for this video before deleting it")

    owned_paths = [video.path, *(asset.path for asset in storage.list_assets(video.id))]
    storage.delete_video(video.id)
    deleted_files = sum(1 for path in owned_paths if _delete_owned_path_if_unreferenced(path))

    video_output_dir = config.outputs_dir / f"video_{video.id}"
    deleted_dirs = 0
    for generated_dir in (video_output_dir / "preview", video_output_dir / "audio_separation"):
        try:
            if generated_dir.exists() and generated_dir.resolve().is_relative_to(config.outputs_dir.resolve()):
                shutil.rmtree(generated_dir, ignore_errors=True)
                deleted_dirs += 1
        except OSError:
            pass
    return {"deletedVideoId": video.id, "deletedFiles": deleted_files, "deletedDirs": deleted_dirs}


def _delete_cleanup_item(project_id: int, item_id: str) -> dict[str, Any]:
    try:
        item_kind, raw_id = item_id.split(":", 1)
        numeric_id = int(raw_id)
    except (ValueError, TypeError):
        raise HTTPException(400, f"Invalid cleanup item: {item_id}")

    if item_kind == "video":
        video = storage.get_video(numeric_id)
        if not video:
            return {"id": item_id, "deletedFiles": 0, "missing": True}
        project_asset = storage.project_asset_for_video(project_id, video.id)
        if not project_asset:
            raise HTTPException(404, "Cleanup item not found in this project")
        if storage.project_video_reference_count(video.id) > 1:
            storage.delete_project_asset(project_asset.id)
            return {"id": item_id, "deletedFiles": 0, "shared": True}
        result = _delete_video_and_owned_files(video)
        return {"id": item_id, **result}

    if item_kind == "asset":
        asset = storage.get_asset(numeric_id)
        if not asset:
            return {"id": item_id, "deletedFiles": 0, "missing": True}
        linked_project_asset = storage.project_asset_for_asset(project_id, asset.id)
        parent_video_asset = storage.project_asset_for_video(project_id, asset.video_id)
        if not linked_project_asset and not parent_video_asset:
            raise HTTPException(404, "Cleanup item not found in this project")
        if parent_video_asset and storage.project_video_reference_count(asset.video_id) > 1:
            return {"id": item_id, "deletedFiles": 0, "shared": True}
        if linked_project_asset and storage.project_asset_reference_count(asset.id) > 1:
            storage.delete_project_asset(linked_project_asset.id)
            return {"id": item_id, "deletedFiles": 0, "shared": True}
        path = asset.path
        storage.delete_asset(asset.id)
        return {"id": item_id, "deletedAssetId": asset.id, "deletedFiles": 1 if _delete_owned_path_if_unreferenced(path) else 0}

    if item_kind == "project_asset":
        project_asset = storage.get_project_asset(numeric_id)
        if not project_asset:
            return {"id": item_id, "deletedFiles": 0, "missing": True}
        if project_asset.project_id != int(project_id):
            raise HTTPException(404, "Cleanup item not found in this project")
        path = project_asset.path
        storage.delete_project_asset(project_asset.id)
        return {"id": item_id, "deletedProjectAssetId": project_asset.id, "deletedFiles": 1 if _delete_owned_path_if_unreferenced(path) else 0}

    raise HTTPException(400, f"Unsupported cleanup item: {item_id}")


def _delete_project_and_owned_files(project) -> dict[str, Any]:
    deleted_files = 0
    results: list[dict[str, Any]] = []
    deleted_video_ids: set[int] = set()

    project_assets = storage.list_project_assets(project.id)
    for project_asset in project_assets:
        if not project_asset.source_video_id:
            continue
        video = storage.get_video(project_asset.source_video_id)
        if not video:
            continue
        if storage.project_video_reference_count(video.id) > 1:
            results.append({"id": f"video:{video.id}", "shared": True, "deletedFiles": 0})
            continue
        result = _delete_video_and_owned_files(video)
        deleted_video_ids.add(video.id)
        deleted_files += int(result.get("deletedFiles") or 0)
        results.append({"id": f"video:{video.id}", **result})

    for project_asset in project_assets:
        if project_asset.source_video_id:
            continue
        if project_asset.source_asset_id:
            asset = storage.get_asset(project_asset.source_asset_id)
            if not asset or asset.video_id in deleted_video_ids:
                continue
            if storage.project_asset_reference_count(asset.id) > 1:
                results.append({"id": f"asset:{asset.id}", "shared": True, "deletedFiles": 0})
                continue
            path = asset.path
            storage.delete_asset(asset.id)
            removed = _delete_owned_path_if_unreferenced(path)
            deleted_files += 1 if removed else 0
            results.append({"id": f"asset:{asset.id}", "deletedAssetId": asset.id, "deletedFiles": 1 if removed else 0})
            continue

        path = project_asset.path
        storage.delete_project_asset(project_asset.id)
        removed = _delete_owned_path_if_unreferenced(path)
        deleted_files += 1 if removed else 0
        results.append({"id": f"project_asset:{project_asset.id}", "deletedProjectAssetId": project_asset.id, "deletedFiles": 1 if removed else 0})

    deleted = storage.delete_workspace_project(project.id)
    return {"deleted": deleted, "deletedFiles": deleted_files, "results": results}


def _is_translation_srt(asset) -> bool:
    metadata = asset.metadata or {}
    return "madlad400" in (asset.engine or "").lower() or metadata.get("role") == "translation"


def _primary_srt_asset(video):
    return next(
        (asset for asset in storage.list_assets(video.id) if asset.kind == "srt" and asset.path.exists() and not _is_translation_srt(asset)),
        None,
    )


def _backup_srt_asset(video, asset, reason: str) -> None:
    if not asset or not asset.path.exists():
        return
    backup_dir = config.outputs_dir / f"video_{video.id}" / "subtitles" / "history"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{asset.path.stem}.{reason}.{stamp}_{time.time_ns() % 1_000_000:06d}.srt"
    shutil.copy2(asset.path, backup_path)
    storage.add_asset(
        video_id=video.id,
        kind="srt_backup",
        path=backup_path,
        engine=f"history:{reason}",
        metadata={"source_asset_id": asset.id, "reason": reason, "source_srt": str(asset.path)},
    )


def _replace_srt_asset(video, asset, content: str, reason: str):
    _backup_srt_asset(video, asset, reason)
    asset.path.write_text(content, encoding="utf-8")
    metadata = dict(asset.metadata or {})
    metadata.update({"role": "primary", "last_replaced_reason": reason})
    storage.update_asset_metadata(asset.id, metadata)
    return storage.get_asset(asset.id)


def _normalize_area_ratio(area: Any) -> dict[str, float] | None:
    if not isinstance(area, dict):
        return None
    try:
        values = {
            "xmin": float(area["xmin"]),
            "xmax": float(area["xmax"]),
            "ymin": float(area["ymin"]),
            "ymax": float(area["ymax"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if values["xmax"] <= values["xmin"] or values["ymax"] <= values["ymin"]:
        return None
    return {
        key: max(0.0, min(1.0, value))
        for key, value in values.items()
    }


def _subtitle_area_payload(video, metadata: dict[str, Any]) -> dict[str, float] | None:
    ratio = _normalize_area_ratio(metadata.get("area_ratio"))
    if ratio:
        return ratio

    area = metadata.get("area")
    if not isinstance(area, dict):
        return None
    try:
        raw = {
            "xmin": float(area["xmin"]),
            "xmax": float(area["xmax"]),
            "ymin": float(area["ymin"]),
            "ymax": float(area["ymax"]),
        }
    except (KeyError, TypeError, ValueError):
        return None

    if max(raw.values()) <= 1.0:
        return _normalize_area_ratio(raw)

    source_path = Path(str(metadata.get("source_video_path") or video.path))
    try:
        width, height = _probe_video_size(source_path)
    except Exception:
        width, height = _probe_video_size(video.path)
    if width <= 0 or height <= 0:
        return None
    return _normalize_area_ratio(
        {
            "xmin": raw["xmin"] / width,
            "xmax": raw["xmax"] / width,
            "ymin": raw["ymin"] / height,
            "ymax": raw["ymax"] / height,
        }
    )


def _video_payload(video, include_workspace_assets: bool = True) -> dict[str, Any]:
    assets = storage.list_assets(video.id)
    metadata = video.metadata or {}
    workspace = storage.find_project_for_video(video.id)
    duration_ms = video.duration_ms
    if not duration_ms and video.path.exists():
        duration_ms = _probe_video_duration_ms(video.path)
        if duration_ms:
            storage.update_video_duration(video.id, duration_ms)
    state = dict(metadata.get("processing_state") or {})
    if video.source == "vsr:remove-subtitles" or video.source.startswith("ffmpeg:blur-") or video.source.startswith("ffmpeg:cover-") or video.source == "ffmpeg:timed-blur-subtitles":
        state.setdefault("subtitle_hidden", True)
        state.setdefault("last_operation", "hide")
    if video.source == "ffmpeg:replace-subtitles":
        state.setdefault("subtitle_inserted", True)
        if metadata.get("mode") in {"blur", "cover"}:
            state.setdefault("subtitle_hidden", True)
        state.setdefault("last_operation", "insert")
    has_srt = any(asset.kind == "srt" for asset in assets)
    has_translation = any(asset.kind == "srt" and "madlad400" in asset.engine.lower() for asset in assets)
    has_tts = any(asset.kind == "tts" for asset in assets)
    audio_stems = audio_separator.cached_stems(video)
    audio_mode = str(metadata.get("audio_mode") or AUDIO_MODE_ORIGINAL)
    if audio_mode not in AUDIO_MODES:
        audio_mode = AUDIO_MODE_ORIGINAL
    return {
        "id": video.id,
        "title": video.title,
        "sourceUrl": video.source_url,
        "source": video.source,
        "path": str(video.path),
        "name": video.path.name,
        "mediaType": video.media_type,
        "durationMs": duration_ms,
        "sizeBytes": video.size_bytes,
        "status": video.status,
        "createdAt": video.created_at,
        "assets": [_asset_payload(asset) for asset in assets],
        "hasSrt": has_srt,
        "hasTranslatedSrt": has_translation,
        "hasTts": has_tts,
        "audioMode": audio_mode,
        "audioSeparation": {
            "ready": {"vocals", "instrumental"}.issubset(audio_stems),
            "model": AUDIO_SEPARATOR_MODEL,
            "vocalsAssetId": audio_stems.get("vocals").id if audio_stems.get("vocals") else None,
            "instrumentalAssetId": audio_stems.get("instrumental").id if audio_stems.get("instrumental") else None,
        },
        "projectId": storage.project_id_for(video),
        "workspaceId": workspace.id if workspace else None,
        "workspaceTitle": workspace.title if workspace else None,
        "projectAssets": [_project_asset_payload(asset, include_linked=False) for asset in storage.list_project_assets(workspace.id)] if workspace and include_workspace_assets else [],
        "workspaceTimeline": (workspace.metadata or {}).get("timeline") or [] if workspace else [],
        "timelineState": (workspace.metadata or {}).get("timeline_state") or None if workspace else None,
        "parentVideoId": metadata.get("source_video_id"),
        "subtitleArea": _subtitle_area_payload(video, metadata),
        "subtitleStyle": metadata.get("subtitle_style") or None,
        "subtitleBlurEffect": metadata.get("subtitle_blur_effect") or None,
        "clipSettings": metadata.get("clip_settings") or None,
        "processingState": {
            "srtGenerated": has_srt,
            "srtTranslated": has_translation,
            "voiceoverGenerated": has_tts,
            "subtitleHidden": bool(state.get("subtitle_hidden")),
            "subtitleInserted": bool(state.get("subtitle_inserted")),
            "lastOperation": state.get("last_operation"),
            "hideMode": state.get("hide_mode"),
            "insertMode": state.get("insert_mode"),
        },
        "ttsTimeline": metadata.get("tts_timeline") or None,
    }


def _video_or_404(video_id: int):
    video = storage.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


def _asset_or_404(asset_id: int):
    asset = storage.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


def _latest_timeline_manifest_path(video_id: int) -> Path | None:
    manifest_asset = storage.latest_asset(video_id, "tts_timeline_manifest")
    if manifest_asset and manifest_asset.path.exists():
        return manifest_asset.path
    tts_asset = storage.latest_asset(video_id, "tts")
    if not tts_asset:
        return None
    timing = (tts_asset.metadata or {}).get("timing") or {}
    manifest = timing.get("manifest_path") or (tts_asset.metadata or {}).get("adaptive_timeline")
    if manifest:
        path = Path(str(manifest))
        if path.exists():
            return path
    for name in ("srt_slot_timeline.json", "adaptive_timeline.json"):
        fallback = tts_asset.path.parent / name
        if fallback.exists():
            return fallback
    return None


def _timeline_issue_payload(row: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    start = float(row.get("original_start_time") or 0)
    end = float(row.get("original_end_time") or 0)
    required_speed = row.get("required_local_speed")
    if required_speed is None:
        available = float(row.get("working_available_duration") or 0)
        tts_duration = float(row.get("original_tts_duration") or 0)
        required_speed = tts_duration / available if available > 0 else None
    return {
        "index": row.get("index"),
        "text": row.get("text") or "",
        "status": row.get("segment_status") or row.get("status") or "",
        "startTime": start,
        "endTime": end,
        "startLabel": seconds_to_srt_time(start),
        "endLabel": seconds_to_srt_time(end),
        "ttsDuration": row.get("original_tts_duration"),
        "availableDuration": row.get("working_available_duration"),
        "requiredLocalSpeed": required_speed,
        "hardMaxLocalSpeed": row.get("hard_max_local_speed") or row.get("max_speed") or state.get("hard_max_local_speed") or state.get("max_speed"),
    }


def _segment_engine(engine: str) -> str:
    value = (engine or "vieneu").strip().lower()
    if value not in {"vieneu", "capcut", "pocket"}:
        raise HTTPException(400, "Per-line TTS currently supports CapCut, VieNeu, and Pocket TTS only")
    return value


def _segment_output_dir(video_id: int, engine: str) -> Path:
    suffix = {"capcut": "tts_capcut", "pocket": "tts_pocket"}.get(engine, "tts_vieneu")
    path = config.outputs_dir / f"video_{video_id}" / suffix
    path.mkdir(parents=True, exist_ok=True)
    return path


def _segment_manifest_path(video_id: int, engine: str) -> Path:
    return _segment_output_dir(video_id, engine) / "manifest.json"


def _read_manifest_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _write_manifest_row(manifest_path: Path, row: dict[str, Any]) -> None:
    rows = [item for item in _read_manifest_rows(manifest_path) if int(item.get("index") or -1) != int(row["index"])]
    rows.append(row)
    rows.sort(key=lambda item: int(item.get("index") or 0))
    manifest_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_audio_path(row: dict[str, Any]) -> Path:
    return Path(str(row.get("wav") or row.get("path") or ""))


def _segment_by_index(srt_path: Path, segment_index: int) -> SubtitleSegment:
    for segment in read_srt(srt_path):
        if int(segment.index) == int(segment_index):
            return segment
    raise HTTPException(404, f"SRT line #{segment_index} not found")


def _segment_signature(engine: str, payload: TtsRequest) -> tuple[str, dict[str, Any]]:
    if engine == "capcut":
        voice_type, resource_id = capcut_tts._resolve_voice("" if payload.voice == "default" else payload.voice, payload.language)
        return _tts_generation_signature(
            engine="capcut:tts",
            voice=voice_type,
            resource_id=resource_id,
            language=payload.language,
            rate=payload.rate,
        ), {"voice_type": voice_type, "resource_id": resource_id}
    if engine == "pocket":
        language = pocket_tts._normalize_language(payload.language)
        voice = pocket_tts._normalize_voice("" if payload.voice == "default" else payload.voice, language)
        return _tts_generation_signature(
            engine="pocket-tts",
            language=language,
            voice=voice,
            quantize=os.environ.get("POCKET_TTS_QUANTIZE", "0"),
        ), {"voice": voice, "language": language}
    voice = "" if payload.voice == "default" else payload.voice
    return _tts_generation_signature(engine="vieneu:v3turbo", voice=voice or "default"), {"voice": voice or None}


def _segment_text_for_engine(segment: SubtitleSegment, engine: str) -> str:
    return _clean_capcut_tts_text(segment.text) if engine == "capcut" else segment.text.strip()


def _segment_status(row: dict[str, Any] | None, segment: SubtitleSegment, engine: str, signature: str) -> dict[str, Any]:
    expected_text = _segment_text_for_engine(segment, engine)
    path = _manifest_audio_path(row or {})
    has_audio = bool(row and path.exists())
    stale = bool(row) and (
        row.get("text") != expected_text
        or row.get("generation_signature") != signature
        or not path.exists()
    )
    return {
        "index": segment.index,
        "startLabel": seconds_to_srt_time(segment.start),
        "endLabel": seconds_to_srt_time(segment.end),
        "text": segment.text,
        "ttsText": expected_text,
        "hasAudio": has_audio and not stale,
        "stale": stale,
        "path": str(path) if has_audio else "",
        "audioUrl": f"/videos/{{video_id}}/tts/segments/{segment.index}/audio?engine={engine}" if has_audio and not stale else "",
    }


def _render_single_tts_segment(video, srt_path: Path, segment_index: int, payload: TtsSegmentRequest, progress: Callable[[str], None]) -> dict[str, Any]:
    engine = _segment_engine(payload.engine)
    segment = _segment_by_index(srt_path, segment_index)
    text = _segment_text_for_engine(segment, engine)
    if not text:
        raise RuntimeError(f"SRT line #{segment.index} has no text for TTS")
    output_dir = _segment_output_dir(video.id, engine)
    manifest_path = output_dir / "manifest.json"
    signature, voice_info = _segment_signature(engine, payload)
    if engine == "capcut":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to convert CapCut TTS mp3 segments.")
        voice_type = voice_info["voice_type"]
        resource_id = voice_info["resource_id"]
        mp3_path = output_dir / f"segment_{segment.index:04d}_original.mp3"
        wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
        progress(f"CapCut TTS segment {segment.index}/1...")
        with capcut_tts._lock:
            capcut_tts._request_segment_mp3(text, mp3_path, voice_type=voice_type, resource_id=resource_id, rate=payload.rate)
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
        row = {
            "index": segment.index,
            "start": segment.start,
            "end": segment.end,
            "text": text,
            "voice": voice_type,
            "resource_id": resource_id,
            "mp3": str(mp3_path),
            "wav": str(wav_path),
            "generation_signature": signature,
        }
    elif engine == "pocket":
        rendered_segment = SubtitleSegment(segment.index, segment.start, segment.end, text)
        _, wav_path, row = pocket_tts.render_segment_to_file(
            rendered_segment,
            output_dir,
            voice=voice_info["voice"],
            language=voice_info["language"],
            progress=progress,
        )
        row["generation_signature"] = signature
    else:
        selected_voice = voice_info["voice"]
        wav_path = output_dir / f"segment_{segment.index:04d}_original.wav"
        progress(f"TTS segment {segment.index}/1...")
        with tts._lock:
            engine_obj = tts._get_engine()
            audio = engine_obj.infer(text, voice=selected_voice)
            engine_obj.save(audio, wav_path)
        row = {
            "index": segment.index,
            "start": segment.start,
            "end": segment.end,
            "text": text,
            "path": str(wav_path),
            "generation_signature": signature,
        }
    _write_manifest_row(manifest_path, row)
    return {"index": segment.index, "path": str(_manifest_audio_path(row)), "manifest": str(manifest_path)}


def _merge_tts_segments(video, srt_path: Path, payload: TtsSegmentRequest, progress: Callable[[str], None]) -> Path:
    engine = _segment_engine(payload.engine)
    signature, voice_info = _segment_signature(engine, payload)
    manifest_path = _segment_manifest_path(video.id, engine)
    rows = {int(row.get("index") or -1): row for row in _read_manifest_rows(manifest_path)}
    rendered: list[tuple[SubtitleSegment, Path]] = []
    missing: list[str] = []
    for segment in read_srt(srt_path):
        text = _segment_text_for_engine(segment, engine)
        if not text:
            continue
        row = rows.get(segment.index)
        path = _manifest_audio_path(row or {})
        if not row:
            missing.append(f"#{segment.index} missing")
            continue
        if row.get("text") != text:
            missing.append(f"#{segment.index} text changed")
            continue
        if row.get("generation_signature") != signature:
            missing.append(f"#{segment.index} voice/settings changed")
            continue
        if not path.exists():
            missing.append(f"#{segment.index} audio missing")
            continue
        rendered.append((SubtitleSegment(segment.index, segment.start, segment.end, text), path))
    if missing:
        preview = ", ".join(missing[:18])
        extra = f", +{len(missing) - 18} more" if len(missing) > 18 else ""
        raise RuntimeError(f"Generate or regenerate these SRT lines before Merge: {preview}{extra}")
    if not rendered:
        raise RuntimeError("No rendered TTS segments found to merge")
    import soundfile as sf

    sample_rate = int(sf.info(str(rendered[0][1])).samplerate)
    timeline_options = _timeline_options(payload)
    result = process_and_register_srt_slot_timeline(
        storage,
        video,
        rendered,
        manifest_path.parent,
        engine=engine,
        source_srt=srt_path,
        sample_rate=sample_rate,
        timeline_options=timeline_options,
        progress=progress,
    )
    voiceover_path = Path(result["voiceover_path"])
    metadata: dict[str, Any] = {
        "segments": len(rendered),
        "manifest": str(manifest_path),
        "source_srt": str(srt_path),
        "timing_mode": "srt_slot",
        "timing": result["state"],
    }
    duration_ms = _probe_video_duration_ms(voiceover_path)
    if duration_ms:
        metadata["duration_ms"] = duration_ms
    if engine == "capcut":
        metadata.update({"voice": voice_info["voice_type"], "resource_id": voice_info["resource_id"], "language": payload.language})
    elif engine == "pocket":
        metadata.update({"voice": voice_info["voice"], "language": voice_info["language"]})
    else:
        metadata.update({"voice": voice_info["voice"]})
    storage.add_asset(video_id=video.id, kind="tts", path=voiceover_path, engine=f"{engine}:segment-merge", metadata=metadata)
    progress(f"TTS segment merge exported {len(rendered)} segment(s): {voiceover_path}")
    return voiceover_path


def _mux_latest_tts_video(video, progress: Callable[[str], None]) -> dict[str, Any]:
    tts_asset = storage.latest_asset(video.id, "tts")
    if not tts_asset or not tts_asset.path.exists():
        raise RuntimeError("Generate a voiceover WAV before inserting it into the video")
    if not video.path.exists():
        raise RuntimeError("Source video file was not found")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to insert the voiceover into the video")

    output_path = tts_asset.path.parent / "video.voiceover.mp4"
    selected_mode = _requested_audio_mode(video, None)
    background_path = _stem_for_audio_mode(video, selected_mode)
    progress("Muxing voiceover into video")
    command = [ffmpeg, "-y", "-i", str(video.path)]
    if background_path:
        command.extend(["-i", str(background_path)])
        background_index = 1
        voice_index = 2
    else:
        background_index = 0
        voice_index = 1
    command.extend(
        [
            "-i",
            str(tts_asset.path),
            "-filter_complex",
            f"[{background_index}:a:0]aresample=44100[background];[{voice_index}:a:0]aresample=44100[voice];[background][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[mixed];[mixed]alimiter=limit=0.98:attack=5:release=50[mix]",
            "-map",
            "0:v:0",
            "-map",
            "[mix]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    )
    if video.duration_ms:
        command.extend(["-t", f"{video.duration_ms / 1000:.10f}"])
    else:
        command.append("-shortest")
    command.append(str(output_path))

    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Final video mux failed: {(proc.stderr or proc.stdout)[-1200:]}")

    asset_id = storage.add_asset(
        video_id=video.id,
        kind="tts_video",
        path=output_path,
        engine=f"{tts_asset.engine}:manual-mux",
        metadata={
            "source_tts_asset_id": tts_asset.id,
            "source_tts_path": str(tts_asset.path),
            "source_video_path": str(video.path),
            "audio_mode": selected_mode,
            "background_audio_path": str(background_path) if background_path else str(video.path),
        },
    )
    progress(f"Dubbed video exported: {output_path}")
    return {"assetId": asset_id, "outputPath": str(output_path)}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/youtube/channels")
def api_get_youtube_channels():
    return storage.get_youtube_channels()


@app.post("/api/youtube/channels")
def api_create_youtube_channel(name: str = Form(...), avatar: UploadFile | None = File(None)):
    avatar_path = None
    if avatar and avatar.filename:
        # Create avatars directory
        avatars_dir = STITCH_ROOT / "workspace" / "avatars"
        avatars_dir.mkdir(parents=True, exist_ok=True)
        # Create a unique filename
        filename = f"{int(time.time())}_{avatar.filename}"
        file_path = avatars_dir / filename
        with open(file_path, "wb") as f:
            shutil.copyfileobj(avatar.file, f)
        avatar_path = f"workspace/avatars/{filename}"
    return storage.create_youtube_channel(name, avatar_path)


@app.put("/api/youtube/channels/{channel_id}")
def api_update_youtube_channel(channel_id: int, payload: YoutubeChannelUpdateRequest):
    updated = storage.update_youtube_channel(channel_id, payload.name, payload.references_json)
    if not updated:
        raise HTTPException(404, "Channel not found")
    return updated


@app.delete("/api/youtube/channels/{channel_id}")
def api_delete_youtube_channel(channel_id: int):
    deleted = storage.delete_youtube_channel(channel_id)
    return {"deleted": deleted}


@app.get("/api/youtube/channels/{channel_id}/prompts")
def api_get_youtube_prompts(channel_id: int):
    return storage.get_youtube_prompts(channel_id)


@app.post("/api/youtube/channels/{channel_id}/prompts")
def api_create_youtube_prompt(channel_id: int, payload: YoutubePromptRequest):
    return storage.create_youtube_prompt(channel_id, payload.name, payload.content)


@app.put("/api/youtube/prompts/{prompt_id}")
def api_update_youtube_prompt(prompt_id: int, payload: YoutubePromptRequest):
    updated = storage.update_youtube_prompt(prompt_id, payload.name, payload.content)
    if not updated:
        raise HTTPException(404, "Prompt not found")
    return updated


@app.delete("/api/youtube/prompts/{prompt_id}")
def api_delete_youtube_prompt(prompt_id: int):
    deleted = storage.delete_youtube_prompt(prompt_id)
    return {"deleted": deleted}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    cookie = config.douyin_cookie_path.read_text(encoding="utf-8").strip() if config.douyin_cookie_path.exists() else ""
    return {
        "hasDouyinCookie": bool(cookie),
        "douyinCookieLength": len(cookie),
    }


@app.put("/api/settings")
def save_settings(payload: SettingsRequest) -> dict[str, Any]:
    if payload.douyinCookie is not None:
        cookie = payload.douyinCookie.strip()
        if cookie:
            config.douyin_cookie_path.parent.mkdir(parents=True, exist_ok=True)
            config.douyin_cookie_path.write_text(cookie, encoding="utf-8")
        elif config.douyin_cookie_path.exists():
            config.douyin_cookie_path.unlink()
    return get_settings()


def _clean_project_title(title: str) -> str:
    cleaned = (title or "").strip()
    if not cleaned:
        raise HTTPException(400, "Project name cannot be empty")
    if len(cleaned) > 160:
        raise HTTPException(400, "Project name is too long")
    return cleaned


def _project_or_404(project_id: int):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _classify_project_upload(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
        return "video"
    if suffix == ".srt":
        return "srt"
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
        return "audio"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return "image"
    raise HTTPException(400, f"Unsupported project asset format: {suffix or filename}")


DEFAULT_TIMELINE_TRACKS = [
    {"id": "V1", "kind": "video", "name": "V1 Main Video"},
    {"id": "S1", "kind": "subtitle", "name": "S1 Subtitles"},
    {"id": "A1", "kind": "audio", "name": "A1 Source Audio"},
    {"id": "A2", "kind": "audio", "name": "A2 Voiceover"},
]


def _timeline_number(value: Any, default: float = 0.0, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        number = float(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    if number != number or number in (float("inf"), float("-inf")):
        number = default
    number = max(minimum, number)
    return min(number, maximum) if maximum is not None else number


def _timeline_track_kind_for_item(kind: str) -> str:
    if kind == "audio":
        return "audio"
    if kind == "srt":
        return "subtitle"
    if kind == "text":
        return "text"
    if kind == "effect":
        return "effect"
    return "video"


def _default_timeline_track_for_kind(kind: str) -> str:
    if kind == "audio":
        return "A2"
    if kind == "srt":
        return "S1"
    if kind == "text":
        return "T1"
    if kind == "effect":
        return "FX1"
    return "V1"


def _next_timeline_track_id(existing: set[str], kind: str) -> str:
    prefix = {"video": "V", "subtitle": "S", "audio": "A", "text": "T", "effect": "FX"}.get(kind, "V")
    index = 1
    while f"{prefix}{index}" in existing:
        index += 1
    return f"{prefix}{index}"


def _clean_timeline_track(track: Any, existing: set[str]) -> dict[str, Any] | None:
    if not isinstance(track, dict):
        return None
    kind = str(track.get("kind") or "").strip().lower()
    if kind not in {"video", "subtitle", "audio", "text", "effect"}:
        return None
    raw_id = str(track.get("id") or "").strip() or _next_timeline_track_id(existing, kind)
    track_id = raw_id[:40]
    if track_id in existing:
        track_id = _next_timeline_track_id(existing, kind)
    existing.add(track_id)
    clean: dict[str, Any] = {
        "id": track_id,
        "kind": kind,
        "name": str(track.get("name") or track_id)[:120],
        "muted": bool(track.get("muted")),
        "hidden": bool(track.get("hidden")),
        "locked": bool(track.get("locked")),
    }
    if track.get("height") is not None:
        clean["height"] = _timeline_number(track.get("height"), 42, 24, 180)
    return clean


def _clean_timeline_items(project, items: list[dict[str, Any]], track_kinds: dict[str, str]) -> list[dict[str, Any]]:
    clean_items: list[dict[str, Any]] = []
    allowed_kinds = {"video", "image", "audio", "srt", "text", "effect"}
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in allowed_kinds:
            continue
        start = _timeline_number(item.get("start"), 0.0)
        duration = _timeline_number(item.get("duration"), 0.05, 0.05)
        clean: dict[str, Any] = {
            "id": str(item.get("id") or f"clip-{index + 1}")[:120],
            "kind": kind,
            "name": str(item.get("name") or kind.upper())[:240],
            "start": start,
            "duration": duration,
            "sourceStart": _timeline_number(item.get("sourceStart"), 0.0),
        }
        track = str(item.get("track") or "").strip()[:40]
        expected_track_kind = _timeline_track_kind_for_item(kind)
        clean["track"] = track if track_kinds.get(track) == expected_track_kind else _default_timeline_track_for_kind(kind)
        if item.get("sourceEnd") is not None:
            clean["sourceEnd"] = _timeline_number(item.get("sourceEnd"), 0.0)
        if item.get("sourceDuration") is not None:
            clean["sourceDuration"] = _timeline_number(item.get("sourceDuration"), 0.0)
        if item.get("volumeDb") is not None:
            clean["volumeDb"] = _timeline_number(item.get("volumeDb"), 0.0, -60.0, 20.0)
        if item.get("speed") is not None:
            clean["speed"] = _timeline_number(item.get("speed"), 1.0, 0.1, 80.0)
        if item.get("opacity") is not None:
            clean["opacity"] = _timeline_number(item.get("opacity"), 1.0, 0.0, 1.0)
        for key in ("muted", "hidden", "sourceAudioMuted"):
            if item.get(key) is not None:
                clean[key] = bool(item.get(key))
        for key in ("linkedVideoItemId", "splitParentId"):
            if item.get(key) is not None:
                clean[key] = str(item.get(key) or "")[:120]
        for key in ("params", "effects", "masks", "animations"):
            if isinstance(item.get(key), (dict, list)):
                clean[key] = item[key]
        if item.get("sourceVideoId") is not None:
            video_id = int(item["sourceVideoId"])
            if not storage.get_video(video_id):
                continue
            storage.attach_video_to_project(project.id, video_id)
            clean["sourceVideoId"] = video_id
        if item.get("projectAssetId") is not None:
            asset_id = int(item["projectAssetId"])
            project_asset = storage.get_project_asset(asset_id)
            if not project_asset or project_asset.project_id != project.id:
                continue
            clean["projectAssetId"] = asset_id
        if item.get("sourceAssetId") is not None:
            clean["sourceAssetId"] = int(item["sourceAssetId"])
        clean_items.append(clean)
    return clean_items


def _clean_timeline_state(raw: dict[str, Any] | None, clean_items: list[dict[str, Any]]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    existing: set[str] = set()
    tracks = [_clean_timeline_track(track, existing) for track in (raw.get("tracks") or [])]
    clean_tracks = [track for track in tracks if track]
    for fallback in DEFAULT_TIMELINE_TRACKS:
        if fallback["id"] not in existing:
            clean_tracks.append(dict(fallback))
            existing.add(fallback["id"])
    for item in clean_items:
        track_id = str(item.get("track") or "")
        if track_id and track_id not in existing:
            kind = _timeline_track_kind_for_item(str(item.get("kind") or "video"))
            clean_tracks.append({"id": track_id, "kind": kind, "name": track_id, "muted": False, "hidden": False, "locked": False})
            existing.add(track_id)
    canvas = raw.get("canvas") if isinstance(raw.get("canvas"), dict) else {}
    view = raw.get("view") if isinstance(raw.get("view"), dict) else {}
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    bookmarks: list[dict[str, Any]] = []
    for index, bookmark in enumerate(raw.get("bookmarks") or []):
        if not isinstance(bookmark, dict):
            continue
        clean_bookmark: dict[str, Any] = {
            "id": str(bookmark.get("id") or f"bookmark-{index + 1}")[:120],
            "time": _timeline_number(bookmark.get("time"), 0.0),
        }
        if bookmark.get("duration") is not None:
            clean_bookmark["duration"] = _timeline_number(bookmark.get("duration"), 0.0)
        if bookmark.get("note") is not None:
            clean_bookmark["note"] = str(bookmark.get("note") or "")[:240]
        if bookmark.get("color") is not None:
            clean_bookmark["color"] = str(bookmark.get("color") or "")[:32]
        bookmarks.append(clean_bookmark)
    return {
        "version": 2,
        "fps": int(_timeline_number(raw.get("fps"), 30, 1, 240)),
        "canvas": {
            "width": int(_timeline_number(canvas.get("width"), 1920, 16, 16384)),
            "height": int(_timeline_number(canvas.get("height"), 1080, 16, 16384)),
            "mode": str(canvas.get("mode") or "source")[:32],
        },
        "tracks": clean_tracks,
        "items": clean_items,
        "bookmarks": bookmarks,
        "view": {
            "zoomLevel": _timeline_number(view.get("zoomLevel"), 1, 0.1, 100),
            "scrollLeft": _timeline_number(view.get("scrollLeft"), 0),
            "scrollTop": _timeline_number(view.get("scrollTop"), 0),
            "playheadTime": _timeline_number(view.get("playheadTime"), 0),
        },
        "options": {
            "snapping": options.get("snapping") is not False,
            "ripple": bool(options.get("ripple")),
        },
    }


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    return [_workspace_project_payload(project) for project in storage.list_projects()]


@app.post("/api/projects")
def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
    title = _clean_project_title(payload.title)
    video_ids = [int(item) for item in payload.videoIds if storage.get_video(int(item))]
    project = storage.create_project(title, video_ids)
    return {"project": _workspace_project_payload(project)}


@app.patch("/api/projects/{project_id}")
def rename_workspace_project(project_id: int, payload: VideoRenameRequest) -> dict[str, Any]:
    _project_or_404(project_id)
    title = _clean_project_title(payload.title)
    storage.rename_workspace_project(project_id, title)
    return {"project": _workspace_project_payload(storage.get_project(project_id))}


@app.delete("/api/projects/{project_id}")
def delete_workspace_project(project_id: int) -> dict[str, Any]:
    project = _project_or_404(project_id)
    return _delete_project_and_owned_files(project)


@app.get("/api/projects/{project_id}/cleanup")
def project_cleanup(project_id: int) -> dict[str, Any]:
    project = _project_or_404(project_id)
    return {
        "project": _workspace_project_payload(project),
        "items": _project_cleanup_items(project),
    }


@app.post("/api/projects/{project_id}/cleanup/delete")
def delete_project_cleanup_items(project_id: int, payload: ProjectCleanupDeleteRequest) -> dict[str, Any]:
    project = _project_or_404(project_id)
    requested_ids = [item_id for item_id in payload.itemIds if item_id]
    if not requested_ids:
        raise HTTPException(400, "No cleanup items selected")
    available = {item["id"] for item in _project_cleanup_items(project)}
    invalid = [item_id for item_id in requested_ids if item_id not in available]
    if invalid:
        raise HTTPException(404, f"Cleanup item not found in this project: {invalid[0]}")

    results = [_delete_cleanup_item(project.id, item_id) for item_id in requested_ids]
    updated = storage.get_project(project.id) or project
    return {
        "results": results,
        "deletedFiles": sum(int(item.get("deletedFiles") or 0) for item in results),
        "project": _workspace_project_payload(updated),
        "items": _project_cleanup_items(updated),
    }


@app.post("/api/projects/reveal-library")
def reveal_project_library() -> dict[str, str]:
    target = config.downloads_dir.parent
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except OSError as exc:
            raise HTTPException(500, f"Could not open folder: {target}") from exc
        return {"status": "opened", "path": str(target)}
    raise HTTPException(400, "Reveal in folder is only supported on Windows in this build")


@app.post("/api/projects/{project_id}/videos")
def attach_project_videos(project_id: int, payload: ProjectAttachVideosRequest) -> dict[str, Any]:
    project = _project_or_404(project_id)
    for video_id in payload.videoIds:
        storage.attach_video_to_project(project.id, int(video_id))
    return {"project": _workspace_project_payload(storage.get_project(project.id))}


@app.post("/api/projects/{project_id}/assets/attach")
def attach_project_assets(project_id: int, payload: ProjectAttachAssetsRequest) -> dict[str, Any]:
    project = _project_or_404(project_id)
    for asset_id in payload.assetIds:
        asset = storage.get_asset(int(asset_id))
        if not asset or not asset.path.exists():
            continue
        if asset.kind == "srt":
            kind = "srt"
        elif asset.kind in {"tts", "audio"} or "audio" in asset.kind:
            kind = "audio"
        elif asset.kind in {"image"}:
            kind = "image"
        elif "video" in asset.kind:
            kind = "video"
        else:
            kind = asset.kind
        existing = storage.project_asset_for_asset(project.id, asset.id)
        if existing:
            continue
        asset_metadata = _metadata_with_media_duration(asset.metadata or {}, asset.path)
        if asset_metadata != (asset.metadata or {}):
            storage.update_asset_metadata(asset.id, asset_metadata)
        storage.add_project_asset(
            project_id=project.id,
            kind=kind,
            path=asset.path,
            name=asset.path.name,
            source_asset_id=asset.id,
            metadata={
                **asset_metadata,
                "source": "library-asset",
                "source_kind": asset.kind,
                "engine": asset.engine,
                "size_bytes": asset.path.stat().st_size if asset.path.exists() else None,
            },
        )
    return {"project": _workspace_project_payload(storage.get_project(project.id))}


@app.put("/api/projects/{project_id}/timeline")
def update_project_timeline(project_id: int, payload: ProjectTimelineRequest) -> dict[str, Any]:
    project = _project_or_404(project_id)
    raw_state = payload.timelineState if isinstance(payload.timelineState, dict) else None
    track_kinds = {track["id"]: track["kind"] for track in DEFAULT_TIMELINE_TRACKS}
    for track in (raw_state or {}).get("tracks") or []:
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("id") or "").strip()[:40]
        kind = str(track.get("kind") or "").strip().lower()
        if track_id and kind in {"video", "subtitle", "audio", "text", "effect"}:
            track_kinds[track_id] = kind
    clean_items = _clean_timeline_items(project, payload.items or [], track_kinds)
    clean_state = _clean_timeline_state(raw_state, clean_items)
    metadata = dict(project.metadata or {})
    metadata["timeline"] = clean_items
    metadata["timeline_state"] = clean_state
    updated = storage.update_project_metadata(project.id, metadata)
    return {"project": _workspace_project_payload(updated or storage.get_project(project.id))}


def _path_has_audio_stream(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False


def _timeline_float(item: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(item.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(0.0, value)


def _timeline_params_float(item: dict[str, Any], key: str, default: float = 0.0) -> float:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    try:
        value = float(params.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(0.0, value)


def _timeline_volume_gain(item: dict[str, Any]) -> float:
    try:
        db = float(item.get("volumeDb", 0.0) or 0.0)
    except (TypeError, ValueError):
        db = 0.0
    db = max(-60.0, min(20.0, db))
    return 0.0 if db <= -60.0 else math.pow(10.0, db / 20.0)


def _timeline_audio_sources(project) -> list[dict[str, Any]]:
    metadata = project.metadata or {}
    timeline_state = metadata.get("timeline_state") if isinstance(metadata.get("timeline_state"), dict) else {}
    timeline = timeline_state.get("items") or metadata.get("timeline") or []
    muted_tracks = {
        str(track.get("id") or "")
        for track in timeline_state.get("tracks") or []
        if isinstance(track, dict) and (track.get("muted") or track.get("hidden"))
    }
    sources: list[dict[str, Any]] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        if item.get("muted") or item.get("hidden") or str(item.get("track") or "") in muted_tracks:
            continue
        kind = str(item.get("kind") or "").lower()
        start = _timeline_float(item, "start")
        duration = max(0.05, _timeline_float(item, "duration", 0.0))
        source_start = _timeline_float(item, "sourceStart")
        fade_in = _timeline_params_float(item, "audioFadeIn")
        fade_out = _timeline_params_float(item, "audioFadeOut")
        fade_in = min(fade_in, duration)
        fade_out = min(fade_out, max(0.0, duration - fade_in))
        path: Path | None = None
        label = str(item.get("name") or kind or "clip")
        if kind == "audio":
            project_asset_id = item.get("projectAssetId")
            source_asset_id = item.get("sourceAssetId")
            source_video_id = item.get("sourceVideoId")
            if project_asset_id is not None:
                project_asset = storage.get_project_asset(int(project_asset_id))
                if project_asset and project_asset.project_id == project.id:
                    path = project_asset.path
                    label = project_asset.name or label
            if path is None and source_asset_id is not None:
                asset = storage.get_asset(int(source_asset_id))
                if asset:
                    path = asset.path
                    label = asset.path.name
            if path is None and source_video_id is not None:
                video = storage.get_video(int(source_video_id))
                if video:
                    path = video.path
                    label = video.path.name
        elif kind == "video" and not item.get("sourceAudioMuted") and item.get("sourceVideoId") is not None:
            video = storage.get_video(int(item["sourceVideoId"]))
            if video:
                mode = str((video.metadata or {}).get("audio_mode") or AUDIO_MODE_ORIGINAL)
                stem = _stem_for_audio_mode(video, mode)
                path = stem or video.path
                label = video.path.name
        if path and _path_has_audio_stream(path):
            sources.append({
                "path": path,
                "start": start,
                "duration": duration,
                "source_start": source_start,
                "volume": _timeline_volume_gain(item),
                "fade_in": fade_in,
                "fade_out": fade_out,
                "label": label,
            })
    return sources


def _render_workspace_timeline_audio(project, progress: Callable[[str], None] | None = None) -> tuple[Path, int]:
    sources = _timeline_audio_sources(project)
    if not sources:
        raise RuntimeError("Timeline does not contain any readable audio.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to prepare timeline audio for subtitles.")
    output_dir = config.outputs_dir / f"project_{project.id}" / "timeline_audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "timeline_subtitle_source.wav"
    command = [ffmpeg, "-y"]
    filters: list[str] = []
    labels: list[str] = []
    for index, source in enumerate(sources):
        command.extend(["-i", str(source["path"])])
        delay_ms = int(round(float(source["start"]) * 1000))
        duration = max(0.05, float(source["duration"]))
        source_start = max(0.0, float(source["source_start"]))
        volume = max(0.0, float(source.get("volume", 1.0)))
        fade_in = max(0.0, min(float(source.get("fade_in", 0.0)), duration))
        fade_out = max(0.0, min(float(source.get("fade_out", 0.0)), max(0.0, duration - fade_in)))
        label = f"a{index}"
        chain = [
            f"[{index}:a:0]atrim=start={source_start:.6f}:duration={duration:.6f}",
            "asetpts=PTS-STARTPTS",
            f"volume={volume:.8f}",
        ]
        if fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out > 0:
            chain.append(f"afade=t=out:st={max(0.0, duration - fade_out):.6f}:d={fade_out:.6f}")
        chain.extend(["aresample=48000", f"adelay={delay_ms}:all=1"])
        filters.append(
            ",".join(chain) + f"[{label}]"
        )
        labels.append(f"[{label}]")
    if len(labels) == 1:
        filters.append(f"{labels[0]}alimiter=limit=0.98[out]")
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.98[out]"
        )
    command.extend([
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ])
    if progress:
        progress(f"Preparing timeline audio from {len(sources)} clip(s)...")
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not prepare timeline audio: {(proc.stderr or proc.stdout)[-1000:]}")
    duration_ms = _probe_video_duration_ms(output_path) or int(max(source["start"] + source["duration"] for source in sources) * 1000)
    return output_path, max(1, duration_ms)


def _generate_workspace_timeline_srt(project, payload: SrtGenerateRequest, progress: Callable[[str], None]) -> dict[str, Any]:
    if payload.source != "audio":
        raise RuntimeError("Workspace subtitle generation currently uses timeline audio. OCR needs a rendered video first.")
    audio_path, duration_ms = _render_workspace_timeline_audio(project, progress)
    video_id = storage.upsert_video(
        title=f"{project.title} timeline audio",
        source_url=f"workspace:{project.id}:timeline-audio",
        source="workspace:timeline-audio",
        path=audio_path,
        media_type="audio",
        duration_ms=duration_ms,
        size_bytes=audio_path.stat().st_size,
        metadata={"hidden": True, "workspace_id": project.id, "timeline_audio": True},
    )
    audio_video = storage.get_video(video_id)
    if not audio_video:
        raise RuntimeError("Could not register timeline audio for transcription.")
    srt_path = transcriber.generate_srt(
        audio_video,
        model_name=payload.model,
        device=payload.device,
        language=payload.language,
        timeline_speed=1.0,
        progress=progress,
    )
    srt_asset = next((asset for asset in storage.list_assets(audio_video.id) if asset.path == srt_path), None) or storage.latest_asset(audio_video.id, "srt")
    if not srt_asset:
        raise RuntimeError("Timeline SRT was generated but not registered.")
    project_asset = storage.project_asset_for_asset(project.id, srt_asset.id)
    if not project_asset:
        storage.add_project_asset(
            project_id=project.id,
            kind="srt",
            path=srt_asset.path,
            name=srt_asset.path.name,
            source_asset_id=srt_asset.id,
            metadata={
                **(srt_asset.metadata or {}),
                "source": "timeline-audio",
                "workspace_id": project.id,
                "engine": srt_asset.engine,
            },
        )
        project_asset = storage.project_asset_for_asset(project.id, srt_asset.id)
    return {"assetId": srt_asset.id, "sourceAssetId": srt_asset.id, "projectAssetId": project_asset.id if project_asset else None}


@app.post("/api/projects/{project_id}/srt/generate")
def generate_workspace_srt(project_id: int, payload: SrtGenerateRequest) -> dict[str, Any]:
    project = _project_or_404(project_id)
    active = _active_job("srt", -project.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("srt", f"Generate Timeline SRT: {project.title}", -project.id)
    _run_job(job_id, lambda progress: _generate_workspace_timeline_srt(project, payload, progress))
    return {"jobId": job_id}


@app.post("/api/projects/{project_id}/assets")
def upload_project_asset(project_id: int, file: UploadFile = File(...)) -> dict[str, Any]:
    project = _project_or_404(project_id)
    filename = Path(file.filename or "asset").name
    kind = _classify_project_upload(filename)
    asset_dir = config.outputs_dir / f"project_{project.id}" / "assets" / kind
    asset_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    destination = asset_dir / filename
    counter = 1
    while destination.exists():
        destination = asset_dir / f"{Path(filename).stem}_{counter}{suffix}"
        counter += 1
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(file.file, output, length=1024 * 1024)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not save uploaded project asset: {exc}") from exc
    if destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded project asset is empty")

    metadata = _metadata_with_media_duration(
        {"original_filename": filename, "size_bytes": destination.stat().st_size},
        destination,
    )
    if kind == "video":
        video_id = storage.upsert_video(
            title=destination.stem,
            source_url="",
            source="project:upload",
            path=destination,
            media_type="video",
            duration_ms=_probe_video_duration_ms(destination),
            size_bytes=destination.stat().st_size,
            metadata={"project_upload": True, "hidden": True, "original_filename": filename},
        )
        storage.attach_video_to_project(project.id, video_id)
    else:
        source_asset_id = None
        if project.primary_video_id:
            source_asset_id = storage.add_asset(
                video_id=project.primary_video_id,
                kind=kind,
                path=destination,
                engine="project-upload",
                metadata=metadata,
            )
        storage.add_project_asset(
            project_id=project.id,
            kind=kind,
            path=destination,
            name=filename,
            source_asset_id=source_asset_id,
            metadata=metadata,
        )
    updated = storage.get_project(project.id)
    return {"project": _workspace_project_payload(updated)}


@app.get("/api/videos")
def list_videos() -> list[dict[str, Any]]:
    return [_video_payload(video) for video in storage.list_videos() if not (video.metadata or {}).get("hidden")]


@app.post("/api/import/video")
def import_video(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "imported-video.mp4").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
        raise HTTPException(400, "Unsupported video format")
    import_dir = config.downloads_dir / "imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    destination = import_dir / filename
    counter = 1
    while destination.exists():
        destination = import_dir / f"{Path(filename).stem}_{counter}{suffix}"
        counter += 1
    try:
        with destination.open("wb") as output:
            shutil.copyfileobj(file.file, output, length=1024 * 1024)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not save imported video: {exc}") from exc
    if destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "Imported video is empty")
    video_id = storage.upsert_video(
        title=destination.stem,
        source_url="",
        source="local:import",
        path=destination,
        media_type="video",
        duration_ms=_probe_video_duration_ms(destination),
        size_bytes=destination.stat().st_size,
        metadata={"imported": True, "original_filename": filename},
    )
    return {"video": _video_payload(storage.get_video(video_id))}


@app.patch("/api/videos/{video_id}")
def rename_video(video_id: int, payload: VideoRenameRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "Project name cannot be empty")
    if len(title) > 160:
        raise HTTPException(400, "Project name is too long")
    updated_ids = storage.rename_project(video.id, title)
    renamed = storage.get_video(video.id)
    return {"updatedVideoIds": updated_ids, "video": _video_payload(renamed)}


@app.put("/api/videos/{video_id}/clip-settings")
def update_clip_settings(video_id: int, payload: ClipSettingsRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    requested = payload.model_dump(exclude_none=True)
    limits = {
        "videoScale": (0.1, 5.0),
        "videoVolumeDb": (-60.0, 20.0),
        "videoSpeed": (0.1, 80.0),
        "voiceVolumeDb": (-60.0, 20.0),
        "voiceSpeed": (0.1, 80.0),
    }
    settings = dict((video.metadata or {}).get("clip_settings") or {})
    for key, value in requested.items():
        minimum, maximum = limits[key]
        if not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            raise HTTPException(400, f"Invalid {key}")
        settings[key] = max(minimum, min(maximum, float(value)))
    metadata = dict(video.metadata or {})
    metadata["clip_settings"] = settings
    storage.update_video_metadata(video.id, metadata)
    updated = storage.get_video(video.id)
    return {"clipSettings": (updated.metadata or {}).get("clip_settings") or {}}


@app.put("/api/videos/{video_id}/subtitle-settings")
def update_subtitle_settings(video_id: int, payload: SubtitleEditorSettingsRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    area = _normalize_area_ratio(payload.area)
    if not area:
        raise HTTPException(400, "Invalid subtitle area")
    metadata = dict(video.metadata or {})
    metadata["area_ratio"] = area
    if payload.style is not None:
        metadata["subtitle_style"] = payload.style
    if payload.blurEffectArea is not None:
        blur_area = _normalize_area_ratio(payload.blurEffectArea)
        if not blur_area:
            raise HTTPException(400, "Invalid blur effect area")
        effect = dict(metadata.get("subtitle_blur_effect") or {})
        effect.update(
            {
                "enabled": True,
                "kind": "subtitle_blur",
                "mode": "manual",
                "area": blur_area,
                "source": "manual-editor",
                "updated_at": time.time(),
            }
        )
        metadata["subtitle_blur_effect"] = effect
    storage.update_video_metadata(video.id, metadata)
    updated = storage.get_video(video.id)
    updated_metadata = updated.metadata or {}
    return {
        "subtitleArea": _subtitle_area_payload(updated, updated_metadata),
        "subtitleBlurEffect": updated_metadata.get("subtitle_blur_effect") or None,
        "subtitleStyle": updated_metadata.get("subtitle_style") or None,
    }


@app.post("/api/videos/{video_id}/reveal")
def reveal_video_file(video_id: int) -> dict[str, str]:
    video = _video_or_404(video_id)
    path = video.path
    target = path if path.exists() else path.parent
    if not target.exists():
        raise HTTPException(404, "Downloaded file location not found")
    if sys.platform.startswith("win"):
        if path.exists() and path.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{str(path)}"])
        else:
            subprocess.Popen(["explorer.exe", str(target)])
        return {"status": "opened", "path": str(path)}
    raise HTTPException(400, "Reveal in folder is only supported on Windows in this build")


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    with jobs_lock:
        return sorted(jobs.values(), key=lambda item: item["createdAt"], reverse=True)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.get("status") in {"completed", "error", "cancelled"}:
            return {"jobId": job_id, "status": job.get("status"), "alreadyFinished": True}
        job["cancelRequested"] = True
        job["status"] = "cancelled"
        job["detail"] = "Cancelling..."
    return {"jobId": job_id, "status": "cancelled"}


@app.delete("/api/jobs/failed")
def clear_failed_jobs() -> dict[str, int]:
    with jobs_lock:
        failed_ids = [
            job_id
            for job_id, job in jobs.items()
            if job.get("kind") == "download" and job.get("status") == "error"
        ]
        for job_id in failed_ids:
            jobs.pop(job_id, None)
    removed_files = 0
    for path in config.downloads_dir.rglob("*"):
        if path.is_file() and (path.suffix.lower() in {".part", ".ytdl", ".tmp"} or ".part." in path.name.lower()):
            try:
                path.unlink()
                removed_files += 1
            except OSError:
                pass
    return {"removedJobs": len(failed_ids), "removedFiles": removed_files}


@app.post("/api/download")
def download_video(payload: DownloadRequest) -> dict[str, Any]:
    value = payload.url.strip()
    if not value:
        raise HTTPException(400, "Missing URL")
    try:
        url = extract_video_url(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    job_id = _new_job("download", url)
    _run_job(job_id, lambda progress: downloader.download_url(url, progress))
    return {"jobId": job_id}


@app.post("/api/download/preview")
def preview_download(payload: DownloadRequest) -> dict[str, str]:
    value = payload.url.strip()
    if not value:
        raise HTTPException(400, "Missing URL")
    try:
        url = extract_video_url(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"url": url}


@app.post("/api/videos/{video_id}/tts/remap-timeline")
def remap_adaptive_timeline(video_id: int, payload: TimelineRemapRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    srt_asset = storage.get_asset(payload.srtAssetId) if payload.srtAssetId else _primary_srt_asset(video)
    tts_asset = storage.latest_asset(video.id, "tts")
    if not srt_asset or srt_asset.video_id != video.id or srt_asset.kind != "srt" or not srt_asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not tts_asset or not tts_asset.path.exists():
        raise HTTPException(404, "Existing TTS output not found")
    manifest_path = Path(str((tts_asset.metadata or {}).get("manifest") or ""))
    if not manifest_path.exists():
        raise HTTPException(409, "Existing TTS segments cannot be reused because its manifest is missing")
    active = _active_job("tts", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("tts", f"Re-run Adaptive Timeline: {video.title}", video.id)
    timeline_options = _timeline_options(payload)

    def run_remap(progress: Callable[[str], None]):
        import soundfile as sf

        rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        original_segments = {segment.index: segment for segment in read_srt(srt_asset.path)}
        rendered = []
        for row in rows:
            index = int(row["index"])
            segment = original_segments.get(index)
            path_value = row.get("path") or row.get("wav")
            path = Path(str(path_value or ""))
            if not segment or not path.exists() or str(row.get("text") or "").strip() != segment.text.strip():
                raise RuntimeError("SRT text or cached TTS segments changed; regenerate TTS before remapping")
            rendered.append((segment, path))
        if not rendered:
            raise RuntimeError("Existing TTS manifest contains no reusable segments")
        sample_rate = int(sf.info(str(rendered[0][1])).samplerate)
        result = process_and_register_adaptive_timeline(
            storage,
            video,
            rendered,
            tts_asset.path.parent,
            engine=tts_asset.engine.split(":", 1)[0] or "tts",
            source_srt=srt_asset.path,
            sample_rate=sample_rate,
            timeline_options=timeline_options,
            progress=progress,
        )
        storage.add_asset(
            video_id=video.id,
            kind="tts",
            path=Path(result["voiceover_path"]),
            engine=f"{tts_asset.engine}:adaptive-remap",
            metadata={**(tts_asset.metadata or {}), "timing_mode": "adaptive", "timing": result["state"]},
        )
        return Path(result["voiceover_path"])

    _run_job(job_id, run_remap)
    return {"jobId": job_id, "reusedTts": True}


@app.post("/api/videos/{video_id}/tts/mux-video")
def mux_tts_video(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    active = _active_job("tts", video.id) or _active_job("tts-segment", video.id) or _active_job("tts-mux", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("tts-mux", f"Insert Voiceover Into Video: {video.title}", video.id)
    _run_job(job_id, lambda progress: _mux_latest_tts_video(video, progress))
    return {"jobId": job_id}


@app.post("/api/videos/{video_id}/audio-mode")
def set_audio_mode(video_id: int, payload: AudioModeRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    mode = payload.mode.strip().lower()
    if mode not in AUDIO_MODES:
        raise HTTPException(400, f"Unsupported audio mode: {payload.mode}")

    metadata = dict(video.metadata or {})
    metadata["audio_mode"] = mode
    storage.update_video_metadata(video.id, metadata)
    if mode == AUDIO_MODE_ORIGINAL:
        return {"mode": mode, "ready": True, "jobId": None}

    refreshed = _video_or_404(video.id)
    stems = audio_separator.cached_stems(refreshed)
    if {"vocals", "instrumental"}.issubset(stems):
        return {"mode": mode, "ready": True, "jobId": None, "reused": True}

    active = _active_job("audio-separate", video.id)
    if active:
        return {"mode": mode, "ready": False, "jobId": active["id"], "alreadyRunning": True}

    job_id = _new_job("audio-separate", f"Separate Audio: {video.title}", video.id)
    _run_job(job_id, lambda progress: audio_separator.separate(video, progress))
    return {"mode": mode, "ready": False, "jobId": job_id}


@app.post("/api/videos/{video_id}/audio/extract")
def extract_source_audio(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "FFmpeg is required to extract audio")

    output_dir = config.outputs_dir / f"video_{video.id}" / "audio_extract"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{video.path.stem}.source-audio.wav"
    newest_input = video.path.stat().st_mtime
    if not output_path.exists() or output_path.stat().st_mtime < newest_input or output_path.stat().st_size == 0:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-map",
                "0:a:0",
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise HTTPException(404, f"No readable audio stream is available for this video: {(proc.stderr or proc.stdout)[-500:]}")

    for existing in reversed(storage.list_assets(video.id)):
        if existing.kind == "audio" and existing.engine == "audio-extract" and existing.path == output_path and existing.path.exists():
            return {"asset": _asset_payload(existing), "reused": True}

    asset_id = storage.add_asset(
        video_id=video.id,
        kind="audio",
        path=output_path,
        engine="audio-extract",
        metadata={
            "source": "timeline-extract",
            "source_video_id": video.id,
            "duration_ms": video.duration_ms,
            "size_bytes": output_path.stat().st_size,
        },
    )
    return {"asset": _asset_payload(storage.get_asset(asset_id)), "reused": False}


def _requested_audio_mode(video, value: str | None) -> str:
    mode = str(value or (video.metadata or {}).get("audio_mode") or AUDIO_MODE_ORIGINAL).strip().lower()
    return mode if mode in AUDIO_MODES else AUDIO_MODE_ORIGINAL


def _stem_for_audio_mode(video, mode: str, *, required: bool = False) -> Path | None:
    if mode == AUDIO_MODE_ORIGINAL:
        return None
    stem = audio_separator.stem_for_mode(video, mode)
    if not stem and required:
        raise HTTPException(409, "Separated audio is still being prepared")
    return stem


def _mux_video_with_stem(source_video: Path, stem: Path, output_path: Path, *, transcode_video: bool = False) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "FFmpeg is required to preview separated audio")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    newest_input = max(source_video.stat().st_mtime, stem.stat().st_mtime)
    if output_path.exists() and output_path.stat().st_mtime >= newest_input and output_path.stat().st_size > 0:
        return output_path

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-i",
        str(stem),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264" if transcode_video else "copy",
    ]
    if transcode_video:
        command += ["-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    command += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-map_metadata",
        "0",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not attach separated audio: {(proc.stderr or proc.stdout)[-1000:]}")
    return output_path


def _browser_preview_path(video) -> Path:
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    preview_dir = config.outputs_dir / f"video_{video.id}" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / f"{video.path.stem}.browser.mp4"
    if preview_path.exists() and preview_path.stat().st_mtime >= video.path.stat().st_mtime and preview_path.stat().st_size > 0:
        return preview_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return video.path
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video.path),
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(preview_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not preview_path.exists():
        raise HTTPException(500, f"Could not create browser preview: {proc.stderr[-800:]}")
    return preview_path


def _render_subtitle_blur_effect(video, source_path: Path) -> Path:
    effect = (video.metadata or {}).get("subtitle_blur_effect") or {}
    if not effect.get("enabled"):
        return source_path
    area = effect.get("area") or {}
    try:
        width, height = _probe_video_size(source_path)
        xmin = max(0, min(width - 2, int(round(width * float(area["xmin"])))))
        xmax = max(xmin + 2, min(width, int(round(width * float(area["xmax"])))))
        ymin = max(0, min(height - 2, int(round(height * float(area["ymin"])))))
        ymax = max(ymin + 2, min(height, int(round(height * float(area["ymax"])))))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(500, "Saved subtitle blur area is invalid")
    box_width = max(2, xmax - xmin)
    box_height = max(2, ymax - ymin)
    smallest = max(2, min(box_width, box_height))
    radius = max(16, min(90, max(1, (smallest - 1) // 2)))
    chroma_radius = max(8, min(45, max(1, (smallest - 1) // 4), max(1, radius // 2)))
    blur = (
        "boxblur="
        f"luma_radius={radius}:luma_power=10:"
        f"chroma_radius={chroma_radius}:chroma_power=6,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.05:t=fill"
    )
    filter_complex = (
        f"[0:v]split[base][region];"
        f"[region]crop={box_width}:{box_height}:{xmin}:{ymin},{blur}[blurred];"
        f"[base][blurred]overlay={xmin}:{ymin}[v]"
    )
    effect_key = "frosted-v4-" + "-".join(
        f"{float(area[key]):.4f}".replace(".", "_")
        for key in ("xmin", "xmax", "ymin", "ymax")
    )
    output_dir = config.outputs_dir / f"video_{video.id}" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_path.stem}.subtitle-blur.{effect_key}.mp4"
    if output_path.exists() and output_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns:
        return output_path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "FFmpeg is required to export the subtitle blur effect")

    def run(audio_codec: str) -> subprocess.CompletedProcess[str]:
        audio_args = ["-c:a", "copy"] if audio_codec == "copy" else ["-c:a", "aac", "-b:a", "192k"]
        return subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source_path),
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
                *audio_args,
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    proc = run("copy")
    if proc.returncode != 0:
        proc = run("aac")
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise HTTPException(500, f"Could not export subtitle blur effect: {proc.stderr[-1000:]}")
    return output_path


@app.get("/api/videos/{video_id}/media")
def media(video_id: int, audioMode: str | None = None, renderEffects: bool = False) -> FileResponse:
    video = _video_or_404(video_id)
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    mode = _requested_audio_mode(video, audioMode)
    stem = _stem_for_audio_mode(video, mode, required=mode != AUDIO_MODE_ORIGINAL)
    media_path = video.path
    if stem:
        output_dir = config.outputs_dir / f"video_{video.id}" / "audio_separation"
        suffix = "no-vocals" if mode == AUDIO_MODE_REMOVE_VOCALS else "no-background-music"
        output_path = output_dir / f"{video.path.stem}.{suffix}.mp4"
        try:
            media_path = _mux_video_with_stem(video.path, stem, output_path)
        except HTTPException:
            media_path = _mux_video_with_stem(video.path, stem, output_path, transcode_video=True)
    if renderEffects:
        media_path = _render_subtitle_blur_effect(video, media_path)
    media_type = "video/mp4" if media_path.suffix.lower() == ".mp4" else mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    return FileResponse(media_path, media_type=media_type, filename=media_path.name)


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    return _delete_video_and_owned_files(video)


@app.get("/api/videos/{video_id}/preview")
def preview_media(video_id: int, audioMode: str | None = None) -> FileResponse:
    video = _video_or_404(video_id)
    preview_path = _browser_preview_path(video)
    mode = _requested_audio_mode(video, audioMode)
    stem = _stem_for_audio_mode(video, mode)
    if stem:
        suffix = "no-vocals" if mode == AUDIO_MODE_REMOVE_VOCALS else "no-background-music"
        output_path = preview_path.parent / f"{video.path.stem}.browser.{suffix}.mp4"
        preview_path = _mux_video_with_stem(preview_path, stem, output_path)
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@app.get("/api/videos/{video_id}/thumbnail")
def video_thumbnail(video_id: int) -> FileResponse:
    video = _video_or_404(video_id)
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    preview_dir = config.outputs_dir / f"video_{video.id}" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = preview_dir / f"{video.path.stem}.thumbnail.jpg"
    if not thumbnail_path.exists() or thumbnail_path.stat().st_mtime < video.path.stat().st_mtime:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(500, "FFmpeg is required to create thumbnails")
        proc = subprocess.run(
            [ffmpeg, "-y", "-ss", "0.5", "-i", str(video.path), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(thumbnail_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not thumbnail_path.exists():
            raise HTTPException(500, f"Could not create thumbnail: {proc.stderr[-500:]}")
    return FileResponse(thumbnail_path, media_type="image/jpeg")


@app.post("/api/videos/{video_id}/frame")
def capture_video_frame(video_id: int, timeSeconds: float = 0.0) -> dict[str, Any]:
    video = _video_or_404(video_id)
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "FFmpeg is required to capture video frames")
    output_dir = config.outputs_dir / f"video_{video.id}" / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_time = max(0.0, float(timeSeconds or 0))
    stamp = f"{int(safe_time * 1000):09d}"
    frame_path = output_dir / f"{video.path.stem}.frame-{stamp}.jpg"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{safe_time:.3f}",
            "-i",
            str(video.path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not frame_path.exists() or frame_path.stat().st_size == 0:
        raise HTTPException(500, f"Could not capture frame: {proc.stderr[-500:]}")
    asset_id = storage.add_asset(
        video_id=video.id,
        kind="image",
        path=frame_path,
        engine="frame-capture",
        metadata={"time_seconds": safe_time, "source_video_id": video.id},
    )
    asset = storage.get_asset(asset_id)
    return {"asset": _asset_payload(asset), "downloadUrl": f"/assets/{asset_id}/download"}


@app.get("/api/videos/{video_id}/waveform")
def video_waveform(video_id: int, audioMode: str | None = None) -> FileResponse:
    video = _video_or_404(video_id)
    if not video.path.exists():
        raise HTTPException(404, "Media file not found")
    mode = _requested_audio_mode(video, audioMode)
    source_audio = _stem_for_audio_mode(video, mode) or video.path
    preview_dir = config.outputs_dir / f"video_{video.id}" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    waveform_path = preview_dir / f"{video.path.stem}.waveform.{mode}.png"
    if not waveform_path.exists() or waveform_path.stat().st_mtime < source_audio.stat().st_mtime:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(500, "FFmpeg is required to create waveforms")
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(source_audio), "-filter_complex", "aformat=channel_layouts=mono,showwavespic=s=1600x80:colors=0x4f8cff", "-frames:v", "1", str(waveform_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0 or not waveform_path.exists():
            raise HTTPException(404, "No readable audio stream is available for this video")
    return FileResponse(waveform_path, media_type="image/png")


@app.post("/api/videos/{video_id}/srt/generate")
def generate_srt(video_id: int, payload: SrtGenerateRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    if payload.source not in {"audio", "hardsub"}:
        raise HTTPException(400, f"Unsupported SRT source: {payload.source}")
    active = _active_job("srt", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    timeline_speed = _srt_timeline_speed(video, payload)
    job_id = _new_job("srt", f"Generate SRT: {video.title}", video.id)
    if payload.source == "hardsub":
        ocr_area = _normalize_area_ratio(payload.ocrArea) if payload.ocrArea is not None else None
        if payload.ocrArea is not None and not ocr_area:
            raise HTTPException(400, "OCR area must contain valid xmin, xmax, ymin and ymax ratios")
        _run_job(
            job_id,
            lambda progress: transcriber.generate_hardsub_srt(
                video,
                language="vi" if payload.language == "auto" else payload.language,
                mode=payload.hardsubMode,
                area=ocr_area,
                timeline_speed=timeline_speed,
                progress=progress,
            ),
        )
        return {"jobId": job_id}
    _run_job(
        job_id,
        lambda progress: transcriber.generate_srt(
            video,
            model_name=payload.model,
            device=payload.device,
            language=payload.language,
            timeline_speed=timeline_speed,
            progress=progress,
        ),
    )
    return {"jobId": job_id}


@app.get("/api/videos/{video_id}/srt/latest")
def latest_srt(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        return {"asset": None, "content": "", "segments": []}
    segments = read_srt(asset.path)
    return {
        "asset": _asset_payload(asset),
        "content": asset.path.read_text(encoding="utf-8-sig"),
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "startLabel": seconds_to_srt_time(segment.start),
                "endLabel": seconds_to_srt_time(segment.end),
                "text": segment.text,
            }
            for segment in segments
        ],
    }


@app.post("/api/videos/{video_id}/srt/import")
def import_srt(video_id: int, file: UploadFile = File(...), replaceAssetId: int | None = Form(None)) -> dict[str, Any]:
    video = _video_or_404(video_id)
    filename = Path(file.filename or "imported.srt").name
    if Path(filename).suffix.lower() != ".srt":
        raise HTTPException(400, "Only .srt subtitle files can be imported")
    try:
        content = file.file.read().decode("utf-8-sig")
        probe_path = config.outputs_dir / f"video_{video.id}" / "subtitles" / f".import-{time.time_ns()}.srt"
        probe_path.parent.mkdir(parents=True, exist_ok=True)
        probe_path.write_text(content, encoding="utf-8")
        valid = read_srt(probe_path)
        probe_path.unlink(missing_ok=True)
        if not valid:
            raise ValueError("SRT contains no readable subtitle segments")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid SRT file: {exc}") from exc

    existing = storage.get_asset(replaceAssetId) if replaceAssetId else _primary_srt_asset(video)
    if existing and (existing.video_id != video.id or existing.kind != "srt" or _is_translation_srt(existing)):
        raise HTTPException(400, "Selected SRT does not belong to this project's primary subtitle track")
    if existing:
        asset = _replace_srt_asset(video, existing, content, "before-import")
        return {"asset": _asset_payload(asset)}

    output_dir = config.outputs_dir / f"video_{video.id}" / "subtitles"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename
    counter = 1
    while destination.exists():
        destination = output_dir / f"{Path(filename).stem}_{counter}.srt"
        counter += 1
    destination.write_text(content, encoding="utf-8")
    asset_id = storage.add_asset(
        video_id=video.id,
        kind="srt",
        path=destination,
        engine="imported",
        metadata={"source": "import", "original_filename": filename, "role": "primary"},
    )
    return {"asset": _asset_payload(storage.get_asset(asset_id))}


@app.get("/api/assets/{asset_id}/srt")
def asset_srt(asset_id: int) -> dict[str, Any]:
    asset = _asset_or_404(asset_id)
    if asset.kind != "srt" or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    segments = read_srt(asset.path)
    return {
        "asset": _asset_payload(asset),
        "content": asset.path.read_text(encoding="utf-8-sig"),
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "startLabel": seconds_to_srt_time(segment.start),
                "endLabel": seconds_to_srt_time(segment.end),
                "text": segment.text,
            }
            for segment in segments
        ],
    }


@app.put("/api/assets/{asset_id}/srt")
def save_asset_srt(asset_id: int, payload: SrtSaveRequest) -> dict[str, str]:
    asset = _asset_or_404(asset_id)
    if asset.kind != "srt" or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    asset.path.write_text(payload.content, encoding="utf-8")
    return {"status": "saved"}


@app.delete("/api/assets/{asset_id}")
def delete_voiceover_asset(asset_id: int) -> dict[str, list[int]]:
    asset = _asset_or_404(asset_id)
    if asset.kind != "tts":
        raise HTTPException(409, "Only the merged voiceover can be removed from the timeline")

    video = _video_or_404(asset.video_id)
    # A2 represents one merged voiceover, even when prior regenerations left
    # several TTS assets behind. Remove the whole voiceover set so the next
    # render starts with an empty A2 track rather than revealing an older one.
    voiceover_kinds = {"tts", "tts_video", "tts_working_audio", "tts_working_srt", "tts_timeline_manifest"}
    assets_to_remove = [candidate for candidate in storage.list_assets(video.id) if candidate.kind in voiceover_kinds]

    deleted_ids: list[int] = []
    output_root = config.outputs_dir.resolve()
    for candidate in assets_to_remove:
        if storage.delete_asset(candidate.id):
            deleted_ids.append(candidate.id)

    for candidate in assets_to_remove:
        try:
            resolved = candidate.path.resolve()
            if resolved.is_relative_to(output_root) and candidate.path.is_file() and not storage.path_is_referenced(candidate.path):
                candidate.path.unlink()
        except OSError:
            pass
    return {"deletedAssetIds": deleted_ids}


@app.post("/api/assets/{asset_id}/reveal")
def reveal_asset_file(asset_id: int) -> dict[str, str]:
    asset = _asset_or_404(asset_id)
    path = asset.path
    target = path if path.exists() else path.parent
    if not target.exists():
        raise HTTPException(404, "Asset file location not found")
    if sys.platform.startswith("win"):
        if path.exists() and path.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{str(path)}"])
        else:
            subprocess.Popen(["explorer.exe", str(target)])
        return {"status": "opened", "path": str(path)}
    raise HTTPException(400, "Reveal in folder is only supported on Windows in this build")


@app.get("/api/assets/{asset_id}/download")
def download_asset(asset_id: int) -> FileResponse:
    asset = _asset_or_404(asset_id)
    if not asset.path.exists():
        raise HTTPException(404, "Asset file not found")
    media_type = mimetypes.guess_type(asset.path.name)[0] or "application/octet-stream"
    return FileResponse(asset.path, media_type=media_type, filename=asset.path.name)


@app.get("/api/project-assets/{project_asset_id}/download")
def download_project_asset(project_asset_id: int) -> FileResponse:
    asset = storage.get_project_asset(project_asset_id)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "Project asset file not found")
    media_type = mimetypes.guess_type(asset.path.name)[0] or "application/octet-stream"
    return FileResponse(asset.path, media_type=media_type, filename=asset.path.name)


@app.get("/api/videos/{video_id}/srt/download")
def download_srt(video_id: int) -> FileResponse:
    video = _video_or_404(video_id)
    asset = _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    return FileResponse(asset.path, media_type="application/x-subrip", filename=asset.path.name)


@app.put("/api/videos/{video_id}/srt/latest")
def save_srt(video_id: int, payload: SrtSaveRequest) -> dict[str, str]:
    video = _video_or_404(video_id)
    asset = _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    asset.path.write_text(payload.content, encoding="utf-8")
    return {"status": "saved"}


@app.post("/api/videos/{video_id}/srt/translate")
def translate_srt(video_id: int, payload: SrtTranslateRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.get_asset(payload.srtAssetId) if payload.srtAssetId else _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt":
        raise HTTPException(400, "SRT asset does not belong to this video")
    active = _active_job("translate", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("translate", f"Translate SRT: {video.title}", video.id)
    def translate_and_replace(progress: Callable[[str], None]):
        translated_path = translator.translate_srt(
            video,
            asset.path,
            source_language=payload.sourceLanguage,
            target_language=payload.targetLanguage,
            engine=payload.engine,
            device=payload.device,
            progress=progress,
            register_asset=False,
        )
        replaced = _replace_srt_asset(video, asset, translated_path.read_text(encoding="utf-8-sig"), "before-translation")
        translated_path.unlink(missing_ok=True)
        progress(f"Translated SRT replaced the active subtitle track: {replaced.path}")
        return {"assetId": replaced.id, "outputPath": str(replaced.path)}

    _run_job(job_id, translate_and_replace)
    return {"jobId": job_id}


@app.post("/api/videos/{video_id}/tts")
def synthesize_tts(video_id: int, payload: TtsRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.get_asset(payload.srtAssetId) if payload.srtAssetId else _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt":
        raise HTTPException(400, "SRT asset does not belong to this video")
    active = _active_job("tts", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    engine = payload.engine or "vieneu"
    job_id = _new_job("tts", f"{engine.title()} TTS: {video.title}", video.id)
    _run_job(job_id, lambda progress: _synthesize_tts_for_video(video, asset.path, payload, progress))
    return {"jobId": job_id}


@app.get("/api/tts/history")
def standalone_tts_history(limit: int = 50) -> dict[str, Any]:
    max_items = max(1, min(int(limit or 50), 200))
    assets = []
    for video in storage.list_videos():
        if not (video.metadata or {}).get("standalone_tts"):
            continue
        for asset in storage.list_assets(video.id):
            if asset.kind == "tts" and asset.path.exists():
                assets.append(asset)
    assets.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    return {"assets": [_asset_payload(asset) for asset in assets[:max_items]]}


@app.post("/api/tts")
def synthesize_standalone_tts(payload: StandaloneTtsRequest) -> dict[str, Any]:
    engine = payload.engine or "vieneu"
    if engine not in {"vieneu", "capcut", "pocket"}:
        raise HTTPException(400, f"Unsupported TTS engine: {engine}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = config.outputs_dir / "standalone_tts" / f"{stamp}_{time.time_ns() % 1_000_000:06d}"
    srt_path = _content_to_standalone_srt(payload, output_dir)
    video = _standalone_tts_video(payload, output_dir, srt_path)
    job_id = _new_job("standalone-tts", f"{engine.title()} TTS: {video.title}", video.id)

    def run(progress: Callable[[str], None]) -> dict[str, Any]:
        output_path = _synthesize_tts_for_video(video, srt_path, payload, progress)
        asset = storage.latest_asset(video.id, "tts")
        return {
            "outputPath": str(output_path),
            "asset": _asset_payload(asset) if asset else None,
            "videoId": video.id,
        }

    _run_job(job_id, run)
    return {"jobId": job_id, "videoId": video.id}


@app.get("/api/videos/{video_id}/tts/segments")
def list_tts_segments(
    video_id: int,
    srtAssetId: int | None = None,
    engine: str = "capcut",
    voice: str = "default",
    language: str = "en-US",
    rate: str = "1.0",
) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.get_asset(srtAssetId) if srtAssetId else _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt":
        raise HTTPException(400, "SRT asset does not belong to this video")
    selected_engine = _segment_engine(engine)
    payload = TtsSegmentRequest(srtAssetId=asset.id, engine=selected_engine, voice=voice, language=language, rate=rate)
    signature, _ = _segment_signature(selected_engine, payload)
    rows = {int(row.get("index") or -1): row for row in _read_manifest_rows(_segment_manifest_path(video.id, selected_engine))}
    segments = []
    for segment in read_srt(asset.path):
        item = _segment_status(rows.get(segment.index), segment, selected_engine, signature)
        if item["audioUrl"]:
            item["audioUrl"] = item["audioUrl"].replace("{video_id}", str(video.id))
        segments.append(item)
    return {"segments": segments}


@app.post("/api/videos/{video_id}/tts/segments/merge")
def merge_tts_segments(video_id: int, payload: TtsSegmentRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.get_asset(payload.srtAssetId) if payload.srtAssetId else _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt":
        raise HTTPException(400, "SRT asset does not belong to this video")
    _segment_engine(payload.engine)
    active = _active_job("tts", video.id) or _active_job("tts-segment", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("tts", f"Merge TTS Segments: {video.title}", video.id)
    _run_job(job_id, lambda progress: _merge_tts_segments(video, asset.path, payload, progress))
    return {"jobId": job_id, "merge": True}


@app.post("/api/videos/{video_id}/tts/segments/{segment_index}")
def generate_tts_segment(video_id: int, segment_index: int, payload: TtsSegmentRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.get_asset(payload.srtAssetId) if payload.srtAssetId else _primary_srt_asset(video)
    if not asset or not asset.path.exists():
        raise HTTPException(404, "SRT not found")
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt":
        raise HTTPException(400, "SRT asset does not belong to this video")
    _segment_engine(payload.engine)
    active = _active_job("tts-segment", video.id) or _active_job("tts", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("tts-segment", f"TTS Line #{segment_index}: {video.title}", video.id)
    _run_job(job_id, lambda progress: _render_single_tts_segment(video, asset.path, segment_index, payload, progress))
    return {"jobId": job_id, "segmentIndex": segment_index}


@app.get("/api/videos/{video_id}/tts/segments/{segment_index}/audio")
def tts_segment_audio(video_id: int, segment_index: int, engine: str = "capcut") -> FileResponse:
    video = _video_or_404(video_id)
    selected_engine = _segment_engine(engine)
    rows = {int(row.get("index") or -1): row for row in _read_manifest_rows(_segment_manifest_path(video.id, selected_engine))}
    row = rows.get(segment_index)
    path = _manifest_audio_path(row or {})
    if not row or not path.exists():
        raise HTTPException(404, f"TTS segment #{segment_index} not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.post("/api/videos/{video_id}/subtitle/remove")
def remove_subtitles(video_id: int, payload: SubtitleRemoveRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    if payload.mode not in {"auto", "manual"}:
        raise HTTPException(400, f"Unsupported subtitle removal mode: {payload.mode}")
    if not (payload.area == "bottom" or isinstance(payload.area, dict)):
        raise HTTPException(400, f"Unsupported subtitle removal area: {payload.area}")
    active = _active_job("remove", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    srt_asset = None
    if payload.mode == "auto":
        if payload.srtAssetId is None:
            raise HTTPException(400, "Automatic blur requires an original SRT file")
        srt_asset = _asset_or_404(payload.srtAssetId)
        if not _asset_belongs_to_video(srt_asset, video) or srt_asset.kind != "srt" or not srt_asset.path.exists():
            raise HTTPException(400, "Selected SRT does not belong to this video")
    job_id = _new_job("remove", f"Remove Subtitles: {video.title}", video.id)
    _run_job(
        job_id,
        lambda progress: subtitle_remover.configure_blur_effect(
            video,
            mode=payload.mode,
            area=payload.area,
            srt_path=srt_asset.path if srt_asset else None,
            srt_asset_id=srt_asset.id if srt_asset else None,
            progress=progress,
        ),
    )
    return {"jobId": job_id}


@app.delete("/api/videos/{video_id}/subtitle/effect")
def delete_subtitle_effect(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    metadata = dict(video.metadata or {})
    removed = metadata.pop("subtitle_blur_effect", None)
    storage.update_video_metadata(video.id, metadata)
    return {"videoId": video.id, "removed": bool(removed)}


@app.post("/api/videos/{video_id}/subtitle/undo")
def undo_subtitle_operation(video_id: int, payload: SubtitleUndoRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    state_keys = {"hide": "subtitle_hidden", "insert": "subtitle_inserted"}
    state_key = state_keys.get(payload.operation)
    if not state_key:
        raise HTTPException(400, f"Unsupported subtitle undo operation: {payload.operation}")
    target = storage.find_ancestor_without_state(video.id, state_key)
    if not target:
        raise HTTPException(409, f"No earlier project version can undo {payload.operation}")
    return {"videoId": target.id, "targetVideoId": target.id, "video": _video_payload(target)}


@app.post("/api/videos/{video_id}/subtitle/replace")
def replace_subtitles(video_id: int, payload: SubtitleReplaceRequest) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = _asset_or_404(payload.srtAssetId)
    if not _asset_belongs_to_video(asset, video) or asset.kind != "srt" or not asset.path.exists():
        raise HTTPException(400, "Selected SRT does not belong to this video")
    if payload.mode not in {"none", "blur", "cover"}:
        raise HTTPException(400, f"Unsupported subtitle replacement mode: {payload.mode}")
    if not (payload.area == "bottom" or isinstance(payload.area, dict)):
        raise HTTPException(400, f"Unsupported subtitle replacement area: {payload.area}")
    active = _active_job("replace", video.id)
    if active:
        return {"jobId": active["id"], "alreadyRunning": True}
    job_id = _new_job("replace", f"Replace Subtitles: {video.title}", video.id)
    _run_job(
        job_id,
        lambda progress: subtitle_remover.replace_subtitles(
            video,
            asset.path,
            srt_asset_id=asset.id,
            mode=payload.mode,
            area=payload.area,
            style=payload.style,
            progress=progress,
        ),
    )
    return {"jobId": job_id}


@app.get("/api/videos/{video_id}/tts/latest")
def latest_tts(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    asset = storage.latest_asset(video.id, "tts")
    if not asset or not asset.path.exists():
        return {"asset": None}
    return {"asset": _asset_payload(asset)}


@app.get("/api/videos/{video_id}/tts/video")
def preview_tts_video(video_id: int, assetId: int | None = None) -> FileResponse:
    video = _video_or_404(video_id)
    asset = storage.get_asset(assetId) if assetId else storage.latest_asset(video.id, "tts_video")
    if not asset or asset.video_id != video.id or asset.kind != "tts_video" or not asset.path.exists():
        raise HTTPException(404, "Dubbed video not found")
    return FileResponse(asset.path, media_type="video/mp4", filename=asset.path.name)


@app.get("/api/videos/{video_id}/tts/timeline/issues")
def tts_timeline_issues(video_id: int) -> dict[str, Any]:
    video = _video_or_404(video_id)
    manifest_path = _latest_timeline_manifest_path(video.id)
    if not manifest_path:
        return {"state": None, "issues": []}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(409, f"Cannot read adaptive timeline manifest: {exc}") from exc
    state = payload.get("state") or {}
    rows = payload.get("segments") or []
    blocking = {"TEXT_TOO_LONG", "OVERLAP", "FINAL_OVERLAP", "FINAL_VOICE_OVERFLOW"}
    issues = [
        _timeline_issue_payload(row, state)
        for row in rows
        if str(row.get("segment_status") or row.get("status") or "") in blocking
    ]
    issues.sort(key=lambda item: int(item.get("index") or 0))
    return {
        "state": state,
        "issues": issues,
        "manifestPath": str(manifest_path),
    }


@app.get("/api/videos/{video_id}/tts/download")
def download_tts(video_id: int) -> FileResponse:
    video = _video_or_404(video_id)
    asset = storage.latest_asset(video.id, "tts")
    if not asset or not asset.path.exists():
        raise HTTPException(404, "TTS output not found")
    return FileResponse(asset.path, media_type="audio/wav", filename=asset.path.name)


@app.get("/api/voices")
def voices(engine: str = "vieneu", language: str | None = None) -> dict[str, Any]:
    values: list[Any] = [{"id": "default", "label": "Default", "engine": engine}]
    try:
        if engine == "capcut":
            values = capcut_tts.list_voices(language) or values
        elif engine == "pocket":
            values = pocket_tts.list_voices(language) or values
        else:
            values += [{"id": voice_id, "label": label, "engine": "vieneu"} for label, voice_id in tts.list_voices()]
    except Exception:
        pass
    return {"voices": values}


@app.on_event("shutdown")
def shutdown() -> None:
    storage.close()

# reload

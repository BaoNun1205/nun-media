from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import SubtitleSegment, VideoItem
from .srt import write_srt


MIN_WORKING_SPEED = 0.7
MAX_WORKING_SPEED = 1.0
PREFERRED_MAX_LOCAL_SPEED = 1.15
HARD_MAX_LOCAL_SPEED = 1.30
SAFETY_GAP_SECONDS = 0.12
TIMELINE_TOLERANCE_SECONDS = 0.002
VIDEO_DURATION_TOLERANCE_SECONDS = 0.08
OVERLAP_THRESHOLD_SECONDS = 0.01
MIN_SEGMENT_DURATION_SECONDS = 0.05
DEFAULT_SLOT_MAX_SPEED = 1.5


class AdaptiveTimelineError(RuntimeError):
    def __init__(self, message: str, *, state: dict, manifest_path: Path, working_srt_path: Path):
        super().__init__(message)
        self.state = state
        self.manifest_path = manifest_path
        self.working_srt_path = working_srt_path


@dataclass(frozen=True)
class TimelineAnalysisItem:
    segment: SubtitleSegment
    original_tts_path: Path
    original_tts_duration: float
    original_available_duration: float


def build_atempo_chain(speed_ratio: float) -> str:
    if not math.isfinite(speed_ratio) or speed_ratio <= 0:
        raise ValueError("Tempo ratio must be a positive finite number")
    factors: list[float] = []
    remaining = speed_ratio
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.10f}" for factor in factors)


def validate_working_speed(value: float) -> float:
    return validate_working_speed_range(value, min_working_speed=MIN_WORKING_SPEED, max_working_speed=MAX_WORKING_SPEED)


def validate_working_speed_range(value: float, *, min_working_speed: float, max_working_speed: float = MAX_WORKING_SPEED) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Working speed must be a number") from exc
    if not min_working_speed <= speed <= max_working_speed:
        raise ValueError(f"Working speed must be between {min_working_speed:.1f} and {max_working_speed:.1f}")
    return speed


def select_adaptive_working_speed(
    durations: list[float],
    original_starts: list[float],
    *,
    video_duration: float,
    safety_gap: float = SAFETY_GAP_SECONDS,
    min_working_speed: float = MIN_WORKING_SPEED,
    preferred_max_local_speed: float = PREFERRED_MAX_LOCAL_SPEED,
    hard_max_local_speed: float = HARD_MAX_LOCAL_SPEED,
) -> tuple[float, dict]:
    if len(durations) != len(original_starts) or not durations:
        raise ValueError("Adaptive analysis requires matching non-empty duration/start arrays")
    limits_preferred: list[float] = []
    limits_hard: list[float] = []
    invalid_timeline = 0
    fit_at_one = 0
    for index, (duration, start) in enumerate(zip(durations, original_starts)):
        next_start = original_starts[index + 1] if index + 1 < len(original_starts) else video_duration
        gap = next_start - start
        available_at_one = gap - safety_gap
        if gap <= 0 or available_at_one <= 0:
            invalid_timeline += 1
            limits_preferred.append(0.0)
            limits_hard.append(0.0)
            continue
        if duration <= available_at_one:
            fit_at_one += 1
        limits_preferred.append(gap / (duration / preferred_max_local_speed + safety_gap))
        limits_hard.append(gap / (duration / hard_max_local_speed + safety_gap))

    if fit_at_one == len(durations) and invalid_timeline == 0:
        selected = 1.0
    else:
        sorted_preferred = sorted(max(0.0, min(1.0, value)) for value in limits_preferred)
        percentile_index = min(len(sorted_preferred) - 1, max(0, math.floor(len(sorted_preferred) * 0.10)))
        preferred_target = sorted_preferred[percentile_index]
        hard_target = min(limits_hard)
        selected = min(1.0, preferred_target)
        if hard_target >= min_working_speed:
            selected = min(selected, hard_target)
        selected = max(min_working_speed, selected)
        selected = round(selected, 4)

    return selected, {
        "segments": len(durations),
        "fit_at_1_0": fit_at_one,
        "invalid_timeline_count": invalid_timeline,
        "min_working_speed": min_working_speed,
        "preferred_max_local_speed": preferred_max_local_speed,
        "hard_max_local_speed": hard_max_local_speed,
    }


def process_adaptive_timeline(
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    sample_rate: int,
    manual_working_speed: float | None = None,
    min_working_speed: float = MIN_WORKING_SPEED,
    preferred_max_local_speed: float = PREFERRED_MAX_LOCAL_SPEED,
    hard_max_local_speed: float = HARD_MAX_LOCAL_SPEED,
    safety_gap: float = SAFETY_GAP_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> dict:
    if not rendered:
        raise RuntimeError("Adaptive Timeline Fit received no TTS segments")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for Adaptive Timeline Fit")
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("numpy and soundfile are required for Adaptive Timeline Fit") from exc

    original_duration = video.duration_ms / 1000 if video.duration_ms else _probe_duration(video.path)
    if not original_duration or original_duration <= 0:
        raise RuntimeError("Could not determine original video duration")
    segments = [segment for segment, _path in rendered]
    _validate_original_timeline(segments, original_duration)
    original_durations = [float(sf.info(str(path)).duration) for _segment, path in rendered]
    starts = [segment.start for segment in segments]
    selected_speed, analysis = select_adaptive_working_speed(
        original_durations,
        starts,
        video_duration=original_duration,
        safety_gap=safety_gap,
        min_working_speed=min_working_speed,
        preferred_max_local_speed=preferred_max_local_speed,
        hard_max_local_speed=hard_max_local_speed,
    )
    timing_mode = "adaptive"
    if manual_working_speed is not None:
        selected_speed = validate_working_speed_range(manual_working_speed, min_working_speed=min_working_speed)
        timing_mode = "manual"
    working_duration = original_duration / selected_speed
    restore_speed = 1.0 / selected_speed
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    processed_rendered: list[tuple[SubtitleSegment, Path]] = []
    blocking_statuses: list[str] = []
    counts = {"FIT": 0, "SPEED_ADJUSTED": 0, "SPEED_ADJUSTED_WARNING": 0, "TEXT_TOO_LONG": 0}
    for index, ((segment, original_path), original_tts_duration) in enumerate(zip(rendered, original_durations)):
        working_start = segment.start / selected_speed
        working_end = segment.end / selected_speed
        next_original_start = segments[index + 1].start if index + 1 < len(segments) else original_duration
        next_working_start = next_original_start / selected_speed
        working_available = next_working_start - working_start - safety_gap
        required_speed = original_tts_duration / working_available if working_available > 0 else float("inf")
        applied_speed = 1.0
        processed_path = original_path
        if required_speed <= 1.0:
            status = "FIT"
        elif required_speed <= preferred_max_local_speed:
            status = "SPEED_ADJUSTED"
            applied_speed = required_speed
        elif required_speed <= hard_max_local_speed:
            status = "SPEED_ADJUSTED_WARNING"
            applied_speed = required_speed
        else:
            status = "TEXT_TOO_LONG"
            blocking_statuses.append(status)
        if applied_speed > 1.000001:
            processed_path = original_path.with_name(f"{original_path.stem}_speed_{applied_speed:.3f}.wav")
            _atempo_file(ffmpeg, original_path, processed_path, applied_speed)
        processed_duration = float(sf.info(str(processed_path)).duration)
        for _ in range(3):
            if status == "TEXT_TOO_LONG" or processed_duration <= working_available + TIMELINE_TOLERANCE_SECONDS:
                break
            measured_required_speed = applied_speed * processed_duration / max(working_available - TIMELINE_TOLERANCE_SECONDS, 0.001) * 1.002
            if measured_required_speed <= hard_max_local_speed:
                applied_speed = measured_required_speed
                status = "SPEED_ADJUSTED" if applied_speed <= preferred_max_local_speed else "SPEED_ADJUSTED_WARNING"
                processed_path = original_path.with_name(f"{original_path.stem}_speed_{applied_speed:.3f}.wav")
                _atempo_file(ffmpeg, original_path, processed_path, applied_speed)
                processed_duration = float(sf.info(str(processed_path)).duration)
            else:
                break
        working_audio_end = working_start + processed_duration
        if status != "TEXT_TOO_LONG" and working_audio_end > next_working_start - safety_gap + TIMELINE_TOLERANCE_SECONDS:
            status = "OVERLAP"
            blocking_statuses.append(status)
        counts[status] = counts.get(status, 0) + 1
        rows.append(
            {
                "index": segment.index,
                "text": segment.text,
                "original_start_time": segment.start,
                "original_end_time": segment.end,
                "working_start_time": working_start,
                "working_end_time": working_end,
                "original_tts_path": str(original_path),
                "original_tts_duration": original_tts_duration,
                "processed_tts_path": str(processed_path),
                "processed_tts_duration": processed_duration,
                "working_available_duration": working_available,
                "required_local_speed": required_speed if math.isfinite(required_speed) else None,
                "applied_local_speed": applied_speed,
                "working_audio_end": working_audio_end,
                "segment_status": status,
            }
        )
        processed_rendered.append((SubtitleSegment(segment.index, working_start, working_end, segment.text), processed_path))

    working_srt = output_dir / "adaptive_timeline.working.srt"
    write_srt([segment for segment, _path in processed_rendered], working_srt)
    base_state = {
        "timing_mode": timing_mode,
        "selected_working_speed": selected_speed,
        "min_working_speed": min_working_speed,
        "preferred_max_local_speed": preferred_max_local_speed,
        "hard_max_local_speed": hard_max_local_speed,
        "safety_gap": safety_gap,
        "original_video_duration": original_duration,
        "working_video_duration": working_duration,
        "global_restore_speed": restore_speed,
        "analysis": analysis,
        "counts": counts,
    }
    manifest = output_dir / "adaptive_timeline.json"
    if blocking_statuses:
        base_state.update({"final_validation_status": "INVALID", "blocking_statuses": sorted(set(blocking_statuses))})
        manifest.write_text(json.dumps({"state": base_state, "segments": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise AdaptiveTimelineError(
            f"Adaptive Timeline Fit blocked export: {counts.get('TEXT_TOO_LONG', 0)} TEXT_TOO_LONG, "
            f"{counts.get('OVERLAP', 0)} OVERLAP. See {manifest}",
            state=base_state,
            manifest_path=manifest,
            working_srt_path=working_srt,
        )

    if progress:
        progress(f"Adaptive Timeline selected {selected_speed:.4f}x; resolving {counts['SPEED_ADJUSTED'] + counts['SPEED_ADJUSTED_WARNING']} segment(s)")
    canvas = np.zeros(round(working_duration * sample_rate), dtype=np.float32)
    for working_segment, path in processed_rendered:
        audio, source_rate = sf.read(str(path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if source_rate != sample_rate:
            try:
                import soxr
            except ImportError as exc:
                raise RuntimeError("soxr is required to resample TTS audio") from exc
            audio = soxr.resample(audio, source_rate, sample_rate)
        start_sample = round(working_segment.start * sample_rate)
        end_sample = start_sample + len(audio)
        if end_sample > len(canvas):
            raise RuntimeError("FINAL_VOICE_OVERFLOW: processed voice exceeds working canvas")
        canvas[start_sample:end_sample] = np.clip(canvas[start_sample:end_sample] + audio, -1.0, 1.0)

    working_audio = output_dir / "voiceover.adaptive.working.wav"
    sf.write(str(working_audio), canvas, sample_rate, subtype="FLOAT")
    restored_temp = output_dir / "voiceover.adaptive.restored.tmp.wav"
    _run_ffmpeg(
        [ffmpeg, "-y", "-i", str(working_audio), "-filter:a", build_atempo_chain(restore_speed), str(restored_temp)],
        "Global audio restore failed",
    )
    restored_audio, restored_rate = sf.read(str(restored_temp), dtype="float32", always_2d=False)
    if restored_audio.ndim > 1:
        restored_audio = restored_audio.mean(axis=1)
    if restored_rate != sample_rate:
        raise RuntimeError("Global restore changed sample rate unexpectedly")

    final_rows, final_status = _validate_final_timeline(rows, original_duration, selected_speed, safety_gap=safety_gap)
    if final_status != "VALID":
        base_state["final_validation_status"] = final_status
        manifest.write_text(json.dumps({"state": base_state, "segments": final_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"Final Timeline Validation failed: {final_status}. See {manifest}")

    target_samples = round(original_duration * sample_rate)
    if len(restored_audio) < target_samples:
        restored_audio = np.pad(restored_audio, (0, target_samples - len(restored_audio)))
    elif len(restored_audio) > target_samples:
        last_voice_end = max(row["final_audio_end"] for row in final_rows)
        if last_voice_end > original_duration + 1 / sample_rate:
            raise RuntimeError("FINAL_VOICE_OVERFLOW: refusing to trim active speech")
        restored_audio = restored_audio[:target_samples]
    final_audio = output_dir / "voiceover.wav"
    sf.write(str(final_audio), restored_audio, sample_rate, subtype="FLOAT")
    actual_samples = int(sf.info(str(final_audio)).frames)
    final_audio_duration = actual_samples / sample_rate
    duration_difference = abs(final_audio_duration - original_duration)
    if abs(actual_samples - target_samples) > 1:
        raise RuntimeError("INVALID_FINAL_DURATION: final WAV differs by more than one sample")

    final_video = output_dir / "video.voiceover.mp4"
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video.path),
            "-i",
            str(final_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-t",
            f"{original_duration:.10f}",
            str(final_video),
        ],
        "Final video mux failed",
    )
    final_video_duration = _probe_duration(final_video)
    if final_video_duration is None or abs(final_video_duration - original_duration) > VIDEO_DURATION_TOLERANCE_SECONDS:
        base_state.update(
            {
                "final_audio_duration": final_audio_duration,
                "final_video_duration": final_video_duration,
                "duration_difference": duration_difference,
                "target_samples": target_samples,
                "actual_samples": actual_samples,
                "final_validation_status": "INVALID_FINAL_DURATION",
            }
        )
        manifest.write_text(json.dumps({"state": base_state, "segments": final_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise AdaptiveTimelineError(
            f"Final video duration does not match source duration. See {manifest}",
            state=base_state,
            manifest_path=manifest,
            working_srt_path=working_srt,
        )
    base_state.update(
        {
            "final_audio_duration": final_audio_duration,
            "final_video_duration": final_video_duration,
            "duration_difference": duration_difference,
            "target_samples": target_samples,
            "actual_samples": actual_samples,
            "final_validation_status": "VALID",
        }
    )
    manifest.write_text(json.dumps({"state": base_state, "segments": final_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "voiceover_path": final_audio,
        "working_audio_path": working_audio,
        "working_srt_path": working_srt,
        "final_video_path": final_video,
        "manifest_path": manifest,
        "state": base_state,
        "segments": final_rows,
    }


def process_plain_timeline(
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    sample_rate: int,
    progress: Callable[[str], None] | None = None,
) -> dict:
    return process_srt_slot_timeline(
        video,
        rendered,
        output_dir,
        sample_rate=sample_rate,
        max_speed=DEFAULT_SLOT_MAX_SPEED,
        progress=progress,
    )


def process_srt_slot_timeline(
    video: VideoItem,
    rendered: list[tuple[SubtitleSegment, Path]],
    output_dir: Path,
    *,
    sample_rate: int,
    max_speed: float = DEFAULT_SLOT_MAX_SPEED,
    progress: Callable[[str], None] | None = None,
) -> dict:
    if not rendered:
        raise RuntimeError("SRT Slot Timeline received no TTS segments")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to mux TTS audio")
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("numpy and soundfile are required for TTS timeline rendering") from exc

    video_duration = video.duration_ms / 1000 if video.duration_ms else _probe_duration(video.path)
    if not video_duration or video_duration <= 0:
        raise RuntimeError("Could not determine original video duration")
    segments = [segment for segment, _path in rendered]
    _validate_original_timeline(segments, video_duration)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    audio_segments: list[np.ndarray] = []
    current_total_samples = 0
    max_speed = max(1.0, float(max_speed or DEFAULT_SLOT_MAX_SPEED))
    counts = {
        "FIT": 0,
        "PADDED": 0,
        "SPEED_ADJUSTED": 0,
        "MAX_SPEED_TRIMMED": 0,
        "LATE_START": 0,
        "LATE_START_EVENTS": 0,
        "OVERLAP": 0,
    }

    for index, (segment, path) in enumerate(rendered):
        start_sample = round(segment.start * sample_rate)
        end_sample = round(segment.end * sample_rate)
        current_head = current_total_samples / sample_rate
        gap_samples = start_sample - current_total_samples
        had_overlap = False
        if gap_samples > 0:
            audio_segments.append(np.zeros(gap_samples, dtype=np.float32))
            current_total_samples += gap_samples
        elif gap_samples < -round(OVERLAP_THRESHOLD_SECONDS * sample_rate):
            counts["OVERLAP"] += 1
            had_overlap = True

        current_head = current_total_samples / sample_rate
        slot_samples = end_sample - current_total_samples
        late_start = False
        if slot_samples < round(MIN_SEGMENT_DURATION_SECONDS * sample_rate):
            slot_samples = round(MIN_SEGMENT_DURATION_SECONDS * sample_rate)
            late_start = True
            counts["LATE_START_EVENTS"] += 1

        original_audio, _source_rate = _read_audio_mono(path, sample_rate)
        original_tts_duration = len(original_audio) / sample_rate
        slot_duration = slot_samples / sample_rate
        required_speed = original_tts_duration / slot_duration if slot_duration > 0 else None
        processed_audio = original_audio
        applied_speed = 1.0
        status = "FIT"
        if slot_samples > 0 and len(original_audio) > 0:
            required_speed = required_speed or 1.0
            if required_speed > max_speed:
                applied_speed = max_speed
                status = "MAX_SPEED_TRIMMED"
            elif required_speed > 1.000001:
                applied_speed = required_speed
                status = "SPEED_ADJUSTED"
            elif required_speed < 0.999999:
                applied_speed = 1.0
                status = "PADDED"
            if abs(applied_speed - 1.0) > 0.000001:
                stretched_path = path.with_name(f"{path.stem}_slot_{applied_speed:.3f}.wav")
                _atempo_file(ffmpeg, path, stretched_path, applied_speed)
                processed_audio, _source_rate = _read_audio_mono(stretched_path, sample_rate)
        processed_audio = _exact_sample_length(processed_audio, slot_samples)
        processed_path = path.with_name(f"{path.stem}_slot.wav")
        sf.write(str(processed_path), processed_audio, sample_rate, subtype="FLOAT")
        audio_segments.append(processed_audio)
        current_total_samples += len(processed_audio)
        if late_start:
            status = "LATE_START" if status == "FIT" else status
        counts[status] = counts.get(status, 0) + 1
        working_audio_end = current_total_samples / sample_rate
        rows.append(
            {
                "index": segment.index,
                "text": segment.text,
                "original_start_time": segment.start,
                "original_end_time": segment.end,
                "working_start_time": current_head,
                "working_end_time": segment.end,
                "original_tts_path": str(path),
                "original_tts_duration": original_tts_duration,
                "processed_tts_path": str(processed_path),
                "processed_tts_duration": len(processed_audio) / sample_rate,
                "working_available_duration": slot_duration,
                "required_local_speed": required_speed,
                "applied_local_speed": applied_speed,
                "working_audio_end": working_audio_end,
                "final_start_time": current_head,
                "final_processed_duration": len(processed_audio) / sample_rate,
                "final_audio_end": working_audio_end,
                "segment_status": status,
                "had_overlap": had_overlap,
                "max_speed": max_speed,
            }
        )

    final_audio_data = np.concatenate(audio_segments) if audio_segments else np.zeros(0, dtype=np.float32)
    target_samples = round(video_duration * sample_rate)
    final_audio_data = _exact_sample_length(final_audio_data, target_samples)

    final_audio = output_dir / "voiceover.wav"
    sf.write(str(final_audio), final_audio_data, sample_rate, subtype="FLOAT")
    working_srt = output_dir / "srt_slot_timeline.srt"
    write_srt(segments, working_srt)
    final_video = output_dir / "video.voiceover.mp4"
    if not (video.metadata or {}).get("standalone_tts"):
        _run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video.path),
                "-i",
                str(final_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-t",
                f"{video_duration:.10f}",
                str(final_video),
            ],
            "Final video mux failed",
        )
    actual_samples = int(sf.info(str(final_audio)).frames)
    actual_duration = actual_samples / sample_rate
    state = {
        "timing_mode": "srt_slot",
        "selected_working_speed": 1.0,
        "global_restore_speed": 1.0,
        "original_video_duration": video_duration,
        "final_audio_duration": actual_duration,
        "final_video_duration": _probe_duration(final_video) if final_video.exists() else actual_duration,
        "target_samples": target_samples,
        "actual_samples": actual_samples,
        "max_speed": max_speed,
        "final_validation_status": "VALID",
        "counts": counts,
    }
    manifest = output_dir / "srt_slot_timeline.json"
    manifest.write_text(json.dumps({"state": state, "segments": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress:
        progress(f"SRT Slot timeline exported {len(rendered)} segment(s)")
    return {
        "voiceover_path": final_audio,
        "working_audio_path": final_audio,
        "working_srt_path": working_srt,
        "final_video_path": final_video,
        "manifest_path": manifest,
        "state": state,
        "segments": rows,
    }


def _validate_original_timeline(segments: list[SubtitleSegment], video_duration: float) -> None:
    previous_start = -1.0
    for segment in segments:
        if segment.start < 0 or segment.end <= segment.start:
            raise RuntimeError(f"Invalid subtitle duration at segment {segment.index}")
        if segment.start <= previous_start:
            raise RuntimeError(f"Subtitle timeline is reversed or has duplicate starts at segment {segment.index}")
        if segment.start >= video_duration:
            raise RuntimeError(f"Subtitle starts outside video duration at segment {segment.index}")
        previous_start = segment.start


def _exact_sample_length(audio, target_samples: int):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for exact sample timeline rendering") from exc
    if target_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) < target_samples:
        return np.pad(audio, (0, target_samples - len(audio)), mode="constant").astype(np.float32)
    return audio[:target_samples].astype(np.float32)


def _read_audio_mono(path: Path, sample_rate: int):
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required for TTS timeline rendering") from exc
    audio, source_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if source_rate != sample_rate:
        try:
            import soxr
        except ImportError as exc:
            raise RuntimeError("soxr is required to resample TTS audio") from exc
        audio = soxr.resample(audio, source_rate, sample_rate)
    return audio.astype("float32"), sample_rate


def _validate_final_timeline(rows: list[dict], original_duration: float, working_speed: float, *, safety_gap: float = SAFETY_GAP_SECONDS) -> tuple[list[dict], str]:
    status = "VALID"
    for index, row in enumerate(rows):
        final_start = row["working_start_time"] * working_speed
        final_duration = row["processed_tts_duration"] * working_speed
        final_end = final_start + final_duration
        next_start = rows[index + 1]["original_start_time"] if index + 1 < len(rows) else original_duration
        if abs(final_start - row["original_start_time"]) > TIMELINE_TOLERANCE_SECONDS:
            status = "INVALID_FINAL_TIMELINE"
        elif final_end > next_start - safety_gap * working_speed + TIMELINE_TOLERANCE_SECONDS:
            status = "FINAL_VOICE_OVERFLOW" if index + 1 == len(rows) else "FINAL_OVERLAP"
        row.update({"final_start_time": final_start, "final_processed_duration": final_duration, "final_audio_end": final_end})
    return rows, status


def _atempo_file(ffmpeg: str, source: Path, output: Path, speed: float) -> None:
    _run_ffmpeg([ffmpeg, "-y", "-i", str(source), "-filter:a", build_atempo_chain(speed), str(output)], "TTS tempo adjustment failed")


def _run_ffmpeg(command: list[str], message: str) -> None:
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    output = Path(command[-1])
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"{message}: {proc.stderr[-1200:]}")


def _probe_duration(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0:
            value = float(proc.stdout.strip())
            return value if value > 0 else None
    except Exception:
        pass
    return None

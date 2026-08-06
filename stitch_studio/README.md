# Stitch AI Video Pipeline Studio

PySide6 desktop studio for a local video pipeline:

1. Paste a video URL and download it with `D:\Lazy-downloader`.
2. Save downloaded media into a SQLite library.
3. Open a video/audio item in the workspace.
4. Generate `.srt` with `faster-whisper`.
5. Import, edit, save, and export `.srt` files.
6. Generate VieNeu-TTS voiceover files from the latest SRT.

The active UI is `stitch_studio/ui_qt.py`, modeled after the provided studio
screens: Home, Downloads Queue, Video Library, Workspace, and Settings. The old
CustomTkinter prototype is kept as `stitch_studio/ui_full.py` for reference only.

## Run

```powershell
cd D:\nun-media\stitch_studio
py -3.11 -m pip install -r requirements.txt
py -3.11 app.py
```

Optional backends:

```powershell
py -3.11 -m pip install faster-whisper
```

Audio separation uses `UVR-MDX-NET-Inst_HQ_3.onnx` with an FFmpeg 95% instrumental + 5% original low-voice mix in an isolated DirectML
environment so its PyTorch dependencies do not affect TTS:

```powershell
powershell -ExecutionPolicy Bypass -File D:\nun-media\tools\setup_audio_separator.ps1
```

In the web editor, right-click the main video clip on the timeline and choose
`Giữ nguyên`, `Bỏ lời`, or `Bỏ nhạc nền`. The first processed choice creates
and caches both stems; later switching is immediate.

Hard-sub OCR uses VideoSubFinder to extract subtitle frames, then RapidVideOCR
to generate SRT. Keep the lightweight VideoSubFinder bundle at the default
path, or point the app to a custom location with `VIDEOSUBFINDER_ROOT`:

```powershell
D:\nun-media\tools\videosubfinder\windows\VideoSubFinderWXW.exe
```

Install the Python dependencies in the hard-sub Python environment, including
`rapid_videocr`. A full VSE checkout is still accepted as a legacy fallback via
`VSE_ROOT`, but it is not required for packaged builds.

Default packaged hard-sub layout:

```text
D:\nun-media\tools\videosubfinder\windows\VideoSubFinderWXW.exe
D:\nun-media\tools\hardsub-ocr-env\Scripts\python.exe
```

VieNeu-TTS can be used either by installing `vieneu` or by keeping the cloned
source at:

```text
D:\nun-media\VieNeu-TTS-src
```

The app automatically adds `D:\nun-media\VieNeu-TTS-src\src` to `sys.path`
before loading VieNeu.

OmniVoice Auto Voice, Voice Design, and Voice Clone are available in the web
studio when the cloned source and its isolated environment are present at:

```text
D:\nun-media\OmniVoice-src
D:\nun-media\OmniVoice-src\.venv-run\Scripts\python.exe
```

Choose `Auto Voice` to let the model select a voice, `Voice Design` to combine
the built-in gender, age, pitch, whisper, English-accent, and Chinese-dialect
attributes, or `Voice Clone` to upload a clear 3–10 second reference recording.
When a clone transcript is empty, Stitch transcribes the reference with its
existing `faster-whisper` service before starting OmniVoice; the OmniVoice
worker never loads a second Whisper model. Inference steps, speed, guidance,
prompt/output processing, temperatures, penalties, and long-text chunking are
configurable in the web studio. The worker loads OmniVoice once per SRT job and
reuses a single clone prompt for every subtitle segment. The first run downloads
the configured `k2-fsa/OmniVoice` checkpoint unless `OMNIVOICE_MODEL` points to
a local model directory. Override the worker interpreter with
`OMNIVOICE_PYTHON` when needed.

## Current MVP Scope

- Download jobs run in a background thread.
- Library metadata is stored at `D:\nun-media\stitch_studio\workspace\app_library.sqlite3`.
- Downloaded media is stored under `D:\nun-media\stitch_studio\workspace\downloads`.
- Generated SRT/TTS assets are stored under `D:\nun-media\stitch_studio\workspace\outputs`.
- Video preview uses Qt Multimedia (`QMediaPlayer` + `QVideoWidget`) for native
  audio/video playback.
- VieNeu-TTS exports one `.wav` per SRT segment, a `manifest.json`, and a merged
  `voiceover.wav`.
- `Adaptive Timeline Fit` is the single timing pipeline for VieNeu, CapCut, and
  OmniVoice. It measures original TTS WAVs, starts at the original 1.0x
  timeline, and automatically selects the smallest necessary stretch down to
  0.7x. Remaining long segments receive pitch-preserving local tempo adjustment
  up to 1.30x. Export is blocked when `TEXT_TOO_LONG` or overlap remains. The
  merged working WAV is globally restored to the original timeline, normalized
  to the exact target sample count, validated again, and muxed directly with
  the unchanged source video. Original segment WAVs are cached by text,
  voice/model, language, and rate so timing-only reruns do not call TTS again.

## Next Steps

- Add real download progress streaming from Lazy-downloader.
- Add CapCut STT.
- Add embedded video preview or external player integration.

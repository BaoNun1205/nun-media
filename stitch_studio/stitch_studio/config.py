from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = APP_ROOT / "workspace"
DOWNLOADS_DIR = WORKSPACE_ROOT / "downloads"
OUTPUTS_DIR = WORKSPACE_ROOT / "outputs"
MODELS_DIR = WORKSPACE_ROOT / "models"
DB_PATH = WORKSPACE_ROOT / "app_library.sqlite3"
DOUYIN_COOKIE_PATH = WORKSPACE_ROOT / "douyin_cookie.txt"
DOUYIN_DOWNLOADER_CONFIG_PATH = WORKSPACE_ROOT / "douyin_downloader_config.json"

LAZY_DOWNLOADER_ROOT = Path("D:/Lazy-downloader")
LAZY_DOWNLOADER_CLI = LAZY_DOWNLOADER_ROOT / "dist" / "cli.js"
LUX_CLI = REPO_ROOT / "tools" / "lux" / "lux.exe"
DOUYIN_DOWNLOADER_ROOT = REPO_ROOT / "tools" / "douyin-downloader"
DOUYIN_DOWNLOADER_PYTHON = DOUYIN_DOWNLOADER_ROOT / ".venv" / "Scripts" / "python.exe"
VIENEU_SRC = REPO_ROOT / "VieNeu-TTS-src" / "src"
CAPCUT_TTS_ROOT = REPO_ROOT / "capcut-tts-api"
VIDEOSUBFINDER_ROOT = REPO_ROOT / "tools" / "videosubfinder"
HARDSUB_PYTHON = REPO_ROOT / "tools" / "hardsub-ocr-env" / "Scripts" / "python.exe"
VSE_ROOT = REPO_ROOT / "tools" / "video-subtitle-extractor"
VSE_PYTHON = VSE_ROOT / ".venv" / "Scripts" / "python.exe"
VSR_ROOT = REPO_ROOT / "tools" / "video-subtitle-remover"
VSR_PYTHON = REPO_ROOT / "tools" / "vsr-env" / "Scripts" / "python.exe"
AUDIO_SEPARATOR_ROOT = REPO_ROOT / "tools" / "audio-separator-env"
AUDIO_SEPARATOR_EXE = AUDIO_SEPARATOR_ROOT / "Scripts" / "audio-separator.exe"


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = DB_PATH
    downloads_dir: Path = DOWNLOADS_DIR
    outputs_dir: Path = OUTPUTS_DIR
    models_dir: Path = MODELS_DIR
    douyin_cookie_path: Path = DOUYIN_COOKIE_PATH
    douyin_downloader_config_path: Path = DOUYIN_DOWNLOADER_CONFIG_PATH
    douyin_downloader_root: Path = DOUYIN_DOWNLOADER_ROOT
    douyin_downloader_python: Path = DOUYIN_DOWNLOADER_PYTHON
    lazy_downloader_cli: Path = LAZY_DOWNLOADER_CLI
    lux_cli: Path = LUX_CLI
    vieneu_src: Path = VIENEU_SRC
    capcut_tts_root: Path = CAPCUT_TTS_ROOT
    videosubfinder_root: Path = VIDEOSUBFINDER_ROOT
    hardsub_python: Path = HARDSUB_PYTHON
    vse_root: Path = VSE_ROOT
    vse_python: Path = VSE_PYTHON
    vsr_root: Path = VSR_ROOT
    vsr_python: Path = VSR_PYTHON
    audio_separator_root: Path = AUDIO_SEPARATOR_ROOT
    audio_separator_exe: Path = AUDIO_SEPARATOR_EXE


def ensure_dirs(config: AppConfig) -> None:
    config.downloads_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    config.models_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    config.douyin_downloader_config_path.parent.mkdir(parents=True, exist_ok=True)

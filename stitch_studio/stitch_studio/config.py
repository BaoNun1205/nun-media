from __future__ import annotations

import os
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


def _environment_value(name: str) -> str:
    """Read a process variable first, then the repository's ignored .env file."""
    value = os.getenv(name)
    if value is not None:
        return value.strip()
    env_path = REPO_ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, candidate = line.split("=", 1)
            if key.strip() == name:
                candidate = candidate.strip()
                if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
                    candidate = candidate[1:-1]
                return candidate.strip()
    except OSError:
        pass
    return ""


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = DB_PATH
    downloads_dir: Path = DOWNLOADS_DIR
    outputs_dir: Path = OUTPUTS_DIR
    models_dir: Path = MODELS_DIR
    douyin_cookie_path: Path = DOUYIN_COOKIE_PATH
    gemini_api_key_path: Path = WORKSPACE_ROOT / "gemini_api_key.txt"
    pexels_api_key_path: Path = WORKSPACE_ROOT / "pexels_api_key.txt"
    openverse_client_id_path: Path = WORKSPACE_ROOT / "openverse_client_id.txt"
    openverse_client_secret_path: Path = WORKSPACE_ROOT / "openverse_client_secret.txt"
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
    # A deployment environment variable is the fallback; Settings can save an
    # application-local key without ever returning it to the frontend.
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "").strip()
    openverse_client_id: str = _environment_value("OPENVERSE_CLIENT_ID")
    openverse_client_secret: str = _environment_value("OPENVERSE_CLIENT_SECRET")


def ensure_dirs(config: AppConfig) -> None:
    config.downloads_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    config.models_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    config.douyin_downloader_config_path.parent.mkdir(parents=True, exist_ok=True)

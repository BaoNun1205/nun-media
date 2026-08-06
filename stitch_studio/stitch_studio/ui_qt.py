from __future__ import annotations

import os
import queue
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, ensure_dirs
from .models import SubtitleSegment, VideoItem
from .services import DownloaderService, TranscriptionService, VieneuTtsService
from .srt import read_srt, seconds_to_srt_time, write_srt
from .storage import Storage
from .theme import APP_THEME, build_stylesheet


class TaskRunner(QThread):
    progress = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[str], None]], Any]):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.finished_ok.emit(self.fn(lambda message: self.progress.emit(message)))
        except Exception as exc:
            self.failed.emit(str(exc))


class StitchQtApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stitch AI Video Pipeline Studio")
        self.resize(1500, 900)
        self.setMinimumSize(1180, 740)

        self.config_obj = AppConfig()
        ensure_dirs(self.config_obj)
        self.storage = Storage(self.config_obj.db_path)
        self.downloader = DownloaderService(self.config_obj, self.storage)
        self.transcriber = TranscriptionService(self.config_obj, self.storage)
        self.tts = VieneuTtsService(self.config_obj, self.storage)

        self.selected_video: VideoItem | None = None
        self.tasks: list[TaskRunner] = []
        self.jobs: list[dict[str, Any]] = []
        self.latest_status = "Ready"
        self.voice_values = ["default"]

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.9)
        self.player.setAudioOutput(self.audio)
        self.player.durationChanged.connect(self._media_duration_changed)
        self.player.positionChanged.connect(self._media_position_changed)
        self.player.playbackStateChanged.connect(self._media_state_changed)

        self._build_ui()
        self._apply_style()
        self.show_home()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.player.stop()
        self.storage.close()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(252)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(20, 24, 20, 20)
        side.setSpacing(8)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(6)
        brand_row = QHBoxLayout()
        brand = QLabel("Stitch Studio")
        brand.setObjectName("Brand")
        version = QLabel("v2.4.1")
        version.setObjectName("VersionBadge")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        brand_row.addWidget(version)
        subtitle = QLabel("AI video pipeline")
        subtitle.setObjectName("Muted")
        brand_box.addLayout(brand_row)
        brand_box.addWidget(subtitle)
        side.addLayout(brand_box)
        side.addSpacing(28)

        self.nav_home = self._nav_button("Home", self.show_home)
        self.nav_downloads = self._nav_button("Downloads", self.show_downloads)
        self.nav_library = self._nav_button("Library", self.show_library)
        side.addWidget(self.nav_home)
        side.addWidget(self.nav_downloads)
        side.addWidget(self.nav_library)
        side.addStretch(1)
        self.nav_settings = self._nav_button("Settings", self.show_settings)
        side.addWidget(self.nav_settings)
        root_layout.addWidget(self.sidebar)

        main = QWidget()
        main.setObjectName("MainArea")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("Topbar")
        topbar.setFixedHeight(72)
        top = QHBoxLayout(topbar)
        top.setContentsMargins(24, 0, 24, 0)
        top.setSpacing(10)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        self.header_title = QLabel("AI Video Processor")
        self.header_title.setObjectName("HeaderTitle")
        self.header_subtitle = QLabel("Download, transcribe, edit subtitles, and generate voiceover")
        self.header_subtitle.setObjectName("HeaderSubtitle")
        title_stack.addWidget(self.header_title)
        title_stack.addWidget(self.header_subtitle)
        top.addLayout(title_stack)
        divider = QLabel("|")
        divider.setObjectName("Muted")
        top.addSpacing(10)
        top.addWidget(divider)
        top.addSpacing(10)
        self.header_library = QPushButton("Library")
        self.header_library.setObjectName("TopLink")
        self.header_library.clicked.connect(self.show_library)
        self.header_project = QPushButton("Project Alpha")
        self.header_project.setObjectName("TopLink")
        self.header_project.clicked.connect(self.show_workspace)
        top.addWidget(self.header_library)
        top.addWidget(self.header_project)
        top.addStretch(1)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search library or project...")
        self.search_entry.setFixedWidth(320)
        top.addWidget(self.search_entry)
        main_layout.addWidget(topbar)

        self.pages = QStackedWidget()
        main_layout.addWidget(self.pages, 1)
        self.status = QLabel("Ready")
        self.status.setObjectName("Status")
        self.status.setFixedHeight(32)
        self.status.setContentsMargins(24, 0, 24, 0)
        main_layout.addWidget(self.status)
        root_layout.addWidget(main, 1)

        self.home_page = self._build_home_page()
        self.downloads_page = self._build_downloads_page()
        self.library_page = self._build_library_page()
        self.workspace_page = self._build_workspace_page()
        self.settings_page = self._build_settings_page()
        for page in [self.home_page, self.downloads_page, self.library_page, self.workspace_page, self.settings_page]:
            self.pages.addWidget(page)

    def _nav_button(self, text: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setMinimumHeight(42)
        button.clicked.connect(callback)
        return button

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        layout = QGridLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        acquire = self._panel("Acquire Source Media")
        acquire_layout = QVBoxLayout(acquire)
        acquire_layout.setContentsMargins(0, 0, 0, 0)
        acquire_layout.setSpacing(0)
        acquire_layout.addWidget(self._panel_title("ACQUIRE SOURCE MEDIA"))
        acquire_body = QHBoxLayout()
        acquire_body.setContentsMargins(20, 18, 20, 20)
        acquire_body.setSpacing(12)
        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("Enter video URL (TikTok, YouTube, IG...)")
        self.url_entry.returnPressed.connect(self._download_from_home)
        download = QPushButton("Download")
        download.setObjectName("PrimaryButton")
        download.clicked.connect(self._download_from_home)
        acquire_body.addWidget(self.url_entry, 1)
        acquire_body.addWidget(download)
        acquire_layout.addLayout(acquire_body)
        layout.addWidget(acquire, 0, 0)

        status_panel = self._panel("System Status")
        status_outer = QVBoxLayout(status_panel)
        status_outer.setContentsMargins(0, 0, 0, 0)
        status_outer.setSpacing(0)
        status_outer.addWidget(self._panel_title("SYSTEM STATUS"))
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(20, 18, 20, 20)
        status_layout.setSpacing(12)
        self.total_label = QLabel("0")
        self.active_label = QLabel("0")
        self.srt_label = QLabel("0")
        for name, label in [("Videos", self.total_label), ("Active Jobs", self.active_label), ("SRT Ready", self.srt_label)]:
            status_layout.addWidget(self._metric_card(name, label))
        status_outer.addLayout(status_layout)
        layout.addWidget(status_panel, 0, 1)

        recent_panel = self._panel("Recent Outputs")
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(0)
        recent_layout.addWidget(self._panel_title("RECENT OUTPUTS", "View All"))
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(lambda item: self._open_video_from_item(item))
        recent_layout.addWidget(self.recent_list)
        layout.addWidget(recent_panel, 1, 0)

        log_panel = self._panel("System Log")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        log_layout.addWidget(self._panel_title("SYSTEM LOG"))
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlainText("Ready: Qt studio initialized")
        log_layout.addWidget(self.log_box)
        layout.addWidget(log_panel, 1, 1)
        layout.setColumnStretch(0, 3)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(1, 1)
        return page

    def _build_downloads_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("Downloads Queue")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Manage active and pending AI processing tasks")
        subtitle.setObjectName("Muted")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        new_job = QPushButton("New Job")
        new_job.setObjectName("PrimaryButton")
        new_job.clicked.connect(self.show_home)
        header.addLayout(title_box)
        header.addStretch(1)
        header.addWidget(new_job)
        layout.addLayout(header)
        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(["Task", "Kind", "Status", "Progress", "Detail"])
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.setShowGrid(False)
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.jobs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.jobs_table, 1)
        return page

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("Video Library")
        title.setObjectName("PageTitle")
        import_btn = QPushButton("Import Video")
        import_btn.setObjectName("PrimaryButton")
        import_btn.clicked.connect(self._import_local)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_library)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(import_btn)
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        controls = QFrame()
        controls.setObjectName("ControlBar")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 12, 16, 12)
        controls_layout.setSpacing(12)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Search library...")
        self.library_search.textChanged.connect(self.refresh_library)
        self.source_filter = QComboBox()
        self.source_filter.addItems(["Source: All", "Local", "TikTok", "YouTube"])
        self.source_filter.currentTextChanged.connect(self.refresh_library)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Status: All", "SRT Ready", "TTS Ready", "Pending"])
        self.status_filter.currentTextChanged.connect(self.refresh_library)
        controls_layout.addWidget(self.library_search, 1)
        controls_layout.addWidget(self.source_filter)
        controls_layout.addWidget(self.status_filter)
        layout.addWidget(controls)
        self.library_table = QTableWidget(0, 6)
        self.library_table.setHorizontalHeaderLabels(["Title", "Source", "Duration", "Size", "Status", "Path"])
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.setAlternatingRowColors(True)
        self.library_table.setShowGrid(False)
        self.library_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.library_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.library_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.library_table.itemDoubleClicked.connect(lambda _item: self._select_library_row())
        layout.addWidget(self.library_table, 1)
        return page

    def _build_workspace_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        project_panel = self._panel("Project Files")
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(0)
        project_layout.addWidget(self._panel_title("Project Files", "+"))
        self.project_files = QListWidget()
        self.project_files.setObjectName("ProjectFiles")
        project_layout.addWidget(self.project_files)
        project_panel.setMinimumWidth(270)
        splitter.addWidget(project_panel)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoSurface")
        self.video_widget.setMinimumHeight(300)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player.setVideoOutput(self.video_widget)
        center_layout.addWidget(self.video_widget, 3)

        controls = QFrame()
        controls.setObjectName("ControlBar")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(14, 10, 14, 10)
        controls_layout.setSpacing(10)
        self.back_btn = QPushButton("Back")
        self.play_btn = QPushButton("Play")
        self.forward_btn = QPushButton("Forward")
        for button in [self.back_btn, self.play_btn, self.forward_btn]:
            button.setObjectName("TransportButton")
        self.back_btn.clicked.connect(lambda: self._seek_media(-5000))
        self.play_btn.clicked.connect(self._toggle_media)
        self.forward_btn.clicked.connect(lambda: self._seek_media(5000))
        self.time_label = QLabel("00:00")
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.duration_label = QLabel("--:--")
        controls_layout.addWidget(self.back_btn)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.forward_btn)
        controls_layout.addWidget(self.time_label)
        controls_layout.addWidget(self.position_slider, 1)
        controls_layout.addWidget(self.duration_label)
        center_layout.addWidget(controls)

        subtitle_panel = self._panel("Subtitle Editor")
        subtitle_layout = QVBoxLayout(subtitle_panel)
        subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_layout.setSpacing(0)
        subtitle_head = self._panel_title("Subtitle Editor")
        subtitle_actions = QHBoxLayout()
        subtitle_actions.setContentsMargins(12, 8, 12, 8)
        subtitle_actions.setSpacing(8)
        find = QPushButton("Find")
        import_srt = QPushButton("Import SRT")
        save_edits = QPushButton("Save Edits")
        export_srt = QPushButton("Export SRT")
        export_srt.setObjectName("PrimarySoftButton")
        import_srt.clicked.connect(self._import_srt)
        save_edits.clicked.connect(self._save_srt_edits)
        export_srt.clicked.connect(self._export_latest_srt)
        subtitle_actions.addStretch(1)
        subtitle_actions.addWidget(find)
        subtitle_actions.addWidget(import_srt)
        subtitle_actions.addWidget(save_edits)
        subtitle_actions.addWidget(export_srt)
        subtitle_bar = QFrame()
        subtitle_bar.setObjectName("PanelHeader")
        subtitle_bar_layout = QHBoxLayout(subtitle_bar)
        subtitle_bar_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_bar_layout.addWidget(subtitle_head)
        subtitle_bar_layout.addLayout(subtitle_actions)
        subtitle_layout.addWidget(subtitle_bar)
        self.subtitle_table = QTableWidget(0, 3)
        self.subtitle_table.setHorizontalHeaderLabels(["Start", "End", "Text"])
        self.subtitle_table.verticalHeader().setVisible(False)
        self.subtitle_table.setAlternatingRowColors(True)
        self.subtitle_table.setShowGrid(False)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        subtitle_layout.addWidget(self.subtitle_table, 1)
        center_layout.addWidget(subtitle_panel, 2)
        splitter.addWidget(center)

        tools = self._panel("Workspace Tools")
        tools.setMinimumWidth(320)
        tools.setMaximumWidth(380)
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(0)
        self.tool_tabs = QTabWidget()
        self.tool_tabs.setObjectName("ToolTabs")
        srt_tab = QWidget()
        srt_layout = QVBoxLayout(srt_tab)
        srt_layout.setContentsMargins(16, 16, 16, 16)
        srt_layout.setSpacing(10)
        srt_layout.addWidget(self._field_label("Subtitle Source"))
        self.srt_source_combo = QComboBox()
        self.srt_source_combo.addItem("Audio Speech (Whisper)", "audio")
        self.srt_source_combo.addItem("Hard-sub OCR (RapidVideOCR)", "hardsub")
        srt_layout.addWidget(self.srt_source_combo)
        srt_layout.addWidget(self._field_label("Target Track"))
        track_combo = QComboBox()
        track_combo.addItems(["Audio Track 1 (Mix)", "Audio Track 2 (Dialogue)"])
        srt_layout.addWidget(track_combo)
        srt_layout.addSpacing(10)
        srt_layout.addWidget(self._field_label("Transcription Model"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"])
        srt_layout.addWidget(self.model_combo)
        hint = QLabel("Start with base/small for quick tests. Use large-v3 for better accuracy when you can wait.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        srt_layout.addWidget(hint)
        srt_layout.addWidget(self._field_label("Language"))
        self.language_entry = QLineEdit("vi")
        srt_layout.addWidget(self.language_entry)
        srt_layout.addWidget(self._field_label("Compute Mode"))
        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu", "cuda", "auto"])
        srt_layout.addWidget(self.device_combo)
        srt_layout.addWidget(self._field_label("Hard-sub OCR Mode"))
        self.hardsub_mode_combo = QComboBox()
        self.hardsub_mode_combo.addItems(["fast", "auto", "accurate"])
        srt_layout.addWidget(self.hardsub_mode_combo)
        hardsub_hint = QLabel("Hard-sub OCR uses VideoSubFinder frames plus RapidVideOCR SRT generation.")
        hardsub_hint.setObjectName("Hint")
        hardsub_hint.setWordWrap(True)
        srt_layout.addWidget(hardsub_hint)
        srt_layout.addStretch(1)
        self.generate_srt_btn = QPushButton("Generate Subtitles")
        self.generate_srt_btn.setObjectName("PrimaryButton")
        self.generate_srt_btn.clicked.connect(self._generate_srt)
        srt_layout.addWidget(self.generate_srt_btn)

        tts_tab = QWidget()
        tts_layout = QVBoxLayout(tts_tab)
        tts_layout.setContentsMargins(16, 16, 16, 16)
        tts_layout.setSpacing(10)
        self.latest_srt_label = QLabel("No SRT yet")
        self.latest_srt_label.setObjectName("Hint")
        self.latest_tts_label = QLabel("No voiceover yet")
        self.latest_tts_label.setObjectName("Hint")
        tts_layout.addWidget(self._field_label("Source SRT"))
        tts_layout.addWidget(self.latest_srt_label)
        tts_layout.addSpacing(10)
        tts_layout.addWidget(self._field_label("VieNeu TTS Voice"))
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(self.voice_values)
        tts_layout.addWidget(self.voice_combo)
        refresh_voices = QPushButton("Refresh Voices")
        refresh_voices.clicked.connect(self._refresh_voices)
        tts = QPushButton("TTS From Latest SRT")
        tts.setObjectName("PrimaryButton")
        tts.clicked.connect(self._tts_latest_srt)
        tts_layout.addWidget(refresh_voices)
        tts_layout.addSpacing(8)
        tts_layout.addWidget(self._field_label("Latest Voice Output"))
        tts_layout.addWidget(self.latest_tts_label)
        tts_layout.addStretch(1)
        tts_layout.addWidget(tts)
        self.tool_tabs.addTab(srt_tab, "Generate SRT")
        self.tool_tabs.addTab(tts_tab, "Text To Speech")
        tools_layout.addWidget(self.tool_tabs)
        splitter.addWidget(tools)
        splitter.setSizes([280, 880, 350])
        layout.addWidget(splitter)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        paths = QTextEdit()
        paths.setReadOnly(True)
        paths.setText(
            "\n".join(
                [
                    f"Database: {self.config_obj.db_path}",
                    f"Downloads: {self.config_obj.downloads_dir}",
                    f"Outputs: {self.config_obj.outputs_dir}",
                    f"Lazy-downloader: {self.config_obj.lazy_downloader_cli}",
                    f"VieNeu source: {self.config_obj.vieneu_src}",
                    f"VSE hard-sub extractor: {self.config_obj.vse_root}",
                ]
            )
        )
        layout.addWidget(paths)
        return page

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setProperty("title", title)
        return panel

    def _metric_card(self, title: str, value: QLabel) -> QFrame:
        card = QFrame()
        card.setObjectName("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        value.setObjectName("BigNumber")
        layout.addWidget(title_label)
        layout.addWidget(value)
        return card

    def _panel_title(self, title: str, action: str = "") -> QFrame:
        frame = QFrame()
        frame.setObjectName("PanelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("PanelHeaderText")
        layout.addWidget(label)
        layout.addStretch(1)
        if action:
            action_label = QLabel(action)
            action_label.setObjectName("Muted")
            layout.addWidget(action_label)
        return frame

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _apply_style(self) -> None:
        app = QApplication.instance()
        if app:
            app.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(build_stylesheet(APP_THEME))

    def _set_page(self, page: QWidget, title: str, active: QPushButton) -> None:
        self.header_title.setText(title)
        self.pages.setCurrentWidget(page)
        for button in [self.nav_home, self.nav_downloads, self.nav_library, self.nav_settings]:
            button.setProperty("selected", button is active)
            button.style().unpolish(button)
            button.style().polish(button)
        self._update_counts()

    def show_home(self) -> None:
        self.refresh_recent()
        self._set_page(self.home_page, "AI Video Processor", self.nav_home)

    def show_downloads(self) -> None:
        self.refresh_jobs()
        self._set_page(self.downloads_page, "AI Video Processor", self.nav_downloads)

    def show_library(self) -> None:
        self.refresh_library()
        self._set_page(self.library_page, "AI Video Processor", self.nav_library)

    def show_workspace(self) -> None:
        if not self.selected_video:
            videos = self.storage.list_videos()
            self.selected_video = videos[0] if videos else None
        self.refresh_workspace()
        self._set_page(self.workspace_page, "Project Alpha", self.nav_library)

    def show_settings(self) -> None:
        self._set_page(self.settings_page, "Settings", self.nav_settings)

    def _update_counts(self) -> None:
        videos = self.storage.list_videos()
        self.total_label.setText(str(len(videos)))
        self.active_label.setText(str(sum(1 for job in self.jobs if job["status"] in {"queued", "running"})))
        self.srt_label.setText(str(sum(1 for video in videos if self.storage.latest_asset(video.id, "srt"))))
        self.status.setText(self.latest_status)

    def _log(self, message: str) -> None:
        self.latest_status = message
        self.status.setText(message)
        if hasattr(self, "log_box"):
            self.log_box.appendPlainText(message)

    def refresh_recent(self) -> None:
        self.recent_list.clear()
        for video in self.storage.list_videos()[:12]:
            item = QListWidgetItem(f"{video.title}\n{video.source or 'local'}  {self._duration_label(video.duration_ms)}")
            item.setData(Qt.UserRole, video.id)
            self.recent_list.addItem(item)

    def refresh_library(self) -> None:
        videos = self.storage.list_videos()
        query = self.library_search.text().strip().lower() if hasattr(self, "library_search") else ""
        source_filter = self.source_filter.currentText() if hasattr(self, "source_filter") else "Source: All"
        status_filter = self.status_filter.currentText() if hasattr(self, "status_filter") else "Status: All"
        filtered: list[VideoItem] = []
        for video in videos:
            srt = self.storage.latest_asset(video.id, "srt")
            tts = self.storage.latest_asset(video.id, "tts")
            if query and query not in video.title.lower() and query not in str(video.path).lower():
                continue
            if source_filter != "Source: All" and source_filter.replace("Source: ", "").lower() not in (video.source or "local").lower():
                continue
            if status_filter == "SRT Ready" and not srt:
                continue
            if status_filter == "TTS Ready" and not tts:
                continue
            if status_filter == "Pending" and (srt or tts):
                continue
            filtered.append(video)
        videos = filtered
        self.library_table.setRowCount(len(videos))
        for row, video in enumerate(videos):
            self.library_table.setRowHeight(row, 58)
            srt = self.storage.latest_asset(video.id, "srt")
            tts = self.storage.latest_asset(video.id, "tts")
            values = [
                video.title,
                video.source or "local",
                self._duration_label(video.duration_ms),
                self._size_label(video.size_bytes),
                "SRT  TTS" if srt and tts else ("SRT" if srt else ("TTS" if tts else video.status)),
                str(video.path),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, video.id)
                self.library_table.setItem(row, col, item)
        self._update_counts()

    def refresh_jobs(self) -> None:
        self.jobs_table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            self.jobs_table.setRowHeight(row, 56)
            for col, key in enumerate(["title", "kind", "status", "progress", "detail"]):
                value = f"{int(job[key] * 100)}%" if key == "progress" else str(job[key])
                self.jobs_table.setItem(row, col, QTableWidgetItem(value))

    def refresh_workspace(self) -> None:
        self.project_files.clear()
        if not self.selected_video:
            self.player.stop()
            self.subtitle_table.setRowCount(0)
            return

        self.project_files.addItem(f"{self.selected_video.path.name}\n{self._size_label(self.selected_video.size_bytes)}")
        for asset in self.storage.list_assets(self.selected_video.id):
            self.project_files.addItem(f"{asset.path.name}\n{asset.kind.upper()}  {asset.engine}")

        if self.selected_video.path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(self.selected_video.path)))
        self._load_latest_segments()
        srt = self.storage.latest_asset(self.selected_video.id, "srt")
        tts = self.storage.latest_asset(self.selected_video.id, "tts")
        if hasattr(self, "latest_srt_label"):
            self.latest_srt_label.setText(srt.path.name if srt and srt.path.exists() else "No SRT yet")
        if hasattr(self, "latest_tts_label"):
            self.latest_tts_label.setText(tts.path.name if tts and tts.path.exists() else "No voiceover yet")

    def _open_video_from_item(self, item: QListWidgetItem) -> None:
        video = self.storage.get_video(int(item.data(Qt.UserRole)))
        if video:
            self.selected_video = video
            self.show_workspace()

    def _select_library_row(self) -> None:
        row = self.library_table.currentRow()
        if row < 0:
            return
        item = self.library_table.item(row, 0)
        if not item:
            return
        video = self.storage.get_video(int(item.data(Qt.UserRole)))
        if video:
            self.selected_video = video
            self.show_workspace()

    def _download_from_home(self) -> None:
        url = self.url_entry.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Paste a video URL first.")
            return
        self._add_job("download", url, "Queued from Home")

        def task(progress: Callable[[str], None]) -> list[int]:
            return self.downloader.download_url(url, progress)

        self._run_task(task, "download", on_done=lambda _result: (self.refresh_library(), self.refresh_recent()))
        self.show_downloads()

    def _import_local(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import video or audio",
            "",
            "Media files (*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a *.aac *.flac);;All files (*.*)",
        )
        if not paths:
            return
        ids = self.storage.import_local_files(Path(path) for path in paths)
        self._log(f"Imported {len(ids)} file(s).")
        self.refresh_library()

    def _generate_srt(self) -> None:
        if not self.selected_video:
            QMessageBox.warning(self, "No video", "Select a video first.")
            return
        if not self.selected_video.path.exists():
            QMessageBox.critical(self, "Missing media", f"Video file not found:\n{self.selected_video.path}")
            return
        model = self.model_combo.currentText()
        device = self.device_combo.currentText()
        language = self.language_entry.text().strip()
        source = self.srt_source_combo.currentData() if hasattr(self, "srt_source_combo") else "audio"
        hardsub_mode = self.hardsub_mode_combo.currentText() if hasattr(self, "hardsub_mode_combo") else "fast"
        detail = f"RapidVideOCR {hardsub_mode}" if source == "hardsub" else f"Model {model}"
        self._add_job("srt", f"Generate SRT: {self.selected_video.title}", detail)

        def task(progress: Callable[[str], None]) -> Path:
            if source == "hardsub":
                return self.transcriber.generate_hardsub_srt(
                    self.selected_video,
                    language="vi" if language == "auto" else language,
                    mode=hardsub_mode,
                    progress=progress,
                )
            return self.transcriber.generate_srt(
                self.selected_video,
                model_name=model,
                device=device,
                language=language,
                progress=progress,
            )

        self._run_task(task, "srt", on_done=lambda _result: self.refresh_workspace())

    def _tts_latest_srt(self) -> None:
        if not self.selected_video:
            QMessageBox.warning(self, "No video", "Select a video first.")
            return
        asset = self.storage.latest_asset(self.selected_video.id, "srt")
        if not asset or not asset.path.exists():
            QMessageBox.warning(self, "Missing SRT", "Generate or import an SRT before running TTS.")
            return
        voice = self.voice_combo.currentText()
        if voice == "default":
            voice = ""
        self._add_job("tts", f"VieNeu TTS: {self.selected_video.title}", "Reading subtitle segments")

        def task(progress: Callable[[str], None]) -> Path:
            return self.tts.synthesize_srt(self.selected_video, asset.path, voice=voice, progress=progress)

        self._run_task(task, "tts", on_done=lambda _result: self.refresh_workspace())

    def _refresh_voices(self) -> None:
        self._add_job("voices", "Refresh VieNeu voices", "Loading voices")

        def task(_progress: Callable[[str], None]) -> list[str]:
            voices = self.tts.list_voices()
            return ["default"] + [voice_id for _, voice_id in voices]

        def done(values: list[str]) -> None:
            self.voice_values = values or ["default"]
            self.voice_combo.clear()
            self.voice_combo.addItems(self.voice_values)

        self._run_task(task, "voices", on_done=done)

    def _latest_srt_asset(self):
        if not self.selected_video:
            return None
        return self.storage.latest_asset(self.selected_video.id, "srt")

    def _load_latest_segments(self) -> None:
        asset = self._latest_srt_asset()
        if not asset or not asset.path.exists():
            self.subtitle_table.setRowCount(0)
            return
        segments = read_srt(asset.path)
        self.subtitle_table.setRowCount(len(segments))
        for row, segment in enumerate(segments):
            self.subtitle_table.setRowHeight(row, 72)
            start = QTableWidgetItem(seconds_to_srt_time(segment.start))
            end = QTableWidgetItem(seconds_to_srt_time(segment.end))
            text = QTableWidgetItem(segment.text)
            start.setData(Qt.UserRole, segment)
            self.subtitle_table.setItem(row, 0, start)
            self.subtitle_table.setItem(row, 1, end)
            self.subtitle_table.setItem(row, 2, text)

    def _export_latest_srt(self) -> None:
        asset = self._latest_srt_asset()
        if not asset or not asset.path.exists():
            QMessageBox.warning(self, "Missing SRT", "Generate or import an SRT before exporting.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "Export SRT", asset.path.name, "SRT subtitles (*.srt);;All files (*.*)")
        if not target:
            return
        shutil.copyfile(asset.path, target)
        self._log(f"SRT exported: {target}")

    def _import_srt(self) -> None:
        if not self.selected_video:
            QMessageBox.warning(self, "No video", "Select a video before importing SRT.")
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Import SRT", "", "SRT subtitles (*.srt);;All files (*.*)")
        if not selected:
            return
        source = Path(selected)
        segments = read_srt(source)
        if not segments:
            QMessageBox.warning(self, "Invalid SRT", "This file does not contain readable subtitle segments.")
            return
        target_dir = self.config_obj.outputs_dir / f"video_{self.selected_video.id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"imported_{source.name}"
        shutil.copyfile(source, target)
        self.storage.add_asset(
            video_id=self.selected_video.id,
            kind="srt",
            path=target,
            engine="manual-import",
            metadata={"segments": len(segments), "source": str(source)},
        )
        self.refresh_workspace()
        self._log(f"SRT imported: {target}")

    def _save_srt_edits(self) -> None:
        asset = self._latest_srt_asset()
        if not asset or not asset.path.exists():
            QMessageBox.warning(self, "Missing SRT", "Generate or import an SRT before saving edits.")
            return
        original = read_srt(asset.path)
        edited: list[SubtitleSegment] = []
        for row, segment in enumerate(original):
            text_item = self.subtitle_table.item(row, 2)
            text = text_item.text().strip() if text_item else segment.text
            edited.append(SubtitleSegment(segment.index, segment.start, segment.end, text))
        write_srt(edited, asset.path)
        self._log(f"SRT edits saved: {asset.path}")

    def _toggle_media(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_media(self, delta_ms: int) -> None:
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + delta_ms)))

    def _media_duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, max(0, duration))
        self.duration_label.setText(self._seconds_label(duration / 1000))

    def _media_position_changed(self, position: int) -> None:
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
        self.time_label.setText(self._seconds_label(position / 1000))

    def _media_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_btn.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")

    def _add_job(self, kind: str, title: str, detail: str) -> None:
        self.jobs.append({"kind": kind, "title": title, "status": "queued", "progress": 0.0, "detail": detail})
        self.refresh_jobs()
        self._update_counts()

    def _run_task(self, fn: Callable[[Callable[[str], None]], Any], kind: str, on_done: Callable[[Any], None] | None = None) -> None:
        job = self.jobs[-1] if self.jobs else None
        runner = TaskRunner(fn)

        def progress(message: str) -> None:
            if job:
                job["status"] = "running"
                job["progress"] = max(float(job["progress"]), 0.35)
                job["detail"] = message
            self._log(message)
            self.refresh_jobs()

        def done(result: Any) -> None:
            if job:
                job["status"] = "completed"
                job["progress"] = 1.0
                job["detail"] = str(result)
            self._log(f"Completed {kind}: {result}")
            if on_done:
                on_done(result)
            self.refresh_jobs()
            self._update_counts()
            self.tasks = [task for task in self.tasks if task.isRunning()]

        def failed(message: str) -> None:
            if job:
                job["status"] = "error"
                job["detail"] = message
            self._log(f"Error: {message}")
            QMessageBox.critical(self, "Stitch Studio", message)
            self.refresh_jobs()
            self.tasks = [task for task in self.tasks if task.isRunning()]

        runner.progress.connect(progress)
        runner.finished_ok.connect(done)
        runner.failed.connect(failed)
        self.tasks.append(runner)
        runner.start()

    @staticmethod
    def _size_label(value: int | None) -> str:
        if not value:
            return "--"
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        unit = 0
        while size >= 1024 and unit < len(units) - 1:
            size /= 1024
            unit += 1
        return f"{size:.1f} {units[unit]}" if unit else f"{int(size)} B"

    @staticmethod
    def _duration_label(duration_ms: int | None) -> str:
        if not duration_ms:
            return "--:--"
        return StitchQtApp._seconds_label(duration_ms / 1000)

    @staticmethod
    def _seconds_label(value: float) -> str:
        total = max(0, int(value))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def main() -> None:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    app = QApplication(sys.argv)
    window = StitchQtApp()
    window.show()
    sys.exit(app.exec())

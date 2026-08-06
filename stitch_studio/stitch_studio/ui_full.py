from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Callable

import customtkinter as ctk

from .config import AppConfig, ensure_dirs
from .models import SubtitleSegment, VideoItem
from .services import DownloaderService, TranscriptionService, VieneuTtsService
from .srt import read_srt, seconds_to_srt_time, write_srt
from .storage import Storage


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#101010"
SIDEBAR = "#171717"
SURFACE = "#1e1e1e"
SURFACE_LOW = "#161616"
SURFACE_HIGH = "#2a2a2a"
BORDER = "#333842"
TEXT = "#e5e7eb"
MUTED = "#a3a7b3"
MUTED_DARK = "#69707f"
PRIMARY = "#3b82f6"
PRIMARY_SOFT = "#9bbcff"
SUCCESS = "#4edea3"
WARNING = "#f5b64c"
ERROR = "#ff9f99"


@dataclass
class JobRecord:
    id: int
    kind: str
    title: str
    status: str = "queued"
    progress: float = 0.0
    size_label: str = "--"
    speed_label: str = "--"
    eta_label: str = "--"
    detail: str = "Waiting in queue"
    created_at: float = field(default_factory=time.time)


class StitchStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("Stitch AI Video Pipeline Studio")
        self.geometry("1500x900")
        self.minsize(1180, 740)

        self.config_obj = AppConfig()
        ensure_dirs(self.config_obj)
        self.storage = Storage(self.config_obj.db_path)
        self.downloader = DownloaderService(self.config_obj, self.storage)
        self.transcriber = TranscriptionService(self.config_obj, self.storage)
        self.tts = VieneuTtsService(self.config_obj, self.storage)

        self.message_queue: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.selected_video: VideoItem | None = None
        self.current_view = "home"
        self.jobs: list[JobRecord] = []
        self.next_job_id = 1
        self.system_logs: list[tuple[str, str]] = [("Ready", "Studio initialized")]
        self.voice_values = ["default"]
        self.subtitle_textboxes: dict[int, ctk.CTkTextbox] = {}
        self.tools_mode = "srt"
        self.srt_model = "tiny"
        self.srt_device = "cpu"
        self.srt_language = "vi"
        self.tts_voice = "default"
        self.video_capture: Any | None = None
        self.video_after_id: str | None = None
        self.video_playing = False
        self.video_fps = 25.0
        self.video_duration_seconds = 0.0
        self.video_photo: Any | None = None
        self.video_frame_label: Any | None = None
        self.video_title_label: Any | None = None
        self.video_overlay_play: Any | None = None
        self.video_play_button: Any | None = None
        self.video_time_label: Any | None = None
        self.video_progress: Any | None = None
        self.video_preview_frame: Any | None = None
        self.ffplay_process: Any | None = None
        self.ffplay_hwnd: int | None = None
        self.ffplay_after_id: str | None = None
        self.ffplay_paused = False
        self.video_clock_start = 0.0
        self.video_clock_position = 0.0
        self.audio_data: Any | None = None
        self.audio_sample_rate = 0
        self.audio_source_path: Path | None = None
        self.audio_loaded = False

        self._build_shell()
        self._show_home()
        self.after(200, self._drain_messages)

    def destroy(self) -> None:
        self._stop_inline_video()
        self.storage.close()
        super().destroy()

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=260, fg_color=SIDEBAR, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 18))
        ctk.CTkLabel(brand, text="AI Studio", text_color=PRIMARY_SOFT, font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        ctk.CTkLabel(brand, text="v2.4.1", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(10, 0), pady=(6, 0))

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._nav("home", "Home", self._show_home)
        self._nav("downloads", "Downloads", self._show_downloads)
        self._nav("library", "Library", self._show_library)
        ctk.CTkFrame(self.sidebar, height=1, fg_color=BORDER).pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        self._nav("settings", "Settings", self._show_settings, side="bottom")

        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        self.topbar = ctk.CTkFrame(self.main, height=56, fg_color=SURFACE, corner_radius=0)
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(2, weight=1)
        self.header_title = ctk.CTkLabel(self.topbar, text="AI Video Processor", font=ctk.CTkFont(size=22, weight="bold"))
        self.header_title.grid(row=0, column=0, padx=(18, 18), sticky="w")
        ctk.CTkLabel(self.topbar, text="|", text_color=MUTED_DARK).grid(row=0, column=1, sticky="w")
        links = ctk.CTkFrame(self.topbar, fg_color="transparent")
        links.grid(row=0, column=2, sticky="w")
        ctk.CTkButton(links, text="Library", width=72, fg_color="transparent", hover_color=SURFACE_HIGH, command=self._show_library).pack(side="left")
        ctk.CTkButton(links, text="Project Alpha", width=120, fg_color="transparent", hover_color=SURFACE_HIGH, command=self._show_workspace).pack(side="left")
        self.search_entry = ctk.CTkEntry(self.topbar, width=230, placeholder_text="Search...")
        self.search_entry.grid(row=0, column=3, padx=(8, 18), sticky="e")

        self.content = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        self.content.grid(row=1, column=0, sticky="nsew")

        self.statusbar = ctk.CTkFrame(self.main, height=28, fg_color="#0d0d0d", corner_radius=0)
        self.statusbar.grid(row=2, column=0, sticky="ew")
        self.statusbar.grid_propagate(False)
        self.status_var = ctk.StringVar(value="Ready")
        self.disk_var = ctk.StringVar(value="Free Space: local workspace")
        self.speed_var = ctk.StringVar(value="Total Speed: --")
        ctk.CTkLabel(self.statusbar, textvariable=self.disk_var, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=(18, 20))
        ctk.CTkLabel(self.statusbar, textvariable=self.speed_var, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkLabel(self.statusbar, textvariable=self.status_var, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="right", padx=18)

    def _nav(self, key: str, text: str, command: Callable[[], None], side: str = "top") -> None:
        btn = ctk.CTkButton(self.sidebar, text=text, anchor="w", height=40, fg_color="transparent", hover_color=SURFACE_HIGH, text_color=MUTED, command=command)
        btn.pack(side=side, fill="x", padx=12, pady=4)
        self.nav_buttons[key] = btn

    def _set_active_nav(self, key: str) -> None:
        for name, btn in self.nav_buttons.items():
            btn.configure(fg_color=SURFACE_HIGH if name == key else "transparent", text_color=PRIMARY_SOFT if name == key else MUTED)

    def _clear_content(self, title: str, nav: str) -> None:
        self._stop_inline_video()
        self.header_title.configure(text=title)
        self.current_view = nav
        self._set_active_nav(nav if nav in self.nav_buttons else "library")
        for child in self.content.winfo_children():
            child.destroy()
        for i in range(8):
            self.content.grid_columnconfigure(i, weight=0)
            self.content.grid_rowconfigure(i, weight=0)
        self._update_status_stats()

    def _show_home(self) -> None:
        self._clear_content("AI Video Processor", "home")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_columnconfigure(1, weight=0)
        self.content.grid_rowconfigure(1, weight=1)

        top = self._panel(self.content)
        top.grid(row=0, column=0, sticky="ew", padx=(14, 2), pady=(14, 2))
        top.grid_columnconfigure(0, weight=1)
        self._section_title(top, "ACQUIRE SOURCE MEDIA").grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 8))
        self.url_entry = ctk.CTkEntry(top, height=42, placeholder_text="Enter Video URL (TikTok, YouTube, IG...)")
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=(18, 10), pady=(0, 18))
        ctk.CTkButton(top, text="PROCESS", width=150, height=42, font=ctk.CTkFont(size=12, weight="bold"), command=self._download_from_entry).grid(row=1, column=1, padx=(0, 18), pady=(0, 18))

        stats = self._panel(self.content, width=360)
        stats.grid(row=0, column=1, sticky="nsew", padx=(2, 14), pady=(14, 2))
        self._section_title(stats, "SYSTEM STATUS").pack(anchor="w", padx=18, pady=(16, 6))
        statrow = ctk.CTkFrame(stats, fg_color="transparent")
        statrow.pack(fill="x", padx=18)
        self._stat(statrow, "TOTAL PROCESSED", str(len(self.storage.list_videos()))).pack(side="left", expand=True, fill="x")
        self._stat(statrow, "ACTIVE", str(self._active_job_count()), PRIMARY).pack(side="left", expand=True, fill="x")
        self._stat(statrow, "STORAGE", "64%").pack(side="left", expand=True, fill="x")

        recent = self._panel(self.content)
        recent.grid(row=1, column=0, sticky="nsew", padx=(14, 2), pady=(2, 14))
        recent.grid_columnconfigure(0, weight=1)
        recent.grid_rowconfigure(1, weight=1)
        header = self._panel_header(recent, "RECENT OUTPUTS")
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(header, text="View All >", width=90, fg_color="transparent", hover_color=SURFACE_HIGH, command=self._show_library).pack(side="right", padx=10)
        card_grid = ctk.CTkScrollableFrame(recent, fg_color="transparent")
        card_grid.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        for col in range(3):
            card_grid.grid_columnconfigure(col, weight=1)
        self._populate_recent_cards(card_grid)

        right = self._panel(self.content, width=360)
        right.grid(row=1, column=1, sticky="nsew", padx=(2, 14), pady=(2, 14))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        self._panel_header(right, "SYSTEM LOG").grid(row=0, column=0, sticky="ew")
        log_body = ctk.CTkScrollableFrame(right, fg_color="transparent")
        log_body.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        for ts, msg in self.system_logs[-8:][::-1]:
            self._log_row(log_body, ts, msg)
        shortcut = ctk.CTkFrame(right, fg_color=SURFACE_LOW, border_width=1, border_color=BORDER, corner_radius=2)
        shortcut.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
        ctk.CTkLabel(shortcut, text="SHORTCUT", text_color=PRIMARY_SOFT, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(shortcut, text="Press CTRL+V in the URL field to queue a copied URL.", text_color=MUTED, wraplength=280).pack(anchor="w", padx=12, pady=(0, 10))

    def _show_downloads(self) -> None:
        self._clear_content("AI Video Processor", "downloads")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(2, weight=1)
        head = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Downloads Queue", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w", padx=28, pady=(22, 4))
        ctk.CTkLabel(head, text="Manage active and pending AI processing tasks", text_color=MUTED).grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))
        ctk.CTkButton(head, text=f"{self._active_job_count()} Active", width=120, fg_color="#111111").grid(row=0, column=1, rowspan=2, padx=8)
        ctk.CTkButton(head, text="Clear Completed", width=150, fg_color="#111111", command=self._clear_completed_jobs).grid(row=0, column=2, rowspan=2, padx=8)
        ctk.CTkButton(head, text="+ New Job", width=130, command=self._show_home).grid(row=0, column=3, rowspan=2, padx=(8, 28))

        table_head = ctk.CTkFrame(self.content, fg_color="#181818", height=36, corner_radius=0)
        table_head.grid(row=1, column=0, sticky="ew")
        table_head.grid_propagate(False)
        for col, weight in enumerate([5, 1, 4, 1, 1, 1]):
            table_head.grid_columnconfigure(col, weight=weight)
        for col, text in enumerate(["FILE NAME", "SIZE", "PROGRESS", "SPEED", "ETA", "ACTIONS"]):
            ctk.CTkLabel(table_head, text=text, text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=col, sticky="w", padx=16)

        body = ctk.CTkScrollableFrame(self.content, fg_color=BG, corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew")
        if not self.jobs:
            ctk.CTkLabel(body, text="No jobs yet. Paste a link on Home or generate SRT/TTS in Workspace.", text_color=MUTED).pack(anchor="w", padx=28, pady=24)
        else:
            for job in sorted(self.jobs, key=lambda j: j.created_at, reverse=True):
                self._download_job_row(body, job)

    def _show_library(self) -> None:
        self._clear_content("AI Video Processor", "library")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self.content, fg_color=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Video Library", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Import Video", width=150, fg_color=SURFACE, border_width=1, border_color=BORDER, command=self._import_local).grid(row=0, column=1, sticky="e")

        controls = self._panel(self.content)
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        controls.grid_columnconfigure(0, weight=1)
        self.library_search = ctk.CTkEntry(controls, placeholder_text="Search library...")
        self.library_search.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        self.library_search.bind("<KeyRelease>", lambda _event: self._populate_library_table())
        self.source_filter = ctk.CTkOptionMenu(controls, values=["Source: All", "local", "tiktok", "youtube"], width=120, command=lambda _v: self._populate_library_table())
        self.source_filter.grid(row=0, column=1, padx=6)
        self.status_filter = ctk.CTkOptionMenu(controls, values=["Status: All", "SRT Ready", "TTS Ready", "Pending"], width=120, command=lambda _v: self._populate_library_table())
        self.status_filter.grid(row=0, column=2, padx=6)
        ctk.CTkButton(controls, text="Grid", width=54, fg_color=SURFACE_HIGH).grid(row=0, column=3, padx=(10, 4))
        ctk.CTkButton(controls, text="List", width=54, fg_color=SURFACE_HIGH).grid(row=0, column=4, padx=(4, 12))

        table = self._panel(self.content)
        table.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(1, weight=1)
        table_header = ctk.CTkFrame(table, fg_color=SURFACE_LOW, height=38, corner_radius=0)
        table_header.grid(row=0, column=0, sticky="ew")
        table_header.grid_propagate(False)
        for col, weight in enumerate([1, 5, 1, 1, 2, 1]):
            table_header.grid_columnconfigure(col, weight=weight)
        for col, text in enumerate(["Thumb", "Title", "Duration", "Size", "Status", "Actions"]):
            ctk.CTkLabel(table_header, text=text, text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=col, sticky="w", padx=14)
        self.library_table_body = ctk.CTkScrollableFrame(table, fg_color="transparent")
        self.library_table_body.grid(row=1, column=0, sticky="nsew")
        self._populate_library_table()

    def _show_workspace(self) -> None:
        self._clear_content("Project Alpha", "workspace")
        if not self.selected_video:
            videos = self.storage.list_videos()
            if videos:
                self.selected_video = videos[0]
            else:
                ctk.CTkLabel(self.content, text="Select or import a video first.", text_color=MUTED).pack(anchor="w", padx=24, pady=24)
                return
        self.content.grid_columnconfigure(0, weight=0)
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_columnconfigure(2, weight=0)
        self.content.grid_rowconfigure(0, weight=1)
        self._project_files_panel(self.content).grid(row=0, column=0, sticky="nsew", padx=(4, 2), pady=4)
        center = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)
        center.grid_columnconfigure(0, weight=1)
        center.grid_rowconfigure(0, weight=3)
        center.grid_rowconfigure(1, weight=2)
        self._video_preview_panel(center).grid(row=0, column=0, sticky="nsew")
        self._subtitle_editor_panel(center).grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self._workspace_tools_panel(self.content).grid(row=0, column=2, sticky="nsew", padx=(2, 4), pady=4)

    def _show_settings(self) -> None:
        self._clear_content("Settings", "settings")
        self.content.grid_columnconfigure(0, weight=1)
        panel = self._panel(self.content)
        panel.grid(row=0, column=0, sticky="ew", padx=18, pady=18)
        self._section_title(panel, "PATHS").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        rows = [
            ("Database", str(self.config_obj.db_path)),
            ("Downloads", str(self.config_obj.downloads_dir)),
            ("Outputs", str(self.config_obj.outputs_dir)),
            ("Lazy-downloader", str(self.config_obj.lazy_downloader_cli)),
            ("VieNeu source", str(self.config_obj.vieneu_src)),
        ]
        for i, (label, value) in enumerate(rows, start=1):
            ctk.CTkLabel(panel, text=label, text_color=MUTED, anchor="w").grid(row=i, column=0, sticky="w", padx=18, pady=4)
            ctk.CTkLabel(panel, text=value, text_color=TEXT, anchor="w", wraplength=900).grid(row=i, column=1, sticky="w", padx=18, pady=4)

    def _populate_recent_cards(self, parent: ctk.CTkScrollableFrame) -> None:
        videos = self.storage.list_videos()[:6]
        if not videos:
            ctk.CTkLabel(parent, text="No recent outputs. Paste a link above to start.", text_color=MUTED).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        for idx, video in enumerate(videos):
            card = ctk.CTkFrame(parent, fg_color=SURFACE_LOW, border_width=1, border_color=BORDER, corner_radius=2)
            card.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)
            thumb = ctk.CTkFrame(card, fg_color="#050505", height=110, corner_radius=0)
            thumb.grid(row=0, column=0, sticky="ew")
            thumb.grid_propagate(False)
            ctk.CTkLabel(thumb, text=video.media_type.upper(), text_color=MUTED_DARK, font=ctk.CTkFont(size=18, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(card, text=video.title, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 2))
            srt = self.storage.latest_asset(video.id, "srt")
            ctk.CTkLabel(card, text="Ready" if srt else "Downloaded", text_color=SUCCESS if srt else PRIMARY_SOFT, anchor="w").grid(row=2, column=0, sticky="w", padx=10, pady=(0, 8))
            ctk.CTkButton(card, text="Open", width=70, height=24, command=lambda v=video: self._select_video(v)).grid(row=2, column=0, sticky="e", padx=10, pady=(0, 8))

    def _download_job_row(self, parent: ctk.CTkScrollableFrame, job: JobRecord) -> None:
        row = ctk.CTkFrame(parent, fg_color=SURFACE if job.status != "error" else "#201818", corner_radius=0)
        row.pack(fill="x", pady=(0, 1))
        for col, weight in enumerate([5, 1, 4, 1, 1, 1]):
            row.grid_columnconfigure(col, weight=weight)
        color = self._status_color(job.status)
        icon = {"completed": "OK", "error": "!", "running": ">", "queued": ".."}.get(job.status, "--")
        ctk.CTkLabel(row, text=icon, text_color=color, width=42, font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=(16, 0), pady=14)
        title_box = ctk.CTkFrame(row, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="ew", padx=(58, 6), pady=10)
        ctk.CTkLabel(title_box, text=job.title, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text=job.detail, text_color=color, anchor="w", font=ctk.CTkFont(size=11)).pack(anchor="w")
        ctk.CTkLabel(row, text=job.size_label, text_color=MUTED).grid(row=0, column=1, sticky="w", padx=12)
        progress_box = ctk.CTkFrame(row, fg_color="transparent")
        progress_box.grid(row=0, column=2, sticky="ew", padx=12)
        ctk.CTkLabel(progress_box, text=f"{int(job.progress * 100)}%", text_color=color, anchor="w").pack(anchor="w")
        bar = ctk.CTkProgressBar(progress_box, height=6, progress_color=color, fg_color="#111111")
        bar.pack(fill="x", pady=(4, 0))
        bar.set(max(0.0, min(1.0, job.progress)))
        ctk.CTkLabel(row, text=job.speed_label, text_color=MUTED).grid(row=0, column=3, sticky="w", padx=12)
        ctk.CTkLabel(row, text=job.eta_label, text_color=MUTED).grid(row=0, column=4, sticky="w", padx=12)
        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=5, sticky="e", padx=16)
        action_text = "Retry" if job.status == "error" else ("Open" if job.status == "completed" else "Pause")
        ctk.CTkButton(actions, text=action_text, width=54, height=26, fg_color=SURFACE_HIGH, command=self._show_library if job.status == "completed" else None).pack(side="left", padx=3)

    def _populate_library_table(self) -> None:
        if not hasattr(self, "library_table_body"):
            return
        for child in self.library_table_body.winfo_children():
            child.destroy()
        query = self.library_search.get().strip().lower() if hasattr(self, "library_search") else ""
        source_filter = self.source_filter.get() if hasattr(self, "source_filter") else "Source: All"
        status_filter = self.status_filter.get() if hasattr(self, "status_filter") else "Status: All"
        filtered: list[VideoItem] = []
        for video in self.storage.list_videos():
            if query and query not in video.title.lower() and query not in str(video.path).lower():
                continue
            if source_filter != "Source: All" and video.source != source_filter:
                continue
            srt = self.storage.latest_asset(video.id, "srt")
            tts = self.storage.latest_asset(video.id, "tts")
            if status_filter == "SRT Ready" and not srt:
                continue
            if status_filter == "TTS Ready" and not tts:
                continue
            if status_filter == "Pending" and (srt or tts):
                continue
            filtered.append(video)
        if not filtered:
            ctk.CTkLabel(self.library_table_body, text="No matching media.", text_color=MUTED).pack(anchor="w", padx=16, pady=18)
            return
        for video in filtered:
            self._library_row(self.library_table_body, video)

    def _library_row(self, parent: ctk.CTkScrollableFrame, video: VideoItem) -> None:
        row = ctk.CTkFrame(parent, fg_color=SURFACE, border_width=0, corner_radius=0)
        row.pack(fill="x", pady=(0, 1))
        for col, weight in enumerate([1, 5, 1, 1, 2, 1]):
            row.grid_columnconfigure(col, weight=weight)
        thumb = ctk.CTkFrame(row, fg_color="#0b0d12", border_width=1, border_color=BORDER, width=74, height=42, corner_radius=2)
        thumb.grid(row=0, column=0, padx=14, pady=10, sticky="w")
        thumb.grid_propagate(False)
        ctk.CTkLabel(thumb, text="1080p" if video.media_type == "video" else "WAV", text_color=TEXT, font=ctk.CTkFont(size=10, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        title = ctk.CTkFrame(row, fg_color="transparent")
        title.grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkLabel(title, text=video.title, font=ctk.CTkFont(size=14, weight="bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(title, text=f"{video.source or 'local'}  {video.created_at[:10]}", text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w")
        ctk.CTkLabel(row, text=self._duration_label(video.duration_ms), text_color=MUTED).grid(row=0, column=2, sticky="w", padx=8)
        ctk.CTkLabel(row, text=self._size_label(video.size_bytes), text_color=MUTED).grid(row=0, column=3, sticky="w", padx=8)
        status = ctk.CTkFrame(row, fg_color="transparent")
        status.grid(row=0, column=4, sticky="w", padx=8)
        self._badge(status, "SRT", bool(self.storage.latest_asset(video.id, "srt")), SUCCESS).pack(side="left", padx=3)
        self._badge(status, "TTS", bool(self.storage.latest_asset(video.id, "tts")), PRIMARY).pack(side="left", padx=3)
        ctk.CTkButton(row, text="Open", width=76, height=28, command=lambda: self._select_video(video)).grid(row=0, column=5, sticky="e", padx=14)

    def _project_files_panel(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        panel = self._panel(parent, width=290)
        panel.grid_propagate(False)
        self._panel_header(panel, "Project Files").pack(fill="x")
        body = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        if self.selected_video:
            self._project_file_row(body, self.selected_video.path.name, self._size_label(self.selected_video.size_bytes), PRIMARY_SOFT)
            for asset in self.storage.list_assets(self.selected_video.id):
                self._project_file_row(body, asset.path.name, f"{asset.kind.upper()}  {asset.engine}", SUCCESS if asset.kind == "srt" else WARNING)
        return panel

    def _project_file_row(self, parent: ctk.CTkScrollableFrame, title: str, subtitle: str, color: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=7)
        ctk.CTkLabel(row, text="■", text_color=color, width=20).pack(side="left")
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text, text=title, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(text, text=subtitle, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")

    def _video_preview_panel(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        panel = self._panel(parent)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(0, weight=1)
        preview = tk.Frame(panel, bg="#000000", bd=0, highlightthickness=0)
        preview.grid(row=0, column=0, sticky="nsew")
        self.video_preview_frame = preview
        self.video_frame_label = tk.Label(preview, text="", bg="#000000", bd=0, highlightthickness=0)
        self.video_frame_label.place(relx=0.5, rely=0.5, relwidth=1, relheight=1, anchor="center")
        title = self.selected_video.title if self.selected_video else "No video"
        self.video_title_label = ctk.CTkLabel(preview, text=title, text_color=TEXT, font=ctk.CTkFont(size=22, weight="bold"), wraplength=620, bg_color="#000000")
        self.video_title_label.place(relx=0.5, rely=0.42, anchor="center")
        self.video_overlay_play = ctk.CTkButton(
            preview,
            text="▶",
            width=72,
            height=72,
            corner_radius=36,
            fg_color=PRIMARY,
            hover_color="#2563eb",
            font=ctk.CTkFont(size=28, weight="bold"),
            command=self._open_selected_video,
        )
        self.video_overlay_play.place(relx=0.5, rely=0.60, anchor="center")
        controls = ctk.CTkFrame(panel, fg_color=SURFACE_HIGH, height=56, corner_radius=0)
        controls.grid(row=1, column=0, sticky="ew")
        controls.grid_propagate(False)
        ctk.CTkButton(controls, text="⏮", width=44, fg_color="transparent", hover_color=SURFACE, command=lambda: self._seek_inline_video(-5)).pack(side="left", padx=(10, 0), pady=12)
        self.video_play_button = ctk.CTkButton(
            controls,
            text="▶",
            width=44,
            fg_color="transparent",
            hover_color=SURFACE,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._open_selected_video,
        )
        self.video_play_button.pack(side="left", padx=(10, 0), pady=12)
        ctk.CTkButton(controls, text="⏭", width=44, fg_color="transparent", hover_color=SURFACE, command=lambda: self._seek_inline_video(5)).pack(side="left", padx=(10, 0), pady=12)
        self.video_time_label = ctk.CTkLabel(controls, text="00:00", text_color=PRIMARY_SOFT, font=ctk.CTkFont(size=12, weight="bold"))
        self.video_time_label.pack(side="left", padx=12)
        self.video_progress = ctk.CTkProgressBar(controls, width=160, height=6)
        self.video_progress.pack(side="left", padx=14)
        self.video_progress.set(0)
        ctk.CTkLabel(controls, text=self._duration_label(self.selected_video.duration_ms), text_color=MUTED).pack(side="left", padx=8)
        ctk.CTkButton(controls, text="📁", width=44, fg_color="transparent", hover_color=SURFACE, command=lambda: self._open_path(self.selected_video.path.parent)).pack(side="right", padx=10)
        return panel

    def _subtitle_editor_panel(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        panel = self._panel(parent)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        head = self._panel_header(panel, "Subtitle Editor")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(head, text="Export SRT", width=96, command=self._export_latest_srt).pack(side="right", padx=(4, 10))
        ctk.CTkButton(head, text="Save Edits", width=92, fg_color=SURFACE_HIGH, command=self._save_srt_edits).pack(side="right", padx=4)
        ctk.CTkButton(head, text="Import SRT", width=92, fg_color=SURFACE_HIGH, command=self._import_srt).pack(side="right", padx=4)
        ctk.CTkButton(head, text="Find", width=72, fg_color=SURFACE_HIGH).pack(side="right", padx=4)
        body = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        segments = self._latest_segments()
        self.subtitle_textboxes = {}
        if not segments:
            ctk.CTkLabel(body, text="No subtitles yet. Generate SRT from the right panel.", text_color=MUTED).pack(anchor="w", padx=8, pady=8)
        else:
            for segment in segments:
                self._subtitle_segment_row(body, segment)
        return panel

    def _subtitle_segment_row(self, parent: ctk.CTkScrollableFrame, segment: SubtitleSegment) -> None:
        row = ctk.CTkFrame(parent, fg_color=SURFACE_LOW, border_width=1, border_color=BORDER, corner_radius=3)
        row.pack(fill="x", padx=4, pady=6)
        row.grid_columnconfigure(1, weight=1)
        times = f"{seconds_to_srt_time(segment.start)}\n{seconds_to_srt_time(segment.end)}"
        ctk.CTkLabel(row, text=times, text_color=MUTED, width=110, font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=10, pady=10, sticky="n")
        box = ctk.CTkTextbox(row, height=54, fg_color="#111111", border_width=1, border_color=BORDER, wrap="word")
        box.grid(row=0, column=1, sticky="ew", padx=8, pady=10)
        box.insert("1.0", segment.text)
        self.subtitle_textboxes[segment.index] = box
        ctk.CTkButton(row, text="Del", width=44, height=26, fg_color=SURFACE_HIGH).grid(row=0, column=2, padx=8)

    def _workspace_tools_panel(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        panel = self._panel(parent, width=340)
        panel.grid_propagate(False)
        tabs = ctk.CTkFrame(panel, fg_color=SURFACE_HIGH, corner_radius=0)
        tabs.pack(fill="x")
        ctk.CTkButton(
            tabs,
            text="Generate SRT",
            height=46,
            fg_color=SURFACE if self.tools_mode == "srt" else SURFACE_HIGH,
            text_color=PRIMARY_SOFT if self.tools_mode == "srt" else TEXT,
            command=lambda: self._set_tools_mode("srt"),
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            tabs,
            text="Text To Speech",
            height=46,
            fg_color=SURFACE if self.tools_mode == "tts" else SURFACE_HIGH,
            text_color=PRIMARY_SOFT if self.tools_mode == "tts" else TEXT,
            command=lambda: self._set_tools_mode("tts"),
        ).pack(side="left", fill="x", expand=True)
        body = ctk.CTkFrame(panel, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=16)
        if self.tools_mode == "srt":
            ctk.CTkLabel(body, text="Target Track", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            ctk.CTkOptionMenu(body, values=["Audio Track 1 (Mix)", "Audio Track 2 (Dialogue)"]).pack(fill="x")
            ctk.CTkFrame(body, height=1, fg_color=BORDER).pack(fill="x", pady=16)
            ctk.CTkLabel(body, text="Transcription Model", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            self.model_menu = ctk.CTkOptionMenu(body, values=["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"])
            self.model_menu.set(self.srt_model)
            self.model_menu.pack(fill="x")
            ctk.CTkLabel(body, text="Start with base/small for quick tests. Use large-v3 for better accuracy when you can wait.", text_color=MUTED, wraplength=285, font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(6, 14))
            ctk.CTkLabel(body, text="Language", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            self.language_entry = ctk.CTkEntry(body, placeholder_text="Auto-Detect or vi")
            self.language_entry.insert(0, self.srt_language)
            self.language_entry.pack(fill="x")
            ctk.CTkLabel(body, text="Compute Mode", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(16, 6))
            self.device_menu = ctk.CTkOptionMenu(body, values=["cpu", "cuda", "auto"])
            self.device_menu.set(self.srt_device)
            self.device_menu.pack(fill="x")
            ctk.CTkButton(panel, text="Generate Subtitles", height=46, font=ctk.CTkFont(size=14, weight="bold"), command=self._generate_srt).pack(side="bottom", fill="x", padx=16, pady=16)
        else:
            asset = self._latest_srt_asset()
            tts_asset = self.storage.latest_asset(self.selected_video.id, "tts") if self.selected_video else None
            srt_text = asset.path.name if asset and asset.path.exists() else "No SRT yet"
            tts_text = tts_asset.path.name if tts_asset and tts_asset.path.exists() else "No voiceover yet"
            ctk.CTkLabel(body, text="Source SRT", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            ctk.CTkLabel(body, text=srt_text, text_color=SUCCESS if asset else WARNING, wraplength=285, justify="left").pack(anchor="w", pady=(0, 14))
            ctk.CTkLabel(body, text="VieNeu TTS Voice", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            values = self.voice_values or ["default"]
            self.voice_menu = ctk.CTkOptionMenu(body, values=values)
            if self.tts_voice in values:
                self.voice_menu.set(self.tts_voice)
            self.voice_menu.pack(fill="x")
            ctk.CTkButton(body, text="Refresh Voices", fg_color=SURFACE_HIGH, command=self._refresh_voices).pack(fill="x", pady=(8, 0))
            ctk.CTkButton(body, text="Open Voice Folder", fg_color=SURFACE_HIGH, command=self._open_latest_tts).pack(fill="x", pady=(8, 0))
            ctk.CTkFrame(body, height=1, fg_color=BORDER).pack(fill="x", pady=16)
            ctk.CTkLabel(body, text="Latest Voice Output", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 6))
            ctk.CTkLabel(body, text=tts_text, text_color=SUCCESS if tts_asset else MUTED, wraplength=285, justify="left").pack(anchor="w")
            ctk.CTkLabel(body, text="VieNeu may download/load its model on the first run, so the first voice job can take a while.", text_color=MUTED, wraplength=285, font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(14, 0))
            ctk.CTkButton(panel, text="Generate Voiceover", height=46, font=ctk.CTkFont(size=14, weight="bold"), command=self._tts_latest_srt).pack(side="bottom", fill="x", padx=16, pady=16)
        return panel

    def _download_from_entry(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a video URL first.")
            return
        job_id = self._add_job("download", url, detail="Queued from Home")
        self._show_downloads()
        self._run_worker(job_id, lambda: self.downloader.download_url(url, lambda msg: self._post_status(msg, job_id)))

    def _import_local(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import video or audio",
            filetypes=[("Media files", "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a *.aac *.flac"), ("All files", "*.*")],
        )
        if not paths:
            return
        ids = self.storage.import_local_files(Path(p) for p in paths)
        self._add_log("Import", f"Imported {len(ids)} file(s)")
        self._post_status(f"Imported {len(ids)} file(s).")
        self._show_library()

    def _select_video(self, video: VideoItem) -> None:
        self.selected_video = video
        self._show_workspace()

    def _generate_srt(self) -> None:
        if not self.selected_video:
            messagebox.showwarning("No video", "Select a video first.")
            return
        if not self.selected_video.path.exists():
            messagebox.showerror("Missing media", f"Video file not found:\n{self.selected_video.path}")
            return
        model = self.model_menu.get()
        device = self.device_menu.get()
        language = self.language_entry.get().strip()
        self.srt_model = model
        self.srt_device = device
        self.srt_language = language
        job_id = self._add_job("srt", f"Generate SRT: {self.selected_video.title}", detail=f"Model {model}")
        self._post_status(f"Starting SRT generation with {model}. First run may download the model.", job_id)
        self._run_worker(
            job_id,
            lambda: self.transcriber.generate_srt(
                self.selected_video,
                model_name=model,
                device=device,
                language=language,
                progress=lambda msg: self._post_status(msg, job_id),
            ),
        )

    def _tts_latest_srt(self) -> None:
        if not self.selected_video:
            messagebox.showwarning("No video", "Select a video first.")
            return
        asset = self.storage.latest_asset(self.selected_video.id, "srt")
        if not asset or not asset.path.exists():
            messagebox.showwarning("Missing SRT", "Generate an SRT before running TTS.")
            return
        voice = self.voice_menu.get()
        self.tts_voice = voice
        if voice == "default":
            voice = ""
        job_id = self._add_job("tts", f"VieNeu TTS: {self.selected_video.title}", detail="Reading subtitle segments")
        self._post_status("Starting VieNeu TTS. First run may download/load the model.", job_id)
        self._run_worker(job_id, lambda: self.tts.synthesize_srt(self.selected_video, asset.path, voice=voice, progress=lambda msg: self._post_status(msg, job_id)))

    def _refresh_voices(self) -> None:
        job_id = self._add_job("voices", "Refresh VieNeu voices", detail="Loading VieNeu engine")
        self._post_status("Loading VieNeu voice list...", job_id)

        def task() -> list[str]:
            voices = self.tts.list_voices()
            return ["default"] + [voice_id for _, voice_id in voices]

        self._run_worker(job_id, task, done_kind="voices")

    def _set_tools_mode(self, mode: str) -> None:
        self.tools_mode = mode
        self._show_workspace()

    def _latest_srt_asset(self):
        if not self.selected_video:
            return None
        return self.storage.latest_asset(self.selected_video.id, "srt")

    def _export_latest_srt(self) -> None:
        asset = self._latest_srt_asset()
        if not asset or not asset.path.exists():
            messagebox.showwarning("Missing SRT", "Generate or import an SRT before exporting.")
            return
        target = filedialog.asksaveasfilename(
            title="Export SRT",
            defaultextension=".srt",
            initialfile=asset.path.name,
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if not target:
            return
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.resolve() != asset.path.resolve():
            shutil.copyfile(asset.path, target_path)
        self._add_log("SRT", f"Exported to {target_path}")
        self._post_status(f"SRT exported: {target_path}")

    def _import_srt(self) -> None:
        if not self.selected_video:
            messagebox.showwarning("No video", "Select a video before importing SRT.")
            return
        selected = filedialog.askopenfilename(
            title="Import SRT",
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if not selected:
            return
        source = Path(selected)
        segments = read_srt(source)
        if not segments:
            messagebox.showwarning("Invalid SRT", "This file does not contain readable subtitle segments.")
            return
        output_dir = self.config_obj.outputs_dir / f"video_{self.selected_video.id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"imported_{int(time.time())}_{source.name}"
        shutil.copyfile(source, target)
        self.storage.add_asset(
            video_id=self.selected_video.id,
            kind="srt",
            path=target,
            engine="manual-import",
            metadata={"segments": len(segments), "source": str(source)},
        )
        self._add_log("SRT", f"Imported {len(segments)} segment(s)")
        self._post_status(f"SRT imported: {target}")
        self._show_workspace()

    def _save_srt_edits(self) -> None:
        asset = self._latest_srt_asset()
        if not asset or not asset.path.exists():
            messagebox.showwarning("Missing SRT", "Generate or import an SRT before saving edits.")
            return
        segments = read_srt(asset.path)
        if not segments:
            messagebox.showwarning("Invalid SRT", "No subtitle segments found to save.")
            return
        edited: list[SubtitleSegment] = []
        for segment in segments:
            box = self.subtitle_textboxes.get(segment.index)
            text = box.get("1.0", "end").strip() if box else segment.text
            edited.append(SubtitleSegment(index=segment.index, start=segment.start, end=segment.end, text=text))
        write_srt(edited, asset.path)
        self._add_log("SRT", f"Saved edits to {asset.path.name}")
        self._post_status(f"SRT edits saved: {asset.path}")
        self._show_workspace()

    def _open_latest_srt(self) -> None:
        asset = self._latest_srt_asset()
        if asset and asset.path.exists():
            self._open_path(asset.path)

    def _open_latest_tts(self) -> None:
        if not self.selected_video:
            return
        asset = self.storage.latest_asset(self.selected_video.id, "tts")
        if asset and asset.path.exists():
            self._open_path(asset.path.parent)
            return
        messagebox.showwarning("Missing voiceover", "Generate a voiceover before opening the output folder.")

    def _focus_tts_tools(self) -> None:
        self._set_tools_mode("tts")

    def _open_selected_video(self) -> None:
        if not self.selected_video:
            messagebox.showwarning("No video", "Select a video first.")
            return
        if not self.selected_video.path.exists():
            messagebox.showerror("Missing media", f"Video file not found:\n{self.selected_video.path}")
            return
        if self.ffplay_process is not None:
            self._toggle_ffplay_pause()
            return
        if self.video_capture is not None:
            self._pause_inline_video() if self.video_playing else self._resume_inline_video()
            return
        self._start_inline_video(self.selected_video.path)

    def _start_inline_video(self, path: Path) -> None:
        if self._start_ffplay_video(path):
            return
        try:
            import cv2
        except ImportError:
            messagebox.showerror("Missing OpenCV", "Install opencv-python to play video inside the tool.")
            return

        self._stop_inline_video()
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            messagebox.showerror("Video playback", f"Could not open video:\n{path}")
            return

        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        self.video_capture = capture
        self.video_fps = max(1.0, float(fps))
        self.video_duration_seconds = float(frames / self.video_fps) if frames else 0.0
        if self.video_title_label and self.video_title_label.winfo_exists():
            self.video_title_label.place_forget()
        if self.video_overlay_play and self.video_overlay_play.winfo_exists():
            self.video_overlay_play.place_forget()
        self._post_status(f"Playing inside workspace: {path.name}")
        self._play_inline_from(0.0)

    def _start_ffplay_video(self, path: Path) -> bool:
        ffplay = shutil.which("ffplay")
        if not ffplay or not self.video_preview_frame:
            return False
        try:
            self._stop_inline_video()
            if self.video_title_label and self.video_title_label.winfo_exists():
                self.video_title_label.place_forget()
            if self.video_overlay_play and self.video_overlay_play.winfo_exists():
                self.video_overlay_play.place_forget()
            if self.video_frame_label and self.video_frame_label.winfo_exists():
                self.video_frame_label.place_forget()

            self.video_preview_frame.update_idletasks()
            self.ffplay_process = subprocess.Popen(
                [
                    ffplay,
                    "-loglevel",
                    "quiet",
                    "-autoexit",
                    "-noborder",
                    str(path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            hwnd = self._wait_for_ffplay_window(self.ffplay_process.pid)
            if not hwnd:
                self._terminate_ffplay()
                return False
            self.ffplay_hwnd = hwnd
            self.ffplay_paused = False
            self._embed_ffplay_window()
            self.video_clock_position = 0.0
            self.video_clock_start = time.perf_counter()
            self.video_playing = True
            self._set_video_button_text("❚❚")
            self._post_status(f"Playing with embedded ffplay: {path.name}")
            self._watch_ffplay()
            return True
        except Exception as exc:
            self._terminate_ffplay()
            self._post_status(f"ffplay embed failed, using fallback player: {exc}")
            return False

    def _wait_for_ffplay_window(self, pid: int) -> int | None:
        deadline = time.time() + 5
        while time.time() < deadline:
            hwnd = self._find_window_by_pid(pid)
            if hwnd:
                return hwnd
            self.update()
            time.sleep(0.05)
        return None

    def _find_window_by_pid(self, pid: int) -> int | None:
        try:
            import win32gui
            import win32process

            matches: list[int] = []

            def enum(hwnd: int, _extra: Any) -> None:
                if not win32gui.IsWindow(hwnd):
                    return
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    matches.append(hwnd)

            win32gui.EnumWindows(enum, None)
            return matches[0] if matches else None
        except Exception:
            return None

    def _embed_ffplay_window(self) -> None:
        if not self.ffplay_hwnd or not self.video_preview_frame:
            return
        try:
            import win32con
            import win32gui

            parent = self.video_preview_frame.winfo_id()
            win32gui.SetParent(self.ffplay_hwnd, parent)
            style = win32gui.GetWindowLong(self.ffplay_hwnd, win32con.GWL_STYLE)
            style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_SYSMENU)
            style |= win32con.WS_CHILD | win32con.WS_VISIBLE
            win32gui.SetWindowLong(self.ffplay_hwnd, win32con.GWL_STYLE, style)
            self._resize_ffplay_window()
            self.after(100, self._resize_ffplay_window)
            self.after(400, self._resize_ffplay_window)
            self.video_preview_frame.bind("<Configure>", lambda _event: self._resize_ffplay_window())
        except Exception as exc:
            self._post_status(f"Could not embed ffplay window: {exc}")

    def _resize_ffplay_window(self) -> None:
        if not self.ffplay_hwnd or not self.video_preview_frame:
            return
        try:
            import win32gui

            width = max(320, self.video_preview_frame.winfo_width())
            height = max(180, self.video_preview_frame.winfo_height())
            win32gui.MoveWindow(self.ffplay_hwnd, 0, 0, width, height, True)
        except Exception:
            pass

    def _toggle_ffplay_pause(self) -> None:
        if not self.ffplay_paused:
            self.video_clock_position = self._playback_video_seconds()
            self.video_playing = False
        else:
            self.video_clock_start = time.perf_counter()
            self.video_playing = True
        self._send_ffplay_key("p")
        self.ffplay_paused = not self.ffplay_paused
        self._set_video_button_text("▶" if self.ffplay_paused else "❚❚")

    def _send_ffplay_key(self, key: str) -> None:
        if not self.ffplay_hwnd:
            return
        try:
            import win32api
            import win32con

            if key == "left":
                vk = win32con.VK_LEFT
            elif key == "right":
                vk = win32con.VK_RIGHT
            else:
                vk = ord(key.upper())
            win32api.PostMessage(self.ffplay_hwnd, win32con.WM_KEYDOWN, vk, 0)
            win32api.PostMessage(self.ffplay_hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception:
            pass

    def _watch_ffplay(self) -> None:
        if not self.ffplay_process:
            return
        if self.ffplay_process.poll() is not None:
            self.ffplay_process = None
            self.ffplay_hwnd = None
            self.ffplay_paused = False
            self.video_playing = False
            self._update_video_progress(self.video_duration_seconds if self.video_duration_seconds else None)
            self._set_video_button_text("▶")
            return
        self._resize_ffplay_window()
        self._update_video_progress()
        self.ffplay_after_id = self.after(250, self._watch_ffplay)

    def _terminate_ffplay(self) -> None:
        if self.ffplay_after_id:
            try:
                self.after_cancel(self.ffplay_after_id)
            except Exception:
                pass
            self.ffplay_after_id = None
        if self.ffplay_process is not None:
            try:
                self.ffplay_process.terminate()
                self.ffplay_process.wait(timeout=2)
            except Exception:
                try:
                    self.ffplay_process.kill()
                except Exception:
                    pass
        self.ffplay_process = None
        self.ffplay_hwnd = None
        self.ffplay_paused = False
        self.video_playing = False

    def _resume_inline_video(self) -> None:
        if not self.video_capture:
            return
        self._play_inline_from(self._current_video_seconds())

    def _pause_inline_video(self) -> None:
        position = self._playback_video_seconds() if self.video_playing else self._current_video_seconds()
        self.video_playing = False
        self._stop_inline_audio()
        self._set_capture_position(position)
        self._set_video_button_text("▶")
        if self.video_after_id:
            try:
                self.after_cancel(self.video_after_id)
            except Exception:
                pass
            self.video_after_id = None

    def _stop_inline_video(self) -> None:
        self.video_playing = False
        self._terminate_ffplay()
        self._stop_inline_audio()
        if self.video_after_id:
            try:
                self.after_cancel(self.video_after_id)
            except Exception:
                pass
            self.video_after_id = None
        if self.video_capture is not None:
            try:
                self.video_capture.release()
            except Exception:
                pass
        self.video_capture = None
        self.video_photo = None
        self.video_clock_start = 0.0
        self.video_clock_position = 0.0
        self._set_video_button_text("▶")

    def _play_inline_from(self, position: float) -> None:
        if not self.video_capture:
            return
        position = max(0.0, min(self.video_duration_seconds or position, position))
        if self.video_after_id:
            try:
                self.after_cancel(self.video_after_id)
            except Exception:
                pass
            self.video_after_id = None
        self._set_capture_position(position)
        self._start_inline_audio(position)
        self.video_clock_position = position
        self.video_clock_start = time.perf_counter()
        self.video_playing = True
        self._set_video_button_text("❚❚")
        self._video_loop()

    def _seek_inline_video(self, seconds: float) -> None:
        if self.ffplay_process is not None:
            self._send_ffplay_key("right" if seconds > 0 else "left")
            current = self._playback_video_seconds() if self.video_playing else self.video_clock_position
            target = max(0.0, min(self.video_duration_seconds or current + seconds, current + seconds))
            self.video_clock_position = target
            self.video_clock_start = time.perf_counter()
            self._update_video_progress(target)
            return
        if not self.video_capture:
            return
        try:
            current = self._playback_video_seconds() if self.video_playing else self._current_video_seconds()
            target = max(0.0, min(self.video_duration_seconds or current + seconds, current + seconds))
            if self.video_playing:
                self._play_inline_from(target)
            else:
                self._set_capture_position(target)
                self._render_current_frame()
                self._update_video_progress(target)
        except Exception as exc:
            self._post_status(f"Seek failed: {exc}")

    def _video_loop(self) -> None:
        if not self.video_playing or self.video_capture is None:
            return
        try:
            target = self._playback_video_seconds()
            if self.video_duration_seconds and target >= self.video_duration_seconds:
                self._pause_inline_video()
                self._set_capture_position(self.video_duration_seconds)
                self._update_video_progress(self.video_duration_seconds)
                return
            current = self._current_video_seconds()
            tolerance = max(0.08, 2.0 / self.video_fps)
            if current < target - tolerance or current > target + 0.2:
                self._set_capture_position(target)
            ok, frame = self.video_capture.read()
        except Exception as exc:
            self._pause_inline_video()
            messagebox.showerror("Video playback", str(exc))
            return
        if not ok:
            self._pause_inline_video()
            self._seek_inline_video(-self.video_duration_seconds)
            return
        self._render_video_frame(frame)
        self._update_video_progress(target)
        delay = max(16, int(1000 / min(self.video_fps, 30)))
        self.video_after_id = self.after(delay, self._video_loop)

    def _render_current_frame(self) -> None:
        if not self.video_capture:
            return
        try:
            ok, frame = self.video_capture.read()
            if ok:
                self._render_video_frame(frame)
        except Exception:
            return

    def _render_video_frame(self, frame: Any) -> None:
        if not self.video_frame_label or not self.video_frame_label.winfo_exists():
            self._pause_inline_video()
            return
        try:
            import cv2
            from PIL import Image, ImageTk

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            width = min(960, max(320, self.video_frame_label.winfo_width()))
            height = min(540, max(180, self.video_frame_label.winfo_height()))
            image.thumbnail((width, height))
            canvas = Image.new("RGB", (width, height), "black")
            x = (width - image.width) // 2
            y = (height - image.height) // 2
            canvas.paste(image, (x, y))
            self.video_photo = ImageTk.PhotoImage(canvas)
            self.video_frame_label.configure(image=self.video_photo, text="")
        except Exception as exc:
            self._pause_inline_video()
            messagebox.showerror("Video render", str(exc))

    def _update_video_progress(self, current: float | None = None) -> None:
        if not self.video_capture:
            return
        try:
            if current is None:
                current = self._playback_video_seconds() if self.video_playing else self._current_video_seconds()
            if self.video_time_label and self.video_time_label.winfo_exists():
                self.video_time_label.configure(text=self._seconds_label(current))
            if self.video_progress and self.video_progress.winfo_exists() and self.video_duration_seconds:
                self.video_progress.set(max(0.0, min(1.0, current / self.video_duration_seconds)))
        except Exception:
            return

    def _playback_video_seconds(self) -> float:
        if not self.video_playing:
            return self._current_video_seconds()
        current = self.video_clock_position + (time.perf_counter() - self.video_clock_start)
        if self.video_duration_seconds:
            return min(self.video_duration_seconds, current)
        return max(0.0, current)

    def _current_video_seconds(self) -> float:
        if not self.video_capture:
            return 0.0
        try:
            import cv2

            return max(0.0, self.video_capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
        except Exception:
            return 0.0

    def _set_capture_position(self, seconds: float) -> None:
        if not self.video_capture:
            return
        try:
            import cv2

            self.video_capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000)
        except Exception:
            pass

    def _start_inline_audio(self, start_seconds: float) -> None:
        self._stop_inline_audio()
        if not self.selected_video:
            return
        if not self._ensure_inline_audio(self.selected_video.path):
            return
        try:
            import sounddevice as sd

            start = max(0, int(start_seconds * self.audio_sample_rate))
            if self.audio_data is None or start >= len(self.audio_data):
                return
            sd.play(self.audio_data[start:], self.audio_sample_rate, blocking=False)
        except Exception as exc:
            self._post_status(f"Audio playback unavailable: {exc}")

    def _stop_inline_audio(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    def _ensure_inline_audio(self, path: Path) -> bool:
        if self.audio_loaded and self.audio_source_path == path and self.audio_data is not None:
            return True
        self.audio_loaded = False
        self.audio_source_path = path
        self.audio_data = None
        self.audio_sample_rate = 0
        try:
            import soundfile as sf
        except ImportError:
            self._post_status("Install soundfile to enable preview audio.")
            return False

        wav_path = self.config_obj.outputs_dir / f"video_{self.selected_video.id}" / "preview_audio.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        if not wav_path.exists() or wav_path.stat().st_mtime < path.stat().st_mtime:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                self._post_status("FFmpeg was not found, so preview audio is disabled.")
                return False
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(path),
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if proc.returncode != 0 or not wav_path.exists():
                self._post_status("This media has no readable audio track.")
                return False
        try:
            self.audio_data, self.audio_sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
            self.audio_loaded = True
            return True
        except Exception as exc:
            self._post_status(f"Could not load preview audio: {exc}")
            return False

    def _set_video_button_text(self, text: str) -> None:
        for button in (self.video_play_button, self.video_overlay_play):
            if button is not None:
                try:
                    if button.winfo_exists():
                        button.configure(text=text)
                except Exception:
                    pass

    def _clear_completed_jobs(self) -> None:
        self.jobs = [job for job in self.jobs if job.status != "completed"]
        self._show_downloads()

    def _add_job(self, kind: str, title: str, detail: str = "Waiting in queue") -> int:
        job = JobRecord(id=self.next_job_id, kind=kind, title=title, detail=detail)
        self.next_job_id += 1
        self.jobs.append(job)
        self._add_log("Queued", title)
        self._update_status_stats()
        return job.id

    def _run_worker(self, job_id: int, fn: Callable[[], Any], done_kind: str = "done") -> None:
        self.message_queue.put(("job", job_id, "running", 0.08, "Running"))

        def runner() -> None:
            try:
                result = fn()
                self.message_queue.put((done_kind, job_id, result))
            except Exception as exc:
                self.message_queue.put(("error", job_id, str(exc)))

        threading.Thread(target=runner, daemon=True).start()

    def _post_status(self, message: str, job_id: int | None = None) -> None:
        if job_id:
            progress = 0.42
            low = message.lower()
            if "segment" in low:
                progress = 0.65
            elif "export" in low or "downloaded" in low:
                progress = 0.9
            self.message_queue.put(("job", job_id, "running", progress, message))
        self.message_queue.put(("status", message))

    def _drain_messages(self) -> None:
        try:
            while True:
                item = self.message_queue.get_nowait()
                kind = item[0]
                if kind == "status":
                    self.status_var.set(item[1])
                elif kind == "job":
                    _, job_id, status, progress, detail = item
                    self._update_job(job_id, status=status, progress=progress, detail=detail)
                elif kind == "done":
                    _, job_id, result = item
                    self._update_job(job_id, status="completed", progress=1.0, detail="Completed", eta_label="Done")
                    self._add_log("Completed", str(result))
                    self.status_var.set(f"Done: {result}")
                    self._refresh_current_view()
                elif kind == "voices":
                    _, job_id, values = item
                    self.voice_values = values if values else ["default"]
                    self._update_job(job_id, status="completed", progress=1.0, detail=f"Loaded {len(self.voice_values) - 1} voices", eta_label="Done")
                    self._add_log("VieNeu", f"Loaded {len(self.voice_values) - 1} voice(s)")
                    if hasattr(self, "voice_menu") and self.voice_menu.winfo_exists():
                        self.voice_menu.configure(values=self.voice_values)
                        self.voice_menu.set(self.voice_values[0])
                elif kind == "error":
                    _, job_id, message = item
                    self._update_job(job_id, status="error", progress=0.1, detail=message, speed_label="0 B/s")
                    self._add_log("Error", message)
                    self.status_var.set(message)
                    messagebox.showerror("Stitch Studio", message)
                    self._refresh_current_view()
        except queue.Empty:
            pass
        finally:
            self.after(200, self._drain_messages)

    def _update_job(self, job_id: int, **changes: Any) -> None:
        job = self._job(job_id)
        if not job:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        if job.status == "running":
            job.speed_label = "working"
            job.eta_label = "--"
        self._update_status_stats()

    def _job(self, job_id: int) -> JobRecord | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    def _refresh_current_view(self) -> None:
        if self.current_view == "home":
            self._show_home()
        elif self.current_view == "downloads":
            self._show_downloads()
        elif self.current_view == "library":
            self._show_library()
        elif self.current_view == "workspace":
            self._show_workspace()

    def _panel(self, parent: ctk.CTkFrame, width: int | None = None) -> ctk.CTkFrame:
        kwargs: dict[str, Any] = {
            "fg_color": SURFACE,
            "border_width": 1,
            "border_color": BORDER,
            "corner_radius": 2,
        }
        if width is not None:
            kwargs["width"] = width
        return ctk.CTkFrame(parent, **kwargs)

    def _panel_header(self, parent: ctk.CTkFrame, text: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, height=42, fg_color=SURFACE_HIGH, corner_radius=0)
        frame.grid_propagate(False)
        ctk.CTkLabel(frame, text=text, text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=14)
        return frame

    def _section_title(self, parent: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"))

    def _stat(self, parent: ctk.CTkFrame, label: str, value: str, color: str = TEXT) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(frame, text=label, text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(frame, text=value, text_color=color, font=ctk.CTkFont(size=28, weight="bold")).pack(anchor="w")
        return frame

    def _badge(self, parent: ctk.CTkFrame, text: str, active: bool, color: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, text_color="#061a12" if active else MUTED, fg_color=color if active else SURFACE_HIGH, corner_radius=12, width=46, height=22, font=ctk.CTkFont(size=11, weight="bold"))

    def _log_row(self, parent: ctk.CTkScrollableFrame, ts: str, msg: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=7)
        ctk.CTkLabel(row, text=">", width=22, text_color=PRIMARY).pack(side="left", anchor="n")
        body = ctk.CTkFrame(row, fg_color="transparent")
        body.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(body, text=msg, anchor="w", wraplength=280, justify="left").pack(anchor="w")
        ctk.CTkLabel(body, text=ts, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")

    def _add_log(self, title: str, message: str) -> None:
        self.system_logs.append((time.strftime("%H:%M"), f"{title}: {message}"))
        self.system_logs = self.system_logs[-30:]

    def _latest_segments(self) -> list[SubtitleSegment]:
        if not self.selected_video:
            return []
        asset = self.storage.latest_asset(self.selected_video.id, "srt")
        if not asset or not asset.path.exists():
            return []
        return read_srt(asset.path)

    def _current_subtitle_text(self) -> str:
        segments = self._latest_segments()
        return segments[0].text if segments else "Generate subtitles to preview caption text."

    def _active_job_count(self) -> int:
        return sum(1 for job in self.jobs if job.status in {"queued", "running"})

    def _update_status_stats(self) -> None:
        self.speed_var.set(f"Total Speed: {self._active_job_count()} active")
        self.disk_var.set("Free Space: local workspace")

    @staticmethod
    def _status_color(status: str) -> str:
        return {"completed": SUCCESS, "error": ERROR, "running": PRIMARY, "queued": MUTED}.get(status, MUTED)

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
        total = int(duration_ms / 1000)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"

    @staticmethod
    def _seconds_label(value: float) -> str:
        total = max(0, int(value))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"

    def _open_path(self, path: Path) -> None:
        try:
            import os

            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("Open path", str(exc))


def main() -> None:
    app = StitchStudioApp()
    app.mainloop()

from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .config import AppConfig, ensure_dirs
from .models import VideoItem
from .services import DownloaderService, TranscriptionService, VieneuTtsService
from .srt import read_srt
from .storage import Storage


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class StitchStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Stitch AI Video Pipeline Studio")
        self.geometry("1320x820")
        self.minsize(1100, 700)

        self.config_obj = AppConfig()
        ensure_dirs(self.config_obj)
        self.storage = Storage(self.config_obj.db_path)
        self.downloader = DownloaderService(self.config_obj, self.storage)
        self.transcriber = TranscriptionService(self.config_obj, self.storage)
        self.tts = VieneuTtsService(self.config_obj, self.storage)

        self.message_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.selected_video: VideoItem | None = None
        self.current_view = "home"

        self._build_layout()
        self._show_home()
        self._refresh_library()
        self.after(200, self._drain_messages)

    def destroy(self) -> None:
        self.storage.close()
        super().destroy()

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="AI Studio", font=ctk.CTkFont(size=24, weight="bold")).pack(
            anchor="w", padx=18, pady=(18, 2)
        )
        ctk.CTkLabel(self.sidebar, text="v0.1 CustomTkinter", text_color="#9ca3af").pack(
            anchor="w", padx=18, pady=(0, 22)
        )

        self.home_btn = ctk.CTkButton(self.sidebar, text="Home", anchor="w", command=self._show_home)
        self.home_btn.pack(fill="x", padx=12, pady=5)
        self.library_btn = ctk.CTkButton(self.sidebar, text="Library", anchor="w", command=self._show_library)
        self.library_btn.pack(fill="x", padx=12, pady=5)
        self.workspace_btn = ctk.CTkButton(self.sidebar, text="Workspace", anchor="w", command=self._show_workspace)
        self.workspace_btn.pack(fill="x", padx=12, pady=5)

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self.sidebar, textvariable=self.status_var, text_color="#9ca3af", wraplength=185).pack(
            side="bottom", fill="x", padx=14, pady=16
        )

        self.main = ctk.CTkFrame(self, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        self.header_title = ctk.CTkLabel(self.main, text="", font=ctk.CTkFont(size=24, weight="bold"))
        self.header_title.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        self.content = ctk.CTkFrame(self.main)
        self.content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

    def _clear_content(self, title: str) -> None:
        self.header_title.configure(text=title)
        for child in self.content.winfo_children():
            child.destroy()
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _show_home(self) -> None:
        self.current_view = "home"
        self._clear_content("AI Video Processor")
        frame = self.content
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(frame, text="Acquire Source Media", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(18, 8)
        )
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=18)
        row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(row, placeholder_text="Paste TikTok, YouTube, Instagram, or other video URL")
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(row, text="Download", width=130, command=self._download_from_entry).grid(row=0, column=1)
        ctk.CTkButton(row, text="Import Local", width=130, command=self._import_local).grid(row=0, column=2, padx=(8, 0))

        recent = ctk.CTkFrame(frame)
        recent.grid(row=2, column=0, sticky="nsew", padx=18, pady=18)
        recent.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(recent, text="Recent Videos", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=12
        )
        self.recent_list = ctk.CTkScrollableFrame(recent)
        self.recent_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        recent.grid_rowconfigure(1, weight=1)
        self._populate_video_rows(self.recent_list, limit=8)

    def _show_library(self) -> None:
        self.current_view = "library"
        self._clear_content("Video Library")
        self.content.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self.content, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        toolbar.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(toolbar, placeholder_text="Search library...")
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(toolbar, text="Import Video", width=130, command=self._import_local).grid(row=0, column=1)

        self.library_list = ctk.CTkScrollableFrame(self.content)
        self.library_list.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self._populate_video_rows(self.library_list)

    def _show_workspace(self) -> None:
        self.current_view = "workspace"
        self._clear_content("Workspace")
        if not self.selected_video:
            ctk.CTkLabel(self.content, text="Select a video from Library first.", text_color="#9ca3af").grid(
                row=0, column=0, padx=20, pady=20
            )
            return

        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self.content)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(3, weight=1)

        video = self.selected_video
        ctk.CTkLabel(left, text=video.title, font=ctk.CTkFont(size=18, weight="bold"), wraplength=480).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 4)
        )
        ctk.CTkLabel(left, text=str(video.path), text_color="#9ca3af", wraplength=520).grid(
            row=1, column=0, sticky="w", padx=16
        )
        ctk.CTkButton(left, text="Open File Location", width=160, command=lambda: self._open_path(video.path.parent)).grid(
            row=2, column=0, sticky="w", padx=16, pady=12
        )

        self.subtitle_box = ctk.CTkTextbox(left, wrap="word")
        self.subtitle_box.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._load_latest_srt_into_editor()

        right = ctk.CTkFrame(self.content)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Generate SRT", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 10)
        )
        self.model_menu = ctk.CTkOptionMenu(right, values=["large-v3", "turbo", "medium", "small", "base", "tiny"])
        self.model_menu.grid(row=1, column=0, sticky="ew", padx=16, pady=5)
        self.device_menu = ctk.CTkOptionMenu(right, values=["cpu", "cuda", "auto"])
        self.device_menu.grid(row=2, column=0, sticky="ew", padx=16, pady=5)
        self.language_entry = ctk.CTkEntry(right, placeholder_text="Language code, e.g. vi")
        self.language_entry.insert(0, "vi")
        self.language_entry.grid(row=3, column=0, sticky="ew", padx=16, pady=5)
        ctk.CTkButton(right, text="Generate Subtitles", command=self._generate_srt).grid(
            row=4, column=0, sticky="ew", padx=16, pady=(8, 18)
        )

        ctk.CTkFrame(right, height=1, fg_color="#374151").grid(row=5, column=0, sticky="ew", padx=16, pady=8)
        ctk.CTkLabel(right, text="Text To Speech - VieNeu", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=6, column=0, sticky="w", padx=16, pady=(12, 10)
        )
        self.voice_menu = ctk.CTkOptionMenu(right, values=["default"])
        self.voice_menu.grid(row=7, column=0, sticky="ew", padx=16, pady=5)
        ctk.CTkButton(right, text="Refresh VieNeu Voices", command=self._refresh_voices).grid(
            row=8, column=0, sticky="ew", padx=16, pady=5
        )
        ctk.CTkButton(right, text="TTS From Latest SRT", command=self._tts_latest_srt).grid(
            row=9, column=0, sticky="ew", padx=16, pady=(8, 18)
        )

        assets = self.storage.list_assets(video.id)
        asset_text = "\n".join(f"{a.kind.upper()}  {a.engine}\n{a.path}" for a in assets) or "No generated assets yet."
        asset_box = ctk.CTkTextbox(right, height=180, wrap="word")
        asset_box.grid(row=10, column=0, sticky="ew", padx=16, pady=(0, 16))
        asset_box.insert("1.0", asset_text)
        asset_box.configure(state="disabled")

    def _populate_video_rows(self, parent: ctk.CTkScrollableFrame, limit: int | None = None) -> None:
        for child in parent.winfo_children():
            child.destroy()
        videos = self.storage.list_videos()
        if limit:
            videos = videos[:limit]
        if not videos:
            ctk.CTkLabel(parent, text="No videos yet. Paste a link or import a local file.", text_color="#9ca3af").pack(
                anchor="w", padx=12, pady=12
            )
            return
        for video in videos:
            row = ctk.CTkFrame(parent)
            row.pack(fill="x", padx=8, pady=5)
            row.grid_columnconfigure(0, weight=1)
            title = f"{video.title}  [{video.media_type}]"
            ctk.CTkLabel(row, text=title, anchor="w", font=ctk.CTkFont(size=14, weight="bold")).grid(
                row=0, column=0, sticky="ew", padx=12, pady=(8, 2)
            )
            srt = self.storage.latest_asset(video.id, "srt")
            tts = self.storage.latest_asset(video.id, "tts")
            badges = f"{video.source or 'local'} | {'SRT' if srt else 'no SRT'} | {'TTS' if tts else 'no TTS'}"
            ctk.CTkLabel(row, text=badges, text_color="#9ca3af", anchor="w").grid(
                row=1, column=0, sticky="ew", padx=12, pady=(0, 8)
            )
            ctk.CTkButton(row, text="Open", width=90, command=lambda v=video: self._select_video(v)).grid(
                row=0, column=1, rowspan=2, padx=12, pady=8
            )

    def _refresh_library(self) -> None:
        if self.current_view == "home" and hasattr(self, "recent_list"):
            self._populate_video_rows(self.recent_list, limit=8)
        if self.current_view == "library" and hasattr(self, "library_list"):
            self._populate_video_rows(self.library_list)

    def _select_video(self, video: VideoItem) -> None:
        self.selected_video = video
        self._show_workspace()

    def _download_from_entry(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a video URL first.")
            return
        self._run_worker("download", lambda: self.downloader.download_url(url, self._post_status))

    def _import_local(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import video or audio",
            filetypes=[
                ("Media files", "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a *.aac *.flac"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        ids = self.storage.import_local_files(Path(p) for p in paths)
        self._post_status(f"Imported {len(ids)} file(s).")
        self._refresh_library()

    def _generate_srt(self) -> None:
        if not self.selected_video:
            return
        model = self.model_menu.get()
        device = self.device_menu.get()
        language = self.language_entry.get().strip()
        self._run_worker(
            "generate_srt",
            lambda: self.transcriber.generate_srt(
                self.selected_video,
                model_name=model,
                device=device,
                language=language,
                progress=self._post_status,
            ),
        )

    def _tts_latest_srt(self) -> None:
        if not self.selected_video:
            return
        asset = self.storage.latest_asset(self.selected_video.id, "srt")
        if not asset:
            messagebox.showwarning("Missing SRT", "Generate or import an SRT before running TTS.")
            return
        voice = self.voice_menu.get()
        if voice == "default":
            voice = ""
        self._run_worker(
            "tts",
            lambda: self.tts.synthesize_srt(
                self.selected_video,
                asset.path,
                voice=voice,
                progress=self._post_status,
            ),
        )

    def _refresh_voices(self) -> None:
        def task():
            voices = self.tts.list_voices()
            values = ["default"] + [voice_id for _, voice_id in voices]
            self.message_queue.put(("voices", "|".join(values)))

        self._run_worker("voices", task)

    def _load_latest_srt_into_editor(self) -> None:
        self.subtitle_box.delete("1.0", "end")
        if not self.selected_video:
            return
        asset = self.storage.latest_asset(self.selected_video.id, "srt")
        if not asset or not asset.path.exists():
            self.subtitle_box.insert("1.0", "No SRT yet. Use Generate Subtitles on the right.")
            return
        segments = read_srt(asset.path)
        text = "\n\n".join(
            f"{seg.index}\n{seg.start:.2f} -> {seg.end:.2f}\n{seg.text}" for seg in segments
        )
        self.subtitle_box.insert("1.0", text)

    def _run_worker(self, name: str, fn) -> None:
        self._post_status(f"{name} started...")

        def runner():
            try:
                result = fn()
                self.message_queue.put(("done", f"{name} done: {result}"))
            except Exception as exc:
                self.message_queue.put(("error", f"{name} failed: {exc}"))

        threading.Thread(target=runner, daemon=True).start()

    def _post_status(self, message: str) -> None:
        self.message_queue.put(("status", message))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, message = self.message_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(message)
                elif kind == "done":
                    self.status_var.set(message)
                    self._refresh_library()
                    if self.current_view == "workspace":
                        self._show_workspace()
                elif kind == "error":
                    self.status_var.set(message)
                    messagebox.showerror("Stitch Studio", message)
                elif kind == "voices":
                    values = message.split("|") if message else ["default"]
                    self.voice_menu.configure(values=values)
                    self.voice_menu.set(values[0])
                    self.status_var.set(f"Loaded {len(values) - 1} VieNeu voice(s).")
        finally:
            self.after(200, self._drain_messages)

    def _open_path(self, path: Path) -> None:
        try:
            import os

            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("Open path", str(exc))


def main() -> None:
    app = StitchStudioApp()
    app.mainloop()

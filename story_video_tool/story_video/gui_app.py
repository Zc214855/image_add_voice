"""儿童故事视频生成器的 Windows 本地桌面界面。"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    BooleanVar,
    Listbox,
    StringVar,
    Text,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import ttk

from PIL import Image, ImageTk

from .media import IMAGE_EXTENSIONS, StoryAssets, natural_key
from .service import generate_story_video


BG = "#F4EEDF"
PANEL = "#FFF9EC"
TEXT = "#3B261D"
MUTED = "#806E60"
ACCENT = "#6F9F4A"
ACCENT_ACTIVE = "#5D893D"
BORDER = "#D8C9B5"


class StoryVideoApp:
    """管理素材导入、选项设置和后台生成任务。"""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.project_root = Path(__file__).resolve().parents[2]
        self.images: list[Path] = []
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False

        self.title_var = StringVar()
        self.text_var = StringVar()
        self.audio_var = StringVar()
        self.output_var = StringVar(
            value=str(self.project_root / "output" / "新故事.mp4")
        )
        self.model_var = StringVar(value="small")
        self.encoder_var = StringVar(value="auto")
        self.draft_var = BooleanVar(value=False)
        self.force_var = BooleanVar(value=False)
        self.status_var = StringVar(value="等待导入素材")
        self.image_count_var = StringVar(value="未添加插图")
        self.title_var.trace_add("write", lambda *_args: self._refresh_default_output())

        self._configure_window()
        self._configure_styles()
        self._build_layout()
        self.root.after(120, self._poll_events)

    def _configure_window(self) -> None:
        self.root.title("儿童故事视频生成器")
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)
        self.root.configure(bg=BG)
        try:
            self.root.tk.call("tk", "scaling", 1.25)
        except Exception:
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=TEXT)
        style.configure("Root.TFrame", background=BG)
        style.configure(
            "Panel.TFrame",
            background=PANEL,
            borderwidth=1,
            relief="solid",
        )
        style.configure("PanelInner.TFrame", background=PANEL)
        style.configure(
            "Note.TFrame",
            background="#F2E9D8",
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=BG,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Note.TLabel", background="#F2E9D8", foreground=MUTED)
        style.configure("TEntry", fieldbackground="#FFFCF5", bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground="#FFFCF5")
        style.configure(
            "Primary.TButton",
            background=ACCENT,
            foreground="#FFFFFF",
            padding=(20, 11),
            font=("Microsoft YaHei UI", 11, "bold"),
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_ACTIVE), ("disabled", "#AAB59F")],
        )
        style.configure(
            "Secondary.TButton",
            background="#EDE3D2",
            foreground=TEXT,
            padding=(12, 7),
        )
        style.map("Secondary.TButton", background=[("active", "#E2D4BE")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure(
            "Story.Horizontal.TProgressbar",
            background=ACCENT,
            troughcolor="#E7DDCB",
        )

    def _build_layout(self) -> None:
        root_frame = ttk.Frame(self.root, style="Root.TFrame", padding=22)
        root_frame.pack(fill=BOTH, expand=True)

        header = ttk.Frame(root_frame, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(
            header,
            text="儿童故事视频生成器",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="导入故事文本、旁白和插图，生成带逐字同步字幕的抖音竖屏视频",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        content = ttk.Frame(root_frame, style="Root.TFrame")
        content.pack(fill=BOTH, expand=True)
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=4)
        content.rowconfigure(0, weight=1)

        left = ttk.Frame(content, style="Panel.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(content, style="Panel.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._build_import_panel(left)
        self._build_options_panel(right)

        footer = ttk.Frame(root_frame, style="Root.TFrame")
        footer.pack(fill="x", pady=(16, 0))
        self.progress = ttk.Progressbar(
            footer,
            style="Story.Horizontal.TProgressbar",
            mode="indeterminate",
        )
        self.progress.pack(fill="x")
        status_row = ttk.Frame(footer, style="Root.TFrame")
        status_row.pack(fill="x", pady=(8, 0))
        ttk.Label(
            status_row,
            textvariable=self.status_var,
            style="Subtitle.TLabel",
        ).pack(side=LEFT)
        self.open_button = ttk.Button(
            status_row,
            text="打开输出目录",
            style="Secondary.TButton",
            command=self._open_output_folder,
        )
        self.open_button.pack(side=RIGHT)
        self.generate_button = ttk.Button(
            status_row,
            text="开始生成视频",
            style="Primary.TButton",
            command=self._start_generation,
        )
        self.generate_button.pack(side=RIGHT, padx=(0, 10))

    def _build_import_panel(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="1. 导入故事素材", style="Section.TLabel").pack(
            anchor="w", pady=(0, 14)
        )
        self._file_field(
            panel,
            "故事名称",
            self.title_var,
            button_text=None,
        )
        self._file_field(
            panel,
            "故事文本",
            self.text_var,
            command=self._choose_text,
            file_label="选择 TXT",
        )
        self._file_field(
            panel,
            "旁白音频",
            self.audio_var,
            command=self._choose_audio,
            file_label="选择音频",
        )

        image_header = ttk.Frame(panel, style="PanelInner.TFrame")
        image_header.pack(fill="x", pady=(5, 7))
        ttk.Label(
            image_header,
            text="故事插图",
            style="Panel.TLabel",
        ).pack(side=LEFT)
        ttk.Label(
            image_header,
            textvariable=self.image_count_var,
            style="Muted.TLabel",
        ).pack(side=RIGHT)

        image_area = ttk.Frame(panel, style="PanelInner.TFrame")
        image_area.pack(fill=BOTH, expand=True)
        image_area.columnconfigure(0, weight=3)
        image_area.columnconfigure(1, weight=2)
        image_area.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(image_area, style="PanelInner.TFrame")
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.image_list = Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg="#FFFCF5",
            fg=TEXT,
            selectbackground="#D9E7C9",
            selectforeground=TEXT,
            borderwidth=1,
            relief="solid",
            highlightthickness=0,
            font=("Microsoft YaHei UI", 9),
        )
        scrollbar.config(command=self.image_list.yview)
        scrollbar.pack(side=RIGHT, fill="y")
        self.image_list.pack(fill=BOTH, expand=True)
        self.image_list.bind("<<ListboxSelect>>", self._show_selected_preview)

        preview_frame = ttk.Frame(image_area, style="PanelInner.TFrame")
        preview_frame.grid(row=0, column=1, sticky="nsew")
        self.preview_label = ttk.Label(
            preview_frame,
            text="选择插图后显示预览",
            style="Muted.TLabel",
            anchor="center",
        )
        self.preview_label.pack(fill=BOTH, expand=True)

        image_actions = ttk.Frame(panel, style="PanelInner.TFrame")
        image_actions.pack(fill="x", pady=(9, 0))
        for text, command in (
            ("添加图片", self._add_images),
            ("添加文件夹", self._add_folder),
            ("上移", lambda: self._move_image(-1)),
            ("下移", lambda: self._move_image(1)),
            ("删除", self._remove_image),
        ):
            ttk.Button(
                image_actions,
                text=text,
                style="Secondary.TButton",
                command=command,
            ).pack(side=LEFT, padx=(0, 6))

    def _build_options_panel(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="2. 输出设置", style="Section.TLabel").pack(
            anchor="w", pady=(0, 14)
        )
        self._file_field(
            panel,
            "输出视频",
            self.output_var,
            command=self._choose_output,
            file_label="选择位置",
        )

        option_grid = ttk.Frame(panel, style="PanelInner.TFrame")
        option_grid.pack(fill="x", pady=(4, 12))
        option_grid.columnconfigure(0, weight=1)
        option_grid.columnconfigure(1, weight=1)
        ttk.Label(option_grid, text="字幕识别模型", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(option_grid, text="视频编码器", style="Panel.TLabel").grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )
        ttk.Combobox(
            option_grid,
            textvariable=self.model_var,
            values=("tiny", "base", "small", "medium"),
            state="readonly",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Combobox(
            option_grid,
            textvariable=self.encoder_var,
            values=("auto", "x264", "nvenc"),
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(6, 0))

        checks = ttk.Frame(panel, style="PanelInner.TFrame")
        checks.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(
            checks,
            text="快速预览模式（540×960）",
            variable=self.draft_var,
            command=self._refresh_default_output,
        ).pack(anchor="w")
        ttk.Checkbutton(
            checks,
            text="忽略缓存，重新识别旁白",
            variable=self.force_var,
        ).pack(anchor="w", pady=(5, 0))

        note = (
            "AI 使用说明\n\n"
            "当前工具使用本地 faster-whisper 模型识别旁白时间，"
            "再把时间映射到你导入的原文。故事文本、音频和插图不会上传到云端。\n\n"
            "small 模型适合正式生成；tiny/base 速度更快但对齐精度较低；"
            "medium 精度更高，但首次下载和识别耗时更长。"
        )
        note_frame = ttk.Frame(panel, style="Note.TFrame", padding=(12, 10))
        note_frame.pack(fill="x", pady=(0, 14))
        ttk.Label(
            note_frame,
            text=note,
            style="Note.TLabel",
            wraplength=390,
            justify=LEFT,
        ).pack(anchor="w")

        ttk.Label(panel, text="生成日志", style="Section.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        self.log = Text(
            panel,
            height=12,
            bg="#312820",
            fg="#F7EFD9",
            insertbackground="#F7EFD9",
            borderwidth=0,
            padx=12,
            pady=10,
            wrap="word",
            state="disabled",
            font=("Cascadia Mono", 9),
        )
        self.log.pack(fill=BOTH, expand=True)

    def _file_field(
        self,
        parent: ttk.Frame,
        label: str,
        variable: StringVar,
        command=None,
        file_label: str | None = None,
        button_text: str | None = "选择",
    ) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").pack(anchor="w")
        row = ttk.Frame(parent, style="PanelInner.TFrame")
        row.pack(fill="x", pady=(6, 12))
        ttk.Entry(row, textvariable=variable).pack(
            side=LEFT,
            fill="x",
            expand=True,
        )
        visible_text = file_label or button_text
        if command and visible_text:
            ttk.Button(
                row,
                text=visible_text,
                style="Secondary.TButton",
                command=command,
            ).pack(side=RIGHT, padx=(8, 0))

    def _choose_text(self) -> None:
        path = filedialog.askopenfilename(
            title="选择故事文本",
            filetypes=(("文本文件", "*.txt"), ("所有文件", "*.*")),
        )
        if not path:
            return
        self.text_var.set(path)
        if not self.title_var.get().strip():
            self.title_var.set(Path(path).stem)
        self._refresh_default_output()

    def _choose_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="选择旁白音频",
            filetypes=(
                ("音频文件", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"),
                ("所有文件", "*.*"),
            ),
        )
        if path:
            self.audio_var.set(path)

    def _choose_output(self) -> None:
        title = self.title_var.get().strip() or "故事视频"
        path = filedialog.asksaveasfilename(
            title="选择视频输出位置",
            defaultextension=".mp4",
            initialfile=f"{title}.mp4",
            filetypes=(("MP4 视频", "*.mp4"),),
        )
        if path:
            self.output_var.set(path)

    def _add_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择故事插图",
            filetypes=(
                ("图片", "*.png *.jpg *.jpeg *.webp"),
                ("所有文件", "*.*"),
            ),
        )
        self._append_images(Path(path) for path in paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择插图文件夹")
        if not folder:
            return
        paths = sorted(
            (
                path
                for path in Path(folder).iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ),
            key=natural_key,
        )
        self._append_images(paths)

    def _append_images(self, paths) -> None:
        existing = {path.resolve() for path in self.images}
        for path in paths:
            resolved = path.resolve()
            if resolved not in existing and resolved.suffix.lower() in IMAGE_EXTENSIONS:
                self.images.append(resolved)
                existing.add(resolved)
        self._refresh_image_list()

    def _refresh_image_list(self, selected: int | None = None) -> None:
        self.image_list.delete(0, END)
        for index, path in enumerate(self.images, start=1):
            self.image_list.insert(END, f"{index:02d}  {path.name}")
        self.image_count_var.set(
            f"共 {len(self.images)} 张" if self.images else "未添加插图"
        )
        if self.images:
            target = min(selected if selected is not None else 0, len(self.images) - 1)
            self.image_list.selection_set(target)
            self.image_list.see(target)
            self._render_preview(self.images[target])
        else:
            self.preview_photo = None
            self.preview_label.configure(
                image="",
                text="选择插图后显示预览",
            )

    def _move_image(self, offset: int) -> None:
        selection = self.image_list.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + offset
        if target < 0 or target >= len(self.images):
            return
        self.images[index], self.images[target] = self.images[target], self.images[index]
        self._refresh_image_list(target)

    def _remove_image(self) -> None:
        selection = self.image_list.curselection()
        if not selection:
            return
        index = selection[0]
        del self.images[index]
        self._refresh_image_list(max(0, index - 1))

    def _show_selected_preview(self, _event=None) -> None:
        selection = self.image_list.curselection()
        if selection:
            self._render_preview(self.images[selection[0]])

    def _render_preview(self, path: Path) -> None:
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((230, 320), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_photo, text="")
        except OSError:
            self.preview_label.configure(image="", text="无法预览该图片")

    def _refresh_default_output(self) -> None:
        title = self.title_var.get().strip()
        current = Path(self.output_var.get()) if self.output_var.get() else None
        if not title or (current and current.parent != self.project_root / "output"):
            return
        suffix = "_draft" if self.draft_var.get() else ""
        self.output_var.set(
            str(self.project_root / "output" / f"{title}{suffix}.mp4")
        )

    def _validate_inputs(self) -> tuple[StoryAssets, Path]:
        title = self.title_var.get().strip()
        text_path = Path(self.text_var.get().strip())
        audio_path = Path(self.audio_var.get().strip())
        output_path = Path(self.output_var.get().strip())
        errors: list[str] = []
        if not title:
            errors.append("请输入故事名称。")
        if not text_path.is_file():
            errors.append("请选择有效的故事文本。")
        if not audio_path.is_file():
            errors.append("请选择有效的旁白音频。")
        if not self.images:
            errors.append("至少添加一张故事插图。")
        if not output_path.name:
            errors.append("请选择视频输出位置。")
        if errors:
            raise ValueError("\n".join(errors))
        if output_path.suffix.lower() != ".mp4":
            output_path = output_path.with_suffix(".mp4")
            self.output_var.set(str(output_path))
        return StoryAssets(title, text_path, audio_path, list(self.images)), output_path

    def _start_generation(self) -> None:
        if self.running:
            return
        try:
            assets, output_path = self._validate_inputs()
        except ValueError as error:
            messagebox.showerror("素材不完整", str(error), parent=self.root)
            return

        self.running = True
        self.generate_button.configure(state="disabled")
        self.progress.start(10)
        self.status_var.set("正在准备生成")
        self._append_log("开始生成，请保持程序运行。")

        worker = threading.Thread(
            target=self._generate_worker,
            args=(
                assets,
                output_path,
                self.model_var.get(),
                self.encoder_var.get(),
                self.draft_var.get(),
                self.force_var.get(),
            ),
            daemon=True,
        )
        worker.start()

    def _generate_worker(
        self,
        assets: StoryAssets,
        output_path: Path,
        model: str,
        encoder: str,
        draft: bool,
        force_transcribe: bool,
    ) -> None:
        try:
            report = generate_story_video(
                assets,
                self.project_root,
                output_path,
                model=model,
                encoder=encoder,
                draft=draft,
                force_transcribe=force_transcribe,
                on_status=lambda message: self.events.put(("status", message)),
            )
            self.events.put(("success", report))
        except Exception as error:
            self.events.put(
                (
                    "error",
                    {
                        "message": str(error),
                        "traceback": traceback.format_exc(),
                    },
                )
            )

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    message = str(payload)
                    self.status_var.set(message)
                    self._append_log(message)
                elif event == "success":
                    self._finish_success(payload)
                elif event == "error":
                    self._finish_error(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def _finish_success(self, report: object) -> None:
        self.running = False
        self.progress.stop()
        self.generate_button.configure(state="normal")
        data = report if isinstance(report, dict) else {}
        ratio = float(data.get("text_audio_match_ratio", 0)) * 100
        self.status_var.set("生成完成")
        self._append_log(
            f"生成完成。字幕匹配率 {ratio:.2f}%，输出：{data.get('output', '')}"
        )
        messagebox.showinfo(
            "生成完成",
            f"视频已生成。\n字幕匹配率：{ratio:.2f}%\n\n{data.get('output', '')}",
            parent=self.root,
        )

    def _finish_error(self, payload: object) -> None:
        self.running = False
        self.progress.stop()
        self.generate_button.configure(state="normal")
        data = payload if isinstance(payload, dict) else {}
        message = str(data.get("message", "生成失败"))
        self.status_var.set("生成失败")
        self._append_log(str(data.get("traceback", message)))
        messagebox.showerror("生成失败", message, parent=self.root)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(END, message.rstrip() + "\n")
        self.log.see(END)
        self.log.configure(state="disabled")

    def _open_output_folder(self) -> None:
        output = Path(self.output_var.get().strip())
        folder = output.parent if output.parent != Path(".") else self.project_root / "output"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)


def main() -> None:
    root = Tk()
    StoryVideoApp(root)
    root.mainloop()

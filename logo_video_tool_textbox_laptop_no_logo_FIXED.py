
import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    raise SystemExit("Thiếu Pillow. Hãy chạy: python -m pip install pillow")

APP_TITLE = "Logo Video Tool"
VIDEO_EXTS = [("Video", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("Tất cả", "*.*")]
IMAGE_EXTS = [("Ảnh logo", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tất cả", "*.*")]

def find_executable(name):
    p = shutil.which(name)
    if p:
        return p
    candidates = [
        Path(sys.executable).parent / name,
        Path.cwd() / name,
        Path.cwd() / "ffmpeg" / "bin" / name,
    ]
    for c in candidates:
        if os.name == "nt" and c.suffix.lower() != ".exe":
            c = c.with_suffix(".exe")
        if c.exists():
            return str(c)
    return None

FFMPEG = find_executable("ffmpeg")
FFPROBE = find_executable("ffprobe")

class LogoVideoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x680")
        self.minsize(900, 560)

        self.video_path = tk.StringVar()
        self.logo_path = tk.StringVar()
        self.output_path = tk.StringVar()

        self.video_w = 1920
        self.video_h = 1080
        self.display_w = 800
        self.display_h = 450
        self.logo_source = None
        self.logo_tk = None
        self.frame_tk = None

        self.logo_x = 50
        self.logo_y = 50
        self.logo_percent = 20.0
        self.logo_opacity = 100

        # Chế độ xóa logo bằng FFmpeg delogo.
        # Đây là nội suy vùng xung quanh, không phải phục hồi AI.
        self.remove_logo_enabled = False
        self.remove_x = 50
        self.remove_y = 50
        self.remove_w_percent = 20.0
        self.remove_h_percent = 12.0

        # Text + background box (dùng để che logo/chữ khác)
        self.overlay_text = ""
        self.text_font_size = 48
        self.text_opacity = 100
        self.text_box_opacity = 100
        self.text_x = 50
        self.text_y = 50
        self.text_padding_x = 40
        self.text_padding_y = 18
        self.text_color = (255, 255, 255, 255)
        self.text_box_color = (0, 0, 0, 255)

        self.dragging = False
        self.drag_target = None
        self.drag_offset = (0, 0)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)

        if not FFMPEG:
            self.status_var.set("Chưa tìm thấy FFmpeg. Đặt ffmpeg.exe trong PATH hoặc thư mục ffmpeg/bin.")
        else:
            self.status_var.set("Sẵn sàng.")

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        except Exception:
            pass

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Video:").grid(row=0, column=0, sticky="w", padx=(0,6), pady=4)
        ttk.Entry(top, textvariable=self.video_path).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="Chọn video", command=self.choose_video).grid(row=0, column=2, padx=6)

        ttk.Label(top, text="Logo:").grid(row=1, column=0, sticky="w", padx=(0,6), pady=4)
        ttk.Entry(top, textvariable=self.logo_path).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="Chọn ảnh logo", command=self.choose_logo).grid(row=1, column=2, padx=6)

        ttk.Label(top, text="Xuất:").grid(row=2, column=0, sticky="w", padx=(0,6), pady=4)
        ttk.Entry(top, textvariable=self.output_path).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="Chọn nơi lưu", command=self.choose_output).grid(row=2, column=2, padx=6)
        top.columnconfigure(1, weight=1)

        body = ttk.Frame(self, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        # Panel bên phải có thanh cuộn để dùng tốt trên laptop màn hình thấp.
        right_outer = ttk.Frame(body, width=285)
        right_outer.pack(side="right", fill="y", padx=(10, 0))
        right_outer.pack_propagate(False)

        right_canvas = tk.Canvas(right_outer, highlightthickness=0, width=265)
        right_scroll = ttk.Scrollbar(right_outer, orient="vertical", command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scroll.pack(side="right", fill="y")

        right = ttk.LabelFrame(right_canvas, text="Chỉnh logo / Text", padding=10)
        right_window = right_canvas.create_window((0, 0), window=right, anchor="nw")

        def _right_panel_configure(_event=None):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))

        def _right_panel_width(_event):
            right_canvas.itemconfigure(right_window, width=right_canvas.winfo_width())

        right.bind("<Configure>", _right_panel_configure)
        right_canvas.bind("<Configure>", _right_panel_width)

        def _right_mousewheel(event):
            right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        right_canvas.bind("<MouseWheel>", _right_mousewheel)
        right.bind("<MouseWheel>", _right_mousewheel)

        self.canvas = tk.Canvas(left, bg="#202020", highlightthickness=1, highlightbackground="#555")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        ttk.Label(right, text="Kéo logo trực tiếp trên khung video", wraplength=245).pack(anchor="w", pady=(0,8))

        ttk.Label(right, text="Kích thước logo (%)").pack(anchor="w")
        self.size_scale = ttk.Scale(right, from_=3, to=80, orient="horizontal",
                                    command=self._size_changed)
        self.size_scale.set(self.logo_percent)
        self.size_scale.pack(fill="x", pady=(4,12))
        self.size_label = ttk.Label(right, text=f"{self.logo_percent:.0f}%")
        self.size_label.pack(anchor="e")

        ttk.Label(right, text="Độ trong suốt (%)").pack(anchor="w", pady=(8,0))
        self.opacity_scale = ttk.Scale(right, from_=10, to=100, orient="horizontal",
                                       command=self._opacity_changed)
        self.opacity_scale.set(self.logo_opacity)
        self.opacity_scale.pack(fill="x", pady=(4,12))
        self.opacity_label = ttk.Label(right, text=f"{self.logo_opacity}%")
        self.opacity_label.pack(anchor="e")

        ttk.Separator(right).pack(fill="x", pady=10)

        # XÓA LOGO CŨ
        ttk.Label(right, text="XÓA LOGO CŨ", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.remove_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            right,
            text="Bật xóa logo bằng delogo",
            variable=self.remove_var,
            command=self._toggle_remove_logo
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(right, text="Chiều rộng vùng xóa (%)").pack(anchor="w")
        self.remove_w_scale = ttk.Scale(
            right, from_=3, to=80, orient="horizontal",
            command=self._remove_w_changed
        )
        self.remove_w_scale.set(self.remove_w_percent)
        self.remove_w_scale.pack(fill="x", pady=(4, 6))
        self.remove_w_label = ttk.Label(right, text=f"{self.remove_w_percent:.0f}%")
        self.remove_w_label.pack(anchor="e")

        ttk.Label(right, text="Chiều cao vùng xóa (%)").pack(anchor="w", pady=(6, 0))
        self.remove_h_scale = ttk.Scale(
            right, from_=2, to=50, orient="horizontal",
            command=self._remove_h_changed
        )
        self.remove_h_scale.set(self.remove_h_percent)
        self.remove_h_scale.pack(fill="x", pady=(4, 6))
        self.remove_h_label = ttk.Label(right, text=f"{self.remove_h_percent:.0f}%")
        self.remove_h_label.pack(anchor="e")

        ttk.Button(
            right, text="Đặt vùng xóa theo logo",
            command=self.set_remove_region_from_logo
        ).pack(fill="x", pady=3)

        ttk.Label(
            right,
            text="Kéo khung màu vàng trên video để đặt đúng vị trí logo cần xóa.",
            wraplength=230
        ).pack(anchor="w", pady=(4, 0))

        ttk.Separator(right).pack(fill="x", pady=12)

        # TEXT + KHUNG CHE LOGO
        ttk.Label(right, text="Text + KHUNG CHE LOGO", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(right, text="Khung đen sẽ che nội dung phía sau; kéo trực tiếp khung để di chuyển.", wraplength=230).pack(anchor="w", pady=(0, 6))
        self.text_entry = ttk.Entry(right)
        self.text_entry.insert(0, "")
        self.text_entry.pack(fill="x", pady=(0, 8))
        self.text_entry.bind("<KeyRelease>", lambda _e: self._text_changed())

        ttk.Label(right, text="Cỡ chữ").pack(anchor="w")
        self.text_size_scale = ttk.Scale(right, from_=16, to=140, orient="horizontal",
                                         command=self._text_size_changed)
        self.text_size_scale.set(self.text_font_size)
        self.text_size_scale.pack(fill="x", pady=(4, 8))
        self.text_size_label = ttk.Label(right, text=f"{self.text_font_size}px")
        self.text_size_label.pack(anchor="e")

        ttk.Label(right, text="Độ đậm của khung (%)").pack(anchor="w", pady=(6, 0))
        self.text_box_opacity_scale = ttk.Scale(right, from_=10, to=100, orient="horizontal",
                                                command=self._text_box_opacity_changed)
        self.text_box_opacity_scale.set(self.text_box_opacity)
        self.text_box_opacity_scale.pack(fill="x", pady=(4, 8))
        self.text_box_opacity_label = ttk.Label(right, text=f"{self.text_box_opacity}%")
        self.text_box_opacity_label.pack(anchor="e")

        ttk.Label(right, text="Độ đậm chữ (%)").pack(anchor="w", pady=(6, 0))
        self.text_opacity_scale = ttk.Scale(right, from_=10, to=100, orient="horizontal",
                                            command=self._text_opacity_changed)
        self.text_opacity_scale.set(self.text_opacity)
        self.text_opacity_scale.pack(fill="x", pady=(4, 8))
        self.text_opacity_label = ttk.Label(right, text=f"{self.text_opacity}%")
        self.text_opacity_label.pack(anchor="e")

        ttk.Button(right, text="Đặt text góc trên trái",
                   command=lambda:self.set_text_corner("tl")).pack(fill="x", pady=2)
        ttk.Button(right, text="Đặt text góc trên phải",
                   command=lambda:self.set_text_corner("tr")).pack(fill="x", pady=2)
        ttk.Button(right, text="Đặt text góc dưới trái",
                   command=lambda:self.set_text_corner("bl")).pack(fill="x", pady=2)
        ttk.Button(right, text="Đặt text góc dưới phải",
                   command=lambda:self.set_text_corner("br")).pack(fill="x", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)

        ttk.Button(right, text="Góc trên trái", command=lambda:self.set_corner("tl")).pack(fill="x", pady=3)
        ttk.Button(right, text="Góc trên phải", command=lambda:self.set_corner("tr")).pack(fill="x", pady=3)
        ttk.Button(right, text="Góc dưới trái", command=lambda:self.set_corner("bl")).pack(fill="x", pady=3)
        ttk.Button(right, text="Góc dưới phải", command=lambda:self.set_corner("br")).pack(fill="x", pady=3)
        ttk.Button(right, text="Chính giữa", command=lambda:self.set_corner("c")).pack(fill="x", pady=3)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Button(right, text="Làm mới khung xem", command=self.refresh_preview).pack(fill="x", pady=3)

        ttk.Button(right, text="XUẤT VIDEO", style="Accent.TButton",
                   command=self.export_video).pack(fill="x", pady=(18,4), ipady=8)

        self.status_var = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=6).pack(fill="x", side="bottom")

    def choose_video(self):
        p = filedialog.askopenfilename(title="Chọn video", filetypes=VIDEO_EXTS)
        if p:
            self.video_path.set(p)
            base = os.path.splitext(p)[0]
            self.output_path.set(base + "_LOGO.mp4")
            self.load_video_preview()

    def choose_logo(self):
        p = filedialog.askopenfilename(title="Chọn ảnh logo", filetypes=IMAGE_EXTS)
        if p:
            self.logo_path.set(p)
            self.load_logo()

    def choose_output(self):
        p = filedialog.asksaveasfilename(
            title="Lưu video xuất",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("MOV", "*.mov")]
        )
        if p:
            self.output_path.set(p)

    def _toggle_remove_logo(self):
        self.remove_logo_enabled = bool(self.remove_var.get())
        if self.remove_logo_enabled:
            video = self.video_path.get().strip()
            if video:
                base = os.path.splitext(video)[0]
                self.output_path.set(base + "_NOLOGO.mp4")
            self.status_var.set(
                "Đã bật xóa logo. Kéo khung màu vàng đến logo cần xóa."
            )
        else:
            video = self.video_path.get().strip()
            if video:
                base = os.path.splitext(video)[0]
                self.output_path.set(base + "_LOGO.mp4")
            self.status_var.set("Đã tắt xóa logo.")
        self.refresh_preview()

    def _remove_w_changed(self, value):
        self.remove_w_percent = float(value)
        self.remove_w_label.config(text=f"{self.remove_w_percent:.0f}%")
        self._clamp_remove_region()
        self.refresh_preview()

    def _remove_h_changed(self, value):
        self.remove_h_percent = float(value)
        self.remove_h_label.config(text=f"{self.remove_h_percent:.0f}%")
        self._clamp_remove_region()
        self.refresh_preview()

    def _remove_region_px(self):
        # Keep a small safety margin because FFmpeg delogo internally
        # expands the requested area by its interpolation band. If the
        # area touches the frame edge, delogo can return AVERROR(EINVAL)
        # (-22 / 4294967274).
        max_w = max(8, self.video_w - 4)
        max_h = max(8, self.video_h - 4)
        w = min(max(8, int(self.video_w * self.remove_w_percent / 100.0)), max_w)
        h = min(max(8, int(self.video_h * self.remove_h_percent / 100.0)), max_h)
        return w, h

    def _clamp_remove_region(self):
        w, h = self._remove_region_px()
        # delogo adds an internal 1-pixel band around the requested area.
        # Avoid x/y == 0 and avoid placing the right/bottom edge exactly
        # on the frame boundary.
        max_x = max(1, self.video_w - w - 2)
        max_y = max(1, self.video_h - h - 2)
        self.remove_x = max(1, min(max_x, int(self.remove_x)))
        self.remove_y = max(1, min(max_y, int(self.remove_y)))

    def _remove_preview_rect(self):
        if not self.remove_logo_enabled or not hasattr(self, "frame_image"):
            return None
        x0, y0, dw, dh = self._canvas_rect()
        rw, rh = self._remove_region_px()
        sx = dw / max(1, self.video_w)
        sy = dh / max(1, self.video_h)
        px = x0 + int(self.remove_x * sx)
        py = y0 + int(self.remove_y * sy)
        pw = max(1, int(rw * sx))
        ph = max(1, int(rh * sy))
        return px, py, px + pw, py + ph

    def set_remove_region_from_logo(self):
        if not self.logo_source:
            messagebox.showwarning(
                "Chưa có logo",
                "Hãy chọn ảnh logo trước để lấy kích thước vùng xóa."
            )
            return
        target_w = max(10, int(self.video_w * self.logo_percent / 100.0))
        target_h = max(10, int(target_w * self.logo_source.height / max(1, self.logo_source.width)))
        self.remove_w_percent = max(3.0, min(80.0, target_w / max(1, self.video_w) * 100.0))
        self.remove_h_percent = max(2.0, min(50.0, target_h / max(1, self.video_h) * 100.0))
        self.remove_w_scale.set(self.remove_w_percent)
        self.remove_h_scale.set(self.remove_h_percent)
        self.remove_w_label.config(text=f"{self.remove_w_percent:.0f}%")
        self.remove_h_label.config(text=f"{self.remove_h_percent:.0f}%")
        self.remove_x = self.logo_x
        self.remove_y = self.logo_y
        self._clamp_remove_region()
        self.remove_logo_enabled = True
        self.remove_var.set(True)
        video = self.video_path.get().strip()
        if video:
            self.output_path.set(os.path.splitext(video)[0] + "_NOLOGO.mp4")
        self.status_var.set("Đã lấy vùng xóa theo vị trí/kích thước logo hiện tại.")
        self.refresh_preview()

    def _probe_video(self, p):
        if not FFPROBE:
            return None
        cmd = [
            FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", p
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            data = json.loads(out)
            st = data["streams"][0]
            return int(st["width"]), int(st["height"])
        except Exception:
            return None

    def _probe_video_bitrate(self, p):
        """Return source video bitrate (bits/sec) when available."""
        if not FFPROBE:
            return None
        cmd = [
            FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", p
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
            br = int(float(out))
            if 100_000 <= br <= 100_000_000:
                return br
        except Exception:
            pass
        return None

    def _probe_duration(self, p):
        """Return source container duration in seconds."""
        if not FFPROBE:
            return None
        cmd = [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", p
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
            duration = float(out)
            if duration > 0:
                return duration
        except Exception:
            pass
        return None

    def _probe_audio_stream(self, p):
        """Choose the best audio stream: prefer default, then the longest track."""
        if not FFPROBE:
            return None
        cmd = [
            FFPROBE, "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index,codec_name,channels,sample_rate,duration:stream_disposition=default",
            "-of", "json", p
        ]
        try:
            data = json.loads(subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True))
            streams = data.get("streams", [])
            if not streams:
                return None

            def dur(s):
                try:
                    return float(s.get("duration"))
                except (TypeError, ValueError):
                    return -1.0

            default_streams = [s for s in streams if int(s.get("disposition", {}).get("default", 0)) == 1]
            pool = default_streams if default_streams else streams
            # If a default track is unexpectedly short, prefer the longest audio track.
            chosen = max(pool, key=dur)
            longest = max(streams, key=dur)
            if dur(chosen) < dur(longest) - 5:
                chosen = longest
            return int(chosen["index"])
        except Exception:
            return None

    def load_video_preview(self):
        p = self.video_path.get().strip()
        if not p or not os.path.isfile(p):
            return
        dims = self._probe_video(p)
        if dims:
            self.video_w, self.video_h = dims

        # Extract one representative frame for positioning.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.close()
        try:
            cmd = [
                FFMPEG, "-y", "-ss", "1", "-i", p,
                "-frames:v", "1", "-vf", "scale=1280:-2",
                "-q:v", "3", tmp.name
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            self.frame_image = Image.open(tmp.name).convert("RGB")
            self.frame_image.load()
            self.refresh_preview()
            self.status_var.set(f"Đã tải video: {self.video_w}x{self.video_h}. Kéo logo trên khung xem.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể đọc khung video:\n{e}")
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass

    def load_logo(self):
        p = self.logo_path.get().strip()
        if not p or not os.path.isfile(p):
            return
        try:
            self.logo_source = Image.open(p).convert("RGBA")
            self.refresh_preview()
            self.status_var.set("Đã tải logo. Có thể kéo-thả logo trên video.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể mở logo:\n{e}")

    def _canvas_rect(self):
        cw = max(10, self.canvas.winfo_width())
        ch = max(10, self.canvas.winfo_height())
        if not hasattr(self, "frame_image"):
            return 0, 0, cw, ch
        fw, fh = self.frame_image.size
        ratio = min(cw/fw, ch/fh)
        dw, dh = int(fw*ratio), int(fh*ratio)
        x0 = (cw-dw)//2
        y0 = (ch-dh)//2
        self.display_w, self.display_h = dw, dh
        return x0, y0, dw, dh

    def refresh_preview(self):
        self.canvas.delete("all")
        if not hasattr(self, "frame_image"):
            self.canvas.create_text(self.canvas.winfo_width()//2, self.canvas.winfo_height()//2,
                                    text="Chọn video để xem trước", fill="white",
                                    font=("Segoe UI", 16))
            return

        x0, y0, dw, dh = self._canvas_rect()
        frame = self.frame_image.resize((dw, dh), Image.LANCZOS)
        self.frame_tk = ImageTk.PhotoImage(frame)
        self.canvas.create_image(x0, y0, image=self.frame_tk, anchor="nw")

        # Khung vùng xóa logo cũ
        rrect = self._remove_preview_rect()
        if rrect:
            rx1, ry1, rx2, ry2 = rrect
            self.canvas.create_rectangle(
                rx1, ry1, rx2, ry2,
                outline="#ffd54a", width=3, dash=(7, 4), tags="remove_box"
            )
            self.canvas.create_text(
                (rx1 + rx2) // 2,
                (ry1 + ry2) // 2,
                text="XÓA LOGO",
                fill="#ffd54a",
                font=("Segoe UI", 10, "bold"),
                tags="remove_box"
            )

        if self.logo_source and not self.remove_logo_enabled:
            # Logo size is a percentage of the video width.
            target_w = max(10, int(self.video_w * self.logo_percent / 100.0))
            lr = self.logo_source.height / max(1, self.logo_source.width)
            target_h = max(10, int(target_w * lr))
            logo = self.logo_source.resize((target_w, target_h), Image.LANCZOS)
            if self.logo_opacity < 100:
                a = logo.getchannel("A").point(lambda v: int(v * self.logo_opacity / 100))
                logo.putalpha(a)

            # Convert video-space position -> preview-space position.
            sx = dw / max(1, self.video_w)
            sy = dh / max(1, self.video_h)
            px = x0 + int(self.logo_x * sx)
            py = y0 + int(self.logo_y * sy)
            pw = max(1, int(target_w * sx))
            ph = max(1, int(target_h * sy))
            logo = logo.resize((pw, ph), Image.LANCZOS)

            self.logo_tk = ImageTk.PhotoImage(logo)
            self.canvas.create_image(px, py, image=self.logo_tk, anchor="nw", tags="logo")
            self.canvas.create_rectangle(px, py, px+pw, py+ph, outline="white", width=1, tags="logo_box")

        # Vẽ text + khung nền để che logo/chữ khác trong phần preview
        if self.overlay_text:
            rect = self._text_preview_rect()
            if rect:
                tx1, ty1, tx2, ty2 = rect
                self.canvas.create_rectangle(
                    tx1, ty1, tx2, ty2,
                    fill="#000000",
                    outline="white",
                    width=1,
                    tags="text_box"
                )
                self.canvas.create_text(
                    (tx1+tx2)//2, (ty1+ty2)//2,
                    text=self.overlay_text,
                    fill="white",
                    font=("Segoe UI", max(8, int(self.text_font_size * self.display_w / max(1, self.video_w)))),
                    tags="overlay_text"
                )

    def _on_canvas_resize(self, _event):
        self.refresh_preview()

    def _size_changed(self, value):
        self.logo_percent = float(value)
        self.size_label.config(text=f"{self.logo_percent:.0f}%")
        self.refresh_preview()

    def _opacity_changed(self, value):
        self.logo_opacity = int(float(value))
        self.opacity_label.config(text=f"{self.logo_opacity}%")
        self.refresh_preview()

    def _event_to_video_xy(self, event):
        x0, y0, dw, dh = self._canvas_rect()
        x = min(max(event.x - x0, 0), dw)
        y = min(max(event.y - y0, 0), dh)
        vx = x * self.video_w / max(1, dw)
        vy = y * self.video_h / max(1, dh)
        return vx, vy

    def _logo_preview_rect(self):
        if not self.logo_source or not hasattr(self, "frame_image"):
            return None
        x0, y0, dw, dh = self._canvas_rect()
        target_w = max(10, int(self.video_w * self.logo_percent / 100.0))
        lr = self.logo_source.height / max(1, self.logo_source.width)
        target_h = max(10, int(target_w * lr))
        sx = dw / max(1, self.video_w)
        sy = dh / max(1, self.video_h)
        px = x0 + int(self.logo_x * sx)
        py = y0 + int(self.logo_y * sy)
        pw = max(1, int(target_w * sx))
        ph = max(1, int(target_h * sy))
        return px, py, px+pw, py+ph

    def _on_drag_start(self, event):
        # Khi bật xóa logo, ưu tiên kéo vùng xóa màu vàng.
        rrect = self._remove_preview_rect()
        if rrect:
            rx1, ry1, rx2, ry2 = rrect
            if rx1 <= event.x <= rx2 and ry1 <= event.y <= ry2:
                self.dragging = True
                self.drag_target = "remove"
                self.drag_offset = (event.x - rx1, event.y - ry1)
                return

        # Ưu tiên text box: click ở bất kỳ đâu trong khung đen đều kéo được cả khung + chữ.
        trect = self._text_preview_rect()
        if trect:
            tx1, ty1, tx2, ty2 = trect
            if tx1 <= event.x <= tx2 and ty1 <= event.y <= ty2:
                self.dragging = True
                self.drag_target = "text"
                self.drag_offset = (event.x-tx1, event.y-ty1)
                return

        rect = self._logo_preview_rect()
        if rect:
            x1,y1,x2,y2 = rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.dragging = True
                self.drag_target = "logo"
                self.drag_offset = (event.x-x1, event.y-y1)

    def _on_drag(self, event):
        if not self.dragging:
            return
        x0, y0, dw, dh = self._canvas_rect()
        ox, oy = self.drag_offset
        px = min(max(event.x - ox, x0), x0 + dw)
        py = min(max(event.y - oy, y0), y0 + dh)

        if self.drag_target == "remove" and self.remove_logo_enabled:
            rw, rh = self._remove_region_px()
            new_x = int((px - x0) * self.video_w / max(1, dw))
            new_y = int((py - y0) * self.video_h / max(1, dh))
            self.remove_x = max(0, min(max(0, self.video_w - rw), new_x))
            self.remove_y = max(0, min(max(0, self.video_h - rh), new_y))
        elif self.drag_target == "logo" and self.logo_source:
            self.logo_x = max(0, min(self.video_w, int((px-x0) * self.video_w / max(1,dw))))
            self.logo_y = max(0, min(self.video_h, int((py-y0) * self.video_h / max(1,dh))))
        elif self.drag_target == "text":
            bw, bh = self._text_size_px()
            new_x = int((px-x0) * self.video_w / max(1,dw))
            new_y = int((py-y0) * self.video_h / max(1,dh))
            # Không cho khung text bị kéo ra ngoài video.
            self.text_x = max(0, min(max(0, self.video_w-bw), new_x))
            self.text_y = max(0, min(max(0, self.video_h-bh), new_y))
        self.refresh_preview()

    def _on_drag_end(self, _event):
        self.dragging = False
        self.drag_target = None

    def _text_changed(self):
        self.overlay_text = self.text_entry.get()
        self.refresh_preview()

    def _text_size_changed(self, value):
        self.text_font_size = int(float(value))
        self.text_size_label.config(text=f"{self.text_font_size}px")
        self.refresh_preview()

    def _text_box_opacity_changed(self, value):
        self.text_box_opacity = int(float(value))
        self.text_box_opacity_label.config(text=f"{self.text_box_opacity}%")
        self.refresh_preview()

    def _text_opacity_changed(self, value):
        self.text_opacity = int(float(value))
        self.text_opacity_label.config(text=f"{self.text_opacity}%")
        self.refresh_preview()

    def _find_font(self):
        candidates = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "tahoma.ttf",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _text_size_px(self):
        if not self.overlay_text:
            return 0, 0
        try:
            from PIL import ImageFont
            font_path = self._find_font()
            if font_path:
                font = ImageFont.truetype(font_path, self.text_font_size)
            else:
                font = ImageFont.load_default()
            bbox = font.getbbox(self.overlay_text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            return tw + self.text_padding_x * 2, th + self.text_padding_y * 2
        except Exception:
            return max(80, len(self.overlay_text) * self.text_font_size // 2), self.text_font_size + 36

    def _text_preview_rect(self):
        if not self.overlay_text or not hasattr(self, "frame_image"):
            return None
        x0, y0, dw, dh = self._canvas_rect()
        bw, bh = self._text_size_px()
        sx = dw / max(1, self.video_w)
        sy = dh / max(1, self.video_h)
        px = x0 + int(self.text_x * sx)
        py = y0 + int(self.text_y * sy)
        pw = max(1, int(bw * sx))
        ph = max(1, int(bh * sy))
        return px, py, px + pw, py + ph

    def set_text_corner(self, corner):
        if not self.overlay_text:
            return
        bw, bh = self._text_size_px()
        margin = max(10, int(min(self.video_w, self.video_h) * 0.02))
        if corner == "tl":
            self.text_x, self.text_y = margin, margin
        elif corner == "tr":
            self.text_x, self.text_y = max(0, self.video_w-bw-margin), margin
        elif corner == "bl":
            self.text_x, self.text_y = margin, max(0, self.video_h-bh-margin)
        elif corner == "br":
            self.text_x, self.text_y = max(0, self.video_w-bw-margin), max(0, self.video_h-bh-margin)
        self.refresh_preview()

    def set_corner(self, corner):
        if not self.logo_source:
            return
        target_w = max(10, int(self.video_w * self.logo_percent / 100.0))
        target_h = int(target_w * self.logo_source.height / max(1, self.logo_source.width))
        margin = max(10, int(min(self.video_w, self.video_h) * 0.02))
        if corner == "tl":
            self.logo_x, self.logo_y = margin, margin
        elif corner == "tr":
            self.logo_x, self.logo_y = max(0, self.video_w-target_w-margin), margin
        elif corner == "bl":
            self.logo_x, self.logo_y = margin, max(0, self.video_h-target_h-margin)
        elif corner == "br":
            self.logo_x, self.logo_y = max(0, self.video_w-target_w-margin), max(0, self.video_h-target_h-margin)
        elif corner == "c":
            self.logo_x, self.logo_y = max(0, (self.video_w-target_w)//2), max(0, (self.video_h-target_h)//2)
        self.refresh_preview()

    def export_video(self):
        video = self.video_path.get().strip()
        logo = self.logo_path.get().strip()
        out = self.output_path.get().strip()

        if not FFMPEG:
            messagebox.showerror("Thiếu FFmpeg", "Không tìm thấy ffmpeg.exe.\n\nĐặt ffmpeg.exe vào PATH hoặc thư mục ffmpeg\\bin cạnh tool.")
            return
        if not video or not os.path.isfile(video):
            messagebox.showwarning("Thiếu video", "Hãy chọn video.")
            return
        if not self.remove_logo_enabled:
            if not logo or not os.path.isfile(logo):
                messagebox.showwarning("Thiếu logo", "Hãy chọn ảnh logo.")
                return
        if not out:
            messagebox.showwarning("Thiếu nơi lưu", "Hãy chọn nơi lưu video xuất.")
            return
        if os.path.abspath(out) == os.path.abspath(video):
            messagebox.showwarning("Không thể ghi đè", "Video xuất phải có tên khác video gốc.")
            return

        target_w = max(10, int(self.video_w * self.logo_percent / 100.0))
        target_h_expr = f"round({target_w}*ih/iw)"
        opacity = max(0.1, min(1.0, self.logo_opacity / 100.0))
        x = max(0, int(self.logo_x))
        y = max(0, int(self.logo_y))

        remove_w, remove_h = self._remove_region_px()
        # Final FFmpeg-safe clamp. This is important after loading an old
        # project/state or when the user drags the box to an edge.
        remove_x = max(1, min(max(1, self.video_w - remove_w - 2), int(self.remove_x)))
        remove_y = max(1, min(max(1, self.video_h - remove_h - 2), int(self.remove_y)))

        # Tạo PNG text + khung nền bằng Pillow để hỗ trợ tiếng Việt ổn định.
        text_overlay_path = None
        if self.overlay_text:
            from PIL import Image, ImageDraw, ImageFont

            bw, bh = self._text_size_px()
            overlay = Image.new("RGBA", (max(1, bw), max(1, bh)), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            font_path = self._find_font()
            try:
                font = ImageFont.truetype(font_path, self.text_font_size) if font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            box_a = int(255 * max(0.90, min(1.0, self.text_box_opacity / 100.0)))
            text_a = int(255 * max(0.1, min(1.0, self.text_opacity / 100.0)))

            # Khung đen gần như đặc để che logo cũ.
            draw.rounded_rectangle(
                (0, 0, bw - 1, bh - 1),
                radius=max(0, min(18, self.text_padding // 2)),
                fill=(0, 0, 0, box_a)
            )
            draw.text(
                (self.text_padding_x, self.text_padding_y),
                self.overlay_text,
                font=font,
                fill=(255, 255, 255, text_a)
            )

            tmp_overlay = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp_overlay.close()
            overlay.save(tmp_overlay.name)
            text_overlay_path = tmp_overlay.name

        duration = self._probe_duration(video)
        audio_index = self._probe_audio_stream(video)

        cmd = [FFMPEG, "-y", "-i", video]

        # Xóa logo cũ bằng delogo. Có thể kết hợp text/khung sau khi xóa.
        if self.remove_logo_enabled:
            vf_parts = [
                f"[0:v]delogo=x={remove_x}:y={remove_y}:w={remove_w}:h={remove_h}:show=0[clean]"
            ]
            current_v = "clean"
            text_input_index = None
        else:
            cmd += ["-loop", "1", "-i", logo]
            vf_parts = []
            current_v = "base"
            vf_parts.append(
                f"[1:v]scale={target_w}:{target_h_expr},format=rgba,"
                f"colorchannelmixer=aa={opacity:.4f}[logo];"
                f"[0:v][logo]overlay=x={x}:y={y}:eof_action=repeat:shortest=0:format=auto[base]"
            )
            text_input_index = 2

        if text_overlay_path:
            if not self.remove_logo_enabled:
                cmd += ["-loop", "1", "-i", text_overlay_path]
                text_input_index = 2
            else:
                cmd += ["-loop", "1", "-i", text_overlay_path]
                text_input_index = 1

            text_x = max(0, int(self.text_x))
            text_y = max(0, int(self.text_y))
            vf_parts.append(
                f"[{text_input_index}:v]format=rgba[text];"
                f"[{current_v}][text]overlay=x={text_x}:y={text_y}:"
                f"eof_action=repeat:shortest=0:format=auto[v]"
            )
            vf = ";".join(vf_parts)
        else:
            vf = ";".join(vf_parts)
            if self.remove_logo_enabled:
                # delogo output is already labeled [clean]
                vf = vf + f";[clean]null[v]"
            else:
                # Base label is [base]
                vf = vf + ";[base]null[v]"

        cmd += [
            "-filter_complex", vf,
            "-map", "[v]",
        ]

        # AUDIO FIX: copy the original AAC bitstream instead of decoding/resampling/re-encoding it.
        # This avoids introducing silence or timestamp problems in otherwise healthy source audio.
        # The user's supplied source has one AAC stereo track that runs for the full video duration.
        if audio_index is not None:
            cmd += [
                "-map", f"0:{audio_index}",
                "-c:a", "copy",
            ]

        # Keep the output video bitrate close to the source so adding a logo does not
        # inflate a small source into a multi-GB file. Fall back to CRF when bitrate is unavailable.
        source_vbitrate = self._probe_video_bitrate(video)
        cmd += [
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-map_metadata", "0",
            "-max_muxing_queue_size", "4096",
        ]
        if source_vbitrate is not None:
            target_k = max(200, int(round(source_vbitrate / 1000.0)))
            cmd += [
                "-b:v", f"{target_k}k",
                "-maxrate", f"{int(target_k * 1.15)}k",
                "-bufsize", f"{int(target_k * 2)}k",
            ]
        else:
            cmd += ["-crf", "22"]

        if duration is not None:
            # Never use -shortest: output follows the source video's duration.
            cmd += ["-t", f"{duration:.6f}"]

        cmd += [
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            out
        ]

        mode_name = "XÓA LOGO" if self.remove_logo_enabled else "LOGO"
        self.status_var.set(f"Đang xuất video... 0% | {mode_name} + text/khung | Audio giữ nguyên")
        self.update_idletasks()

        try:
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True
            )
            last_text = ""
            last_error_lines = []
            for raw in iter(p.stdout.readline, ""):
                line = raw.strip()
                if line and (
                    "Error" in line or "error" in line or
                    "Invalid" in line or "failed" in line or
                    "Failed" in line or "outside of the frame" in line
                ):
                    last_error_lines.append(line)
                    if len(last_error_lines) > 20:
                        last_error_lines.pop(0)
                if line.startswith("out_time_ms=") and duration:
                    try:
                        sec = int(line.split("=",1)[1]) / 1_000_000.0
                        pct = max(0.0, min(100.0, sec / duration * 100.0))
                        last_text = f"Đang xuất video... {pct:.1f}%"
                        self.status_var.set(last_text)
                        self.update_idletasks()
                    except Exception:
                        pass
                elif line.startswith("speed="):
                    speed = line.split("=",1)[1]
                    if last_text:
                        self.status_var.set(f"{last_text} | Tốc độ {speed} | {mode_name} + text/khung | Audio giữ nguyên")
                        self.update_idletasks()

            rc = p.wait()
            if rc != 0:
                # The process output contains both progress and FFmpeg errors.
                # Show the last useful error lines so the user can diagnose
                # future FFmpeg failures without opening a console.
                err_lines = []
                try:
                    # p.stdout is already exhausted by the loop above, but
                    # keep the collected diagnostic text in a bounded buffer.
                    pass
                except Exception:
                    pass
                detail = "FFmpeg kết thúc với mã lỗi %s." % rc
                if "last_error_lines" in locals() and last_error_lines:
                    detail += "\n\n" + "\n".join(last_error_lines[-12:])
                raise RuntimeError(detail)

            self.status_var.set("Xuất xong 100%.")
            if self.remove_logo_enabled:
                messagebox.showinfo("Hoàn tất", f"Đã xuất video đã xóa logo + text/khung:\n\n{out}")
            else:
                messagebox.showinfo("Hoàn tất", f"Đã xuất video có logo + text/khung:\n\n{out}")
        except Exception as e:
            self.status_var.set("Xuất thất bại.")
            messagebox.showerror("Lỗi FFmpeg", str(e))
        finally:
            if text_overlay_path:
                try:
                    os.unlink(text_overlay_path)
                except OSError:
                    pass

    def _close(self):
        self.destroy()

if __name__ == "__main__":
    app = LogoVideoApp()
    app.mainloop()

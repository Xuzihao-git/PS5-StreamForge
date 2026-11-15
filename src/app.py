"""Standalone Windows PS5 receiver and OBS companion. GPL-3.0-or-later."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import webbrowser

from PIL import Image, ImageTk
from engine import Engine, FrameMailbox, discover, pair
from storage import Store, normalize_account, validate_host
from obs_bridge import ObsClient, configure, window_selector, SCENE

VERSION = "0.1.0-experimental"
VIDEO_TITLE = "PS5 Live - Wireless Bridge"
BG = "#101721"
CARD = "#192433"
TEXT = "#eef4fc"
MUTED = "#a5b6c9"
ACCENT = "#69dfc0"


class App:
    def __init__(self, root, store):
        self.root = root
        self.store = store
        self.events = queue.Queue()
        self.mailbox = FrameMailbox()
        self.engine = Engine(self.mailbox, self.post_status)
        self.video = None
        self.photo = None
        self.last_count = -1
        self.busy = False
        self.closed = False
        self.last_stat = (time.monotonic(), 0)
        self.profiles = {}
        self.config = store.load_config()
        root.title("PS5 Wireless Bridge")
        root.geometry("1040x800")
        root.minsize(940, 740)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.ui_error
        self.ip = tk.StringVar(value=self.config.get("host", ""))
        self.account = tk.StringVar()
        self.pin = tk.StringVar()
        self.resolution = tk.StringVar(value=self.config.get("resolution", "720p"))
        self.fps = tk.StringVar(value=str(self.config.get("fps", 30)))
        self.bitrate = tk.StringVar(value=str(self.config.get("bitrate", 10000)))
        self.audio = tk.BooleanVar(value=True)
        self.port = tk.StringVar(value=str(self.config.get("obsPort", 4455)))
        self.password = tk.StringVar()
        self.obs_audio = tk.BooleanVar(value=True)
        self.switch_scene = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="就绪 · 请先配对 PS5")
        self.stats = tk.StringVar(value="尚未接收视频帧")
        self._theme()
        self._layout()
        try:
            self.profiles = self.store.load_profiles()
            if self.profiles:
                self.account.set(self.profiles.get("local", {}).get("id", ""))
                self.log("已读取加密配对资料，可以直接连接已配对的 PS5。")
                self.status.set("就绪 · 已有配对资料")
        except ValueError as exc:
            self.log(str(exc))
        self.log("实验版：当前 PS5 固件兼容性需实机验证；不会把等待状态显示为串流成功。")
        self.root.after(30, self.tick)

    def _theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        s.configure("Head.TLabel", font=("Microsoft YaHei UI", 13, "bold"))
        s.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(13, 8),
                    background="#293b50", foreground=TEXT, borderwidth=0)
        s.map("TButton", background=[("active", "#36516d"), ("disabled", "#202b39")])
        s.configure("Accent.TButton", background=ACCENT, foreground="#0b2b27")
        s.map("Accent.TButton", background=[("active", "#9cebd5"), ("disabled", "#35554f")])
        s.configure("TEntry", fieldbackground="#223247", foreground=TEXT, padding=7,
                    insertcolor=TEXT, bordercolor="#3a4e66")
        s.configure("TCombobox", fieldbackground="#223247", background="#293b50", foreground=TEXT, padding=6)
        s.map("TCombobox", fieldbackground=[("readonly", "#223247")], foreground=[("readonly", TEXT)])
        s.configure("TCheckbutton", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(20, 10), font=("Microsoft YaHei UI", 10))
        s.map("TNotebook.Tab", background=[("selected", "#294257")], foreground=[("selected", TEXT)])

    def _layout(self):
        outer = ttk.Frame(self.root, padding=28)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="PS5 Wireless Bridge", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="PS5  ── 同一 Wi-Fi ──  Windows 实时接收  ──  OBS", style="Muted.TLabel").pack(anchor="w", pady=(5, 6))
        ttk.Label(header, text="独立接收端  /  无需外部串流软件  /  实验版 0.1 · 固件兼容性待实机验证", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew")
        def scroll_page(title):
            page = ttk.Frame(notebook)
            canvas = tk.Canvas(page, bg=BG, highlightthickness=0, width=1, height=1)
            bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
            bar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            canvas.configure(yscrollcommand=bar.set)
            inner = ttk.Frame(canvas, padding=20)
            item = canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
            inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            def wheel(event):
                widget = self.root.winfo_containing(event.x_root, event.y_root)
                while widget:
                    if widget == page:
                        canvas.yview_scroll(int(-event.delta / 120), "units")
                        break
                    widget = getattr(widget, "master", None)
            self.root.bind_all("<MouseWheel>", wheel, add="+")
            notebook.add(page, text=title)
            return inner
        connect = scroll_page("01  连接 PS5")
        obs = scroll_page("02  接入 OBS")
        guide = ttk.Frame(notebook, padding=20)
        notebook.add(guide, text="使用说明")
        connect.columnconfigure(1, weight=1)

        ttk.Label(connect, text="主机与配对", style="Head.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))
        self.entry(connect, 1, "PS5 IPv4 地址", self.ip)
        ttk.Button(connect, text="搜索主机", command=self.scan).grid(row=1, column=2, padx=(10, 0))
        self.hosts = ttk.Combobox(connect, state="readonly")
        self.hosts.grid(row=2, column=1, columnspan=2, sticky="ew", pady=7)
        self.hosts.bind("<<ComboboxSelected>>", self.select_host)
        self.entry(connect, 3, "PSN Account-ID", self.account)
        ttk.Button(connect, text="获取账号 ID", command=self.oauth).grid(row=3, column=2, padx=(10, 0))
        ttk.Label(connect, text="支持 8 字节 Base64 或十进制账号 ID；PSN 昵称不能用于配对。", style="Muted.TLabel").grid(row=4, column=1, columnspan=2, sticky="w", pady=(0, 9))
        self.entry(connect, 5, "8 位配对码", self.pin, show="*")
        ttk.Button(connect, text="配对 PS5", command=self.register).grid(row=5, column=2, padx=(10, 0))
        ttk.Label(connect, text="PS5：设置 → 系统 → 遥控游玩 → 启用遥控游玩 → 链接设备", style="Muted.TLabel").grid(row=6, column=1, columnspan=2, sticky="w", pady=(0, 14))
        ttk.Separator(connect).grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(connect, text="接收参数", style="Head.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 10))
        options = ttk.Frame(connect)
        options.grid(row=9, column=0, columnspan=3, sticky="ew")
        for i, (label, variable, values, width) in enumerate([
            ("分辨率", self.resolution, ("540p", "720p", "1080p"), 10),
            ("帧率", self.fps, ("30", "60"), 6),
            ("码率 kbps", self.bitrate, ("4000", "6000", "10000", "15000"), 9)]):
            ttk.Label(options, text=label).grid(row=0, column=i * 2, padx=(0 if i == 0 else 18, 8))
            ttk.Combobox(options, textvariable=variable, values=values, state="readonly", width=width).grid(row=0, column=i * 2 + 1)
        ttk.Checkbutton(connect, text="播放 PS5 音频（由 Windows 默认音频设备输出）", variable=self.audio).grid(row=10, column=0, columnspan=3, sticky="w", pady=15)
        actions = ttk.Frame(connect)
        actions.grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 12))
        ttk.Button(actions, text="连接并接收画面", style="Accent.TButton", command=self.start).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="断开连接", command=self.stop).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="显示实时窗口", command=self.show_video).pack(side="left")
        ttk.Label(connect, textvariable=self.stats, style="Muted.TLabel").grid(row=12, column=0, columnspan=3, sticky="w")

        obs.columnconfigure(1, weight=1)
        ttk.Label(obs, text="自动添加画面到 OBS", style="Head.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 15))
        ttk.Label(obs, text="先在 OBS 打开：工具 → WebSocket 服务器设置 → 启用 WebSocket 服务器。\nOBS 与本工具运行在同一台 Windows 电脑；连接地址固定为 127.0.0.1。",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.entry(obs, 2, "WebSocket 端口", self.port)
        self.entry(obs, 3, "WebSocket 密码", self.password, show="*")
        ttk.Label(obs, text="密码仅用于本次运行，不保存到磁盘。", style="Muted.TLabel").grid(row=4, column=1, sticky="w", pady=(0, 14))
        ttk.Checkbutton(obs, text="请求采集本程序音频（需 OBS 和 Windows 支持）", variable=self.obs_audio).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(obs, text="配置后将 OBS 当前节目切换到新场景", variable=self.switch_scene).grid(row=6, column=0, columnspan=2, sticky="w", pady=8)
        row = ttk.Frame(obs)
        row.grid(row=7, column=0, columnspan=2, sticky="w", pady=17)
        ttk.Button(row, text="测试 OBS 连接", command=self.test_obs).pack(side="left", padx=(0, 10))
        ttk.Button(row, text="一键添加到 OBS", command=self.setup_obs, style="Accent.TButton").pack(side="left")
        ttk.Button(obs, text="保存当前真实帧 PNG", command=self.snapshot).grid(row=8, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Label(obs, text=f"管理场景：{SCENE}\n采集方式：Windows Graphics Capture，保持宽高比适配现有画布。\n请保持实时画面窗口打开，不要最小化；本工具不启动直播或录制。",
                  style="Muted.TLabel").grid(row=9, column=0, columnspan=2, sticky="w", pady=18)

        text = ("首次使用\n\n"
                "1. PS5 和 Windows 接入同一个局域网，建议使用稳定的 5 GHz / 6 GHz Wi-Fi。\n"
                "2. PS5 开启遥控游玩，进入“链接设备”，获取当前 8 位配对码。\n"
                "3. 填写 PS5 IP、PSN Account-ID 和配对码，点击“配对 PS5”。\n"
                "4. 先以 720p / 30 FPS 连接，看到真实画面后再增加分辨率或帧率。\n"
                "5. 在“接入 OBS”页输入 OBS WebSocket 密码，点击“一键添加到 OBS”。\n\n"
                "Account-ID\n\n"
                "可手动填写已有 ID，或点击“获取账号 ID”：在系统浏览器的索尼页面登录，\n"
                "将跳转后的 URL 粘贴回来。程序不接收 PSN 密码，不保存 OAuth 令牌。\n\n"
                "当前边界\n\n"
                "这是带 EXE 入口的独立接收程序，OBS 通过窗口采集接入。\n"
                "内置开源 Remote Play 协议库，协议库已停止维护；新固件可能不兼容。\n"
                "本版使用 CPU H.264 解码，未内置 FEC 丢包恢复，也不提供 HDR。\n"
                "请先使用 PS5 主机手柄操作；本版没有完整的电脑手柄转发。\n"
                "未连接实机测试，不承诺固定延迟、1080p60 性能或当前固件必然可用。")
        guide_scroll = ttk.Scrollbar(guide)
        guide_scroll.pack(side="right", fill="y")
        guide_text = tk.Text(guide, bg=BG, fg=TEXT, wrap="word", relief="flat",
            height=1, width=1, font=("Microsoft YaHei UI", 10), yscrollcommand=guide_scroll.set)
        guide_text.insert("1.0", text)
        guide_text.configure(state="disabled")
        guide_text.pack(fill="both", expand=True)
        guide_scroll.configure(command=guide_text.yview)
        footer = ttk.Frame(outer)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 6))
        ttk.Label(footer, textvariable=self.status, foreground=ACCENT, wraplength=660).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="数据目录", command=lambda: os.startfile(str(self.store.root))).pack(side="right")
        ttk.Button(footer, text="重置本机配对", command=self.reset).pack(side="right", padx=8)
        self.logbox = tk.Text(outer, height=4, bg="#0b1119", fg=MUTED, relief="flat",
                              wrap="word", font=("Microsoft YaHei UI", 9), padx=10, pady=6, state="disabled")
        self.logbox.grid(row=3, column=0, sticky="ew")

    def entry(self, parent, row, label, variable, **kwargs):
        ttk.Label(parent, text=label, width=17).grid(row=row, column=0, sticky="w", pady=7)
        ttk.Entry(parent, textvariable=variable, **kwargs).grid(row=row, column=1, sticky="ew", pady=7)

    def log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("%H:%M:%S  ") + text + "\n")
        self.logbox.see("end")
        if int(self.logbox.index("end-1c").split(".")[0]) > 100:
            self.logbox.delete("1.0", "30.0")
        self.logbox.configure(state="disabled")
        try:
            path = self.store.root / "bridge.log"
            if path.exists() and path.stat().st_size > 1_000_000:
                path.replace(path.with_suffix(".previous.log"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + text + "\n")
        except OSError:
            pass

    def post_status(self, text):
        self.events.put(("status", text))

    def job(self, label, action, done=None):
        if self.busy:
            messagebox.showinfo("请稍候", "正在执行上一项操作。")
            return
        self.busy = True
        self.status.set(label)
        self.log(label)

        def worker():
            try:
                value = action()
                self.events.put(("done", (done, value)))
            except Exception as exc:
                # Only our validation/protocol messages are presented verbatim.
                safe = str(exc) if type(exc) in (ValueError, RuntimeError) or exc.__class__.__name__ == "ObsError" else "操作失败：" + type(exc).__name__ + "。请检查网络和设置。"
                self.events.put(("error", safe))
        threading.Thread(target=worker, daemon=True).start()

    def scan(self):
        if self.engine.running:
            messagebox.showinfo("串流中", "为避免占用发现端口，请先断开再搜索；可直接使用已填 IP。")
            return
        def done(hosts):
            self.discovered = hosts
            self.hosts["values"] = [f"{h.get('host-name', 'PS5')}  |  {h['host-ip']}  |  " +
                ("在线" if h.get("status-code") == 200 else "待机") for h in hosts]
            if hosts:
                self.hosts.current(0)
                self.select_host()
                self.post_status(f"发现 {len(hosts)} 台 PS5。")
            else:
                self.post_status("未发现 PS5，可手动填 IP。请检查同一局域网、访客网络隔离及私有网络防火墙。")
        self.job("正在搜索局域网 PS5…", discover, done)

    def select_host(self, *_):
        index = self.hosts.current()
        if index >= 0 and getattr(self, "discovered", None):
            self.ip.set(self.discovered[index]["host-ip"])

    def register(self):
        if self.engine.running:
            messagebox.showinfo("串流中", "请先断开串流再配对。")
            return
        host, account, pin = self.ip.get(), self.account.get(), self.pin.get()
        def action():
            data = pair(host, account, pin, self.profiles)
            self.store.save_profiles(data)
            return data
        def done(data):
            self.profiles = data
            self.pin.set("")
            self.save_config()
            self.post_status("配对成功。资料已加密保存，可以连接 PS5。")
        self.job("正在与 PS5 配对…", action, done)

    def oauth(self):
        from pyremoteplay.oauth import get_login_url, get_user_account
        webbrowser.open(get_login_url())
        dialog = tk.Toplevel(self.root)
        dialog.title("从索尼登录页面获取 Account-ID")
        dialog.geometry("700x240")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        ttk.Label(dialog, text="请在浏览器完成 PSN 登录，然后复制跳转页面的完整 URL。\n只在索尼页面输入密码；这里仅粘贴 redirect 地址。", padding=16).pack(anchor="w")
        url = tk.StringVar()
        ttk.Entry(dialog, textvariable=url, show="*").pack(fill="x", padx=16, pady=8)
        ttk.Label(dialog, text="不保存跳转地址、OAuth 授权码或令牌。", style="Muted.TLabel", padding=16).pack(anchor="w")
        def submit():
            value = url.get().strip()
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(value)
            if parsed.scheme != "https" or parsed.netloc != "remoteplay.dl.playstation.net" or parsed.path != "/remoteplay/redirect" or not parse_qs(parsed.query).get("code"):
                messagebox.showerror("地址无效", "需要索尼 remoteplay.dl.playstation.net/remoteplay/redirect?code=… 地址。", parent=dialog)
                return
            url.set("")
            dialog.destroy()
            def done(data):
                if not data:
                    raise ValueError("索尼未返回账号 ID，请重试登录，或手动填写已有 Account-ID。")
                self.account.set(normalize_account(data["user_rpid"]))
                self.post_status("已取得 Account-ID，可以使用 PS5 配对码配对。")
            self.job("正在向索尼查询账号 ID…", lambda: get_user_account(value), done)
        ttk.Button(dialog, text="读取 Account-ID", command=submit, style="Accent.TButton").pack(anchor="e", padx=16)

    def save_config(self):
        self.store.save_config({"host": self.ip.get().strip(), "resolution": self.resolution.get(),
            "fps": int(self.fps.get()), "bitrate": int(self.bitrate.get()), "obsPort": int(self.port.get())})

    def start(self):
        if self.busy:
            messagebox.showinfo("请稍候", "正在执行配对或其他操作。")
            return
        validate_host(self.ip.get())
        self.engine.start(self.ip.get(), self.profiles, self.resolution.get(), int(self.fps.get()),
                          int(self.bitrate.get()), self.audio.get())
        self.last_count = -1
        self.last_stat = (time.monotonic(), 0)
        self.show_video()
        self.video_label.configure(image="", text="正在连接 PS5，等待真实视频帧…")
        self.photo = None
        self.save_config()
        self.post_status("正在连接 PS5…")

    def stop(self):
        self.engine.stop()
        self.post_status("正在断开…" if self.engine.running else "当前没有活动会话。")

    def show_video(self):
        if self.video is not None and self.video.winfo_exists():
            self.video.deiconify()
            self.video.lift()
            return
        self.video = tk.Toplevel(self.root)
        self.video.title(VIDEO_TITLE)
        self.video.geometry("960x540")
        self.video.minsize(480, 270)
        self.video.configure(bg="black")
        self.video_label = tk.Label(self.video, bg="black", fg=MUTED, text="等待 PS5 实时画面",
                                    font=("Microsoft YaHei UI", 16), borderwidth=0)
        self.video_label.pack(fill="both", expand=True)
        self.video.protocol("WM_DELETE_WINDOW", lambda: self.video.withdraw())
        self.last_count = -1

    def selector(self):
        self.show_video()
        self.video.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        hwnd = user32.GetAncestor(self.video.winfo_id(), 2)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, len(cls))
        exe = Path(sys.executable).name
        return window_selector(VIDEO_TITLE, cls.value, exe)

    def test_obs(self):
        port, password = int(self.port.get()), self.password.get()
        def action():
            with ObsClient(port, password) as obs:
                return obs.request("GetVersion").get("obsVersion", "未知")
        self.job("正在连接本机 OBS…", action, lambda version: self.post_status("OBS 连接成功，版本 " + version))

    def setup_obs(self):
        frame, _, received = self.mailbox.get()
        if frame is None or not self.engine.running or time.monotonic() - received > 3:
            raise ValueError("请先连接 PS5，确认实时画面窗口收到新画面后，再添加到 OBS。")
        selector = self.selector()
        port, password, audio, switch = int(self.port.get()), self.password.get(), self.obs_audio.get(), self.switch_scene.get()
        def action():
            with ObsClient(port, password) as obs:
                return configure(obs, selector, audio, switch)
        self.job("正在配置 OBS 采集场景…", action, self.post_status)

    def snapshot(self):
        frame, _, received = self.mailbox.get()
        if frame is None or time.monotonic() - received > 3:
            raise ValueError("尚无新鲜的真实视频帧，请先连接 PS5。")
        filename = filedialog.asksaveasfilename(title="保存 PS5 当前帧", defaultextension=".png",
            initialfile="PS5-" + time.strftime("%Y%m%d-%H%M%S") + ".png", filetypes=[("PNG 图像", "*.png")])
        if filename:
            frame.to_image().save(filename)
            self.post_status("已保存当前真实帧 PNG。")

    def reset(self):
        if self.engine.running or self.busy:
            raise ValueError("请先断开会话，并等待当前操作结束。")
        if messagebox.askyesno("重置本机配对", "删除本程序保存的本机配对资料？之后需要重新配对 PS5。"):
            self.store.pairing.unlink(missing_ok=True)
            self.profiles = {}
            self.account.set("")
            self.pin.set("")
            self.post_status("已清除本机配对资料。")

    def tick(self):
        if self.closed:
            return
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status.set(value)
                self.log(value)
            elif kind == "done":
                self.busy = False
                callback, result = value
                try:
                    if callback:
                        callback(result)
                except Exception as exc:
                    self.ui_error(type(exc), exc, None)
            elif kind == "error":
                self.busy = False
                self.status.set("操作未完成，请查看提示。")
                self.log(value)
                messagebox.showerror("操作未完成", value)
        frame, count, received = self.mailbox.get()
        now = time.monotonic()
        if frame is not None and count != self.last_count and self.video is not None and self.video.winfo_exists():
            width, height = max(1, self.video.winfo_width()), max(1, self.video.winfo_height())
            scale = min(width / frame.width, height / frame.height)
            # Only the preview is scaled; exported frames retain their decoded resolution.
            image = frame.reformat(width=max(1, int(frame.width * scale)), height=max(1, int(frame.height * scale)), format="rgb24").to_image()
            self.photo = ImageTk.PhotoImage(image)
            self.video_label.configure(image=self.photo, text="")
            self.last_count = count
        if now - self.last_stat[0] > 1:
            dt, previous = self.last_stat
            rate = (count - previous) / (now - dt)
            if frame is not None and now - received < 3 and self.engine.running:
                self.stats.set(f"正在接收真实画面  ·  {frame.width} × {frame.height}  ·  {rate:.1f} 解码 FPS  ·  累计 {count} 帧")
            elif frame is not None:
                self.stats.set(f"画面已停止更新  ·  上次接收于 {now - received:.0f} 秒前")
                if self.video is not None and self.video.winfo_exists():
                    self.video_label.configure(image="", text="画面已停止更新，请检查连接")
                    self.photo = None
            else:
                self.stats.set("尚未接收到真实视频帧")
            self.last_stat = (now, count)
        self.root.after(15, self.tick)

    def ui_error(self, exc_type, value, trace):
        text = str(value) if exc_type in (ValueError, RuntimeError) else "操作失败：" + exc_type.__name__ + "。请检查输入或数据目录权限。"
        self.log(text)
        messagebox.showerror("提示", text)

    def close(self):
        self.engine.stop()
        self.closed = True
        self.password.set("")
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--diagnose", metavar="JSON_PATH")
    parser.add_argument("--ui-smoke", metavar="RESULT_PATH")
    args = parser.parse_args()
    if args.diagnose:
        from diagnostics import diagnose
        Path(args.diagnose).write_text(json.dumps(diagnose(), ensure_ascii=False, indent=2), "utf-8")
        return
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72)
        app = App(root, Store(args.data_dir))
        if args.ui_smoke:
            def smoke():
                app.show_video()
                root.update_idletasks()
                result = {"version": VERSION, "main_title": root.title(), "video_title": app.video.title(),
                          "selector": app.selector(), "main_size": [root.winfo_width(), root.winfo_height()],
                          "real_frames": app.mailbox.get()[1], "engine_running": app.engine.running}
                Path(args.ui_smoke).write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
                app.close()
            root.after(800, smoke)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("PS5 Wireless Bridge 启动失败", type(exc).__name__ + ": 请检查数据目录权限或查看说明。")
        raise


if __name__ == "__main__":
    main()

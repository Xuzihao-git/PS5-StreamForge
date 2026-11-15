"""Embedded Remote Play engine. No external Remote Play application is launched."""
import asyncio
from collections import deque
import logging
import struct
import threading
import time

import av
from pyremoteplay import RPDevice
from pyremoteplay.ddp import search
from pyremoteplay.profile import Profiles, UserProfile
from pyremoteplay.receiver import AVReceiver

from storage import normalize_account, validate_host

# Upstream debug logs can contain pairing material. Keep them out of diagnostics.
logging.getLogger("pyremoteplay").disabled = True
logging.getLogger("pyremoteplay").setLevel(logging.CRITICAL + 1)
for name in ("session", "register", "oauth", "util", "crypt", "ddp", "stream", "av"):
    logging.getLogger("pyremoteplay." + name).setLevel(logging.CRITICAL + 1)


class LocalPS5(RPDevice):
    def _set_status(self, data):
        # Cover-art lookups are unrelated to local capture. Upstream schedules them
        # on an implicit event loop, which no longer exists on worker threads.
        data = dict(data or {})
        data.pop("running-app-titleid", None)
        super()._set_status(data)


def discover():
    return [x for x in search(host_type="PS5", timeout=3) if x.get("host-type", "").upper() == "PS5"]


def pair(host, account, pin, previous=None):
    host = validate_host(host)
    account = normalize_account(account)
    if not pin.isascii() or not pin.isdecimal() or len(pin) != 8:
        raise ValueError("请输入 PS5“链接设备”页面上当前显示的 8 位数字。")
    profiles = Profiles(previous or {})
    # One account per app profile, with multiple registered consoles supported.
    user = "local"
    current = profiles.get(user)
    if current and current.get("id") != account:
        raise ValueError("已保存资料属于另一账号。请先在设置中清除配对资料，再配对新账号。")
    if not current:
        profiles.update_user(UserProfile(user, {"id": account, "hosts": {}}))
    device = LocalPS5(host)
    status = device.get_status()
    if not status or status.get("host-type", "").upper() != "PS5":
        raise RuntimeError("未收到 PS5 状态。请确认 IP、同一局域网、遥控游玩及防火墙设置。")
    if status.get("status-code") != 200:
        raise RuntimeError("请先打开 PS5，再进入“设置 → 系统 → 遥控游玩 → 链接设备”。")
    profile = device.register(user, pin, timeout=10, profiles=profiles, save=False)
    if profile is None:
        raise RuntimeError("PS5 配对失败：请检查 Account-ID、8 位配对码是否正确且未过期。当前固件也可能与内置协议库不兼容。")
    return profiles.data


class FrameMailbox:
    """A single latest decoded RGB frame: bounded memory, no accumulating delay."""
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.count = 0
        self.received_at = 0.0

    def put(self, frame):
        with self.lock:
            self.frame = frame
            self.count += 1
            self.received_at = time.monotonic()

    def get(self):
        with self.lock:
            return self.frame, self.count, self.received_at

    def clear(self):
        with self.lock:
            self.frame = None
            self.count = 0
            self.received_at = 0.0


class AudioSink:
    def __init__(self, notify):
        self.queue = deque(maxlen=16)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.notify = notify
        self.thread = None

    def put(self, data):
        if self.stopped.is_set():
            return
        with self.lock:
            self.queue.append(data)
        self.ready.set()
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="PS5-audio")
            self.thread.start()

    def _run(self):
        try:
            import sounddevice as sd
            with sd.RawOutputStream(samplerate=48000, channels=2, dtype="int16", latency="low") as stream:
                while not self.stopped.is_set():
                    self.ready.wait(.1)
                    with self.lock:
                        packet = self.queue.popleft() if self.queue else None
                        if not self.queue:
                            self.ready.clear()
                    if packet:
                        stream.write(packet)
        except Exception:
            self.notify("音频设备无法打开；画面继续接收。请检查 Windows 默认输出设备后重新连接。")
            self.stopped.set()

    def close(self):
        self.stopped.set()
        self.ready.set()


class LiveReceiver(AVReceiver):
    """Modern PyAV decoder adapter; keeps upstream networking separate from presentation."""
    def __init__(self, mailbox, notify, audio=True):
        super().__init__()
        self.mailbox = mailbox
        self.notify = notify
        self.audio = AudioSink(notify) if audio else None
        self.decode_lock = threading.RLock()
        self.closed = False

    def _get_video_codec(self):
        with self.decode_lock:
            ctx = av.CodecContext.create(self._session.codec, "r")
            ctx.flags |= av.codec.context.Flags.low_delay
            ctx.flags2 |= av.codec.context.Flags2.fast
            ctx.thread_type = "SLICE"
            ctx.thread_count = 2
            ctx.open()
            self._video_decoder = ctx

    def _get_audio_codec(self, header):
        with self.decode_lock:
            self._audio_config = {"channels": header[0], "bits": header[1],
                                  "rate": struct.unpack_from("!I", header, 2)[0],
                                  "frame_size": struct.unpack_from("!I", header, 6)[0]}
            if self.audio:
                self._audio_decoder = av.CodecContext.create("opus", "r")
                self._audio_decoder.open()
                self._audio_resampler = av.AudioResampler(format="s16", layout="stereo", rate=48000)

    def handle_video_data(self, data):
        with self.decode_lock:
            if self.closed or self._video_decoder is None:
                return
            try:
                for frame in self._video_decoder.decode(av.Packet(data)):
                    if not frame.is_corrupt:
                        self.handle_video(frame.reformat(format="rgb24"))
            except av.error.InvalidDataError:
                pass  # Wait for the next complete/key frame after packet loss.

    def handle_audio_data(self, data):
        with self.decode_lock:
            if self.closed or self._audio_decoder is None:
                return
            try:
                for frame in self._audio_decoder.decode(av.Packet(data)):
                    for converted in self._audio_resampler.resample(frame):
                        self.handle_audio(converted)
            except av.error.InvalidDataError:
                pass

    def handle_video(self, frame):
        self.mailbox.put(frame)

    def handle_audio(self, frame):
        if self.audio:
            self.audio.put(bytes(frame.planes[0])[:frame.samples * 4])

    def close(self):
        with self.decode_lock:
            self.closed = True
            self._video_decoder = None
            self._audio_decoder = None
        if self.audio:
            self.audio.close()


class Engine:
    def __init__(self, mailbox, notify):
        self.mailbox = mailbox
        self.notify = notify
        self.thread = None
        self.loop = None
        self.device = None
        self.task = None
        self.cancel = threading.Event()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, host, profiles, resolution="720p", fps=30, bitrate=10000, audio=True):
        if self.running:
            raise RuntimeError("已有连接正在运行，请先断开。")
        host = validate_host(host)
        if resolution not in ("540p", "720p", "1080p") or fps not in (30, 60) or bitrate not in (4000, 6000, 10000, 15000):
            raise ValueError("无效的视频参数。")
        if not profiles:
            raise RuntimeError("请先输入 Account-ID 和配对码，完成首次配对。")
        self.cancel.clear()
        self.mailbox.clear()
        self.thread = threading.Thread(target=self._worker,
            args=(host, profiles, resolution, fps, bitrate, audio), daemon=True, name="PS5-session")
        self.thread.start()

    def _worker(self, host, profiles, resolution, fps, bitrate, audio):
        loop = asyncio.SelectorEventLoop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        receiver = LiveReceiver(self.mailbox, self.notify, audio)

        async def run():
            self.device = LocalPS5(host)
            status = await asyncio.to_thread(self.device.get_status)
            if self.cancel.is_set():
                return
            if not status:
                raise RuntimeError("PS5 未响应，请检查 IP、同一局域网及遥控游玩设置。")
            if status.get("status-code") != 200:
                raise RuntimeError("PS5 处于待机，请先开机后再连接。")
            session = self.device.create_session("local", profiles=Profiles(profiles), loop=loop,
                receiver=receiver, resolution=resolution, fps=fps, quality=bitrate, codec="h264")
            if session is None:
                raise RuntimeError("当前 PS5 或账号未配对，请重新配对。")
            self.notify("正在进行 Remote Play 认证…")
            if not await asyncio.wait_for(self.device.connect(), timeout=20):
                raise RuntimeError("Remote Play 认证失败。请检查账号和配对资料；也可能是 PS5 固件协议不兼容。")
            self.notify("认证完成，等待首个真实视频帧…")
            started = time.monotonic()
            while not self.cancel.is_set() and not session.is_stopped:
                frame, _, received = self.mailbox.get()
                if frame is None and time.monotonic() - started > 20:
                    raise RuntimeError("已认证但 20 秒内未解码出画面。请检查网络丢包、Windows 防火墙或固件兼容性。")
                if received and time.monotonic() - received > 15:
                    raise RuntimeError("超过 15 秒未收到新画面，连接已停止。")
                await asyncio.sleep(.1)
            if not self.cancel.is_set():
                self.notify("PS5 已结束串流会话，请检查主机后重新连接。")

        try:
            self.task = loop.create_task(run())
            loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            self.notify("连接超时，请检查 PS5 遥控游玩、IP 和防火墙。")
        except Exception as exc:
            # No upstream exception payloads containing authentication material.
            self.notify(str(exc) if type(exc) is RuntimeError else "串流异常：" + type(exc).__name__ + "。请检查网络、配对及固件兼容性。")
        finally:
            try:
                if self.device and self.device.session:
                    self.device.session.stop()
                receiver.close()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor(timeout=3))
            finally:
                loop.close()
                self.loop = None
                self.device = None
                self.task = None
                self.notify("会话已停止。")

    def stop(self):
        self.cancel.set()
        loop, task = self.loop, self.task
        if loop and task and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

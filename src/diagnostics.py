"""Offline runtime checks. Synthetic codec fixtures are never shown as PS5 video."""
import hashlib
import importlib.metadata
import platform
import struct
from types import SimpleNamespace
import av
from PIL import Image
from engine import FrameMailbox, LiveReceiver
from storage import dpapi


def codec_check():
    mailbox = FrameMailbox()
    receiver = LiveReceiver(mailbox, lambda _: None, audio=False)
    receiver._set_session(SimpleNamespace(codec="h264"))
    receiver._get_video_codec()
    encoder = av.CodecContext.create("libx264", "w")
    encoder.width, encoder.height = 128, 72
    encoder.pix_fmt = "yuv420p"
    encoder.options = {"tune": "zerolatency", "preset": "ultrafast", "crf": "18"}
    encoder.open()
    fixture = av.VideoFrame.from_image(Image.new("RGB", (128, 72), (40, 180, 90)))
    packets = list(encoder.encode(fixture)) + list(encoder.encode(None))
    for packet in packets:
        receiver.handle_video_data(bytes(packet))
    decoded, count, _ = mailbox.get()
    if decoded is None or count != 1:
        raise RuntimeError("H.264 fixture did not decode")
    pixel = decoded.to_image().getpixel((30, 30))
    if max(abs(a-b) for a, b in zip(pixel, (40, 180, 90))) > 20:
        raise RuntimeError("H.264 fixture color mismatch")
    receiver.close()
    return {"decoded_frames": count, "size": [decoded.width, decoded.height], "color": list(pixel),
            "note": "synthetic offline fixture; not a PS5 hardware test"}


def audio_check():
    receiver = LiveReceiver(FrameMailbox(), lambda _: None, audio=False)
    class Sink:
        def __init__(self):
            self.packets = []
        def put(self, data):
            self.packets.append(data)
        def close(self):
            pass
    sink = Sink()
    receiver.audio = sink
    receiver._get_audio_codec(bytes([2, 16]) + struct.pack("!III", 48000, 960, 0))
    encoder = av.CodecContext.create("libopus", "w")
    encoder.sample_rate = 48000
    encoder.layout = "stereo"
    encoder.format = "s16"
    encoder.open()
    frame = av.AudioFrame(format="s16", layout="stereo", samples=960)
    frame.sample_rate = 48000
    for plane in frame.planes:
        plane.update(bytes(plane.buffer_size))
    for packet in list(encoder.encode(frame)) + list(encoder.encode(None)):
        receiver.handle_audio_data(bytes(packet))
    receiver.close()
    if not sink.packets:
        raise RuntimeError("Opus fixture did not decode")
    return {"decoded_bytes": sum(map(len, sink.packets)), "sample_rate": 48000, "channels": 2,
            "note": "offline silent fixture; no sound output"}


def diagnose():
    result = {"version": "0.1.0-experimental", "platform": platform.platform(),
              "python": platform.python_version(), "ps5_hardware_tested": False,
              "obs_real_instance_tested": False, "checks": {}}
    for name, action in [("h264_decode", codec_check), ("opus_decode", audio_check),
                         ("dpapi_roundtrip", lambda: {"ok": dpapi(dpapi(b"bridge-test"), decrypt=True) == b"bridge-test"})]:
        try:
            result["checks"][name] = {"passed": True, "detail": action()}
        except Exception as exc:
            result["checks"][name] = {"passed": False, "error": type(exc).__name__ + ": " + str(exc)}
    result["passed"] = all(x["passed"] for x in result["checks"].values())
    return result

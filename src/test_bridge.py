import asyncio
import base64
import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from diagnostics import codec_check, audio_check
from engine import FrameMailbox, Engine, LocalPS5, pair
from obs_bridge import ObsClient, ObsError, authentication, window_selector, configure, SCENE, SOURCE
from storage import Store, normalize_account, validate_host


class FakeObs:
    def __init__(self):
        self.scenes, self.inputs, self.items = [], [], []
        self.calls = []
        self.audio_supported = True
    def request(self, kind, data=None):
        data = data or {}
        self.calls.append((kind, data))
        if kind == "GetInputKindList": return {"inputKinds": ["window_capture"]}
        if kind == "GetInputList": return {"inputs": self.inputs}
        if kind == "GetInputDefaultSettings": return {"defaultInputSettings": {"capture_audio": False} if self.audio_supported else {}}
        if kind == "GetSceneList": return {"scenes": self.scenes}
        if kind == "CreateScene": self.scenes.append({"sceneName": data["sceneName"]})
        elif kind == "CreateInput":
            self.inputs.append({"inputName": data["inputName"], "inputKind": data["inputKind"]})
            self.items.append({"sourceName": data["inputName"], "sceneItemId": 7})
            return {"sceneItemId": 7}
        elif kind == "GetSceneItemList": return {"sceneItems": self.items}
        elif kind == "CreateSceneItem":
            self.items.append({"sourceName": data["sourceName"], "sceneItemId": 7})
            return {"sceneItemId": 7}
        elif kind == "GetVideoSettings": return {"baseWidth": 2560, "baseHeight": 1440}
        elif kind == "GetVersion": return {"obsVersion": "mock-32"}
        return {}


def read_frame(stream):
    header = stream.read(2)
    if len(header) != 2:
        return None
    opcode, length = header[0] & 15, header[1] & 127
    if length == 126: length = struct.unpack("!H", stream.read(2))[0]
    elif length == 127: length = struct.unpack("!Q", stream.read(8))[0]
    mask = stream.read(4) if header[1] & 128 else None
    data = stream.read(length)
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data


def ws_frame(payload, opcode=1, final=True):
    data = payload.encode() if isinstance(payload, str) else payload
    start = (128 if final else 0) | opcode
    length = len(data)
    header = bytes([start, length]) if length < 126 else bytes([start, 126]) + struct.pack("!H", length)
    return header + data


class MockWebSocket(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        accept = base64.b64encode(hashlib.sha1((self.headers["Sec-WebSocket-Key"] +
            "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        hello = json.dumps({"op": 0, "d": {"rpcVersion": 1,
            "authentication": {"salt": "salt", "challenge": "challenge"}}})
        # Deliberately fragmented: verifies the actual client, not just JSON helpers.
        self.wfile.write(ws_frame(hello[:30], final=False) + ws_frame(hello[30:], opcode=0))
        self.wfile.flush()
        identified = read_frame(self.rfile)
        if not identified:
            return
        auth = json.loads(identified[1]).get("d", {}).get("authentication")
        if auth != authentication("test-password", "salt", "challenge"):
            self.wfile.write(ws_frame(struct.pack("!H", 4009), opcode=8))
            self.wfile.flush()
            return
        self.wfile.write(ws_frame(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}})))
        self.wfile.flush()
        while True:
            frame = read_frame(self.rfile)
            if not frame or frame[0] == 8:
                return
            request = json.loads(frame[1])["d"]
            data = self.server.fake.request(request["requestType"], request.get("requestData"))
            response = {"op": 7, "d": {"requestId": request["requestId"], "requestType": request["requestType"],
                "requestStatus": {"result": True, "code": 100}, "responseData": data}}
            self.wfile.write(ws_frame(json.dumps({"op": 5, "d": {"eventType": "TestEvent"}})))
            self.wfile.write(ws_frame(json.dumps(response)))
            self.wfile.flush()


class Tests(unittest.TestCase):
    def test_account_formats(self):
        self.assertEqual(normalize_account("1"), "AQAAAAAAAAA=")
        self.assertEqual(normalize_account("AQAAAAAAAAA="), "AQAAAAAAAAA=")
        for value in ("nickname", "AAAA", "0", str(2**64), "AAAAAAAAAAA="):
            with self.assertRaises(ValueError): normalize_account(value)

    def test_host_validation(self):
        self.assertEqual(validate_host(" 192.168.1.50 "), "192.168.1.50")
        for value in ("0.0.0.0", "::1", "localhost", "255.255.255.255", "224.0.0.1"):
            with self.assertRaises(ValueError): validate_host(value)

    def test_pair_pin_validation_before_network(self):
        for pin in ("1234", "１２３４５６７８", "1234567a"):
            with self.assertRaises(ValueError): pair("192.168.1.50", "1", pin)

    def test_dpapi_profile_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            profile = {"local": {"id": "AQAAAAAAAAA=", "hosts": {"test": "private-key-fixture"}}}
            store.save_profiles(profile)
            self.assertEqual(store.load_profiles(), profile)
            self.assertNotIn(b"private-key-fixture", store.pairing.read_bytes())
            store.save_profiles({"local": {"id": "two"}})
            self.assertEqual(store.load_profiles()["local"]["id"], "two")

    def test_window_selector(self):
        self.assertEqual(window_selector("PS5:#", "TkTopLevel", "x.exe"), "PS5#3A#22:TkTopLevel:x.exe")

    def test_auth_known_vector(self):
        import hashlib
        secret = base64.b64encode(hashlib.sha256(b"test-passwordsalt").digest())
        expected = base64.b64encode(hashlib.sha256(secret + b"challenge").digest()).decode()
        self.assertEqual(authentication("test-password", "salt", "challenge"), expected)

    def test_obs_idempotent_and_safe_defaults(self):
        obs = FakeObs()
        configure(obs, "title:class:PS5OBSBridge.exe")
        configure(obs, "title:class:PS5OBSBridge.exe")
        self.assertEqual(len(obs.scenes), 1)
        self.assertEqual(len(obs.inputs), 1)
        self.assertEqual(len(obs.items), 1)
        calls = [x[0] for x in obs.calls]
        self.assertNotIn("SetCurrentProgramScene", calls)
        self.assertFalse(any("Stream" in x or "Record" in x for x in calls))
        transform = next(d for k, d in obs.calls if k == "SetSceneItemTransform")["sceneItemTransform"]
        self.assertEqual(transform["boundsWidth"], 2560)
        self.assertEqual(transform["boundsHeight"], 1440)

    def test_obs_source_collision(self):
        obs = FakeObs()
        obs.inputs = [{"inputName": SOURCE, "inputKind": "image_source"}]
        with self.assertRaises(ObsError): configure(obs, "title:class:exe")
        self.assertFalse(obs.scenes)

    def test_obs_audio_fallback(self):
        obs = FakeObs()
        obs.audio_supported = False
        self.assertIn("应用程序音频", configure(obs, "title:class:exe"))
        self.assertNotIn("capture_audio", next(d for k, d in obs.calls if k == "CreateInput")["inputSettings"])

    def test_h264_roundtrip(self):
        self.assertEqual(codec_check()["decoded_frames"], 1)

    def test_opus_roundtrip(self):
        self.assertGreater(audio_check()["decoded_bytes"], 0)

    def test_mailbox_is_bounded(self):
        box = FrameMailbox()
        for n in range(10000): box.put(n)
        self.assertEqual(box.get()[:2], (9999, 10000))
        box.clear()
        self.assertEqual(box.get()[:2], (None, 0))

    def test_local_status_does_not_schedule_cover_art(self):
        errors = []
        def worker():
            try:
                device = LocalPS5("192.0.2.1")
                device._set_status({"host-type": "PS5", "host-id": "abcd", "running-app-titleid": "TEST"})
            except Exception as exc: errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start(); thread.join()
        self.assertEqual(errors, [])

    def test_cancel_connecting_session(self):
        entered = threading.Event()
        class Session:
            is_stopped = False
            def stop(self): self.is_stopped = True
        class Device:
            def __init__(self, host): self.session = Session()
            def get_status(self): return {"status-code": 200}
            def create_session(self, *args, **kwargs): return self.session
            async def connect(self):
                entered.set()
                await asyncio.sleep(3600)
        with patch("engine.LocalPS5", Device):
            engine = Engine(FrameMailbox(), lambda _: None)
            engine.start("192.168.1.50", {"local": {}}, audio=False)
            self.assertTrue(entered.wait(2))
            engine.stop()
            engine.thread.join(3)
            self.assertFalse(engine.running)

    def test_real_websocket_transport(self):
        server = HTTPServer(("127.0.0.1", 0), MockWebSocket)
        server.fake = FakeObs()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with ObsClient(server.server_port, "test-password") as obs:
                self.assertEqual(obs.request("GetVersion")["obsVersion"], "mock-32")
                configure(obs, "PS5 Live:TkTopLevel:PS5OBSBridge.exe")
                configure(obs, "PS5 Live:TkTopLevel:PS5OBSBridge.exe")
            with self.assertRaises(ObsError):
                ObsClient(server.server_port, "wrong-password")
            self.assertEqual(len(server.fake.inputs), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

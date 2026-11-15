"""OBS WebSocket v5 client, local connections only, no recording/streaming actions."""
import base64
import hashlib
import json
import time
import uuid
import websocket

SCENE = "PS5 Wireless Bridge"
SOURCE = "PS5 Wireless Bridge - Video"


def authentication(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def window_selector(title, cls, exe):
    def escape(text):
        return text.replace("#", "#22").replace(":", "#3A")
    return ":".join(map(escape, (title, cls, exe)))


class ObsError(RuntimeError):
    pass


class ObsClient:
    def __init__(self, port=4455, password=""):
        if not 1 <= int(port) <= 65535:
            raise ValueError("OBS 端口必须在 1–65535 之间。")
        self.sock = None
        try:
            self.sock = websocket.create_connection(
                f"ws://127.0.0.1:{int(port)}", timeout=6,
                http_no_proxy=["127.0.0.1", "localhost"], enable_multithread=True)
            hello = self._recv()
            if hello.get("op") != 0 or hello.get("d", {}).get("rpcVersion", 0) < 1:
                raise ObsError("需要支持 WebSocket v5 的 Windows OBS。")
            identify = {"rpcVersion": 1, "eventSubscriptions": 0}
            auth = hello["d"].get("authentication")
            if auth:
                identify["authentication"] = authentication(password, auth["salt"], auth["challenge"])
            self._send({"op": 1, "d": identify})
            if self._recv().get("op") != 2:
                raise ObsError("OBS 身份验证失败，请核对 WebSocket 密码。")
        except Exception as exc:
            self.close()
            if isinstance(exc, ObsError):
                raise
            raise ObsError("连接 OBS 失败。请启动 OBS，启用“工具 → WebSocket 服务器设置”，并核对端口及密码。") from exc

    def _send(self, value):
        self.sock.send(json.dumps(value))

    def _recv(self):
        raw = self.sock.recv()
        if not raw:
            raise ObsError("OBS 断开连接，请检查密码及服务器状态。")
        if len(raw) > 2_000_000:
            raise ObsError("OBS 消息过大。")
        return json.loads(raw)

    def request(self, kind, data=None):
        request_id = uuid.uuid4().hex
        self._send({"op": 6, "d": {"requestType": kind, "requestId": request_id, "requestData": data or {}}})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            reply = self._recv()
            if reply.get("op") != 7 or reply.get("d", {}).get("requestId") != request_id:
                continue
            status = reply["d"]["requestStatus"]
            if not status.get("result"):
                raise ObsError(f"OBS {kind} 失败：{status.get('code')} {status.get('comment', '')}")
            return reply["d"].get("responseData", {})
        raise ObsError(f"OBS {kind} 请求超时。")

    def close(self):
        if self.sock:
            try:
                self.sock.close(timeout=1)
            except Exception:
                pass
            self.sock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def configure(obs, selector, audio=True, switch=False):
    if not selector:
        raise ValueError("请先连接 PS5 并打开实时画面窗口。")
    if "window_capture" not in obs.request("GetInputKindList", {"unversioned": True})["inputKinds"]:
        raise ObsError("此 OBS 没有 Windows 窗口采集源。")
    inputs = obs.request("GetInputList")["inputs"]
    existing = next((x for x in inputs if x["inputName"] == SOURCE), None)
    if existing and existing.get("unversionedInputKind", existing.get("inputKind")) != "window_capture":
        raise ObsError(f"OBS 已有其他类型的同名源 {SOURCE}，请先重命名。")
    defaults = obs.request("GetInputDefaultSettings", {"inputKind": "window_capture"})["defaultInputSettings"]
    audio_supported = "capture_audio" in defaults
    settings = {"window": selector, "method": 2, "priority": 0, "cursor": False,
                "client_area": True, "force_sdr": True}
    if audio_supported:
        settings["capture_audio"] = audio
    if not any(x["sceneName"] == SCENE for x in obs.request("GetSceneList")["scenes"]):
        obs.request("CreateScene", {"sceneName": SCENE})
    if existing:
        obs.request("SetInputSettings", {"inputName": SOURCE, "inputSettings": settings, "overlay": True})
        items = obs.request("GetSceneItemList", {"sceneName": SCENE})["sceneItems"]
        item = next((x for x in items if x["sourceName"] == SOURCE), None)
        item_id = item["sceneItemId"] if item else obs.request("CreateSceneItem", {
            "sceneName": SCENE, "sourceName": SOURCE, "sceneItemEnabled": True})["sceneItemId"]
    else:
        item_id = obs.request("CreateInput", {"sceneName": SCENE, "inputName": SOURCE,
            "inputKind": "window_capture", "inputSettings": settings, "sceneItemEnabled": True})["sceneItemId"]
    canvas = obs.request("GetVideoSettings")
    transform = {"positionX": 0, "positionY": 0, "alignment": 5, "rotation": 0,
                 "scaleX": 1, "scaleY": 1, "cropLeft": 0, "cropRight": 0, "cropTop": 0, "cropBottom": 0,
                 "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0,
                 "boundsWidth": canvas["baseWidth"], "boundsHeight": canvas["baseHeight"]}
    obs.request("SetSceneItemTransform", {"sceneName": SCENE, "sceneItemId": item_id, "sceneItemTransform": transform})
    obs.request("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": item_id, "sceneItemEnabled": True})
    if switch:
        obs.request("SetCurrentProgramScene", {"sceneName": SCENE})
    return ("已配置画面源，请在 OBS 预览确认。" if not audio or audio_supported else
            "已配置画面源；此 OBS 版本需手动添加应用程序音频采集，选择 PS5OBSBridge.exe。")

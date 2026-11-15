# PS5 StreamForge

[![中文](https://jaywcjlove.github.io/sb/lang/chinese.svg)](./README_CN.md)
[![English](https://jaywcjlove.github.io/sb/lang/english.svg)](./README.md)

[中文文档](./README_CN.md) | [English Documentation](./README.md)

PS5 StreamForge 是面向 Windows 的 PS5 局域网串流接收工具。通过 Remote Play 接收 PS5 画面和音频，并提供实时画面窗口，供同一台电脑上的 OBS 或直播伴侣采集，无需采集卡。

## 功能

- 搜索、配对并连接局域网中的 PS5。
- 支持请求 540p、720p、1080p 画面，以及 30 / 60 FPS。
- 播放 PS5 音频、保存当前画面为 PNG。
- 通过 OBS WebSocket 自动添加画面源，也可手动进行窗口采集。
- 在本机加密保存配对资料，便于再次连接。

## 使用方法

### 连接 PS5

1. 将 PS5 与 Windows 电脑接入同一局域网，建议优先使用有线连接。
2. 在 PS5 中打开“设置 → 系统 → 远程游玩”，启用远程游玩。
3. 双击运行 `PS5OBSBridge.exe`。运行成品无需安装 Python、Chiaki-ng 或索尼 PS Remote Play。
4. 点击“搜索主机”，选择 PS5；也可以手动填写 PS5 的 IPv4 地址。
5. 填写对应账号的 **PSN Account-ID**，支持十进制数字或 8 字节 Base64 编码。也可点击“获取账号 ID”，在索尼网页登录后，将跳转页面的完整地址粘贴回程序。
6. 在 PS5 的“远程游玩 → 链接设备”获取 8 位配对码，输入程序并点击“配对 PS5”。
7. 选择分辨率、帧率和码率，点击“连接并接收画面”。后续使用通常只需确认主机地址并重新连接。

### 接入 OBS 或直播伴侣

- **手动采集**：添加窗口采集素材，选择 `PS5 Live - Wireless Bridge`。
- **OBS 自动配置**：在 OBS 的“工具 → WebSocket 服务器设置”启用服务器；在本程序“接入 OBS”页填写端口（默认 `4455`）和密码，再点击“一键添加到 OBS”。生成的场景名为 `PS5 Wireless Bridge`。
- **音频**：本程序通过 Windows 默认输出设备播放声音。需要单独采集时，添加应用程序音频采集并选择 `PS5OBSBridge.exe`，避免与桌面音频重复收音。

### 从源码构建

构建环境为 Windows x64 和 Python 3.13，在项目目录运行：

```powershell
.\build.ps1
```

脚本会安装 `requirements-lock.txt` 中的依赖并生成 `PS5OBSBridge.exe`。

## 注意事项

- 本程序面向 Windows 10/11 x64；OBS 或直播伴侣需要单独安装。
- Account-ID 应与配对使用的 PS5 用户对应，不是 PSN 昵称。PSN 密码只在索尼登录网页中输入。
- 保持实时画面窗口打开，不要最小化；本程序不会自动开始直播或录制。
- 当前接收画面为 H.264 SDR，最高可请求 1080p / 60 FPS；实际表现取决于网络和主机状态。手柄通过 PS5 操作。
- 配对资料保存在 `%LOCALAPPDATA%\PS5OBSStandalone`，使用 Windows 当前用户加密。更换用户或系统后可能需要重新配对，请勿分享配对资料。
- 本项目使用第三方 Remote Play 协议实现，兼容性可能受 PS5 系统及认证服务更新影响；项目非索尼官方产品。

## 许可

本项目采用 GPL-3.0-or-later。详见 [LICENSE.txt](LICENSE.txt)；第三方组件及许可见 [THIRD-PARTY.md](THIRD-PARTY.md) 和 [third-party-licenses/](third-party-licenses/)。

# PS5 StreamForge

[![中文](https://jaywcjlove.github.io/sb/lang/chinese.svg)](./README_CN.md)
[![English](https://jaywcjlove.github.io/sb/lang/english.svg)](./README.md)

[中文文档](./README_CN.md) | [English Documentation](./README.md)

PS5 StreamForge is a PS5 LAN streaming receiver for Windows. It receives PS5 video and audio through Remote Play and provides a live video window for capture by OBS or Douyin Live Companion on the same computer, without a capture card.

## Features

- Discover, pair with, and connect to a PS5 on the local network.
- Request video at 540p, 720p, or 1080p, at 30 / 60 FPS.
- Play PS5 audio and save the current frame as a PNG.
- Automatically add a video source through OBS WebSocket, or capture the window manually.
- Store encrypted pairing information locally for subsequent connections.

## Usage

### Connect to PS5

1. Connect the PS5 and Windows computer to the same local network. A wired connection is recommended.
2. On the PS5, open "Settings → System → Remote Play" and enable Remote Play.
3. Double-click `PS5OBSBridge.exe`. The packaged application does not require Python, Chiaki-ng, or Sony PS Remote Play to be installed.
4. Click "Search for Console" and select the PS5, or enter the PS5's IPv4 address manually.
5. Enter the account's **PSN Account-ID**, as a decimal number or a Base64 encoding of 8 bytes. Alternatively, click "Get Account ID", sign in on Sony's website, and paste the full redirect URL back into the application.
6. On the PS5, obtain the 8-digit pairing code from "Remote Play → Link Device", enter it in the application, and click "Pair PS5".
7. Select the resolution, frame rate, and bitrate, then click "Connect and Receive Video". For subsequent use, you usually only need to confirm the console address and reconnect.

### Connect to OBS or Douyin Live Companion

- **Manual capture**: Add a window capture source and select `PS5 Live - Wireless Bridge`.
- **Automatic OBS setup**: Enable the server in OBS under "Tools → WebSocket Server Settings". On the application's "Connect to OBS" tab, enter the port (default: `4455`) and password, then click "Add to OBS". The created scene is named `PS5 Wireless Bridge`.
- **Audio**: The application plays audio through the default Windows output device. To capture it separately, add an application audio capture source and select `PS5OBSBridge.exe`, avoiding duplicate capture with desktop audio.

### Build from Source

The build environment requires Windows x64 and Python 3.13. Run the following in the project directory:

```powershell
.\build.ps1
```

The script installs the dependencies in `requirements-lock.txt` and generates `PS5OBSBridge.exe`.

## Notes

- The application targets Windows 10/11 x64. OBS or Douyin Live Companion must be installed separately.
- The Account-ID must correspond to the PS5 user used for pairing; it is not the PSN nickname. Enter the PSN password only on Sony's sign-in website.
- Keep the live video window open and do not minimize it. The application does not automatically start streaming or recording.
- The received video is H.264 SDR, with requests supported up to 1080p / 60 FPS. Actual performance depends on the network and console status. Use a controller connected to the PS5.
- Pairing information is stored in `%LOCALAPPDATA%\PS5OBSStandalone` and encrypted for the current Windows user. Changing users or reinstalling the system may require pairing again. Do not share pairing information.
- This project uses a third-party Remote Play protocol implementation. Compatibility may be affected by updates to the PS5 system and authentication services. This is not an official Sony product.

## License

This project is licensed under GPL-3.0-or-later. See [LICENSE.txt](LICENSE.txt). For third-party components and licenses, see [THIRD-PARTY.md](THIRD-PARTY.md) and [third-party-licenses/](third-party-licenses/).

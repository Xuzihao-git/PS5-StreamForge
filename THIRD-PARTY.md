# Third-party components

This program embeds libraries; it does not launch or include the Chiaki-ng application or Sony PS Remote Play application. It is not endorsed by Sony.

- pyremoteplay 0.7.6, GPL-3.0: https://github.com/ktnrg45/pyremoteplay
- pyps4-2ndscreen 1.3.1, MIT: https://github.com/ktnrg45/pyps4-2ndscreen
- PyAV, BSD-3-Clause: https://github.com/PyAV-Org/PyAV
- FFmpeg shared libraries from the PyAV Windows wheel, with upstream build configuration retained in verification: https://ffmpeg.org/
- x264 / x265 libraries in the PyAV wheel retain their upstream GPL licenses. Other bundled codec/runtime libraries retain their own licenses.
- Cryptography, PyCryptodome, Pillow, sounddevice/PortAudio, pyee, psutil, requests, websocket-client, protobuf, aiohttp and dependencies retain their respective upstream licenses.
- Python and Tcl/Tk retain the PSF and Tcl/Tk licenses.
- PyInstaller retains its license and bootloader distribution exception.

Installed versions are recorded in requirements-lock.txt. License notices copied from the installed distributions are provided in third-party-licenses/. Upstream source archives and source acquisition information are in third-party-sources/. Our complete application source, compatibility adapter, build procedure and tests are in src/ and build.ps1.

Local compatibility changes are implemented in our source, rather than modifying the installed pyremoteplay package: modern PyAV decoder handling, psutil-backed netifaces compatibility, suppression of optional cover-art lookups on worker threads, bounded frame buffering and Windows DPAPI profile storage.

No guarantee of compatibility with current or future PS5 firmware is implied by redistribution of these components.

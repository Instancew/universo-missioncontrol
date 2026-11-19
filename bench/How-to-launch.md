# Launching the IRC Rover system

Open PowerShell and run these commands:

```powershell
Set-Location "C:\Users\Vallabh\Documents\Codex\2026-11-19\irc-rover-gstreamer-mediamtx-dashboard-integration\outputs"
.\IRC-Rover-System.ps1 -Action Start
```

The launcher starts the single MediaMTX server, MikroTik statistics backend, laptop dashboard, phone dashboard, and USB camera publisher. A visible Chrome window opens for the camera. Keep it open while streaming.

The current default camera is the **Lenovo FHD Webcam**.

- Laptop dashboard: http://127.0.0.1:5173/
- Phone dashboard while connected to the mANTBox Wi-Fi: http://192.168.88.254:5174/

Check the system:

```powershell
.\IRC-Rover-System.ps1 -Action Status
```

Stop processes started by the launcher:

```powershell
.\IRC-Rover-System.ps1 -Action Stop
```

The default laptop address is `192.168.88.254` and the authorized phone address is `192.168.88.252`. If the phone receives a different address from the mANTBox, start the system with that address:

```powershell
.\IRC-Rover-System.ps1 -Action Start -PhoneIp 192.168.88.NEW
```

To select another connected camera, use its Windows camera name:

```powershell
.\IRC-Rover-System.ps1 -Action Start -CameraName "USB2.0 HD UVC WebCam"
```

If PowerShell reports that required ports are busy, a previous copy is still running. Use `-Action Status`, close the visible camera window if it was started manually, and stop the previous copy before starting again. Logs are saved under `work\runtime` in this workspace.

Smart App Control blocks the installed GStreamer and FFmpeg builds. This launcher therefore uses the tested Chrome camera publisher at 640 × 360, 15 FPS and 700 kbps.

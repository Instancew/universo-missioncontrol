# Historical Windows/phone bench

This is not the production publisher. No browser webcam publisher, phone allowlist,
second MediaMTX, or Windows launcher is used by deploy/jetson or deploy/network.

Previous bench assets remain in the existing handoff ZIP and local workspace;
they were not duplicated into startup scripts. Local workspace:
`C:\Users\Vallabh\Documents\Codex\2026-11-19\irc-rover-gstreamer-mediamtx-dashboard-integration\outputs`.
Historic laptop/phone addresses were `127.0.0.1`, `192.168.88.254`, phone
`192.168.88.252`; these do not belong in production deployment configuration.

For a bench viewer only, create an ignored .env.local:

```dotenv
VITE_ROVER_WHEP_URL=http://localhost:8889/rovercam/whep
BACKEND_PROXY_URL=http://localhost:8000
```

Run only an approved publisher on Windows. Smart App Control previously blocked
GStreamer; no exclusions, signing bypass or security changes are part of this work.
Jetson-local RTSP loopback in production is intentional and is not a Windows bench URL.

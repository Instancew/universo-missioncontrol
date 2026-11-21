# IRC rover deployment and acceptance

Status: deployment candidate, **not hardware accepted**. Do not enable automatic
route changes until the checklist below passes. No CPE, Windows security, branch
history or deployed service was changed while preparing these files.

## Wiring and proposed IP map

These are proposed addresses, not claims about the exhibition installation.
Check for subnet conflicts and record actual interface names, firmware and MACs.

| Node/path | Address | Connection |
|---|---|---|
| Jetson service/camera | `10.42.0.10/24`, gateway `10.42.0.1` | USB camera; Ethernet to NetMetal LAN |
| NetMetal LAN | `10.42.0.1/24` | Jetson and local controller |
| Base dashboard/backend | `10.43.0.10/24`, gateway `10.43.0.1` | Ethernet to mANTBox LAN |
| mANTBox LAN | `10.43.0.1/24` | Base controller and independent viewer access |
| 5 GHz transit | mANTBox `10.44.50.1/30`, NetMetal `10.44.50.2/30` | Dedicated routed WiFi interfaces |
| 2.4 GHz transit | mANTBox `10.44.24.1/30`, NetMetal `10.44.24.2/30` | Dedicated routed WiFi interfaces, always associated |

USB → GStreamer H.264 → **one MediaMTX on Jetson** → WebRTC/UDP across either
transit → base browser. The RTSP/TCP hop is confined to Jetson loopback; it never
crosses the wireless link. The stable service IP is the Jetson LAN address, not
either transit address. No inter-site NAT or address changes during failover.

Use a wired base viewer or a separate LAN access point. A phone connected to the
mANTBox 5 GHz radio being disabled cannot independently test rover-link recovery.
Do not use either transit radio for viewer access during acceptance.

## Jetson preparation (commands for the operator, not executed here)

GStreamer is assumed installed. Install no packages automatically. Verify the
controller has Python 3.8+ (JetPack 4's default Python 3.6 is not sufficient);
the existing base backend requires Python 3.10+. Verify the
approved MediaMTX **1.21.4** Linux ARM64 binary is at `/usr/local/bin/mediamtx`;
compare its release checksum using the team's approved download process. Review
the configuration reference before using another version. Copy this repository
to `/opt/irc-rover`. Create service accounts only if they do not already exist:

```sh
cd /opt/irc-rover
sudo useradd --system --no-create-home --groups video,render rover-video
sudo useradd --system --no-create-home rover-link
sudo install -d -m 0755 /etc/irc-rover
sudo install -m 0644 deploy/jetson/rover.env.example /etc/irc-rover/rover.env
sudoedit /etc/irc-rover/rover.env
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
cat /proc/device-tree/model
gst-inspect-1.0 nvv4l2h264enc
gst-inspect-1.0 x264enc
```

If this JetPack lacks the `render` group, omit it in the account command and in
`SupplementaryGroups` after confirming device permissions. Prefer a stable
`/dev/v4l/by-id/...` path. Match CAMERA_FORMAT=raw or mjpeg and supported camera
dimensions/FPS. The raw path negotiates camera capture then scales; for MJPEG,
the requested capture dimensions/FPS must be supported by the camera.

Defaults are 640×360, 15 FPS, 700 kbit/s, one-second IDR interval. Set WIDTH,
HEIGHT, FPS, BITRATE_KBPS, KEYFRAME_SECONDS in rover.env. `ENCODER=auto` checks
nvvidconv/nvv4l2h264enc and selects x264enc otherwise; Orin Nano explicitly uses
software because it has no NVENC. Plugin presence alone does not prove that
hardware works: if a hardware runtime test fails, inspect logs and explicitly
choose `ENCODER=software`. The script never silently changes encoder after an
error. Check CPU/temperature/throttling with the actual camera under load.
No B frames, a leaky two-frame queue and a five-second buffer watchdog bound
publisher-side queueing/stalls; these are not an end-to-end latency guarantee.

```sh
set -a; . /etc/irc-rover/rover.env; set +a
python3 deploy/jetson/publish.py --check
sudo install -m 0644 deploy/jetson/rover-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rover-mediamtx.service rover-publisher.service
systemctl status rover-mediamtx.service rover-publisher.service --no-pager
journalctl -u rover-mediamtx -u rover-publisher -f
```

Missing plugins exit nonzero with names. Approve any installation separately.
The units retry failures every two seconds and log in journald. A manual
`systemctl stop` deliberately stays stopped. Verify BOTH deliberate start/stop
and process-crash recovery on the Jetson:

```sh
sudo systemctl stop rover-publisher
sudo systemctl start rover-publisher
# Confirm fresh video, then simulate a process crash while stationary:
sudo systemctl kill --kill-whom=main --signal=SIGKILL rover-publisher
sleep 3
systemctl show rover-publisher -p ActiveState -p NRestarts
```

For a camera-free test: stop the publisher service, keep the single MediaMTX
service running, then `SOURCE=test ENCODER=software python3 deploy/jetson/publish.py`.
This needs videotestsrc/timeoverlay/x264enc and displays a moving timestamped
source. Stop the foreground test with Ctrl+C, then start rover-publisher again.
Also restart MediaMTX and unplug/replug the USB camera; verify fresh frames return.

MediaMTX permits publishing only on loopback and reading from the proposed base
subnet. Match MTX_WEBRTCADDITIONALHOSTS to the stable Jetson IP and
MTX_WEBRTCALLOWORIGINS to the dashboard origin. Allow TCP 8889 (WHEP), UDP 8189
(WebRTC media) from the base subnet to Jetson. RTSP 8554 is loopback only.
HTTP examples are for the isolated rover LAN; if serving the dashboard over HTTPS,
configure trusted HTTPS WHEP as well to avoid mixed-content blocking. Do not
expose these services to the Internet.

## Dashboard/backend startup on the base station

The existing telemetry UDP receiver, message schema, controls, radio panel and
draggable layout are preserved. This work does not implement missing rover motor
command acknowledgements: independently confirm the team's control protocol before
driving. Existing UI defaults/simulated values are not proof of live telemetry.

```sh
cd /opt/irc-rover
cp .env.example .env.local
# Edit addresses/origin in .env.local before building.
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Fill read-only router credentials and install trusted CA files locally.
# Keep disruptive scans disabled. Never commit these local files.
python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000
```

In a second terminal, after approving dependency installation if necessary:

```sh
cd /opt/irc-rover
npm ci
npm run build
npm run preview -- --host 0.0.0.0 --port 5173
```

Open `http://10.43.0.10:5173`. For development use `npm run dev -- --host 0.0.0.0
--port 5173`. Vite preview is for acceptance; permanent hosting should serve dist
and reverse-proxy `/api`, `/health`, `/ws` to the base backend with WebSocket
upgrade support. Backend UDP 9000 must be reachable from the rover; configure
the existing Jetson telemetry sender to the base address using its own protocol.
Do not run the tracked Windows `backend/venv`; create the local `.venv` above.

Front Camera uses VITE_ROVER_WHEP_URL. It marks video stale after two seconds
without presented frames (decoded-frame counters are the browser fallback), even
with an established ICE connection. Connection attempts time out at eight seconds.
Six retries back off 0.25/0.5/1/2/3/5 seconds, then require the Retry video button.
Ten continuous seconds of fresh video resets that budget for the next outage.
Frame drops and RTP loss display only when available. Fresh-frame resumption is
logged to the browser console and existing dashboard log. Browser background
throttling can affect these timings; measure in a foreground tab.

## Routed failover preparation and guards

**No current RouterOS export, Netwatch source or channel-hopper source was found.**
Their compatibility is unverified. The templates do not guess radio names,
security settings, country, frequency plans, DHCP or firewall rule order.

Before changes, connect wired recovery access at BOTH ends and export configs:

```text
/export file=before-irc
/system resource print
/system package print
/interface wifi print detail
/interface wifi registration-table print detail
/interface bridge port print detail
/interface bridge monitor [find] once
/tool netwatch print detail
/system scheduler print detail
/system script print detail
/ip route print detail
/routing rule print detail
/ip firewall filter print detail
/ip firewall mangle print detail
/ip firewall nat print detail
```

Review referenced scripts, not only scheduler names. Find interface disable/enable,
channel changes/scans, route distance changes, Netwatch up/down scripts and startup
jobs. Record exact IDs, enabled states and original settings. With approval,
disable only conflicting Netwatch/scheduler entries before enabling this design.
Channel hopping must not interrupt the 2.4 GHz standby, and no second writer may
alter these routes. Retain the read-only stats collector; disruptive scans stay off.

The old shared RSTP bridge cannot prove per-band health: one management-IP ping
can traverse either band, and a blocked bridge port may discard standby probes.
Templates remove the two WiFi ports from that bridge and give each a separate /30.
Ethernet stays in its LAN bridge. Verify both radios can associate simultaneously
using the installed RouterOS WiFi driver. Configure AP/station/security from the
actual approved radio plan; the templates preserve those settings.

Fill `REPLACE_WIFI_5`, `REPLACE_WIFI_24`, `REPLACE_LAN_BRIDGE` in BOTH .rsc files.
Review every command; change `reviewed` only during the supervised migration.
These are one-time templates, not idempotent reimports. Route comments must be unique.
Each template installs a per-peer /32 route in a separate probe table and a
`lookup-only-in-table` rule with no default fallback. The controller specifies
source address, interface AND routing table. The opposite CPE has matching
peer rules to pin the reply. Rules must precede any conflicting policy/mangle
rules. Verify replies and requests with captures on BOTH radios at BOTH ends.

Adapt firewall rules to allow transit-peer ICMP input, output and replies;
forward only the approved base/rover subnets and services. Permit local-controller
HTTPS REST only from its wired LAN address with verified CA/name. Exclude these
flows from conflicting FastTrack/mangle/NAT. Use loose reverse-path filtering if
required by tested temporary asymmetric paths; assess security rules before changing
it. Do not broadly disable firewalling. Validate that transit destinations cannot
escape through default routes, policy rules or the opposite radio.

Service routes are installed **disabled**. Enable the exact two owned route IDs
per CPE for supervised static testing (distance 1 on 5 GHz and 20 on 2.4 GHz).
Start dry-run only after those static routes pass. Never enable a route by a broad
`find` that might match unrelated routes. Both radios remain enabled and associated
after recovery. The controller changes route distances only, never radio state.

## Controllers, dry-run and enabling after acceptance

Run one on the Jetson wired to NetMetal (`rover.json.example`), one on the base
machine wired to mANTBox (`base.json.example`). The dashboard/backend is not the
switching controller and may restart independently. On a Windows base, run the
same Python script in a supervised terminal with local environment variables and a
writable status_file; systemd instructions below are for a Linux base.

```sh
cd /opt/irc-rover
sudo install -m 0600 deploy/network/controller.env.example /etc/irc-rover/controller.env
# Choose rover on Jetson, base on base station:
sudo install -m 0644 deploy/network/rover.json.example /etc/irc-rover/link.json
sudoedit /etc/irc-rover/link.json /etc/irc-rover/controller.env
# Install trusted router CA at the configured readable path, fill peer MACs/interfaces.
sudo install -m 0644 deploy/network/irc-failover.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start irc-failover
journalctl -u irc-failover -f
```

Both examples set auto_apply=false and hardware_acceptance_passed=false.
Dry-run logs **would switch**, updating only simulated selection/status, never
routes. `--dry-run` forces observation even if config flags are true. For a
foreground check, export ROUTER_USER, ROUTER_PASSWORD, ROUTER_CA_FILE locally and
run `python3 deploy/network/failover.py --config /etc/irc-rover/link.json --dry-run`.
TLS validation cannot be disabled. Use a dedicated controller account with just
the RouterOS permissions needed for ping/read and, after acceptance, route writes;
keep the existing stats account read-only. RouterOS permissions are coarse: review
the account's actual privileges and restrict service access by source address.

Five 100-ms-spaced probes per band are evaluated every cycle in parallel. Default
usable thresholds: loss ≤20%, RTT ≤100 ms. Confirmed total loss holds 2 seconds;
degradation holds 5 seconds; healthy backup holds 1 second. Recovery to 5 GHz needs
20 continuous seconds with loss ≤5%, RTT ≤60 ms. A failed active backup can return
early to healthy 5 GHz. Missing/invalid API measurements are UNKNOWN, not RF loss.
A gap over 5 seconds resets evidence timers. Scheduling, REST latency and actual
probe duration add to these settings; they are not guaranteed recovery times.

Before first live actuation, pass static forwarding/probe and supervised dry-run
tests. Then, during the agreed stationary acceptance window, set both flags true
on both controllers and restart services for the automatic-cycle tests. Boot
enable (`systemctl enable irc-failover`) comes only after those pass. Both ends
decide independently; brief asymmetric routing is possible. Verify it is accepted
by firewalls, rp-filter, control protocol and WebRTC. If not, do not deploy; design
coordinated routing first. Failed route writes attempt rollback and stop the
controller for review; monitor service failure and stale status. This is not a
substitute for a rover-side deadman timeout/emergency stop.

## Acceptance checklist and evidence still required

1. Verify firmware/models, both WiFi associations, approved non-overlapping channels,
   CA identity, peer MACs, interface names, wiring and LAN/transit addresses.
2. Prove RSTP no longer gates either transit, and audit all Netwatch/hopper callers.
3. Capture both probe directions on each band. Disable 5 GHz: only its probes fail.
   Repeat on 2.4 GHz. Verify no default-route/bridge fallback and no shared-IP probe.
4. Test static routes on both paths, return routing, firewall/NAT/rp-filter and MTU.
   Confirm Jetson service IP and base service IP stay unchanged.
5. Confirm publisher plugins/encoder, negotiated H.264, CPU/temperature, restart after
   process crash, USB unplug and MediaMTX restart. Record actual resolution/FPS/bitrate.
6. Dry-run healthy, weak-but-associated, hard outage, failed backup and video-only
   freeze. Stop only the publisher while network remains healthy: no route change.
7. With vehicle stationary, run TWO consecutive automatic 5→2.4→5 cycles. After
   the first recovery, explicitly verify 2.4 association AND its probes remain ready.
8. Repeat with a physical obstruction and complete link interruption, using an
   independent base viewer. Observe both radio registrations, RSSI, PHY rates, per-band
   loss/RTT, route decisions, frame-drop counters and console fresh-frame events.
9. Record separately: fault onset → first valid control command ACK; onset → first
   newly timestamped telemetry packet; onset → first newly presented video frame.
   A cached frame, socket-open event or changing UI placeholder does not count.
   Film a timestamp/LED at source and viewer for end-to-end video delay. Agree maximum
   acceptable control/video recovery times with the captain before moving the rover.
10. Verify panel drag persistence, camera switching/controls, telemetry and emergency
    stop behavior after recovery; verify expired retry budget/manual retry and two cycles.
11. Record trial count, median/worst delay, losses and logs in a team test report.
    Do not label this field-ready if the agreed limits are missed.

## Rollback

Stop/disable irc-failover on BOTH endpoints first. Restore exact original route
distances and enabled states from the recorded export; disable/remove only this
deployment's uniquely commented routes, routing rules and IP addresses. Restore
original WiFi bridge membership/PVID/STP settings and firewall exceptions from
the export over wired recovery access. Restore Netwatch/scheduler states only
after the original topology is back. Do not blindly import an export on top of
existing objects; use a reviewed restoration procedure to avoid duplicates.
Stop/disable rover-publisher and rover-mediamtx if rolling back video. Restore
previous local dashboard env and rebuild. No reset, reboot, radio reconfiguration
or rollback commands have been sent to hardware by this preparation.

## Offline validation

```sh
python -B -m unittest discover -s tests -v
node --test tests/video.test.mjs
npm run build
npm run lint
git diff --check
```

Mocks test decision logic and REST command construction, NOT actual WiFi forwarding,
RouterOS import syntax on your firmware, GStreamer encoding or systemd restart.
See REVIEW.md for the exact preparation results and publication commands.

References used for implementation: [MediaMTX configuration](https://mediamtx.org/docs/references/configuration-file),
[GStreamer publishing](https://mediamtx.org/docs/publish/gstreamer),
[NVIDIA accelerated GStreamer](https://docs.nvidia.com/jetson/archives/r38.2/DeveloperGuide/SD/Multimedia/AcceleratedGstreamer.html),
[Orin Nano software encoding](https://docs.nvidia.com/jetson/archives/r36.2/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html),
[RouterOS REST API](https://manual.mikrotik.com/docs/developer-guides/rest-api/),
[RouterOS ping](https://help.mikrotik.com/docs/spaces/ROS/pages/8323183/Ping),
[Netwatch](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/netwatch/).

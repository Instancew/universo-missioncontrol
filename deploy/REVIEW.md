# Review and publication — 21 November 2026

## Where the changes are

The original checkout was on `dashboard-rewrite`, with ten unresolved files and
saved MikroTik/video changes. With the owner's approval, implementation was done
in a separate **worktree of the same repository**:

`C:\Users\Vallabh\OneDrive\Documents\GitHub\IRC_DASHBOARD-feature`

Branch: `feature/mikrotik-https-integration`. The original conflicted checkout,
its index/stash, `dashboard-rewrite` and `main` were left alone. Nothing was
committed, staged, pushed, merged, reset or deployed to a CPE.

The saved feature changes were restored from Git object
`19f7636d386090451504b6de51ab1a660a724615`, excluding generated Python caches and
four old standalone router-probe scripts that contain local credentials. The
original versions remain untouched in the original checkout. No actual .env,
certificate private key, credentials, ZIP, node_modules or local executable is
included in this change. Existing dependencies were reused through an ignored
node_modules junction and the original approved Python virtual environment;
no software was installed.

## Team comparison

`git remote -v` showed:

- `origin`: https://github.com/vallabhchendke125-bot/IRC_DASHBOARD.git (kept)
- **`upstream`**: https://github.com/Rutss123/IRC_DASHBOARD.git (team destination)

No `team` remote was necessary. After fetching upstream, both the feature HEAD
and `upstream/networkstats-rewrite` were
`8b3f02f13d4af6fe2a76f858c4a4de1b725957a2`.
`git log upstream/networkstats-rewrite..HEAD` was empty: **no unrelated commits**.
Once reviewed and committed, the proposed PR to `networkstats-rewrite` would
contain the restored integration and new deployment work below. It does not
include the separate `dashboard-rewrite` overhaul or the old ZIP handoff commit.
Re-fetch/recompare immediately before publishing in case the team branch moves.

Existing shared history tracks **2,616 runtime/generated files**, largely
backend/venv and Python caches. None was changed or newly added here. Removing
them would be a separate team-approved cleanup; .gitignore does not untrack
existing files. The preserved react-grid-layout dependency/lockfile change came
from the saved integration, although CockpitLayout currently uses native dragging.
Review that pre-existing dependency choice before publication.

## File groups and behavior

The exact explicit staging allowlist is [PUBLICATION_FILES.txt](PUBLICATION_FILES.txt).
It avoids `git add .` and excludes unrelated/generated files.

| Files | Purpose |
|---|---|
| `.gitignore`, `.env.example`, `backend/.env.example` | Ignore local secrets/artifacts; document deployment addresses and settings |
| `backend/main.py`, `models/telemetry.py`, `routers/telemetry.py`, `services/telemetry_service.py` | Restore saved independent radio collection/custom telemetry without replacing UDP/WS telemetry |
| `backend/services/mikrotik_collector.py` | Preserve user's HTTPS radio collector, CA verification and scan safeguards |
| `backend/routers/radio_diagnostics.py` | Preserve optional diagnostic module, correct old import path; remains unregistered/disruptive scan disabled |
| `backend/routers/link_paths.py` | Read-only, freshness-checked controller status API |
| `src/components/system/RadioLinkPanel.jsx`, `src/pages/CockpitLayout.jsx` | Preserve existing radio statistics and captain's draggable panels |
| `src/pages/PrimaryOperatorView.jsx` | Use saved draggable layout; append per-band status within radio slot |
| `src/components/system/LinkPathStatus.jsx` | Both-band loss/RTT/association/RSSI/PHY context; dry-run/stale labels; video-only warning |
| `src/components/video/CameraFrame.jsx`, `RoverWebRTC.jsx`, `src/services/roverVideo.js`, `cameras.js` | Front Camera native WHEP receiver; frame freshness, drops/loss, bounded retries, session cleanup and resume logging |
| `src/context/RoverContext.jsx`, `vite.config.js` | Restore radio polling; same-origin API/WS defaults and configurable base proxy, avoiding viewer-local backend URLs |
| `package.json`, `package-lock.json` | Preserve saved dependency changes; no added test libraries |
| `deploy/jetson/*` | MediaMTX config, GStreamer publisher/plugin checks, systemd units and low-rate example profile |
| `deploy/network/*` | Local-router decision/controller, separate band probes, guarded CPE templates, dry-run examples and service |
| `deploy/bench/README.md` | Isolate historical Windows/phone instructions from production startup |
| `deploy/RUNBOOK.md`, `deploy/REVIEW.md`, `deploy/PUBLICATION_FILES.txt` | Setup, wiring/IP map, acceptance/rollback, review and publication |
| `tests/*` | Offline backend, failover, pipeline configuration and player lifecycle tests |

The existing radio panel, collector, draggable layout and telemetry service were
compared with the original checkout and match. Control components, UDP listener,
WebSocket service, other telemetry components and schema names were not rewritten.
UI controls being preserved does NOT certify physical motor control or command
acknowledgement; that remains a field verification.

## Validation actually run

| Check | Result |
|---|---|
| Approved Python env: `python -B -m unittest discover -s tests -v` | **22 passed**, no skips: healthy/weak/outage/backup-down/video-only/stable recovery/two cycles, API unknowns, parser/pinning, rollback, publisher configuration and backend APIs |
| `node --test tests/video.test.mjs` | **5 passed**: freshness, finite retries, mocked full receiver reconnect, frame-resume logging and session cleanup |
| `npm run build` | **Passed**, using existing Vite 8.0.14 dependencies; Browserslist age warning only |
| ESLint on new player/status modules and Vite config | **Passed** |
| `npm run lint` | **Fails: 107 errors, 1 warning** in preserved/existing code; compared against saved integration with identical per-file counts. No new lint violations |
| `git diff --check` | **Passed** |
| MediaMTX 1.21.4 local config smoke | **Passed**: config loaded; isolated loopback RTSP 18554 / WHEP 18889 reachable and UDP 18189 opened; temporary process terminated afterward |
| Known local-secret values, token/private-key patterns, new/generated files | **No matches/new artifacts in the proposed changes**; not a full historical secret audit |
| Generated-source GStreamer encode/WebRTC decode | **Not run**: no runnable gst-launch/gst-inspect detected on this Windows host; no Jetson attached; no security bypass or installation attempted |
| systemd process-crash/USB/publisher restart | **Pending Jetson**; runbook gives exact commands, not claimed as a passed runtime test |
| Live radios, RouterOS template import, route/return-path capture, RF recovery | **Pending hardware** |

Python tests were run with
`..\IRC_DASHBOARD\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`.
The global Python lacks backend dependencies; using it skips the three backend
tests. Fresh installs should use the approved requirements in a new environment.
The MediaMTX smoke only validates config/listeners; it does not prove streaming.

## Remaining live CPE checks

- Obtain exact exports, RouterOS/JetPack versions, interface/peer MAC inventory and
  Netwatch/hopper script sources; review conflict handling and rollback.
- Confirm separate routed transits, no RSTP blocking, both standby associations,
  and BOTH request/reply packet captures pinned to their respective band.
- Check policy rules, firewall, NAT, FastTrack, reverse-path filtering and stable
  service address during asymmetric route convergence.
- Run Jetson camera/encoder/CPU/restart tests and base-viewer playback/dragging checks.
- Run two consecutive failover cycles, weak associated link, unhealthy backup,
  video-only freeze, obstruction and complete interruption.
- Measure control ACK recovery, new telemetry recovery, and first fresh video
  separately against captain-approved limits. Do not drive from stale video.

Examples keep auto_apply=false and hardware_acceptance_passed=false; CPE service
routes are also disabled. Changing these guards is an explicit field deployment
step after static/dry-run acceptance, not something this preparation performed.

## Exact review, commit and push commands (NOT executed)

In PowerShell, use the feature worktree, not the conflicted original directory:

```powershell
Set-Location 'C:\Users\Vallabh\OneDrive\Documents\GitHub\IRC_DASHBOARD-feature'
git status --short --branch
git remote -v
git fetch upstream
git log --oneline upstream/networkstats-rewrite..HEAD
git diff --stat upstream/networkstats-rewrite
# Review all listed new files too: ordinary git diff omits untracked files.
Get-Content deploy/PUBLICATION_FILES.txt
git add --pathspec-from-file=deploy/PUBLICATION_FILES.txt
git diff --cached --check
git diff --cached --stat
git diff --cached
# Proceed only after reviewing that exact staged set:
git commit -m "Prepare Jetson video deployment and guarded dual-band failover"
git push upstream HEAD:refs/heads/feature/mikrotik-https-integration
```

The push command targets only the feature branch, never main or
networkstats-rewrite. No force push. It may be refused if the team has not granted
write access or a remote feature branch has diverged; stop and review rather than
overwriting anything. Once pushed, choose **base: networkstats-rewrite** and
**compare: feature/mikrotik-https-integration** in the team repository's PR UI.
No push permission test or write to GitHub was performed for this task.

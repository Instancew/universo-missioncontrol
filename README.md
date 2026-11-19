# IRC Dashboard handoff

The accompanying ZIP contains the last observed modified dashboard source files and untracked source files from the session. Paths are preserved so updated files can be compared with the same paths in the repository. RadioLinkPanel.jsx and the backend collector and telemetry files are included.

The Git working-tree inventory could not be rechecked in the current session because Git returned “this operation must be run in a work tree” under the current environment. The list is based on the last successful status captured earlier in this chat. Further changes since that status may be missing. Review each file against the target branch before applying it. No commit, upload or push was performed.

The ZIP deliberately excludes .env, credentials, virtual environments, node_modules, compiled Python caches, .git and build output. The launcher and camera scripts depend on local paths and existing dependencies. The launcher also refers to work/phone-dashboard.py and a local built dashboard. They are included as bench setup files, and require adaptation for another computer.

The base commit last observed is 8b3f02f, on branch feature/mikrotik-https-integration. The GitHub remote configured locally is https://github.com/Rutss123/IRC_DASHBOARD.git. Remote branch contents have not been verified.

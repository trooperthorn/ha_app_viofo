# Validation record — 0.1.0

## Inventory before implementation

- New local repository, branch `main`; no preexisting source, remote, dependencies or CI in the task directory.
- Windows host: Python 3.14.7, Node 26.8.1, Git 2.53.0.windows.3.
- No Docker executable/engine available in this task environment.
- HA Core/OS/Supervisor versions and server hardware not supplied; no connection to the Home Assistant host was made.
- Cameras were offline/unavailable. No settings were sent to either camera.
- RAZR became available during development. Both installed VIOFO APKs were copied read-only for static inspection; no phone settings, permissions or recordings were changed.

## Verified locally

**17 automated tests passed, no skips**, including real media operations using FFmpeg/ffprobe 9.0.2 on Windows. See `test-results.txt`.

Coverage includes:

- Private camera-address restrictions and file-path traversal rejection.
- Custom export filename header-injection rejection and sensor-row parsing/filtering.
- XML file-list parsing, current-state parsing, ambiguous settings disabled.
- Synthetic Novatek GPS atom decoding and corrupt-atom bounds.
- UI/status service, mutation header requirement, Ingress restriction and forwarded-header spoof rejection.
- Companion API authentication and token absence from status.
- Diagnostic bundle credential/IP redaction.
- Persistent job enqueue/dedup/pause/retry.
- Protected original deletion rejection and HTTP byte ranges.
- Setting write followed by read-back verification with a simulated response.
- Truncated camera transfer rejected against a local test server.
- Actual screenshot extraction, two-segment export with title card, three-view grid and invalid export cleanup without changing originals.

Python compilation and JavaScript syntax checks passed. Linux CPython 3.13 amd64 dependency wheels were resolved/downloaded successfully for the pinned aiohttp version. This checks dependency availability, not container execution.

Browser verification in the Codex browser:

- Overview rendered with two unconfigured cameras and no fabricated device status.
- Responsive layout inspected and adjusted for narrow app panels.
- A generated four-second MP4 was imported through the actual file chooser and analyzed to a four-second duration.
- Review interface displayed playback, speed, zoom, screenshot, route and telemetry controls.
- Screenshot initiated through the UI completed and exposed a download link in Activity.
- Actual browser playback reached readyState 4 with advancing playback time and no media error.
- A one-second trim with a three-second title was queued from the editor UI and completed with a downloadable result.
- The final map-enabled review page produced no browser console errors.
- No actual VIOFO recording or real GPS route was used in browser verification.

## Not established by those results

- HA OS container build/startup, amd64/aarch64 runtime behavior, default AppArmor behavior.
- Companion integration config-flow loading and entities inside actual HA Core.
- Camera protocol responses, downloads, recording coexistence, settings, live RTSP and station-mode recovery.
- GPS layout/time alignment or embedded G-sensor calibration for either user's camera.
- 4K rendering performance on the HA server, mobile Companion WebView codec behavior, live-stream concurrency.
- Remote GitHub CI, repository publication, release installation or HACS installation.

The supplied CI workflow is designed to run tests and build both architectures after publication. A successful future CI build still will not count as camera hardware validation.

## Reference provenance

Phone package inventory: older VIOFO 3.2.23-202603021912 (112), newer VIOFO Dashcam 2.2.03 (20260914). Camera metadata extracted from the actual newer package with `scripts/extract_command_metadata.py`; the database and APKs are not included in the deliverable.

GPS decoding helper derived from the MIT-licensed RobXYZ/viofosync source retrieved during this task. Container FFmpeg comes from Debian; local FFmpeg executables were used only for testing and are not included in the source archive. Leaflet 1.9.4 is vendored with its license.

## 0.1.1 field follow-up (2026-09-24)

User reports A229 Pro infrastructure Wi-Fi persists across reboot. Supplied 0.1.0 Linux diagnostics show four downloaded recordings, FFmpeg preview exits with code 1, and one timeout termination. FFmpeg stderr was discarded, so the precise cause remains unknown. Screenshot shows OSM access-block tiles; explicit tile origin referrer is now set to address possible enclosing-page policy interference. See https://operations.osmfoundation.org/policies/tiles/. No block bypass or tile proxy is introduced.

18 local tests pass, including failed-stream error capture/redaction and slot cleanup. JavaScript syntax check passes. Physical stream and HA browser map retests remain pending.

# VIOFO Workbench for Home Assistant OS

**0.1.2 — debug alpha.** A local app and companion integration for an A119 Mini 2 and A229 Pro. This is runnable software, not a UI mockup. It is **not yet a complete replacement for either official Android app or Windows Player**. See [the feature matrix](docs/CAPABILITIES.md) for exact implemented, experimental and unavailable workflows.

## Included

- HA OS app packaging for amd64 and aarch64, authenticated Ingress sidebar UI.
- Two independent camera profiles, station-mode HTTP adapter, XML/HTML listings, queued downloads, scheduled sync and serialized camera access.
- Local MP4/MOV/JPEG import, original downloads, filtering, camera pairing, browser playback, speed, zoom/pan, screenshots and sequential playback.
- FFmpeg trimming, multiple selected segments, optional title card, custom download filenames, one/two/three-view composition and 720p/1080p/2160p H.264/AAC exports.
- Embedded Novatek GPS parsing, local interactive route plotting, optional OpenStreetMap background, GPX export and mph/km/h display. G-sensor CSV import/plotting plus ExifTool embedded extraction where supported; embedded units/timing are not validated.
- Model-specific camera setting metadata from **the VIOFO Dashcam 2.2.03 package actually installed on the user's RAZR**. Writes are opt-in, enum-validated, restricted to commands reported by the camera, and checked by read-back. Ambiguous firmware-specific options remain read-only.
- Persistent queue with pause/cancel/retry/priority, quotas, optional age retention and protected originals.
- Debug enabled by default, rotating logs and downloadable redacted diagnostic ZIP.
- Companion entities: connectivity, firmware, last download, recording count, queued downloads, progress, inspect and sync buttons.

## Install on Home Assistant OS

Add `https://github.com/trooperthorn/ha_app_viofo` under **Settings → Apps → App store → Repositories**, then install **VIOFO Workbench**. Supervisor builds the app from this repository. Continue with step 3 below.

Alternatively, install through HA OS's local app directory:

1. Enable access to the HA OS **addons** share, for example using the official Samba share app. Copy the entire `viofo_workbench` folder into the share, producing `/addons/viofo_workbench/config.yaml` and `/addons/viofo_workbench/Dockerfile`.
2. In Home Assistant, open **Settings → Apps → App store** (older versions call these Add-ons), use **Check for updates / Reload**, then find **VIOFO Workbench** under local apps.
3. Install. Supervisor builds the container; the first build needs internet access for the Python base image, Debian packages and PyPI dependencies. Save the full build log if it fails.
4. Leave `log_level: debug`. Default footage storage is `/media/viofo`; retention deletion is **off** by default. Select a quota appropriate for your server.
5. Start the app and open its Web UI. Enable **Show in sidebar** if desired. The app does not require a privileged container, host networking, Bluetooth, USB access or Supervisor API permissions.
6. Import a few original recordings while cameras are offline. Analysis and exports appear under **Activity**. Download a diagnostic ZIP under **Diagnostics**.
7. When cameras are available, use the official app to configure station mode, then enter each camera's LAN IP under Workbench **Settings**. Start with **Inspect**, then **Browse files**, then one download. Enable scheduled sync only after checking the first transfer.

**Not yet tested:** installation under your HA Supervisor, container builds, real camera traffic and HA Core integration loading. Local Windows application tests are not evidence of those checks.

### Companion integration (optional)

1. Copy `custom_components/viofo_workbench` to `/config/custom_components/viofo_workbench` in Home Assistant. Restart Home Assistant.
2. Set a long random `api_token` in the app's Supervisor configuration and restart the app. This token is separate from Home Assistant access tokens. The default blank value disables the companion API.
3. Add **VIOFO Workbench** under Settings → Devices & services. For a local install, use `http://local-viofo-workbench:8100` and the same API token. For a repository install, use the app's actual internal hostname shown by Supervisor; the repository prefix will differ.
4. Leave port 8100 unpublished. HA Core can reach the internal app network. Port 8099 accepts only Supervisor Ingress; 8100 uses bearer-token authentication.

Example automation using the entities created by your installation:

```yaml
alias: Sync dashcams each evening
triggers:
  - trigger: time
    at: "20:00:00"
actions:
  - action: button.press
    target:
      entity_id:
        - button.a119_mini_2_sync_recordings
        - button.a229_pro_sync_recordings
mode: single
```

Entity IDs can differ; choose the actual entities in the automation editor. App polling is sufficient for ordinary automatic syncing. Neither scheduling mechanism can power on a sleeping camera or enable station mode remotely.

## Local development

Requires Python 3.13+, FFmpeg and ffprobe on PATH:

```powershell
python -m pip install -r viofo_workbench/requirements.txt
cd viofo_workbench
python -m app.server
```

Open `http://127.0.0.1:8099`. By default development data stays in `runtime/`, excluded from Git. Environment variables `VIOFO_DATA`, `FFMPEG`, `FFPROBE`, `PORT` and `API_PORT` override paths/ports. `VIOFO_HA=1` enables the HA Ingress source-IP restriction and `/media` storage requirement.

```powershell
python -m unittest discover -s tests -v
node --check viofo_workbench/app/static/app.js
python -m compileall -q viofo_workbench/app custom_components
```

CI runs Python tests and both architecture builds. See [GitHub Actions](https://github.com/trooperthorn/ha_app_viofo/actions) for results for each commit. Media tests require actual FFmpeg/ffprobe; do not count skipped tests as validation.

## Documents

- [Architecture and interface contract](docs/ARCHITECTURE.md)
- [Capability matrix and remaining work](docs/CAPABILITIES.md)
- [Hardware test and log-collection guide](docs/HARDWARE_TEST.md)
- [Verified evidence and validation results](docs/VALIDATION.md)

## Privacy and maintenance

No analytics or cloud upload is implemented. Map tiles are off by default. Enabling the map background sends tile coordinates, browser IP and origin to OpenStreetMap; the GPS route itself is rendered locally. Offline plotting does not require any map service.

Recordings, exports and diagnostic bundles stay local until you choose to download/share them. Debug logs exclude tokens, raw responses and GPS. Always review a bundle before sharing. Retention only removes unprotected local recordings; it never deletes camera files. Keep originals separately before using this alpha against valuable footage.

Firmware installation, SD formatting, factory reset and camera-file deletion are intentionally not implemented until their model-specific protocols can be validated. The UI links to the official firmware workflow instead of offering a nonfunctional update button.

Independent software, not affiliated with VIOFO. No VIOFO APKs, database assets, icons or proprietary application code are redistributed. GPS decoding includes MIT-licensed portions of RobXYZ/viofosync with attribution in `THIRD_PARTY_LICENSES.txt`; Leaflet has its own license in `app/static/vendor/leaflet-LICENSE`.

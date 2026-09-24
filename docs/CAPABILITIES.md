# Android / Windows parity matrix

This is the full **tracked scope**, not a claim of full parity in version 0.1.0. "Implemented" means code exists and the stated local checks ran; it does not imply a physical-camera test. Features requiring further implementation are explicitly identified.

## Actual installed applications inspected

RAZR package-manager inventory on 2026-09-24 UTC:

- `com.viofo.viofo`: **3.2.23-202603021912**, version code 112.
- `com.viofo.dashcam`: **2.2.03**, version code 20260914.

Both installed package files were inspected read-only. The new app's device command SQLite asset contains records for A119 MINI2 and A229P. Factual command/enum data was regenerated from that exact asset, preserving version fields. The DB SHA-256 is `102e631e02f48a8fc22632dbf57e24be696b6ff9f5ad24d8ceb195ed90d2d445`. The new app also contains battery-management/OTA components: those concern optional VIOFO battery accessories, not a Bluetooth video interface for these cameras.

The old app contains GPS parsing, video-trim and firmware-related classes. Their presence establishes code paths, not that a particular camera exposes each feature. Neither app was connected to a camera during this inspection. No proprietary app code or images are shipped.

Windows installation: binary strings verified single/dual/three-channel playback, screenshot paths, map choice, speed units, zoom, trim, title-screen and export controls. PE version is 0.0.0.0 and installer version is 1.0.0; these are not reliable product-build identifiers. Official current release notes supplement this static inspection.

## Camera connection and control

| Workflow | Workbench 0.1.0 | Evidence / remaining acceptance |
|---|---|---|
| Remember multiple devices | Implemented: two persistent editable profiles | Local tests / UI |
| Connect phone directly to camera AP | Replaced by server access to station-mode camera IP | No server Wi-Fi management or Bluetooth needed |
| Configure station SSID/password | Official app setup workflow documented | Not sent by Workbench |
| Reconnect automatically | Poll reachable configured IP; optional scheduled sync | Camera must independently enable/rejoin station mode |
| Live preview | Root RTSP → MJPEG bridge | No camera test; no live audio |
| Switch live lenses / split live preview | Not implemented beyond root stream | Need actual per-lens endpoints and concurrency limits |
| Start / stop recording | Implemented gated command + read-back | Simulated protocol test; hardware pending |
| Resolution, loop, audio, HDR, parking and other enum settings | Model-driven settings where present, unambiguous and reported by camera | Firmware-specific acceptance pending; ambiguous enums read-only |
| Photo capture | Local frame screenshot implemented | Camera-triggered still-photo capture not implemented |
| Firmware version | Read and display implemented | Hardware pending |
| Firmware update notification/download/OTA flashing | Official firmware link only | Not implemented: signed/model-matched update workflow required |
| SD format, factory reset, reboot | Not implemented; commands blocked | Must validate exact parameters and recovery behavior |
| Bluetooth remote / battery accessory setup | Not implemented | Separate hardware/protocol scope from dashcam video |

## Recording acquisition and management

| Workflow | Workbench 0.1.0 | Evidence / limitation |
|---|---|---|
| Camera file lists | XML listing and HTML fallback | Parser tests; actual firmware pending |
| Driving/parking/locked categories | Parsed from remote path/attributes; local filtering | Manual imports default to driving |
| Date filtering / filename ordering | Implemented local-library controls | Filename timestamp convention |
| Calendar with recording-day markers | Date picker/filter only | Month marker visualization not implemented |
| Multi-select downloads | Implemented | No camera test |
| Download queue and prioritization | Persisted, pause/cancel/retry/prioritize | Local tests; pause restarts transfer rather than byte-range resume |
| Automatic acquisition at home | Optional polling/sync | Station reconnect and parking power need hardware tests |
| Local phone/PC album equivalent | Local server library and original-file downloads | Browser import verified |
| Protect/unprotect files | Local retention protection | Does not set camera-side file lock |
| Delete recordings | Explicit local deletion only | Camera deletion unavailable |
| Share footage | Download original/export; then share through your browser/OS | No cloud sharing links or Android share-sheet integration |
| Storage limits / retention | Quota, free-space reserve, opt-in age cleanup | No automatic cleanup of exports; no remote deletion |

## Playback and editing

| Workflow | Workbench 0.1.0 | Evidence / limitation |
|---|---|---|
| Play original video | Byte-range browser playback | Synthetic MP4 imported/reviewed in UI |
| Single / dual / three-view review | Group by camera and filename timestamp | Relative time synchronization; not acoustic/frame calibration |
| Next recording | Sequential same-camera/same-channel progression | Browser autoplay permission can require a click |
| Slow/fast playback | 0.25×, 0.5×, 1×, 2×, 4× | Browser media control |
| Fullscreen / landscape | Fullscreen and responsive UI | HA mobile WebView policies may constrain fullscreen |
| Zoom / pan | Implemented | Digital enlargement only |
| Frame stepping | ±1/30 second controls | Time-based; not exact stepping for every source frame rate |
| Screenshots | FFmpeg JPEG output | Real media test and browser job verified |
| Single-range trim | Implemented | Real FFmpeg test |
| Multi-segment selection/join | Implemented | Real FFmpeg test |
| Multi-stream composition | Side-by-side or grid, up to three sources | Real three-view grid test |
| Title card | Optional three-second card | Real FFmpeg test |
| Export resolution | 720p / 1080p / 2160p | Tests at 720p; server capacity determines 4K throughput |
| Output filename | Generated job filename | Custom filenames not implemented |
| Audio in exports | First selected view, otherwise silence | Live bridge has no audio |
| Hardware acceleration | Not implemented | Software x264, bounded thread count |
| Live Photo | Not implemented | Official feature is iOS-only, not RAZR parity |

## Telemetry, settings and support

| Workflow | Workbench 0.1.0 | Evidence / limitation |
|---|---|---|
| GPS extraction / speed | Novatek parser, speed units | Synthetic binary fixture; original camera samples pending |
| Route with playback cursor | Interactive local map + optional OSM background | First-fix timing approximation disclosed |
| Google / Baidu provider choice | OSM alternative only | Google/Baidu integration not implemented |
| GPX export | Implemented | Synthetic parser test |
| G-sensor graph | Imported calibrated CSV plots | Embedded decoding unavailable, no synthetic claims |
| Language selection | English UI | Localization not implemented |
| Debug logs / support bundle | Enabled, rotated, redacted ZIP | Redaction test passed |
| HA automation entities | Companion integration source included | HA Core install/loading untested |

## Implementation priorities after installation

1. Complete HA OS amd64/aarch64 builds and actual ingress/integration checks.
2. Collect read-only firmware/settings/file-list evidence from both cameras, then verify single-file downloads and restart/parking behavior.
3. Validate GPS timing, three-channel grouping and G-sensor binary layout against original clips from each camera.
4. Resolve firmware-conditioned setting enums; validate recording controls and rejection behavior while recording.
5. Implement per-lens live preview/audio, camera photo/lock/delete/maintenance and firmware workflows only from verified protocol evidence.
6. Add calendar markers, localized UI, custom filenames, byte-range download resumption, hardware encoding and richer editing as recorded in this matrix.

## Sources

- [VIOFO new Android app workflow](https://www.viofo.com/blogs/viofo-car-dash-camera-guide-faq-and-news/get-to-know-the-new-viofo-app-smart-control-for-your-dash-cam)
- [VIOFO mobile editing/download update](https://www.viofo.com/blogs/viofo-car-dash-camera-guide-faq-and-news/viofo-dashcam-app-update-faster-playback-easier-editing-smarter-file-management)
- [VIOFO Windows Player releases](https://www.viofo.com/pages/viofo-app)
- [Station-mode support and root RTSP](https://www.viofo.com/blogs/viofo-car-dash-camera-guide-faq-and-news/how-to-enable-wi-fi-station-mode-on-your-dashcam)
- [RobXYZ/viofosync primary source](https://github.com/RobXYZ/viofosync) — MIT GPS decoder and camera protocol reference.
- [Novatek command reference](https://github.com/nutsey/novatek-web-api-commands/tree/command-list) — general protocol reference, not proof of VIOFO model support.
- [HA app configuration](https://developers.home-assistant.io/docs/apps/configuration/) and [Ingress requirements](https://developers.home-assistant.io/docs/apps/presentation/).

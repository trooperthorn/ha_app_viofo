# 0.1.3

- Preserve original download filenames.
- Display filename-derived camera-local recording dates in the library and transfers; remote listings can fall back to camera TIME fields. Unknown dates remain explicit.
- Browse/Sync opens a day-range picker defaulting to the latest dated day, with explicit selection and count/size summary. Automatic sync requires a saved date range.
- Pause all downloads and disable automatic sync to manage an existing full-card backlog. Paused jobs remain resumable.

# 0.1.2

- Fullscreen recording playback fills the available viewport, centers each camera view, and removes the normal 480px height limit. Preserve aspect ratio and native controls; overlay channel labels. Portrait displays stack views. Applies to every workflow using the shared recording player.

# 0.1.1

- Correct RTSP timeout option; retain bounded, redacted FFmpeg errors in diagnostics and display preview failures.
- Explicit origin-only referrer policy for optional OpenStreetMap tiles under HA Ingress; browser confirmation pending.
- User confirmed A229 Pro station Wi-Fi persists across reboot on their installation.

# Changelog

## 0.1.0

Initial debug alpha: HA OS packaging, local recording library, camera profiles and command metadata, queue and scheduled downloads, browser playback, FFmpeg screenshots and editing, GPS routes/GPX, telemetry CSV, companion integration and redacted diagnostics. Physical cameras and Supervisor installation remain untested. Full Android/Windows parity is tracked in the included capability matrix.

# VIOFO Workbench

Debug alpha for A119 Mini 2 and A229 Pro. Open the Web UI to import recordings, configure camera addresses and download diagnostics.

## Options

- `log_level`: defaults to `debug`; rotating application log, plus Supervisor stdout.
- `storage_path`: defaults to `/media/viofo`; must be inside `/media`. Do not change after importing without migrating the library/index.
- `max_storage_gb`: quota includes originals, exports and temporary export files.
- `retention_days`: local import/download age, not video capture time.
- `retention_enabled`: defaults to false. When enabled, expired unprotected local originals can be removed. Camera files and exports are not deleted.
- `sync_interval_seconds`: defaults to 300; profiles separately opt into scheduled sync.
- `api_token`: optional companion integration token. Blank disables the integration API. Do not use your Home Assistant access token.

Changes to preferences in the UI persist in `/data/preferences.json` and override the matching initial options. Storage path and API token remain controlled by Supervisor options. Changing those options requires an app restart.

Leave port 8100 unpublished when using the companion integration on HA OS. Use the app's internal hostname on port 8100. UI access is via Ingress on 8099.

## First run

1. Import an original recording; check Activity for analysis.
2. Review playback and try a small export.
3. When the cameras are on your home Wi-Fi, enter their station-mode IPs in Settings.
4. Inspect, browse and test one completed file before enabling scheduled sync.
5. Use Diagnostics → Download diagnostic bundle for troubleshooting.

Actual camera operation, HA OS installation and companion integration loading still require validation. Unsupported device-maintenance operations are explicitly shown in Settings. The complete README and feature matrix are included in the source package.

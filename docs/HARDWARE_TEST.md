# First installation and hardware test

This guide separates container, Home Assistant, recording-file and camera evidence. Do not mark a later stage passed based on an earlier one.

## 1. Build and startup

Install the local app as described in README. Keep debug on. Save the Supervisor installation/build log. If installation fails, capture the first failing command and its error, the HA OS version, host architecture and available disk space.

After starting, open the Web UI through Ingress. Check Diagnostics: both FFmpeg and ffprobe must be available. Confirm only the two unconfigured camera profiles are shown. Download `viofo-diagnostics.zip`; it should open and contain `report.json`, `debug.log` and `README.txt`.

For the companion integration, configure the separate token, leave the API host port unpublished, and confirm both devices and their entities appear. Unobserved cameras should be unknown, not falsely online. A successful app startup does not establish that HA Core can reach the integration API.

## 2. Original recording files

Use short original files, including matching front/rear (and interior, if fitted) clips from A229 Pro. Retain an independent original copy.

1. Import into the correct camera profile.
2. Check the analysis job completes, filename/channel/category/size and duration are correct, and original-file download matches a locally computed SHA-256.
3. Play each view. If HEVC fails in the browser, create a compatible copy and review that export.
4. Check paired views against an unmistakable event; record any synchronization offset. Filename grouping alone does not prove alignment.
5. Capture a screenshot. Export a short trim, two non-adjacent segments, a title card and a front/rear composition. Confirm duration, sound source, geometry and resolution.
6. Check GPS coordinates, speed and time against known recorded location/overlay. If absent, provide a short original MP4 for format analysis; re-encoded video may discard metadata. No GPS track is sent to a map service unless you enable online background tiles.
7. Embedded G-sensor support requires a recording containing known movement plus the official player display for comparison. CSV import is a separate, already implemented path and must not be mistaken for binary decoding.

## 3. Read-only camera connection

For each camera separately, record exact firmware version, attached channels, and whether parking power is available.

Configure station mode using the official mobile app. VIOFO documents REC+Wi-Fi for A119 Mini 2 and MIC+Wi-Fi for A229 Pro; consult the exact firmware's instructions before using buttons. Assign a DHCP reservation in your router if desired. Workbench needs the resulting private LAN IP, not the camera AP's address when it is disconnected from your network.

Save the profile with controls and automatic sync **off**. Run Inspect. Check the firmware string and status. Run Browse files and compare a small sample with the official app. Save diagnostics after each distinct failure. No need to send camera credentials or private footage in an initial bug report.

## 4. One transfer, then scheduled transfers

Select a completed, older recording. Compare reported byte count, downloaded duration and original SHA-256 if you have the SD-card copy. Observe whether camera recording continues during transfer. Repeat for another channel, parking and locked files.

Test network interruption during a transfer. The job must fail or be cancelled visibly and must not register a partial file as complete. Retry should create a usable original. Pause/resume restarts from zero in this release.

Enable automatic sync only after this works. Automatic sync defers the newest recording per channel to reduce the chance of copying an active segment. The final segment of a parked camera can therefore remain deferred until a later recording appears; manual download is available after it is known closed.

Then test: ignition cycle, camera restart, return home, parking-mode transition, and Wi-Fi loss/recovery. Record whether station mode needs manual enabling. If the firmware does not start station mode itself, polling cannot solve that hardware behavior. Don't report unattended arrival-home sync as validated until this sequence passes.

## 5. Camera controls

Enable controls for one camera. Start with a reversible, unambiguous setting and note its original value. Apply, verify the official display, then restore the original. Confirm Workbench reports read-back rather than just HTTP success. Test rejection while recording without allowing the app to stop recording implicitly.

Check recording start/stop deliberately and restore recording. Where the settings table shows an ambiguous/unsupported state, capture firmware and setting context; do not force numeric values. Format/reset/update/delete commands are blocked and are not part of this alpha's live test.

## Reporting a failure

Provide:

- App version, HA Core/OS/Supervisor versions, CPU architecture and available memory/storage.
- Camera model, firmware, channel configuration and power/parking state.
- Exact operation and time, expected result, actual result and request/job ID.
- App diagnostic ZIP and Supervisor build/startup log if relevant.
- For GPS/codec faults only, a deliberately selected short original recording, shared separately after reviewing its location/audio content.

The diagnostic ZIP is generated locally and is not uploaded anywhere by the app. Camera settings bodies, footage, IPs, tokens and GPS tracks are excluded. Review the ZIP before posting it publicly.

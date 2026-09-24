"""Bounded media processing and GPS parsing. Originals are never rewritten."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import struct
import textwrap
import xml.etree.ElementTree as ET
from .gps_vendor import get_gps_data

FFMPEG = os.getenv("FFMPEG", "ffmpeg")
FFPROBE = os.getenv("FFPROBE", "ffprobe")


async def process(args, timeout=600):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        raise
    if proc.returncode:
        # Paths and user title text deliberately excluded from outward diagnostics.
        raise ValueError(f"Media process failed ({proc.returncode}); check codec/input availability")
    return stdout


async def probe(path):
    if Path(path).suffix.lower() in (".jpg", ".jpeg"):
        return {"duration": 0, "image": True}
    raw = await process([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)], 30)
    data = json.loads(raw)
    if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
        raise ValueError("No video stream")
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid or unfinished recording")
    return dict(duration=duration, streams=data["streams"])


def atoms(f, start, end):
    position = start
    while position + 8 <= end:
        f.seek(position)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            if position + 16 > end:
                break
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        if size == 0:
            size = end - position
        if size < header or position + size > end:
            break
        yield position, size, header, kind
        position += size


def gps(path):
    """Novatek gps table; reject corrupt offsets and unreasonable allocations."""
    result = []
    path = Path(path)
    total = path.stat().st_size
    with path.open("rb") as f:
        for pos, size, header, kind in atoms(f, 0, total):
            if kind != b"moov":
                continue
            for sub, count, sh, sk in atoms(f, pos+header, pos+size):
                if sk != b"gps ":
                    continue
                offset = sub + sh + 8
                table_end = min(sub + count, offset + 800000)
                while offset + 8 <= table_end and len(result) < 100000:
                    f.seek(offset)
                    location, length = struct.unpack(">II", f.read(8))
                    offset += 8
                    if length < 12 or length > 65536 or location + length > total:
                        continue
                    f.seek(location)
                    data = f.read(length)
                    if data[4:12] != b"freeGPS ":
                        continue
                    decoded = get_gps_data(data[12:])
                    if not decoded:
                        continue
                    try:
                        when = dt.datetime.fromisoformat(decoded["DT"]["DT"])
                        loc = decoded["Loc"]
                        lat, lon, speed = loc["Lat"]["Float"], loc["Lon"]["Float"], loc["Speed"]
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= speed <= 100):
                            continue
                        result.append(dict(time=when.isoformat(), epoch=when.timestamp(), lat=lat, lon=lon,
                                           speed_kmh=speed*3.6, bearing=loc["Bearing"]))
                    except (ValueError, OverflowError, KeyError):
                        continue
    if result:
        origin = result[0]["epoch"]
        for point in result:
            point["seconds"] = point.pop("epoch") - origin
    return {"points": result, "source": "embedded Novatek GPS", "timing": "relative to first valid GPS fix; verify against video",
            "status": "decoded_unverified" if result else "no_supported_gps", "gsensor_status": "embedded_format_not_validated"}


def gpx(track):
    root = ET.Element("gpx", version="1.1", creator="VIOFO Workbench", xmlns="http://www.topografix.com/GPX/1/1")
    segment = ET.SubElement(ET.SubElement(root, "trk"), "trkseg")
    for p in track["points"]:
        node = ET.SubElement(segment, "trkpt", lat=str(p["lat"]), lon=str(p["lon"]))
        ET.SubElement(node, "time").text = p["time"]
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


async def screenshot(source, target, seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Invalid screenshot time")
    await process([FFMPEG, "-nostdin", "-v", "error", "-y", "-ss", str(seconds), "-i", str(source), "-frames:v", "1", str(target)], 60)
    if not target.exists():
        raise ValueError("No frame at this timestamp")


async def render_export(state, job, progress):
    payload = json.loads(job["payload"])
    segments = payload.get("segments", [])
    if not 1 <= len(segments) <= 50:
        raise ValueError("Select 1–50 segments")
    height = int(payload.get("height", 1080))
    if height not in (720, 1080, 2160):
        raise ValueError("Choose 720, 1080 or 2160")
    width = height * 16 // 9
    mode = payload.get("layout", "single")
    if mode not in ("single", "side_by_side", "grid"):
        raise ValueError("Invalid export layout")
    workspace = state.storage / "exports" / (job["id"] + "_work")
    workspace.mkdir(exist_ok=True)
    output = state.storage / "exports" / (job["id"] + ".mp4")
    parts = []
    encoding = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-threads", "2"]
    try:
        title = str(payload.get("title", ""))[:160]
        if title:
            # Text file plus expansion=none prevents filter-expression interpolation.
            (workspace / "title.txt").write_text("\n".join(textwrap.wrap(title, 45)), encoding="utf-8")
            font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            font_arg = f":fontfile='{font}'" if Path(font).exists() else ""
            textpath = str(workspace / "title.txt").replace("\\", "/").replace(":", "\\:")
            target = workspace / "title.mp4"
            await process([FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x101826:s={width}x{height}:r=30:d=3", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", f"drawtext=textfile='{textpath}':expansion=none{font_arg}:fontcolor=white:fontsize={height//25}:x=(w-text_w)/2:y=(h-text_h)/2", "-t", "3", *encoding, str(target)])
            parts.append(target)
        for index, segment in enumerate(segments):
            ids = segment.get("clips", [])
            if not 1 <= len(ids) <= 3 or (mode == "single" and len(ids) != 1):
                raise ValueError("Select one view for single mode, up to three for combined modes")
            start, end = float(segment["start"]), float(segment["end"])
            if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start or end-start > 3600:
                raise ValueError("Each segment must be between 0 and 3600 seconds")
            state.space(int((end-start)*height*width/4))
            command = [FFMPEG, "-nostdin", "-v", "error", "-y"]
            metadata = []
            for cid in ids:
                source = Path(state.clip(cid)["path"])
                info = await probe(source)
                if end > info["duration"] + .1:
                    raise ValueError("Segment exceeds one of the selected recordings")
                metadata.append(info)
                command += ["-ss", str(start), "-t", str(end-start), "-i", str(source)]
            audio = any(s.get("codec_type") == "audio" for s in metadata[0].get("streams", []))
            if not audio:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            n = len(ids)
            columns = n if mode == "side_by_side" else 2 if n > 1 else 1
            rows = 2 if mode == "grid" and n > 2 else 1
            cellw, cellh = width//columns//2*2, height//rows//2*2
            filters = []
            for i in range(n):
                filters.append(f"[{i}:v]setpts=PTS-STARTPTS,scale={cellw}:{cellh}:force_original_aspect_ratio=decrease,pad={cellw}:{cellh}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]")
            if n == 1:
                filters.append(f"[v0]scale={width}:{height}[out]")
            else:
                layout = "|".join(f"{(i%columns)*cellw}_{(i//columns)*cellh}" for i in range(n))
                filters.append("".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black,pad={width}:{height}:0:0[out]")
            target = workspace / f"segment{index}.mp4"
            command += ["-filter_complex", ";".join(filters), "-map", "[out]", "-map", "0:a:0" if audio else f"{n}:a:0", "-t", str(end-start), *encoding, str(target)]
            await process(command, 3600)
            parts.append(target)
            await progress((index+1)/(len(segments)+1))
        manifest = workspace / "concat.txt"
        manifest.write_text("\n".join("file '" + p.name + "'" for p in parts), encoding="utf-8")
        await process([FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", str(manifest), "-c", "copy", "-movflags", "+faststart", str(output)])
        await probe(output)
        state.space()
        return str(output.name)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

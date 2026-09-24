"""Model-scoped Novatek adapter. No automatic recording-state changes."""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import unquote, urlsplit, quote
import xml.etree.ElementTree as ET

import aiohttp
from .core import MODELS

MAP = json.loads((Path(__file__).parent / "command_map.json").read_text(encoding="utf-8"))
BLOCKED = {3010, 3011, 3013, 3018, 3023, 4003, 4004, 5001, 8230, 9316, 9317}
READS = {3012, 3014, 3017, 3024}


def remote_path(raw):
    raw = unquote(raw).replace("\\", "/")
    raw = re.sub(r"^[A-Za-z]:", "", raw)
    if "?" in raw or "#" in raw or ":" in raw or "\x00" in raw:
        raise ValueError("Invalid camera file path")
    if any(p in ("..", ".") for p in raw.split("/")):
        raise ValueError("Invalid camera file path")
    p = PurePosixPath("/" + raw.lstrip("/"))
    if not str(p).upper().startswith("/DCIM/") or p.suffix.lower() not in (".mp4", ".mov", ".jpg", ".jpeg"):
        raise ValueError("File is not a supported DCIM recording")
    return str(p)


def file_record(path, size=0, stamp="", locked=False):
    path = remote_path(path)
    upper = path.upper()
    return dict(path=path, name=PurePosixPath(path).name, size=int(size), timestamp=stamp,
                category="locked" if locked or "/RO/" in upper else "parking" if "/PARKING/" in upper else "driving")


def parse_listing(body):
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        raise ValueError("Unexpected XML declaration")
    root = ET.fromstring(body)
    files = []
    for node in root.findall(".//File"):
        data = {c.tag.upper(): c.text or "" for c in node}
        try:
            files.append(file_record(data["FPATH"], data.get("SIZE", 0), data.get("TIME", ""), data.get("ATTR") == "33"))
        except (ValueError, KeyError):
            continue
    return files


class Links(HTMLParser):
    def __init__(self, directory):
        super().__init__()
        self.files = []
        self.directory = directory

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        if tag != "a" or urlsplit(href).netloc or urlsplit(href).scheme:
            return
        try:
            self.files.append(file_record(href if href.startswith("/") else self.directory + "/" + href))
        except ValueError:
            pass


def states(body):
    return {int(k): int(v) for k, v in re.findall(r"<Cmd>\s*(\d+)\s*</Cmd>\s*<Status>\s*(-?\d+)\s*</Status>", body)}


def settings_for(model, channels, current):
    result = []
    for cmd, item in MAP[MODELS[model]]["commands"].items():
        cmd = int(cmd)
        if cmd <= 0 or cmd in BLOCKED or not item["options"]:
            continue
        options = {}
        ambiguous = False
        for option in item["options"]:
            tag = option.get("camera_tag", "")
            if tag and tag != channels:
                continue
            key = str(option["index"])
            if key in options and options[key] != option["value"]:
                ambiguous = True
            options.setdefault(key, option["value"])
        # Only offer commands actually reported by this camera's current-status response.
        result.append(dict(command=cmd, key=item["key"], label=item["key"].removeprefix("CMD_").replace("_", " ").title(),
                           options=options, current=current.get(cmd), writable=bool(options) and cmd in current and not ambiguous,
                           ambiguous=ambiguous,
                           evidence="Android command database; unverified on your firmware"))
    return result


class CameraClient:
    def __init__(self, state, session):
        self.state, self.session = state, session
        self.locks = {c["id"]: asyncio.Lock() for c in state.cameras}

    async def request(self, camera, cmd, par=None):
        if cmd in BLOCKED or not camera["address"]:
            raise ValueError("Command unsupported or camera address not configured")
        args = dict(custom=1, cmd=cmd)
        if par is not None:
            args["par"] = par
        start = time.monotonic()
        async with self.session.get(camera["address"] + "/", params=args, allow_redirects=False,
                                    timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                raise ValueError(f"Camera HTTP status {r.status}")
            chunks = []
            length = 0
            async for chunk in r.content.iter_chunked(65536):
                length += len(chunk)
                if length > 8_000_000:
                    raise ValueError("Camera response exceeds limit")
                chunks.append(chunk)
            data = b"".join(chunks)
        self.state.log.debug("camera_request camera=%s cmd=%d elapsed_ms=%d bytes=%d", camera["id"], cmd, 1000*(time.monotonic()-start), len(data))
        return data.decode("utf-8", errors="replace")

    async def inspect(self, cid):
        c = self.state.camera(cid)
        async with self.locks[cid]:
            try:
                firmware = await self.request(c, 3012)
                current = states(await self.request(c, 3014))
                strings = re.findall(r"<String>([^<]*)</String>", firmware)
                obs = dict(online=True, observed_at=time.time(), firmware=strings[0][:200] if strings else "Unrecognized response",
                           settings=settings_for(c["model"], c["channels"], current), recording=current.get(2001),
                           hardware_validated=False)
                if not current and not strings:
                    raise ValueError("Address did not return recognizable VIOFO data")
                obs["last_download"] = self.state.observations.get(cid, {}).get("last_download")
                self.state.observations[cid] = obs
                return obs
            except Exception as exc:
                self.state.observations[cid] = dict(online=False, observed_at=time.time(), error=type(exc).__name__)
                raise

    async def listing(self, cid):
        c = self.state.camera(cid)
        async with self.locks[cid]:
            try:
                files = parse_listing(await self.request(c, 3015, 1))
            except (ValueError, ET.ParseError):
                files = []
                succeeded = False
                for directory in ("/DCIM/Movie", "/DCIM/Movie/RO", "/DCIM/Movie/Parking"):
                    async with self.session.get(c["address"] + directory + "/", allow_redirects=False,
                                                timeout=aiohttp.ClientTimeout(total=12)) as r:
                        if r.status != 200:
                            continue
                        parser = Links(directory)
                        parser.feed((await r.content.read(8_000_000)).decode("utf-8", errors="replace"))
                        files.extend(parser.files)
                        succeeded = True
                if not succeeded:
                    raise ValueError("Neither XML nor HTML file listing was available")
            files = list({f["path"]: f for f in files}.values())
            self.state.remote[cid] = {f["path"]: f for f in files}
            return files

    async def write(self, cid, cmd, value):
        c = self.state.camera(cid)
        if not c["writes"]:
            raise ValueError("Enable camera controls in the camera profile first")
        async with self.locks[cid]:
            current = states(await self.request(c, 3014))
            if cmd == 2001:
                if value not in (0, 1):
                    raise ValueError("Recording accepts 0 or 1")
            else:
                entry = next((s for s in settings_for(c["model"], c["channels"], current) if s["command"] == cmd), None)
                if not entry or not entry["writable"] or str(value) not in entry["options"]:
                    raise ValueError("Setting/value is not supported by this model and current camera response")
            response = states(await self.request(c, cmd, value))
            if response.get(cmd, -1) != 0:
                raise ValueError("Camera rejected command; recording was not automatically interrupted")
            for _ in range(3):
                await asyncio.sleep(.4)
                after = states(await self.request(c, 3014))
                if after.get(cmd) == value:
                    self.state.log.info("camera_write_verified camera=%s command=%d", cid, cmd)
                    return dict(verified=True, command=cmd, value=value)
            raise ValueError("Command sent but read-back did not confirm it; inspect camera before retrying")

    async def download(self, cid, record, target, progress):
        c = self.state.camera(cid)
        path = remote_path(record["path"])
        url = c["address"] + quote(path, safe="/")
        async with self.locks[cid]:
            # Two HEAD observations protect against normal in-progress files. Some firmware
            # reports stale sizes; ffprobe and post-transfer checks are additional, not proof.
            async def head():
                async with self.session.head(url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status != 200:
                        raise ValueError("Camera HEAD unavailable; cannot verify transfer length")
                    return int(r.headers.get("Content-Length", 0))
            expected = await head()
            await asyncio.sleep(1)
            if not expected or await head() != expected:
                raise ValueError("Recording size is changing; retry after recording segment closes")
            self.state.space(expected)
            received = 0
            async with self.session.get(url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=None, sock_read=30)) as r:
                if r.status != 200:
                    raise ValueError("Download failed")
                with target.open("wb") as out:
                    async for chunk in r.content.iter_chunked(256*1024):
                        received += len(chunk)
                        if received > expected:
                            raise ValueError("Recording grew during download")
                        out.write(chunk)
                        await progress(received / expected)
            if received != expected or await head() != expected:
                raise ValueError("Incomplete or changing recording; retry later")
        return expected

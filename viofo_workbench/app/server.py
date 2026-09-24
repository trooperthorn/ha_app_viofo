from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import time
import zipfile

import aiohttp
from aiohttp import web
from . import VERSION
from .core import State, atomic_json
from .camera import CameraClient
from . import media

STATIC = Path(__file__).parent / "static"


@web.middleware
async def security(request, handler):
    state = request.app["state"]
    if request.content_type == "application/json" and (request.content_length or 0) > 2_000_000:
        raise web.HTTPRequestEntityTooLarge(max_size=2_000_000, actual_size=request.content_length)
    if request.app["integration"]:
        token = state.options.get("api_token", "")
        if not token or not secrets.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise web.HTTPUnauthorized()
    elif os.getenv("VIOFO_HA") == "1":
        if request.remote != "172.30.32.2":
            raise web.HTTPForbidden(text="Ingress only")
    elif request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden(text="Local development only")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.app["integration"]:
        if request.headers.get("X-Viofo-Request") != "1":
            raise web.HTTPForbidden(text="Missing same-origin request header")
    request_id = secrets.token_hex(4)
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except (ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        state.log.warning("request_failed request=%s reason=%s", request_id, str(exc))
        response = web.json_response({"error": str(exc), "request_id": request_id}, status=400)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        state.log.warning("transport_failed request=%s type=%s", request_id, type(exc).__name__)
        response = web.json_response({"error": "Camera or media service unavailable: " + type(exc).__name__, "request_id": request_id}, status=503)
    except Exception as exc:
        state.log.error("unexpected_error request=%s type=%s", request_id, type(exc).__name__)
        response = web.json_response({"error": "Unexpected error; use request ID in diagnostics", "request_id": request_id}, status=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'"
    return response


def public_status(state):
    cameras = []
    for c in state.cameras:
        obs = state.observations.get(c["id"], {})
        age = time.time() - obs.get("observed_at", 0)
        camera_jobs = [j for j in state.rows("SELECT kind,state,progress,updated,payload FROM jobs WHERE kind='download'") if json.loads(j["payload"]).get("camera") == c["id"]]
        completed = [j["updated"] for j in camera_jobs if j["state"] == "done"]
        if completed:
            obs = obs | {"last_download": max(completed)}
        running = [j["progress"] for j in camera_jobs if j["state"] == "running"]
        stats = dict(download_progress=round(max(running, default=0)*100,1), queued_downloads=sum(j["state"] in ("queued","running","paused") for j in camera_jobs), recordings=state.rows("SELECT count(*) AS n FROM clips WHERE camera=?", (c["id"],))[0]["n"])
        cameras.append(c | {"observation": obs | {"stale": age > 600}, "configured": bool(c["address"]), "stats":stats})
    clips = state.rows("SELECT count(*) AS count, coalesce(sum(size),0) AS bytes FROM clips")[0]
    jobs = state.rows("SELECT id,kind,state,progress,created,updated,error,result,priority FROM jobs ORDER BY priority DESC, created DESC LIMIT 200")
    return dict(version=VERSION, cameras=cameras, library=clips, jobs=jobs,
                media_tools=dict(ffmpeg=bool(shutil.which(media.FFMPEG)), ffprobe=bool(shutil.which(media.FFPROBE)), exiftool=bool(shutil.which(media.EXIFTOOL))),
                options={k:v for k,v in state.options.items() if k != "api_token"}, uptime=time.time()-state.started)


async def index(request):
    return web.FileResponse(STATIC / "index.html")


async def status(request):
    return web.json_response(public_status(request.app["state"]))


async def camera_config(request):
    if request.app["camera"].locks[request.match_info["cid"]].locked():
        raise ValueError("Camera is busy; wait for its current operation before editing the profile")
    return web.json_response(request.app["state"].save_camera(request.match_info["cid"], await request.json()))


async def camera_action(request):
    client, state = request.app["camera"], request.app["state"]
    cid, action = request.match_info["cid"], request.match_info["action"]
    if action == "inspect":
        return web.json_response(await client.inspect(cid))
    if action == "files":
        return web.json_response(await client.listing(cid))
    if action == "settings":
        body = await request.json()
        return web.json_response(await client.write(cid, int(body["command"]), int(body["value"])))
    if action == "sync":
        files = await client.listing(cid)
        # Never enqueue the newest clip of any channel while the camera may be recording.
        newest = {}
        for f in files:
            channel = re.search(r"([FRI])\.(?:MP4|MOV)$", f["name"], re.I)
            key = channel[1].upper() if channel else "F"
            if key not in newest or f["name"] > newest[key]:
                newest[key] = f["name"]
        known = {r["name"] for r in state.rows("SELECT name FROM clips WHERE camera=?", (cid,))}
        ids = [state.add_job("download", {"camera":cid, "record":f}) for f in files if f["name"] not in known and f["name"] not in newest.values()]
        return web.json_response({"queued":ids, "deferred_newest":list(newest.values())})
    if action == "download":
        body = await request.json()
        paths = body.get("paths", [])
        if not 1 <= len(paths) <= 500:
            raise ValueError("Select 1–500 recordings")
        records = request.app["state"].remote.get(cid, {})
        jobs = [state.add_job("download", {"camera":cid, "record":records[p]}) for p in paths]
        return web.json_response({"queued":jobs})
    raise web.HTTPNotFound()


async def library(request):
    clips = request.app["state"].rows("SELECT id,camera,name,category,channel,group_key,size,created,protected,sha256,metadata FROM clips ORDER BY name DESC LIMIT 10000")
    for c in clips:
        c["metadata"] = json.loads(c["metadata"])
    return web.json_response(clips)


async def upload(request):
    state = request.app["state"]
    camera = request.query.get("camera", "mini2")
    state.camera(camera)
    reader = await request.multipart()
    ids = []
    while field := await reader.next():
        if not field.filename:
            continue
        name = field.filename.replace("\\", "/").split("/")[-1][:160]
        if Path(name).suffix.lower() not in (".mp4", ".mov", ".jpg", ".jpeg"):
            raise ValueError("Import MP4, MOV or JPEG files")
        safe_name = secrets.token_hex(12) + Path(name).suffix.lower()
        path = state.storage / "recordings" / safe_name
        part = path.with_suffix(".part")
        registered = False
        try:
            with part.open("wb") as out:
                while chunk := await field.read_chunk(256*1024):
                    state.space(len(chunk))
                    out.write(chunk)
            os.replace(part, path)
            # Probe/index runs in the queue, so large imports do not hold an HTTP request open.
            cid = state.register(path, camera, name, metadata={"status":"analysis_queued"})
            registered = True
            state.add_job("analyze", {"clip":cid})
            ids.append(cid)
        except BaseException:
            part.unlink(missing_ok=True)
            if not registered:
                path.unlink(missing_ok=True)
            raise
    return web.json_response({"imported":ids})


async def clip_action(request):
    state = request.app["state"]
    clip = state.clip(request.match_info["clip"])
    path = Path(clip["path"])
    action = request.match_info["action"]
    allowed = {"media": {"GET", "HEAD"}, "download": {"GET", "HEAD"}, "gps": {"GET"}, "gpx": {"GET"}, "telemetry": {"GET", "POST"}, "protect": {"POST"}, "delete": {"POST"}, "snapshot": {"POST"}, "proxy": {"POST"}}
    if action not in allowed or request.method not in allowed[action]:
        raise web.HTTPMethodNotAllowed(request.method, allowed.get(action, set()))
    if action in ("media", "download"):
        headers = {"Content-Disposition": "attachment; filename=recording" + path.suffix} if action == "download" else {}
        return web.FileResponse(path, headers=headers)
    if action == "protect":
        data = await request.json()
        state.execute("UPDATE clips SET protected=? WHERE id=?", (int(bool(data["protected"])), clip["id"]))
        return web.json_response({"protected":bool(data["protected"])})
    if action == "delete":
        data = await request.json()
        if data.get("confirm") != clip["id"]:
            raise ValueError("Confirm local recording ID")
        if clip["protected"]:
            raise ValueError("Unprotect the local recording first")
        active = state.rows("SELECT payload FROM jobs WHERE state IN ('queued','running','paused')")
        if any(clip["id"] in j["payload"] for j in active):
            raise ValueError("Recording is referenced by an active job")
        path.unlink(missing_ok=True)
        state.execute("DELETE FROM clips WHERE id=?", (clip["id"],))
        return web.json_response({"deleted_local":True})
    if action in ("gps", "gpx"):
        track = await asyncio.to_thread(media.gps, path)
        if action == "gpx":
            return web.Response(body=media.gpx(track), content_type="application/gpx+xml", headers={"Content-Disposition":"attachment; filename=track.gpx"})
        return web.json_response(track)
    if action == "snapshot":
        data = await request.json()
        return web.json_response({"job":state.add_job("snapshot", {"clip":clip["id"], "seconds":float(data["seconds"])})})
    if action == "proxy":
        return web.json_response({"job":state.add_job("export", {"segments":[{"clips":[clip["id"]],"start":0,"end":json.loads(clip["metadata"])["duration"]}], "height":720,"layout":"single"})})
    if action == "telemetry":
        # CSV import allows calibrated telemetry without pretending unknown embedded layouts work.
        if request.method == "GET":
            sidecar = state.root / (clip["id"] + "_telemetry.json")
            embedded = state.root / (clip["id"] + "_embedded_telemetry.json")
            source = sidecar if sidecar.exists() else embedded
            return web.json_response(json.loads(source.read_text()) if source.exists() else {"status":"no_calibrated_gsensor_data", "points":[]})
        data = await request.json()
        rows = list(csv.DictReader(io.StringIO(data["csv"])))
        if len(rows) > 100000:
            raise ValueError("Too many telemetry samples")
        points = []
        import math
        for r in rows:
            p = {k:float(r[k]) for k in ("seconds", "x", "y", "z")}
            if not all(math.isfinite(v) for v in p.values()) or p["seconds"] < 0:
                raise ValueError("Invalid telemetry sample")
            points.append(p)
        points.sort(key=lambda p:p["seconds"])
        result = {"status":"imported", "units":str(data.get("units","unspecified"))[:30], "points":points}
        atomic_json(state.root / (clip["id"] + "_telemetry.json"), result)
        return web.json_response(result)
    raise web.HTTPNotFound()


async def export(request):
    body = await request.json()
    if "filename" in body:
        filename = re.sub(r"[^A-Za-z0-9_. -]", "_", str(body["filename"]))[:100].strip(" .")
        body["filename"] = (filename.removesuffix(".mp4") or "edited-recording") + ".mp4"
    return web.json_response({"job":request.app["state"].add_job("export", body)})


async def job_action(request):
    state, jid = request.app["state"], request.match_info["jid"]
    job = state.job(jid)
    body = await request.json()
    action = body["action"]
    if action == "prioritize":
        state.update_job(jid, priority=int(time.time()))
    elif action in ("pause", "cancel"):
        if job["state"] in ("done", "failed", "cancelled"):
            raise ValueError("Job is no longer active")
        state.update_job(jid, state="paused" if action == "pause" else "cancelled")
        running = request.app["running"].get(jid)
        if running:
            running.cancel()
    elif action == "retry":
        if job["state"] not in ("failed", "paused", "cancelled"):
            raise ValueError("Only failed, paused or cancelled jobs can be retried")
        state.update_job(jid, state="queued", error="", progress=0)
    else:
        raise ValueError("Unknown queue action")
    return web.json_response(state.job(jid) | {"payload":"omitted"})


async def exported(request):
    state = request.app["state"]
    job = state.job(request.match_info["jid"])
    if job["state"] != "done" or not job["result"]:
        raise ValueError("Export is not ready")
    path = state.storage / "exports" / Path(job["result"]).name
    filename = json.loads(job["payload"]).get("filename", path.name)
    return web.FileResponse(path, headers={"Content-Disposition":'attachment; filename="' + filename + '"'})


async def live(request):
    state = request.app["state"]
    c = state.camera(request.match_info["cid"])
    if not c["address"]:
        raise ValueError("Configure camera address first")
    if request.app["live_count"] >= 2:
        raise ValueError("Two live previews are already open")
    from urllib.parse import urlsplit
    host = urlsplit(c["address"]).hostname
    # Vendor documents the root RTSP stream. Per-lens RTSP endpoints need hardware discovery.
    request.app["live_count"] += 1
    proc = None
    stderr_task = None
    async def collect_errors(stream):
        tail = b""
        while chunk := await stream.read(4096):
            tail = (tail + chunk)[-8192:]
        return tail.decode("utf-8", errors="replace")
    try:
        proc = await asyncio.create_subprocess_exec(
            media.FFMPEG, "-nostdin", "-v", "error", "-rtsp_transport", "tcp",
            "-timeout", "10000000", "-i", f"rtsp://{host}/", "-an",
            "-vf", "fps=5,scale=960:-2", "-threads", "2", "-f", "mpjpeg",
            "-boundary_tag", "frame", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stderr_task = asyncio.create_task(collect_errors(proc.stderr))
        # Do not send a successful HTTP response until FFmpeg produces output.
        chunk = await asyncio.wait_for(proc.stdout.read(65536), 20)
        if not chunk:
            raise ValueError("Live preview failed to start; download diagnostics for the FFmpeg error")
        response = web.StreamResponse(headers={"Content-Type":"multipart/x-mixed-replace; boundary=frame", "Cache-Control":"no-store"})
        await response.prepare(request)
        while chunk:
            await response.write(chunk)
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), 20)
            except asyncio.TimeoutError:
                state.log.warning("live_preview_stalled camera=%s", c["id"])
                break
        return response
    except ConnectionError:
        return response if 'response' in locals() else web.Response(status=503)
    finally:
        if proc is not None:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        if stderr_task is not None:
            error = await stderr_task
            if error.strip():
                # Omit endpoint URLs and addresses before diagnostics are persisted.
                error = re.sub(r"rtsp://[^\s]+", "<camera-stream>", error)
                error = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<address>", error)
                state.log.warning("live_preview_ffmpeg camera=%s detail=%s", c["id"], error[-4096:].replace("\n", " | "))
        request.app["live_count"] -= 1
        state.log.info("live_preview_closed camera=%s process_code=%s", c["id"], proc.returncode if proc else "not_started")


async def diagnostics(request):
    state = request.app["state"]
    # Export only selected fields; no raw configuration, camera responses, paths or GPS.
    report = dict(version=VERSION, platform=platform.system(), python=platform.python_version(),
                  uptime_seconds=int(time.time()-state.started),
                  models=[{"id":c["id"], "model":c["model"], "configured":bool(c["address"]), "auto_sync":c["auto_sync"]} for c in state.cameras],
                  counts=state.rows("SELECT kind,state,count(*) AS count FROM jobs GROUP BY kind,state"),
                  library=state.rows("SELECT count(*) AS clips,sum(size) AS bytes FROM clips"),
                  ffmpeg=bool(shutil.which(media.FFMPEG)), exiftool=bool(shutil.which(media.EXIFTOOL)), aiohttp=aiohttp.__version__, machine=platform.machine(), hardware_validation="pending")
    log = (state.root / "logs" / "debug.log").read_text(encoding="utf-8")[-250000:]
    for c in state.cameras:
        for value in (c.get("address"), c.get("name")):
            if value:
                log = log.replace(value, "[REDACTED]")
    for value in (str(state.root), str(state.storage), state.options.get("api_token")):
        if value:
            log = log.replace(value, "[REDACTED]")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", json.dumps(report, indent=2))
        z.writestr("debug.log", log)
        z.writestr("README.txt", "No recordings, GPS tracks, IP addresses, API tokens or raw camera settings are included. Review before sharing.\n")
    return web.Response(body=buf.getvalue(), content_type="application/zip", headers={"Content-Disposition":"attachment; filename=viofo-diagnostics.zip"})


async def preferences(request):
    state = request.app["state"]
    body = await request.json()
    for key, low, high in (("max_storage_gb",1,100000), ("retention_days",1,3650), ("sync_interval_seconds",30,86400)):
        if key in body:
            n = int(body[key])
            if not low <= n <= high:
                raise ValueError("Setting outside permitted range")
            state.options[key] = n
    if "retention_enabled" in body:
        state.options["retention_enabled"] = bool(body["retention_enabled"])
    if "log_level" in body:
        if body["log_level"] not in ("debug", "info", "warning", "error"):
            raise ValueError("Invalid log level")
        state.options["log_level"] = body["log_level"]
        state.log.setLevel(body["log_level"].upper())
    # HA options remain Supervisor-owned. UI preferences stored separately and reloaded.
    saved = {k:v for k,v in state.options.items() if k not in ("api_token", "storage_path")}
    atomic_json(state.root / "preferences.json", saved)
    return web.json_response(saved)


async def execute_job(app, job):
    state = app["state"]
    jid = job["id"]
    payload = json.loads(job["payload"])
    state.update_job(jid, state="running")
    async def progress(value):
        if state.job(jid)["state"] != "running":
            raise asyncio.CancelledError()
        state.update_job(jid, progress=value)
        await asyncio.sleep(0)
    result = ""
    part = None
    try:
        if job["kind"] == "download":
            record = payload["record"]
            suffix = Path(record["name"]).suffix.lower()
            final = state.storage / "recordings" / (jid + suffix)
            part = final.with_suffix(".part")
            await app["camera"].download(payload["camera"], record, part, progress)
            os.replace(part, final)
            try:
                info = await media.probe(final)
                cid = state.register(final, payload["camera"], record["name"], record["category"], info)
                state.add_job("analyze", {"clip":cid})
            except BaseException:
                final.unlink(missing_ok=True)
                raise
            state.observations.setdefault(payload["camera"], {})["last_download"] = time.time()
        elif job["kind"] == "analyze":
            clip = state.clip(payload["clip"])
            info = await media.probe(clip["path"])
            track = await asyncio.to_thread(media.gps, clip["path"])
            telemetry = await media.embedded_telemetry(clip["path"])
            atomic_json(state.root / (clip["id"] + "_embedded_telemetry.json"), telemetry)
            info.update(gps_points=len(track["points"]), gps_status=track["status"], gsensor_status=telemetry["status"])
            state.execute("UPDATE clips SET metadata=? WHERE id=?", (json.dumps(info), clip["id"]))
        elif job["kind"] == "snapshot":
            state.space(10_000_000)
            result = jid + ".jpg"
            await media.screenshot(state.clip(payload["clip"])["path"], state.storage / "exports" / result, payload["seconds"])
        elif job["kind"] == "export":
            result = await media.render_export(state, job, progress)
        else:
            raise ValueError("Unknown job type")
        state.update_job(jid, state="done", progress=1, result=result)
        state.log.info("job_complete job=%s kind=%s", jid, job["kind"])
    except asyncio.CancelledError:
        if state.job(jid)["state"] == "running":
            state.update_job(jid, state="queued", progress=0)
        raise
    except Exception as exc:
        # Error strings are constrained: raw network error text may include credentials/paths.
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        state.update_job(jid, state="failed", error=error[:250])
        state.log.warning("job_failed job=%s kind=%s reason=%s", jid, job["kind"], error)
    finally:
        if part:
            part.unlink(missing_ok=True)


async def worker(app):
    while True:
        state = app["state"]
        jobs = state.rows("SELECT * FROM jobs WHERE state='queued' ORDER BY priority DESC,created LIMIT 1")
        if not jobs:
            await asyncio.sleep(.5)
            continue
        job = jobs[0]
        task = asyncio.create_task(execute_job(app, job))
        app["running"][job["id"]] = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise
        finally:
            app["running"].pop(job["id"], None)


async def scheduler(app):
    while True:
        state = app["state"]
        for c in state.cameras:
            if not c["auto_sync"] or not c["address"]:
                continue
            try:
                await app["camera"].inspect(c["id"])
                files = await app["camera"].listing(c["id"])
                known = {x["name"] for x in state.rows("SELECT name FROM clips WHERE camera=?", (c["id"],))}
                newest = {}
                for f in files:
                    key = re.search(r"([FRI])\.", f["name"], re.I)
                    key = key[1] if key else "F"
                    newest[key] = max(newest.get(key,""), f["name"])
                for f in files:
                    if f["name"] not in known and f["name"] not in newest.values():
                        state.add_job("download", {"camera":c["id"], "record":f})
            except Exception as exc:
                state.log.debug("auto_sync_unavailable camera=%s reason=%s", c["id"], type(exc).__name__)
        if state.options["retention_enabled"]:
            cutoff = time.time() - int(state.options["retention_days"])*86400
            pending = " ".join(j["payload"] for j in state.rows("SELECT payload FROM jobs WHERE state IN ('queued','running','paused')"))
            for clip in state.rows("SELECT id,path FROM clips WHERE protected=0 AND created<?", (cutoff,)):
                if clip["id"] not in pending:
                    path = Path(clip["path"]).resolve()
                    if path.is_relative_to(state.storage / "recordings"):
                        path.unlink(missing_ok=True)
                        state.execute("DELETE FROM clips WHERE id=?", (clip["id"],))
                        state.log.info("retention_removed clip=%s", clip["id"])
        await asyncio.sleep(int(state.options["sync_interval_seconds"]))


async def lifecycle(app):
    state = app["state"]
    preferences_path = state.root / "preferences.json"
    if preferences_path.exists():
        state.options.update(json.loads(preferences_path.read_text()))
        state.log.setLevel(state.options["log_level"].upper())
    async with aiohttp.ClientSession() as session:
        app["camera"] = app.get("shared_camera") or CameraClient(state, session)
        tasks = [asyncio.create_task(worker(app)), asyncio.create_task(scheduler(app))] if app["background"] else []
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app(state, integration=False, background=True):
    app = web.Application(middlewares=[security], client_max_size=4*1024**3)
    app.update(state=state, integration=integration, running={}, live_count=0, background=background)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/cameras/{cid}/{action}", camera_action)
    if not integration:
        app.router.add_get("/", index)
        app.router.add_static("/static/", STATIC)
        app.router.add_put("/api/cameras/{cid}", camera_config)
        app.router.add_get("/api/library", library)
        app.router.add_post("/api/import", upload)
        app.router.add_route("*", "/api/clips/{clip}/{action}", clip_action)
        app.router.add_post("/api/exports", export)
        app.router.add_post("/api/jobs/{jid}", job_action)
        app.router.add_get("/api/exports/{jid}", exported)
        app.router.add_get("/api/live/{cid}", live)
        app.router.add_get("/api/diagnostics", diagnostics)
        app.router.add_put("/api/preferences", preferences)
    return app


async def main():
    state = State(os.getenv("VIOFO_DATA", "runtime"))
    app = create_app(state)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0" if os.getenv("VIOFO_HA") == "1" else "127.0.0.1", int(os.getenv("PORT", "8099"))).start()
    # Dedicated token-only API; no unauthenticated access to the UI listener.
    integration = create_app(state, integration=True, background=False)
    integration["shared_camera"] = app["camera"]
    second = web.AppRunner(integration, access_log=None)
    await second.setup()
    await web.TCPSite(second, "0.0.0.0" if os.getenv("VIOFO_HA") == "1" else "127.0.0.1", int(os.getenv("API_PORT", "8100"))).start()
    try:
        await asyncio.Event().wait()
    finally:
        await second.cleanup()
        await runner.cleanup()
        state.close()


if __name__ == "__main__":
    asyncio.run(main())

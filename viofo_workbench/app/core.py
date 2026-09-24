"""Persistent state, bounded diagnostics, and validated configuration."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from . import VERSION

DEFAULTS = dict(log_level="debug", max_storage_gb=100, retention_days=30,
                retention_enabled=False, sync_interval_seconds=300, api_token="")
MODELS = {"A119 Mini 2": "A119 MINI2", "A229 Pro": "A229P"}


def atomic_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def local_address(value):
    """Only literal RFC1918 camera IPs; no DNS rebinding, userinfo or arbitrary URLs."""
    parts = urlsplit(value if "://" in value else "http://" + value)
    try:
        ip = ipaddress.ip_address(parts.hostname or "")
        port = parts.port
    except ValueError as exc:
        raise ValueError("Enter the camera's private IPv4 address") from exc
    allowed = any(ip in ipaddress.ip_network(n) for n in
                  ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    if not allowed or parts.scheme != "http" or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("Camera must be an http:// private IPv4 address without a path or credentials")
    return f"http://{ip}" + (f":{port}" if port else "")


class Redactor(logging.Filter):
    def __init__(self, state):
        super().__init__()
        self.state = state

    def filter(self, record):
        msg = record.getMessage()
        token = self.state.options.get("api_token", "")
        if token:
            msg = msg.replace(token, "[TOKEN]")
        msg = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", msg)
        msg = re.sub(r"(?i)(authorization|password|token|ssid|passphrase)([\s=:]+)[^\s,;]+", r"\1\2[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


class State:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        opts = self.root / "options.json"
        self.options = DEFAULTS | (json.loads(opts.read_text(encoding="utf-8")) if opts.exists() else {})
        self.options.setdefault("storage_path", str(self.root / "library"))
        storage = Path(self.options["storage_path"]).resolve()
        if os.getenv("VIOFO_HA") == "1" and not storage.is_relative_to(Path("/media")):
            raise ValueError("HA storage_path must be within /media")
        self.storage = storage
        for p in (self.storage, self.storage / "recordings", self.storage / "exports", self.root / "logs", self.root / "live"):
            p.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "workbench.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY, camera TEXT, name TEXT, category TEXT, channel TEXT,
            group_key TEXT, path TEXT UNIQUE, size INTEGER, created REAL,
            protected INTEGER DEFAULT 0, sha256 TEXT, metadata TEXT DEFAULT '{}');
          CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT, state TEXT, payload TEXT, progress REAL,
            created REAL, updated REAL, error TEXT DEFAULT '', result TEXT DEFAULT '', priority INTEGER DEFAULT 0);
        ''')
        self.db.execute("UPDATE jobs SET state='queued',progress=0 WHERE state='running'")
        self.db.commit()
        path = self.root / "cameras.json"
        self.cameras = json.loads(path.read_text(encoding="utf-8")) if path.exists() else [
            dict(id="mini2", name="A119 Mini 2", model="A119 Mini 2", address="", auto_sync=False, writes=False, channels="F"),
            dict(id="a229pro", name="A229 Pro", model="A229 Pro", address="", auto_sync=False, writes=False, channels="FR")]
        self.observations = {}
        self.remote = {}
        self.started = time.time()
        self.log = logging.getLogger(f"viofo.{id(self)}")
        self.log.setLevel(self.options["log_level"].upper())
        self.log.propagate = False
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        for h in (RotatingFileHandler(self.root / "logs" / "debug.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8"), logging.StreamHandler()):
            h.addFilter(Redactor(self))
            h.setFormatter(formatter)
            self.log.addHandler(h)
        self.log.info("startup version=%s debug=%s hardware_validation=pending", VERSION, self.options["log_level"])

    def rows(self, sql, args=()):
        return [dict(x) for x in self.db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        self.db.execute(sql, args)
        self.db.commit()

    def camera(self, cid):
        return next(c for c in self.cameras if c["id"] == cid)

    def save_camera(self, cid, data):
        old = self.camera(cid)
        model = data.get("model", old["model"])
        if model not in MODELS:
            raise ValueError("Unsupported model profile")
        address = data.get("address", old["address"]).strip()
        channels = data.get("channels", old["channels"])
        if channels not in ("F", "FR", "FI", "FRI"):
            raise ValueError("Invalid camera channels")
        old.update(name=str(data.get("name", old["name"]))[:80], model=model,
                   address=local_address(address) if address else "", channels=channels,
                   auto_sync=bool(data.get("auto_sync", old["auto_sync"])), writes=bool(data.get("writes", old["writes"])))
        atomic_json(self.root / "cameras.json", self.cameras)
        self.remote.pop(cid, None)
        self.observations.pop(cid, None)
        self.log.info("camera_config_changed camera=%s", cid)
        return old

    def clip(self, cid):
        rows = self.rows("SELECT * FROM clips WHERE id=?", (cid,))
        if not rows:
            raise ValueError("Recording not found")
        return rows[0]

    def register(self, path, camera, name, category="driving", metadata=None):
        path = Path(path).resolve()
        if not path.is_relative_to(self.storage):
            raise ValueError("Recording outside library")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        cid = secrets.token_hex(8)
        match = re.search(r"([FRI])\.(?:MP4|MOV)$", name, re.I)
        channel = match[1].upper() if match else "F"
        timestamp = re.search(r"\d{4}_\d{4}_\d{6}", name)
        group = timestamp[0] if timestamp else Path(name).stem
        self.execute("INSERT INTO clips(id,camera,name,category,channel,group_key,path,size,created,protected,sha256,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, camera, name, category, channel, group, str(path), path.stat().st_size, time.time(), int(category == "locked"), digest, json.dumps(metadata or {})))
        return cid

    def add_job(self, kind, payload):
        existing = self.rows("SELECT id FROM jobs WHERE kind=? AND payload=? AND state IN ('queued','running','paused')", (kind, json.dumps(payload, sort_keys=True)))
        if existing:
            return existing[0]["id"]
        jid = secrets.token_hex(8)
        self.execute("INSERT INTO jobs(id,kind,state,payload,progress,created,updated) VALUES(?,?,'queued',?,0,?,?)", (jid, kind, json.dumps(payload, sort_keys=True), time.time(), time.time()))
        self.log.debug("job_queued job=%s kind=%s", jid, kind)
        return jid

    def job(self, jid):
        rows = self.rows("SELECT * FROM jobs WHERE id=?", (jid,))
        if not rows:
            raise ValueError("Job not found")
        return rows[0]

    def update_job(self, jid, **values):
        if not set(values) <= {"state", "progress", "error", "result", "priority"}:
            raise ValueError("Invalid job fields")
        values["updated"] = time.time()
        self.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*values.values(), jid))

    def space(self, incoming=0):
        import shutil
        used = sum(p.stat().st_size for p in self.storage.rglob("*") if p.is_file())
        free = shutil.disk_usage(self.storage).free
        limit = int(self.options["max_storage_gb"]) * 1024**3
        if used + incoming > limit or free - incoming < 128 * 1024**2:
            raise ValueError("Storage limit or free-space reserve reached")
        return dict(used_bytes=used, limit_bytes=limit, free_bytes=free)

    def close(self):
        self.db.close()
        for handler in self.log.handlers[:]:
            handler.close()
            self.log.removeHandler(handler)

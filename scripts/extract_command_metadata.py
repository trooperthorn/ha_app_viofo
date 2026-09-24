"""Extract factual protocol metadata from a user-provided VIOFO Dashcam APK.

Does not redistribute application code, UI assets or the original database.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("apk", type=Path)
parser.add_argument("--out", type=Path, default=Path("viofo_workbench/app/command_map.json"))
args = parser.parse_args()
with zipfile.ZipFile(args.apk) as archive:
    raw = archive.read("assets/device-cmd-manager.db")
with tempfile.TemporaryDirectory() as root:
    path = Path(root) / "metadata.db"
    path.write_bytes(raw)
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    output = {}
    for model in ("A119 MINI2", "A229P"):
        commands = {}
        for row in db.execute("SELECT DISTINCT m.CMD,m.CMD_KEY FROM CMD_MANAGER m JOIN CMD_DEVICE_MANAGER d ON d.CMD_ID=m._ID WHERE d.DEVICE_MODEL=? ORDER BY CAST(m.CMD AS INTEGER)", (model,)):
            options = []
            for opt in db.execute("SELECT DISTINCT o._INDEX,o._VALUE,o.CAMERA_TAG,o.VERSION FROM DASHCAM_MENU_OPTION_INFO o JOIN CMD_MANAGER m ON m._ID=o.CMD_ID WHERE o.DEVICE_MODEL=? AND m.CMD=?", (model,row["CMD"])):
                if not str(opt["_INDEX"]).lstrip("-").isdigit():
                    continue
                options.append(dict(index=int(opt["_INDEX"]),value=opt["_VALUE"],camera_tag=opt["CAMERA_TAG"],version=opt["VERSION"]))
            commands[str(row["CMD"])] = dict(key=row["CMD_KEY"],options=options)
        output[model] = dict(commands=commands)
    db.close()
args.out.write_text(json.dumps(output,indent=2),encoding="utf-8")
print(json.dumps({"database_sha256":hashlib.sha256(raw).hexdigest(), "models":{k:len(v['commands']) for k,v in output.items()}}))

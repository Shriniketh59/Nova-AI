import json
import os
from datetime import datetime, timezone

_LOG_DIR = os.path.join(os.path.dirname(__file__), "../../logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")
os.makedirs(_LOG_DIR, exist_ok=True)


def _timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(level, message, meta):
    line = json.dumps({"timestamp": _timestamp(), "level": level, "message": message, **meta}) + "\n"
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass


class _Logger:
    def info(self, message, meta=None):
        meta = meta or {}
        print(f"[{_timestamp()}] INFO {message}" + (f" {json.dumps(meta)}" if meta else ""))
        _write("INFO", message, meta)

    def warn(self, message, meta=None):
        meta = meta or {}
        print(f"[{_timestamp()}] WARN {message}" + (f" {json.dumps(meta)}" if meta else ""))
        _write("WARN", message, meta)

    def error(self, message, meta=None):
        meta = meta or {}
        print(f"[{_timestamp()}] ERROR {message}" + (f" {json.dumps(meta)}" if meta else ""))
        _write("ERROR", message, meta)


logger = _Logger()

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_SECRET = "CHANGE_THIS_SECRET_BEFORE_SELLING"
DATA_DIR = Path(os.environ.get("SLIDENARRATE_DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "usage.db"


def _secret() -> bytes:
    return os.environ.get("LICENSE_SECRET", DEFAULT_SECRET).encode("utf-8")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def create_license(customer: str, plan: str, days: int, mp3_limit: int = 500, sync_limit: int = 100) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=int(days))
    payload = {
        "customer": customer,
        "plan": plan,
        "expires": exp.strftime("%Y-%m-%d"),
        "mp3_limit": int(mp3_limit),
        "sync_limit": int(sync_limit),
        "iat": datetime.now(timezone.utc).isoformat(),
    }
    body = b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{b64url(sig)}"


def parse_license(key: str) -> dict[str, Any]:
    if not key or "." not in key:
        raise ValueError("Missing or invalid license key.")
    body, sig = key.strip().split(".", 1)
    expected = b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise ValueError("Invalid license signature.")
    payload = json.loads(b64url_decode(body).decode("utf-8"))
    exp = datetime.strptime(payload["expires"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp + timedelta(days=1):
        raise ValueError("License expired.")
    return payload


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            license_hash TEXT NOT NULL,
            period TEXT NOT NULL,
            kind TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (license_hash, period, kind)
        )
        """)
        con.commit()


def license_hash(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:24]


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_usage(key: str) -> dict[str, int]:
    init_db()
    h = license_hash(key)
    period = current_period()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT kind, count FROM usage WHERE license_hash=? AND period=?", (h, period)).fetchall()
    return {kind: count for kind, count in rows}


def assert_and_increment(key: str | None, kind: str) -> dict[str, Any]:
    require = os.environ.get("REQUIRE_LICENSE", "false").lower() in ("1", "true", "yes")
    if not require and not key:
        return {"ok": True, "license_required": False, "usage": {}}

    payload = parse_license(key or "")
    limit_name = "mp3_limit" if kind == "mp3" else "sync_limit"
    limit = int(payload.get(limit_name, 0) or 0)
    init_db()
    h = license_hash(key or "")
    period = current_period()
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT count FROM usage WHERE license_hash=? AND period=? AND kind=?", (h, period, kind)).fetchone()
        count = int(row[0]) if row else 0
        if limit and count >= limit:
            raise ValueError(f"Monthly {kind} usage limit reached.")
        count += 1
        con.execute("INSERT OR REPLACE INTO usage (license_hash, period, kind, count) VALUES (?, ?, ?, ?)", (h, period, kind, count))
        con.commit()
    return {"ok": True, "payload": payload, "usage": {kind: count}, "limit": limit}

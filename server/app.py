#!/usr/bin/env python3
"""
HTTP API for weekly/monthly rank snapshots: read from disk, replace via PUT, or refresh from Binance.

Auth in production (never put secrets in the frontend bundle):
  - Header: Authorization: Bearer <VOL_MONITOR_READ_SECRET|WRITE_SECRET>
  - Or: X-API-Key: <same secret>

GET  /api/vol-snapshot           — read snapshot
PUT  /api/vol-snapshot           — replace entire JSON body
POST /api/vol-snapshot/refresh   — optional body {"targets":["ARPAUSDT"],"mode":"full"|"light"}

Local dev may set VOL_MONITOR_DISABLE_AUTH=1 (never on the public internet).
Browsers should use the Vercel same-origin proxy `/api/vol-snapshot-proxy`; keep secrets in Vercel env only.

Production: bind 127.0.0.1 and put Nginx in front, e.g.:
  uvicorn app:app --host 127.0.0.1 --port 8787 --workers 2
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, List, Optional

# Ensure sibling modules in this directory are importable
_SERVER_DIR = Path(__file__).resolve().parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from snapshot_service import atomic_write_json, build_light_rank_snapshot, build_rank_snapshot

READ_SECRET = (
    os.environ.get("VOL_MONITOR_READ_SECRET")
    or os.environ.get("VOL_MONITOR_API_SECRET")
    or ""
).strip()
WRITE_SECRET = (
    os.environ.get("VOL_MONITOR_WRITE_SECRET") or READ_SECRET
).strip()
DISABLE_AUTH = os.environ.get("VOL_MONITOR_DISABLE_AUTH", "").lower() in (
    "1",
    "true",
    "yes",
)

DATA_DIR = Path(
    os.environ.get("VOL_MONITOR_DATA_DIR", str(Path.cwd() / "data" / "research"))
).resolve()
SNAPSHOT_PATH = Path(
    os.environ.get(
        "VOL_MONITOR_SNAPSHOT_PATH",
        str(DATA_DIR / "binance_vol_monitor_rank_snapshot.json"),
    )
).resolve()

DEFAULT_TARGETS = [
    x.strip().upper()
    for x in os.environ.get("VOL_MONITOR_TARGETS", "ARPAUSDT,BELUSDT").split(",")
    if x.strip()
]
MIN_INTERVAL = float(os.environ.get("VOL_MONITOR_MIN_INTERVAL", "0.18"))
FULL_MARKET_TTL = float(os.environ.get("VOL_MONITOR_FULL_MARKET_TTL_SEC", "3600"))

app = FastAPI(title="Vol monitor API", version="1.0")

_cors_raw = os.environ.get("VOL_MONITOR_CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-API-Key") or "").strip()


def require_read(request: Request) -> None:
    if DISABLE_AUTH:
        return
    if not READ_SECRET:
        raise HTTPException(
            status_code=503,
            detail="VOL_MONITOR_READ_SECRET or VOL_MONITOR_API_SECRET not set",
        )
    if _token_from_request(request) != READ_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_write(request: Request) -> None:
    if DISABLE_AUTH:
        return
    if not WRITE_SECRET:
        raise HTTPException(
            status_code=503,
            detail="VOL_MONITOR_WRITE_SECRET not set",
        )
    if _token_from_request(request) != WRITE_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/vol-snapshot", dependencies=[Depends(require_read)])
def get_snapshot():
    if not SNAPSHOT_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail="snapshot file not found; run POST /api/vol-snapshot/refresh first",
        )
    raw = SNAPSHOT_PATH.read_text(encoding="utf-8")
    return Response(content=raw, media_type="application/json; charset=utf-8")


@app.put("/api/vol-snapshot", dependencies=[Depends(require_write)])
def put_snapshot(data: dict[str, Any]):
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    atomic_write_json(SNAPSHOT_PATH, data)
    return {"ok": True, "path": str(SNAPSHOT_PATH)}


class RefreshBody(BaseModel):
    targets: Optional[List[str]] = None
    mode: str = Field(default="full", description="full | light")


@app.post("/api/vol-snapshot/refresh", dependencies=[Depends(require_write)])
def post_refresh(body: RefreshBody = Body(default_factory=RefreshBody)):
    if body.targets:
        tlist = [str(x).upper().strip() for x in body.targets if str(x).strip()]
    else:
        tlist = list(DEFAULT_TARGETS)
    if not tlist:
        raise HTTPException(status_code=400, detail="no targets")

    mode = body.mode.lower()
    if mode == "light":
        snap = build_light_rank_snapshot(
            tlist,
            min_interval_sec=MIN_INTERVAL,
        )
    elif mode == "full":
        snap = build_rank_snapshot(
            tlist,
            data_dir=DATA_DIR,
            min_interval_sec=MIN_INTERVAL,
            full_market_ttl_sec=FULL_MARKET_TTL,
        )
    else:
        raise HTTPException(status_code=400, detail='mode must be "full" or "light"')
    atomic_write_json(SNAPSHOT_PATH, snap)
    return snap


def main():
    host = os.environ.get("VOL_MONITOR_HOST", "127.0.0.1")
    port = int(os.environ.get("VOL_MONITOR_PORT", "8787"))
    reload = os.environ.get("UVICORN_RELOAD", "").lower() in ("1", "true")
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()

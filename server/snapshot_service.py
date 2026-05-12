"""Build rank snapshot JSON aligned with `binance_trading_pair_vol_monitor.py`."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from binance_minimal import (
    WINDOW_30D,
    WINDOW_7D,
    fetch_daily_klines,
    get_spot_usdt_tickers_sorted,
    sum_quote_volume_last_n_candles,
)


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_full_market_cache(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return None
        d.setdefault("version", 2)
        d.setdefault("updated_at", 0.0)
        d.setdefault("entries", {})
        return d
    except (OSError, json.JSONDecodeError):
        return None


def full_market_cache_fresh(data: Dict[str, Any], ttl_sec: float, now: float) -> bool:
    try:
        ts = float(data.get("updated_at", 0))
        ent = data.get("entries")
        if not isinstance(ent, dict) or not ent:
            return False
        return (now - ts) <= ttl_sec
    except (TypeError, ValueError):
        return False


def build_full_market_entries(
    symbols: List[str],
    *,
    min_interval_sec: float,
    cache_path: Path,
    cache_ttl_sec: float,
    now: float,
) -> Tuple[Dict[str, Dict[str, float]], float]:
    disk = load_full_market_cache(cache_path)
    if disk is not None and full_market_cache_fresh(disk, cache_ttl_sec, now):
        ent = disk.get("entries")
        if isinstance(ent, dict) and set(symbols).issubset(set(ent.keys())):
            out = {
                s: {
                    "qv_7d": float(ent[s]["qv_7d"]),
                    "qv_30d": float(ent[s]["qv_30d"]),
                }
                for s in symbols
                if s in ent
            }
            try:
                ts = float(disk.get("updated_at", 0))
            except (TypeError, ValueError):
                ts = 0.0
            return out, ts

    entries: Dict[str, Dict[str, float]] = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
        try:
            klines = fetch_daily_klines(sym)
            q7 = sum_quote_volume_last_n_candles(klines, WINDOW_7D)
            q30 = sum_quote_volume_last_n_candles(klines, WINDOW_30D)
            entries[sym] = {"qv_7d": q7, "qv_30d": q30}
        except Exception:
            entries[sym] = {"qv_7d": 0.0, "qv_30d": 0.0}
        time.sleep(min_interval_sec)
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  full-market klines {i + 1}/{total}", flush=True)

    ts = time.time()
    atomic_write_json(
        cache_path,
        {
            "version": 2,
            "updated_at": ts,
            "symbol_count": len(entries),
            "entries": entries,
        },
    )
    return entries, ts


def rank_percentile_from_sorted_volumes(
    sorted_pairs: List[Tuple[str, float]],
    target: str,
) -> Optional[Tuple[int, int, float]]:
    total = len(sorted_pairs)
    for i, (sym, _) in enumerate(sorted_pairs):
        if sym == target:
            rank = i + 1
            return rank, total, rank / total
    return None


def build_rank_snapshot(
    targets: List[str],
    *,
    data_dir: Path,
    min_interval_sec: float,
    full_market_ttl_sec: float,
) -> Dict[str, Any]:
    sorted_data = get_spot_usdt_tickers_sorted()
    universe = [x["symbol"] for x in sorted_data]
    total = len(sorted_data)
    now = time.time()

    fm_path = data_dir / "binance_vol_monitor_full_market_klines.json"
    fm_entries, fm_updated_at = build_full_market_entries(
        universe,
        min_interval_sec=min_interval_sec,
        cache_path=fm_path,
        cache_ttl_sec=full_market_ttl_sec,
        now=now,
    )

    sorted_7d = sorted(
        ((s, v["qv_7d"]) for s, v in fm_entries.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    sorted_30d = sorted(
        ((s, v["qv_30d"]) for s, v in fm_entries.items()),
        key=lambda x: x[1],
        reverse=True,
    )

    snapshot_rows: Dict[str, Any] = {}
    for target in targets:
        rank = None
        volume_24h = 0.0
        for i, x in enumerate(sorted_data):
            if x["symbol"] == target:
                rank = i + 1
                volume_24h = float(x["quoteVolume"])
                break
        if rank is None:
            continue

        percentile = rank / total
        ent = fm_entries.get(target, {"qv_7d": 0.0, "qv_30d": 0.0})
        q7 = float(ent["qv_7d"])
        q30 = float(ent["qv_30d"])
        r7 = rank_percentile_from_sorted_volumes(sorted_7d, target)
        r30 = rank_percentile_from_sorted_volumes(sorted_30d, target)

        snap: Dict[str, Any] = {
            "rank_24h": rank,
            "total_24h": total,
            "percentile_24h": percentile,
            "qv_24h": volume_24h,
            "qv_7d": q7,
            "qv_30d": q30,
            "long_vol_src": "network",
        }
        if r7 is not None:
            snap["rank_7d"] = r7[0]
            snap["total_7d"] = r7[1]
            snap["percentile_7d"] = r7[2]
        if r30 is not None:
            snap["rank_30d"] = r30[0]
            snap["total_30d"] = r30[1]
            snap["percentile_30d"] = r30[2]
        snapshot_rows[target] = snap

    return {
        "version": 1,
        "full_market_cache_updated_at": fm_updated_at,
        "snapshot_written_at": time.time(),
        "universe_total": total,
        "window_7d": WINDOW_7D,
        "window_30d": WINDOW_30D,
        "targets": snapshot_rows,
    }


def build_light_rank_snapshot(
    targets: List[str],
    *,
    min_interval_sec: float,
) -> Dict[str, Any]:
    """
    Fetch daily K + 24h rank for targets only; no full-market 7d/30d sort (faster, no rank_7d/rank_30d).
    """
    sorted_data = get_spot_usdt_tickers_sorted()
    total = len(sorted_data)
    now = time.time()
    snapshot_rows: Dict[str, Any] = {}

    for ti, target in enumerate(targets):
        rank = None
        volume_24h = 0.0
        for i, x in enumerate(sorted_data):
            if x["symbol"] == target:
                rank = i + 1
                volume_24h = float(x["quoteVolume"])
                break
        if rank is None:
            continue

        try:
            klines = fetch_daily_klines(target)
            q7 = sum_quote_volume_last_n_candles(klines, WINDOW_7D)
            q30 = sum_quote_volume_last_n_candles(klines, WINDOW_30D)
        except Exception:
            q7, q30 = 0.0, 0.0

        percentile = rank / total
        snapshot_rows[target] = {
            "rank_24h": rank,
            "total_24h": total,
            "percentile_24h": percentile,
            "qv_24h": volume_24h,
            "qv_7d": q7,
            "qv_30d": q30,
            "long_vol_src": "network (light)",
        }
        if ti < len(targets) - 1:
            time.sleep(min_interval_sec)

    return {
        "version": 1,
        "full_market_cache_updated_at": now,
        "snapshot_written_at": time.time(),
        "universe_total": total,
        "window_7d": WINDOW_7D,
        "window_30d": WINDOW_30D,
        "targets": snapshot_rows,
        "mode": "light",
    }

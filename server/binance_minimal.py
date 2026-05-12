"""Binance spot public REST helpers (urllib) for the vol monitor service."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Set

BASE = "https://api.binance.com"
KLINES_LIMIT = 35
WINDOW_7D = 7
WINDOW_30D = 30


def http_get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FastToolbox-vol-monitor-server/1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_spot_usdt_symbol_set(exchange_json: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for s in exchange_json.get("symbols") or []:
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("status") != "TRADING":
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        out.add(s["symbol"])
    return out


def get_spot_usdt_tickers_sorted() -> List[Dict[str, Any]]:
    info = http_get_json(f"{BASE}/api/v3/exchangeInfo")
    spot = build_spot_usdt_symbol_set(info)
    tickers = http_get_json(f"{BASE}/api/v3/ticker/24hr")
    rows = [x for x in tickers if x.get("symbol") in spot]
    rows.sort(key=lambda x: float(x.get("quoteVolume") or 0), reverse=True)
    return rows


def fetch_daily_klines(symbol: str, limit: int = KLINES_LIMIT) -> List[Any]:
    q = urllib.parse.quote(symbol, safe="")
    url = f"{BASE}/api/v3/klines?symbol={q}&interval=1d&limit={limit}"
    return http_get_json(url)


def sum_quote_volume_last_n_candles(klines: List[Any], n: int) -> float:
    if not klines:
        return 0.0
    take = min(n, len(klines))
    chunk = klines[-take:]
    return sum(float(c[7]) for c in chunk if len(c) > 7)

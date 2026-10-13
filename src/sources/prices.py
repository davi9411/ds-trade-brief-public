"""
Fonte: PREÇOS DO DIA ANTERIOR (para a seção Opinião do Brief Diário)

Usa Yahoo Finance (keyless) para buscar fechamento anterior e variação %:
  EUR/USD · GBP/USD · Ouro (XAU/USD) · Bitcoin · Dólar (USD/BRL) · Ibovespa

Symbols Yahoo Finance:
  EURUSD=X · GBPUSD=X · GC=F (ouro) · BTC-USD · BRL=X · ^BVSP
"""

import requests
from src import config  # noqa: F401

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

ASSETS = [
    {"symbol": "EURUSD=X", "label": "EUR/USD",        "decimals": 4},
    {"symbol": "GBPUSD=X", "label": "GBP/USD",        "decimals": 4},
    {"symbol": "GC=F",     "label": "Ouro (XAU/USD)", "decimals": 2},
    {"symbol": "BTC-USD",  "label": "Bitcoin (BTC)",  "decimals": 0},
    {"symbol": "BRL=X",    "label": "Dólar (USD/BRL)","decimals": 4},
    {"symbol": "^BVSP",    "label": "Ibovespa",       "decimals": 0},
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _pct(current: float, prev: float) -> float:
    if not prev:
        return 0.0
    return round((current - prev) / prev * 100, 2)


def _direction(pct: float) -> str:
    if pct > 0.15:
        return "alta"
    if pct < -0.15:
        return "queda"
    return "estável"


def _fetch_yahoo(symbol: str, decimals: int) -> dict | None:
    try:
        r = requests.get(
            YAHOO_URL.format(symbol=symbol),
            params={"interval": "1d", "range": "5d"},
            headers=UA,
            timeout=10,
        )
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return None
        price, prev = closes[-1], closes[-2]
        pct = _pct(price, prev)
        return {
            "price":      round(price, decimals),
            "prev_close": round(prev, decimals),
            "change_pct": pct,
            "direction":  _direction(pct),
        }
    except Exception:
        return None


def fetch_prices() -> list[dict]:
    """Retorna lista de preços com variação para os principais ativos.

    Cada item: {"asset": str, "price": float, "prev_close": float,
                 "change_pct": float, "direction": "alta"|"queda"|"estável"}
    """
    results = []
    for asset in ASSETS:
        data = _fetch_yahoo(asset["symbol"], asset["decimals"])
        if data:
            results.append({"asset": asset["label"], **data})
    return results


if __name__ == "__main__":
    for p in fetch_prices():
        sign = "+" if p["change_pct"] >= 0 else ""
        print(f"{p['asset']:22} {p['price']:>12}  ({sign}{p['change_pct']}%  {p['direction']})")

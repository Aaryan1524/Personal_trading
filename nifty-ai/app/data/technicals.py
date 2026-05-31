# Technical indicators
from datetime import date, timedelta
from typing import TypedDict

import pandas as pd

from .kite import get_kite_client

_INDEX_TOKENS = {
    "NIFTY 50": 256265,
    "NIFTY BANK": 260105,
}


class Technicals(TypedDict):
    symbol: str
    last_close: float
    ema_20: float
    ema_50: float
    support: float
    resistance: float
    iv_proxy_today: float
    iv_percentile: float


def _resolve_token(kite, symbol: str) -> int:
    if symbol in _INDEX_TOKENS:
        return _INDEX_TOKENS[symbol]
    for inst in kite.instruments("NSE"):
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Could not resolve instrument token for symbol: {symbol}")


def get_technicals(symbol: str) -> Technicals:
    kite = get_kite_client()
    token = _resolve_token(kite, symbol)
    today = date.today()

    bars_60 = kite.historical_data(token, today - timedelta(days=90), today, "day")
    df = pd.DataFrame(bars_60)
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    last20 = df.tail(20)
    support = float(last20["low"].min())
    resistance = float(last20["high"].max())

    bars_365 = kite.historical_data(token, today - timedelta(days=400), today, "day")
    df365 = pd.DataFrame(bars_365)
    iv_proxy = (df365["high"] - df365["low"]) / df365["close"]
    today_iv = float(iv_proxy.iloc[-1])
    iv_percentile = float((iv_proxy < today_iv).sum()) / len(iv_proxy) * 100.0

    return Technicals(
        symbol=symbol,
        last_close=float(df["close"].iloc[-1]),
        ema_20=float(df["ema_20"].iloc[-1]),
        ema_50=float(df["ema_50"].iloc[-1]),
        support=support,
        resistance=resistance,
        iv_proxy_today=today_iv,
        iv_percentile=iv_percentile,
    )

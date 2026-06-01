# Technical indicators
from datetime import date, datetime, timedelta
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


class IntradayData(TypedDict):
    vwap: float
    ema_9: float
    day_high: float
    day_low: float
    opening_range_high: float   # high of the first 30 min (first 2 candles)
    opening_range_low: float    # low of the first 30 min
    breakout_status: str        # "breakout" | "breakdown" | "inside_range"
    intraday_trend: str         # "bullish" | "bearish" | "sideways"
    candle_count: int


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


def get_intraday_technicals(symbol: str) -> IntradayData | None:
    """15-min VWAP, opening range, and trend for the current session.

    Returns None before market open or when no candles exist (holiday/weekend).
    """
    kite = get_kite_client()
    token = _resolve_token(kite, symbol)
    today = date.today()

    market_open = datetime(today.year, today.month, today.day, 9, 15, 0)
    now = datetime.now()
    if now < market_open:
        return None

    market_close = datetime(today.year, today.month, today.day, 15, 30, 0)
    to_dt = min(now, market_close)

    bars = kite.historical_data(token, market_open, to_dt, "15minute")
    if not bars:
        return None

    df = pd.DataFrame(bars)
    if df.empty:
        return None

    # VWAP: cumulative (typical_price × volume) / cumulative volume
    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["tp"] * df["volume"]
    total_vol = df["volume"].sum()
    vwap = float(df["tp_vol"].sum() / total_vol) if total_vol > 0 else float(df["tp"].iloc[-1])

    # 9-period EMA on 15-min closes
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    ema_9 = float(df["ema_9"].iloc[-1])

    # Opening range = first two 15-min candles (9:15–9:45)
    orb = df.head(2)
    orb_high = float(orb["high"].max())
    orb_low = float(orb["low"].min())

    current = float(df["close"].iloc[-1])
    if current > orb_high:
        breakout_status = "breakout"
    elif current < orb_low:
        breakout_status = "breakdown"
    else:
        breakout_status = "inside_range"

    # Trend: price AND 9-EMA must agree relative to VWAP to call a direction
    if current > vwap and ema_9 > vwap:
        intraday_trend = "bullish"
    elif current < vwap and ema_9 < vwap:
        intraday_trend = "bearish"
    else:
        intraday_trend = "sideways"

    return IntradayData(
        vwap=round(vwap, 2),
        ema_9=round(ema_9, 2),
        day_high=float(df["high"].max()),
        day_low=float(df["low"].min()),
        opening_range_high=orb_high,
        opening_range_low=orb_low,
        breakout_status=breakout_status,
        intraday_trend=intraday_trend,
        candle_count=len(df),
    )

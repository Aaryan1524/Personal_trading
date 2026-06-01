# Intraday data functions — VWAP, opening range, session stats.
# All functions are independent; none modify any existing data file.

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .kite import get_kite_client

_IST = ZoneInfo("Asia/Kolkata")

_INSTRUMENT_TOKENS = {
    "NIFTY":     256265,
    "BANKNIFTY": 260105,
}

_MARKET_OPEN  = (9, 15)
_MARKET_CLOSE = (15, 30)


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _session_open() -> datetime:
    n = _now_ist()
    return datetime(n.year, n.month, n.day, *_MARKET_OPEN, tzinfo=_IST)


def _session_close() -> datetime:
    n = _now_ist()
    return datetime(n.year, n.month, n.day, *_MARKET_CLOSE, tzinfo=_IST)


def _market_is_open() -> bool:
    now = _now_ist()
    return _session_open() <= now <= _session_close()


def _resolve_token(instrument: str) -> int:
    token = _INSTRUMENT_TOKENS.get(instrument.upper())
    if token is None:
        raise ValueError(f"Unknown instrument {instrument!r}. Expected 'NIFTY' or 'BANKNIFTY'.")
    return token


# ──────────────────────────────────────────────────────────────────────────────


def get_vwap(instrument: str) -> float | None:
    """VWAP from today's 5-minute candles (9:15 IST → now).

    Returns None if the market is closed or data is unavailable.
    """
    if not _market_is_open():
        return None
    try:
        kite  = get_kite_client()
        token = _resolve_token(instrument)
        now   = _now_ist()

        bars = kite.historical_data(token, _session_open(), now, "5minute")
        if not bars:
            return None

        df = pd.DataFrame(bars)
        df = df[df["volume"] > 0]
        if df.empty:
            return None

        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
        total_vol = df["volume"].sum()
        if total_vol == 0:
            return None

        return round(float((df["typical_price"] * df["volume"]).sum() / total_vol), 2)

    except Exception:
        return None


def get_opening_range(instrument: str) -> dict:
    """High and low of the first 15 minutes of trading (9:15 – 9:30 IST).

    Returns:
        {
            "high":        float | None,
            "low":         float | None,
            "range":       float | None,
            "established": bool          # True only after 9:30 IST has passed
        }
    """
    _empty = {"high": None, "low": None, "range": None, "established": False}
    try:
        now      = _now_ist()
        open_dt  = _session_open()
        or_end   = datetime(now.year, now.month, now.day, 9, 30, 0, tzinfo=_IST)

        if now < open_dt:
            return _empty

        kite  = get_kite_client()
        token = _resolve_token(instrument)

        bars = kite.historical_data(token, open_dt, or_end, "minute")
        if not bars:
            return {**_empty, "established": now > or_end}

        df = pd.DataFrame(bars)
        if df.empty:
            return {**_empty, "established": now > or_end}

        high  = float(df["high"].max())
        low   = float(df["low"].min())
        return {
            "high":        round(high, 2),
            "low":         round(low, 2),
            "range":       round(high - low, 2),
            "established": now > or_end,
        }

    except Exception:
        return {"high": None, "low": None, "range": None, "established": False}


def get_intraday_stats(instrument: str) -> dict:
    """Open, high, low, close, range %, and cumulative volume for today's session.

    Returns:
        {
            "open":         float | None,
            "high":         float | None,
            "low":          float | None,
            "close":        float | None,
            "range_pct":    float | None,   # (high - low) / open * 100
            "volume":       int   | None,
            "candle_count": int,
        }
    """
    _empty = {
        "open": None, "high": None, "low": None, "close": None,
        "range_pct": None, "volume": None, "candle_count": 0,
    }
    try:
        now      = _now_ist()
        open_dt  = _session_open()
        close_dt = _session_close()

        if now < open_dt:
            return _empty

        kite  = get_kite_client()
        token = _resolve_token(instrument)
        to_dt = min(now, close_dt)

        bars = kite.historical_data(token, open_dt, to_dt, "5minute")
        if not bars:
            return _empty

        df = pd.DataFrame(bars)
        if df.empty:
            return _empty

        day_open  = float(df["open"].iloc[0])
        day_high  = float(df["high"].max())
        day_low   = float(df["low"].min())
        day_close = float(df["close"].iloc[-1])
        volume    = int(df["volume"].sum())
        range_pct = round((day_high - day_low) / day_open * 100, 3) if day_open > 0 else None

        return {
            "open":         round(day_open, 2),
            "high":         round(day_high, 2),
            "low":          round(day_low, 2),
            "close":        round(day_close, 2),
            "range_pct":    range_pct,
            "volume":       volume,
            "candle_count": len(df),
        }

    except Exception:
        return _empty


# ──────────────────────────────────────────────────────────────────────────────
# Sample output for manual verification

if __name__ == "__main__":
    import json

    print("=== get_vwap('NIFTY') ===")
    print(get_vwap("NIFTY"))

    print("\n=== get_opening_range('NIFTY') ===")
    print(json.dumps(get_opening_range("NIFTY"), indent=2))

    print("\n=== get_intraday_stats('NIFTY') ===")
    print(json.dumps(get_intraday_stats("NIFTY"), indent=2))

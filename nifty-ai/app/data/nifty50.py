# Nifty 50 data fetchers
from datetime import date
from math import erf, exp, log, pi, sqrt

from .kite import get_kite_client

NIFTY_INSTRUMENT_TOKEN = 256265
NIFTY_NAME = "NIFTY"
NIFTY_LOT_SIZE = 65
RISK_FREE_RATE = 0.07


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _bs_price(opt_type: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if opt_type == "CE" else max(K - S, 0.0)
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * exp(-r * T) * _norm_cdf(d2)
    return K * exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _implied_vol(opt_type: str, price: float, S: float, K: float, T: float, r: float):
    if price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(S - K, 0.0) if opt_type == "CE" else max(K - S, 0.0)
    if price < intrinsic - 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _bs_price(opt_type, S, K, T, r, mid) > price:
            hi = mid
        else:
            lo = mid
    iv = 0.5 * (lo + hi)
    return iv if 1e-3 < iv < 4.99 else None


def _greeks(opt_type: str, S: float, K: float, T: float, r: float, sigma):
    if not sigma or T <= 0 or sigma <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None}
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S * sigma * sqrt(T))
    vega = S * pdf * sqrt(T) / 100.0
    if opt_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-S * pdf * sigma / (2 * sqrt(T)) - r * K * exp(-r * T) * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-S * pdf * sigma / (2 * sqrt(T)) + r * K * exp(-r * T) * _norm_cdf(-d2)) / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def _build_option_chain(kite, index_name: str, spot: float):
    today = date.today()
    instruments = kite.instruments("NFO")
    rows = [
        i for i in instruments
        if i["name"] == index_name
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] >= today
    ]
    if not rows:
        return [], today

    nearest_expiry = min(r["expiry"] for r in rows)
    rows = [r for r in rows if r["expiry"] == nearest_expiry]

    symbols = [f"NFO:{r['tradingsymbol']}" for r in rows]
    quotes: dict = {}
    for i in range(0, len(symbols), 200):
        quotes.update(kite.quote(symbols[i:i + 200]))

    T = max((nearest_expiry - today).days, 0) / 365.0
    by_strike: dict = {}
    for r in rows:
        sym = f"NFO:{r['tradingsymbol']}"
        q = quotes.get(sym, {})
        ltp = float(q.get("last_price") or 0.0)
        oi = int(q.get("oi") or 0)
        volume = int(q.get("volume") or 0)
        strike = float(r["strike"])
        opt_type = r["instrument_type"]
        iv = _implied_vol(opt_type, ltp, spot, strike, T, RISK_FREE_RATE)
        g = _greeks(opt_type, spot, strike, T, RISK_FREE_RATE, iv)
        leg = {"ltp": ltp, "oi": oi, "volume": volume, "iv": iv, **g}
        entry = by_strike.setdefault(strike, {"strike": strike, "CE": None, "PE": None})
        entry[opt_type] = leg

    chain = sorted(by_strike.values(), key=lambda x: x["strike"])
    return chain, nearest_expiry


def get_nifty50_data() -> dict:
    kite = get_kite_client()
    q = kite.quote([NIFTY_INSTRUMENT_TOKEN])
    spot = float(q[str(NIFTY_INSTRUMENT_TOKEN)]["last_price"])
    chain, expiry = _build_option_chain(kite, NIFTY_NAME, spot)
    atm = min((leg["strike"] for leg in chain), key=lambda k: abs(k - spot)) if chain else None
    return {
        "spot": spot,
        "strikes": chain,
        "atm_strike": atm,
        "expiry_date": expiry.strftime("%d-%b-%Y"),
        "days_to_expiry": (expiry - date.today()).days,
        "lot_size": NIFTY_LOT_SIZE,
    }

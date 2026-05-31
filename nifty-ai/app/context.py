# Market context builder
from .data.banknifty import get_banknifty_data
from .data.nifty50 import get_nifty50_data
from .data.technicals import get_technicals
from .data.vix import get_india_vix
from .trades.positions import get_positions

_TECHNICAL_SYMBOL = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}

_SYSTEM_PROMPT_TAIL = (
    "You are a professional options trading assistant. "
    "Reason from the above data. Be direct and specific with strikes, sizing, and exit levels. "
    "The user is trading with ₹50,000 capital. Max risk per trade is ₹5,000."
)


def _ce(strike):
    return strike["CE"] or {}


def _pe(strike):
    return strike["PE"] or {}


def _compute_pcr(strikes):
    ce_oi = sum(_ce(s).get("oi", 0) for s in strikes)
    pe_oi = sum(_pe(s).get("oi", 0) for s in strikes)
    if ce_oi == 0:
        return None
    return pe_oi / ce_oi


def _oi_walls(strikes, leg: str, top_n: int = 2):
    getter = _ce if leg == "CE" else _pe
    entries = [(s["strike"], getter(s).get("oi", 0)) for s in strikes if getter(s)]
    entries.sort(key=lambda x: x[1], reverse=True)
    return [{"strike": k, "oi": oi} for k, oi in entries[:top_n] if oi > 0]


def _max_pain(strikes):
    if not strikes:
        return None
    rows = [(s["strike"], _ce(s).get("oi", 0), _pe(s).get("oi", 0)) for s in strikes]
    best_strike = None
    best_pain = None
    for k_test, _, _ in rows:
        pain = 0.0
        for k, ce_oi, pe_oi in rows:
            if k_test > k:
                pain += (k_test - k) * ce_oi
            elif k_test < k:
                pain += (k - k_test) * pe_oi
        if best_pain is None or pain < best_pain:
            best_pain = pain
            best_strike = k_test
    return best_strike


def _trend(last_close: float, ema_20: float, ema_50: float) -> str:
    if last_close > ema_20 > ema_50:
        return "bullish"
    if last_close < ema_20 < ema_50:
        return "bearish"
    return "sideways"


def build_market_context(instrument: str) -> dict:
    instrument = instrument.upper()
    if instrument == "NIFTY":
        data = get_nifty50_data()
    elif instrument == "BANKNIFTY":
        data = get_banknifty_data()
    else:
        raise ValueError(f"Unknown instrument: {instrument!r} (expected 'NIFTY' or 'BANKNIFTY')")

    tech = get_technicals(_TECHNICAL_SYMBOL[instrument])
    vix = get_india_vix()
    positions = get_positions()
    strikes = data["strikes"]

    return {
        "instrument": instrument,
        "spot": data["spot"],
        "atm_strike": data["atm_strike"],
        "days_to_expiry": data["days_to_expiry"],
        "lot_size": data["lot_size"],
        "trend": _trend(tech["last_close"], tech["ema_20"], tech["ema_50"]),
        "technicals": {
            "last_close": tech["last_close"],
            "ema_20": tech["ema_20"],
            "ema_50": tech["ema_50"],
            "support": tech["support"],
            "resistance": tech["resistance"],
            "iv_rank": tech["iv_percentile"],
        },
        "india_vix": vix,
        "pcr": _compute_pcr(strikes),
        "oi_walls": {
            "ce": _oi_walls(strikes, "CE", 2),
            "pe": _oi_walls(strikes, "PE", 2),
        },
        "max_pain": _max_pain(strikes),
        "positions": positions,
        "strikes": strikes,
    }


def _fmt(v, prec: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{prec}f}"
    return str(v)


def _fmt_walls(walls):
    if not walls:
        return "n/a"
    return ", ".join(f"{w['strike']:.0f} (OI {w['oi']:,})" for w in walls)


def build_system_prompt(context: dict) -> str:
    t = context["technicals"]
    lines = [
        f"MARKET CONTEXT — {context['instrument']}",
        f"Spot: {_fmt(context['spot'])}   ATM: {_fmt(context['atm_strike'], 0)}   "
        f"DTE: {context['days_to_expiry']}   Lot: {context['lot_size']}",
        f"Trend: {context['trend']}   EMA20: {_fmt(t['ema_20'])}   EMA50: {_fmt(t['ema_50'])}",
        f"Support: {_fmt(t['support'])}   Resistance: {_fmt(t['resistance'])}",
        f"IV Rank (52w percentile): {_fmt(t['iv_rank'], 1)}   India VIX: {_fmt(context['india_vix'])}",
        f"PCR: {_fmt(context['pcr'], 2)}   Max pain: {_fmt(context['max_pain'], 0)}",
        f"CE OI walls: {_fmt_walls(context['oi_walls']['ce'])}",
        f"PE OI walls: {_fmt_walls(context['oi_walls']['pe'])}",
        "",
    ]

    positions = context.get("positions") or []
    if positions:
        lines.append("OPEN POSITIONS:")
        for p in positions:
            symbol = p.get("symbol") or p.get("tradingsymbol") or "?"
            qty = p.get("quantity", p.get("qty", "?"))
            entry = p.get("entry_price", p.get("avg_price", "?"))
            g = p.get("greeks") or {}
            greek_str = (
                f"  Δ={_fmt(g.get('delta'), 3)} Γ={_fmt(g.get('gamma'), 5)} "
                f"Θ={_fmt(g.get('theta'), 3)} ν={_fmt(g.get('vega'), 3)}"
            )
            lines.append(f"  - {symbol}  qty={qty}  entry={entry}{greek_str}")
    else:
        lines.append("OPEN POSITIONS: none")

    lines.append("")
    lines.append(_SYSTEM_PROMPT_TAIL)
    return "\n".join(lines)

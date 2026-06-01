# Market context builder
from pathlib import Path

from .data.banknifty import get_banknifty_data
from .data.nifty50 import get_nifty50_data
from .data.technicals import get_technicals
from .data.vix import get_india_vix
from .trades.positions import get_positions

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

_TECHNICAL_SYMBOL = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}

_SCENARIO_STRATEGY = {
    "expiry_day": {
        "primary": "ATM Straddle Scalp (expiry only)",
        "alternatives": ["Profit booking on open positions", "Stay flat"],
        "reasoning": "DTE is 0 or 1 — gamma risk is extreme; only expiry-specific plays are allowed.",
    },
    "high_vix": {
        "primary": "Iron Condor (reduced size)",
        "alternatives": ["Bull Put Spread (half lots)", "Bear Call Spread (half lots)"],
        "reasoning": "VIX > 18 — fear mode; defined-risk only with 50% lot reduction.",
    },
    "high_iv_bearish": {
        "primary": "Short Strangle / Iron Condor",
        "alternatives": ["Bear Call Spread", "Iron Condor (wider wings)"],
        "reasoning": "IV rank >60% with bearish trend — sell premium while IV contracts.",
    },
    "high_iv_bullish": {
        "primary": "Bull Put Spread",
        "alternatives": ["Cash-Secured Put", "Iron Condor (skewed bearish)"],
        "reasoning": "IV rank >60% with bullish trend — sell puts in direction of trend.",
    },
    "low_iv_bullish": {
        "primary": "Bull Call Spread",
        "alternatives": ["Long Call (ATM)", "Long Straddle (if breakout expected)"],
        "reasoning": "IV rank <40% with bullish trend — cheap options favor buying premium.",
    },
    "low_iv_bearish": {
        "primary": "Bear Put Spread",
        "alternatives": ["Long Put (ATM)", "Long Straddle (if breakdown expected)"],
        "reasoning": "IV rank <40% with bearish trend — cheap options favor buying puts.",
    },
    "neutral_rangebound": {
        "primary": "Iron Condor",
        "alternatives": ["Iron Butterfly", "Short Strangle (if IV near top of range)"],
        "reasoning": "IV 40-60% and price between S1/R1 — range-bound, collect theta decay.",
    },
}


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


def detect_scenario(context: dict) -> str:
    dte = context.get("days_to_expiry", 999)
    vix = context.get("india_vix")  # None means NSE scrape failed — do not default to 0
    iv_rank = (context.get("technicals") or {}).get("iv_rank") or 0
    trend = context.get("trend", "sideways")

    if dte <= 1:
        return "expiry_day"
    if vix is not None and vix > 18:
        return "high_vix"
    if iv_rank > 60 and trend == "bearish":
        return "high_iv_bearish"
    if iv_rank > 60 and trend == "bullish":
        return "high_iv_bullish"
    if iv_rank < 40 and trend == "bullish":
        return "low_iv_bullish"
    if iv_rank < 40 and trend == "bearish":
        return "low_iv_bearish"
    return "neutral_rangebound"


def load_scenario_prompt(scenario: str) -> str:
    path = PROMPTS_DIR / f"{scenario}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[Scenario prompt for '{scenario}' not found]"


def build_market_context(instrument: str, target_expiry=None) -> dict:
    instrument = instrument.upper()
    if instrument == "NIFTY":
        data = get_nifty50_data(target_expiry)
    elif instrument == "BANKNIFTY":
        data = get_banknifty_data(target_expiry)
    else:
        raise ValueError(f"Unknown instrument: {instrument!r} (expected 'NIFTY' or 'BANKNIFTY')")

    tech = get_technicals(_TECHNICAL_SYMBOL[instrument])
    vix = get_india_vix()
    positions = get_positions()
    strikes = data["strikes"]

    ctx = {
        "instrument": instrument,
        "spot": data["spot"],
        "atm_strike": data["atm_strike"],
        "expiry_date": data["expiry_date"],
        "days_to_expiry": data["days_to_expiry"],
        "lot_size": data["lot_size"],
        "expiries": data.get("expiries", []),
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
    ctx["scenario"] = detect_scenario(ctx)
    return ctx


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


def _fmt_chain_slice(strikes: list, atm_strike) -> list[str]:
    if not strikes:
        return []
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i]["strike"] - (atm_strike or 0)))
    lo = max(0, atm_idx - 15)
    hi = min(len(strikes), atm_idx + 16)
    lines = []
    for s in strikes[lo:hi]:
        ce = s.get("CE") or {}
        pe = s.get("PE") or {}
        ce_iv = ce.get("iv")
        pe_iv = pe.get("iv")
        ce_iv_str = f"{ce_iv * 100:.1f}%" if ce_iv is not None else "n/a"
        pe_iv_str = f"{pe_iv * 100:.1f}%" if pe_iv is not None else "n/a"
        line = (
            f"{s['strike']:.0f} | "
            f"CE: LTP ₹{_fmt(ce.get('ltp'), 2)} IV {ce_iv_str} "
            f"Δ{_fmt(ce.get('delta'), 2)} θ{_fmt(ce.get('theta'), 1)} OI {ce.get('oi', 0)} | "
            f"PE: LTP ₹{_fmt(pe.get('ltp'), 2)} IV {pe_iv_str} "
            f"Δ{_fmt(pe.get('delta'), 2)} θ{_fmt(pe.get('theta'), 1)} OI {pe.get('oi', 0)}"
        )
        lines.append(line)
    return lines


def build_system_prompt(context: dict) -> str:
    t = context["technicals"]

    # Load file-based prompt components
    base = (PROMPTS_DIR / "base_system.txt").read_text(encoding="utf-8")
    scenario = context.get("scenario") or detect_scenario(context)
    scenario_prompt = load_scenario_prompt(scenario)
    output_fmt = (PROMPTS_DIR / "output_format.txt").read_text(encoding="utf-8")

    parts = [base, ""]

    positions = context.get("positions") or []
    if positions:
        position_review = load_scenario_prompt("position_review")
        parts.append(position_review)
        parts.append("")

    parts.append(scenario_prompt)
    parts.append("")
    parts.append(output_fmt)
    parts.append("")

    # Market data block
    market_lines = [
        f"MARKET CONTEXT — {context['instrument']}",
        f"Spot: {_fmt(context['spot'])}   ATM: {_fmt(context['atm_strike'], 0)}   "
        f"Expiry: {context.get('expiry_date', 'n/a')}   DTE: {context['days_to_expiry']}   Lot: {context['lot_size']}",
        f"Trend: {context['trend']}   EMA20: {_fmt(t['ema_20'])}   EMA50: {_fmt(t['ema_50'])}",
        f"Support: {_fmt(t['support'])}   Resistance: {_fmt(t['resistance'])}",
        f"IV Rank (52w percentile): {_fmt(t['iv_rank'], 1)}   India VIX: {_fmt(context['india_vix'])}"
        + ("   [VIX unavailable — treat as elevated risk, use defined-risk only]" if context['india_vix'] is None else ""),
        f"PCR: {_fmt(context['pcr'], 2)}   Max pain: {_fmt(context['max_pain'], 0)}",
        f"CE OI walls: {_fmt_walls(context['oi_walls']['ce'])}",
        f"PE OI walls: {_fmt_walls(context['oi_walls']['pe'])}",
        f"Active scenario: {scenario}",
        "",
    ]

    chain_lines = _fmt_chain_slice(context.get("strikes", []), context.get("atm_strike"))
    if chain_lines:
        market_lines.append(
            "OPTION CHAIN (ATM ±15 strikes — use ONLY these strikes and "
            "these premiums when building trade legs):"
        )
        market_lines.extend(chain_lines)
        market_lines.append(
            "IMPORTANT: Never suggest a strike not listed above. "
            "Never invent a premium — use only the LTP values shown."
        )
        market_lines.append("")

    if positions:
        market_lines.append("OPEN POSITIONS:")
        for p in positions:
            symbol = p.get("symbol") or p.get("tradingsymbol") or "?"
            qty = p.get("quantity", p.get("qty", "?"))
            entry = p.get("entry_price", p.get("avg_price", "?"))
            ltp_val = p.get("last_price")
            ltp_str = f"₹{_fmt(ltp_val)}" if ltp_val is not None else "unavailable"
            g = p.get("greeks") or {}
            greek_str = (
                f"  Δ={_fmt(g.get('delta'), 3)} Γ={_fmt(g.get('gamma'), 5)} "
                f"Θ={_fmt(g.get('theta'), 3)} ν={_fmt(g.get('vega'), 3)}"
            )
            market_lines.append(f"  - {symbol}  qty={qty}  entry={entry}  ltp={ltp_str}{greek_str}")
    else:
        market_lines.append("OPEN POSITIONS: none")

    parts.append("\n".join(market_lines))
    return "\n".join(parts)

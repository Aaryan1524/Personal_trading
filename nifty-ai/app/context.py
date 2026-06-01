# Market context builder
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data.account import get_account_equity
from .data.banknifty import get_banknifty_data
from .data.events import event_risk_level, get_upcoming_events
from .data.intraday import get_intraday_stats
from .data.nifty50 import get_nifty50_data
from .data.technicals import get_intraday_technicals, get_technicals
from .data.vix import get_india_vix
from .trades.positions import get_positions

_IST = ZoneInfo("Asia/Kolkata")

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
    "long_volatility": {
        "primary": "Long Straddle / Long Strangle",
        "alternatives": ["Long ATM Call (if breakout up)", "Long ATM Put (if breakdown)"],
        "reasoning": "IV rank <25% and price coiling sideways — options are cheap and a volatility "
                     "expansion is overdue. Convex, defined-risk buy: this is a primary growth engine.",
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
    if iv_rank < 25 and trend == "sideways":
        return "long_volatility"
    return "neutral_rangebound"


def load_scenario_prompt(scenario: str) -> str:
    path = PROMPTS_DIR / f"{scenario}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[Scenario prompt for '{scenario}' not found]"


def detect_intraday_setup(context: dict) -> dict:
    """Detect the active mechanical intraday setup based on time window, VWAP,
    opening range, and OI data already present in *context*.

    Runs after detect_scenario(); does not modify any existing context field.

    Returns:
        {
            "is_intraday_eligible": bool,
            "active_setup":         str | None,
            "reasoning":            str,
            "time_window":          str,
        }
    """
    now      = datetime.now(_IST)
    time_dec = now.hour + now.minute / 60.0   # e.g. 10:30 → 10.5

    _not_eligible = {
        "is_intraday_eligible": False,
        "active_setup": None,
        "reasoning": "Outside intraday trading window (9:30 – 15:00 IST)",
        "time_window": "closed",
    }

    # ── Rule 1: time gate ────────────────────────────────────────────────────
    if time_dec < 9.5 or time_dec > 15.0:
        return _not_eligible

    intraday    = context.get("intraday") or {}
    spot        = context.get("spot") or 0.0
    prev_close  = (context.get("technicals") or {}).get("last_close") or 0.0
    dte         = context.get("days_to_expiry", 999)
    instrument  = context.get("instrument", "NIFTY")

    vwap            = intraday.get("vwap")
    or_high         = intraday.get("opening_range_high")
    or_low          = intraday.get("opening_range_low")
    breakout_status = intraday.get("breakout_status")      # "breakout" | "breakdown" | "inside_range"
    intraday_trend  = intraday.get("intraday_trend", "sideways")
    day_high        = intraday.get("day_high") or 0.0
    day_low         = intraday.get("day_low") or 0.0

    # ── Window 1: 9:30 – 11:00 (opening window) ──────────────────────────────
    if time_dec < 11.0:
        win = "09:15 – 11:00 IST (opening window)"

        # Setup A — opening range breakout
        if or_high and or_low and breakout_status in ("breakout", "breakdown"):
            direction = "above OR high" if breakout_status == "breakout" else "below OR low"
            return {
                "is_intraday_eligible": True,
                "active_setup": "opening_range_breakout",
                "reasoning": (
                    f"Spot has broken {direction} "
                    f"(opening range: {or_low:.0f} – {or_high:.0f}). "
                    "Momentum trade in breakout direction."
                ),
                "time_window": win,
            }

        # Setup B — gap fill
        stats = get_intraday_stats(instrument)
        today_open = stats.get("open") or 0.0
        if prev_close and today_open:
            gap_pct = (today_open - prev_close) / prev_close * 100
            if abs(gap_pct) > 0.4:
                filling = (
                    (gap_pct > 0 and intraday_trend == "bearish") or
                    (gap_pct < 0 and intraday_trend == "bullish")
                )
                if filling:
                    direction = "up" if gap_pct > 0 else "down"
                    return {
                        "is_intraday_eligible": True,
                        "active_setup": "gap_fill",
                        "reasoning": (
                            f"Market gapped {direction} {abs(gap_pct):.2f}% from prev close "
                            f"({prev_close:.0f} → open {today_open:.0f}). "
                            f"Intraday trend is {intraday_trend} — spot is moving back toward the gap fill."
                        ),
                        "time_window": win,
                    }

        return {
            "is_intraday_eligible": True,
            "active_setup": None,
            "reasoning": "Opening window active — OR not broken and gap < 0.4% (or not filling)",
            "time_window": win,
        }

    # ── Window 2: 11:00 – 14:00 (midday window) ─────────────────────────────
    if time_dec < 14.0:
        win = "11:00 – 14:00 IST (midday window)"

        # Setup C — VWAP rejection
        if vwap and spot:
            vwap_diff_pct = abs(spot - vwap) / vwap * 100
            if vwap_diff_pct <= 0.1:
                side = "above" if spot >= vwap else "below"
                return {
                    "is_intraday_eligible": True,
                    "active_setup": "vwap_rejection",
                    "reasoning": (
                        f"Spot ({spot:.0f}) is within 0.1% of VWAP ({vwap:.0f}) — "
                        f"currently {side} VWAP. "
                        f"Watch for rejection {'back down' if side == 'above' else 'back up'} off this level."
                    ),
                    "time_window": win,
                }

        # Setup D — OI concentration (proxy for 30-min shift; true delta requires time-series polling)
        strikes = context.get("strikes") or []
        if strikes:
            def _top_oi_pct(leg: str) -> float:
                vals = [
                    (s.get(leg) or {}).get("oi", 0) or 0
                    for s in strikes if s.get(leg)
                ]
                total = sum(vals)
                return max(vals) / total * 100 if total > 0 else 0.0

            ce_conc = _top_oi_pct("CE")
            pe_conc = _top_oi_pct("PE")
            if ce_conc > 40 or pe_conc > 40:
                side = "CE" if ce_conc > pe_conc else "PE"
                pct  = ce_conc if side == "CE" else pe_conc
                return {
                    "is_intraday_eligible": True,
                    "active_setup": "oi_shift",
                    "reasoning": (
                        f"Unusual {side} OI concentration: {pct:.1f}% of total {side} OI "
                        "sits at a single strike — possible institutional positioning. "
                        "(Note: precise 30-min OI delta requires time-series polling.)"
                    ),
                    "time_window": win,
                }

        return {
            "is_intraday_eligible": True,
            "active_setup": None,
            "reasoning": "Midday window — spot not at VWAP (>0.1% away) and no unusual OI concentration",
            "time_window": win,
        }

    # ── Window 3: 14:00 – 15:15 (closing window) ────────────────────────────
    win = "14:00 – 15:15 IST (closing window)"

    # Setup E — theta scalp
    if dte <= 1 and spot > 0 and day_high > 0 and day_low > 0:
        range_pct = (day_high - day_low) / spot * 100
        if range_pct < 0.5:
            return {
                "is_intraday_eligible": True,
                "active_setup": "theta_scalp",
                "reasoning": (
                    f"DTE = {dte} and intraday range only {range_pct:.2f}% — "
                    "tight range near expiry. ATM straddle sell for final theta decay. "
                    "Exit by 2:30 PM; no new positions after that."
                ),
                "time_window": win,
            }

    # Setup F — closing momentum
    if vwap and intraday_trend in ("bullish", "bearish"):
        side = "above" if intraday_trend == "bullish" else "below"
        return {
            "is_intraday_eligible": True,
            "active_setup": "closing_momentum",
            "reasoning": (
                f"Strong {intraday_trend} trend persisting into the close — "
                f"spot consistently {side} VWAP ({_fmt(vwap)}). "
                "Momentum likely to continue to 3:15 PM close."
            ),
            "time_window": win,
        }

    return {
        "is_intraday_eligible": True,
        "active_setup": None,
        "reasoning": "No mechanical setup currently active",
        "time_window": win,
    }


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
    equity = get_account_equity()
    intraday = get_intraday_technicals(_TECHNICAL_SYMBOL[instrument])
    strikes = data["strikes"]
    expiries = data.get("expiries", [])
    events = get_upcoming_events(expiries)

    ctx = {
        "instrument": instrument,
        "account_equity": equity,
        "spot": data["spot"],
        "atm_strike": data["atm_strike"],
        "expiry_date": data["expiry_date"],
        "days_to_expiry": data["days_to_expiry"],
        "lot_size": data["lot_size"],
        "expiries": expiries,
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
        "intraday": intraday,
        "events": events,
    }
    ctx["scenario"] = detect_scenario(ctx)

    # Intraday setup detection runs after scenario is known
    setup = detect_intraday_setup(ctx)
    if ctx.get("intraday") is None:
        ctx["intraday"] = setup
    else:
        ctx["intraday"].update(setup)

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

    # Inject intraday setup prompt when a mechanical setup is active
    _intraday_ctx = context.get("intraday") or {}
    _active_setup = _intraday_ctx.get("active_setup")
    if _active_setup:
        intraday_prompt = load_scenario_prompt(f"intraday_{_active_setup}")
        parts.append(
            "===========================================\n"
            "ADDITIONAL: INTRADAY OPPORTUNITY DETECTED\n"
            "===========================================\n"
            "\n"
            "An intraday setup is currently active. The operator may choose either:\n"
            "(a) The positional strategy above (multi-day hold), OR\n"
            "(b) The intraday setup below (same-day exit)\n"
            "\n"
            "When asked to recommend a trade, present BOTH options:\n"
            "- Option A: positional play (from the main scenario)\n"
            "- Option B: intraday play (from the setup below)\n"
            "\n"
            "Let the operator choose. Default to intraday only if explicitly requested\n"
            "with words like 'intraday', 'scalp', 'today only', 'quick trade'."
        )
        parts.append("")
        parts.append(intraday_prompt)
        parts.append("")

    parts.append(output_fmt)
    parts.append("")

    # Account equity drives position sizing — 7% of equity is the per-trade risk cap.
    equity = context.get("account_equity")
    if equity is not None:
        equity_line = (
            f"Account equity: ₹{equity:,.0f}   "
            f"Max risk this trade (7%): ₹{equity * 0.07:,.0f}"
        )
    else:
        equity_line = (
            "Account equity: unavailable (Kite margins call failed) — "
            "size from ₹40,000 default and flag that equity is stale"
        )

    # Market data block
    market_lines = [
        f"MARKET CONTEXT — {context['instrument']}",
        equity_line,
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

    # ── Intraday setup status block ──────────────────────────────────────────
    _id = context.get("intraday") or {}
    _active_setup = _id.get("active_setup")
    market_lines += [
        "INTRADAY SETUP STATUS:",
        f"  Active setup: {_active_setup}" if _active_setup
            else "  Active setup: None — no mechanical intraday entry available right now",
        f"  Reasoning: {_id.get('reasoning', 'n/a')}",
        f"  Time window: {_id.get('time_window', 'n/a')}",
        "",
    ]

    # ── Upcoming events block ────────────────────────────────────────────────
    events = context.get("events") or []
    if events:
        risk = event_risk_level(events)
        market_lines.append("UPCOMING EVENTS (next 7 days):")
        for ev in events:
            market_lines.append(
                f"  - {ev['date_str']}: {ev['name']} [{ev['impact']}] — "
                f"{ev['days_away']} day{'s' if ev['days_away'] != 1 else ''} away. {ev['notes']}"
            )
        if risk == "HIGH":
            urgent = next(e for e in events if e["impact"] == "HIGH")
            market_lines.append(
                f"EVENT RISK: HIGH — {urgent['name']} is {urgent['days_away']} day(s) away. "
                "Do NOT open new naked or undefined-risk premium-selling positions. "
                "Defined-risk spreads are acceptable but keep width narrow. "
                "Long volatility (straddle/strangle) is actively favoured — IV is cheap "
                "relative to the coming event and the move will reprice it."
            )
        elif risk == "MEDIUM":
            market_lines.append(
                "EVENT RISK: MEDIUM — flag the upcoming event to the user and "
                "recommend defined-risk strategies only."
            )
        market_lines.append("")

    # ── Intraday momentum block ──────────────────────────────────────────────
    intraday = context.get("intraday")
    if intraday:
        vs_vwap = "ABOVE" if context["spot"] > intraday["vwap"] else "BELOW"
        orb_status = {
            "breakout": "ABOVE opening range high — bullish momentum holding",
            "breakdown": "BELOW opening range low — bearish momentum holding",
            "inside_range": "Inside opening range — no directional breakout yet",
        }.get(intraday["breakout_status"], intraday["breakout_status"])
        market_lines += [
            f"INTRADAY MOMENTUM (15-min candles — {intraday['candle_count']} candles so far today):",
            f"  VWAP: {_fmt(intraday['vwap'])}   Spot vs VWAP: {vs_vwap} "
            f"({'bullish intraday' if vs_vwap == 'ABOVE' else 'bearish intraday'})",
            f"  Opening range (9:15–9:45 IST): {_fmt(intraday['opening_range_low'])} – {_fmt(intraday['opening_range_high'])}",
            f"  Breakout status: {orb_status}",
            f"  9-EMA (15m): {_fmt(intraday['ema_9'])}   Day range: {_fmt(intraday['day_low'])} – {_fmt(intraday['day_high'])}",
            f"  Intraday trend: {intraday['intraday_trend'].upper()}",
            "  Use this to time entries: only enter a bullish trade when intraday trend is "
            "BULLISH or a bearish trade when BEARISH. If intraday trend conflicts with the "
            "daily scenario, flag it and wait for alignment.",
            "",
        ]
    else:
        market_lines += [
            "INTRADAY MOMENTUM: market not yet open or no candles available — "
            "base entry decisions on daily context only.",
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

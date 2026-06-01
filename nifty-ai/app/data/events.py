# Market event calendar — three live sources, zero hardcoded dates:
#   1. F&O expiry dates        → Kite instruments API (already in context)
#   2. Market holidays         → NSE India /api/holidays
#   3. Macro events (RBI/FOMC) → NSE India /api/event-calendar
#
# All three are fetched at request time; each falls back gracefully.

import httpx
from datetime import date, datetime, timedelta

NSE_BASE = "https://www.nseindia.com"
NSE_HOLIDAYS_URL = "https://www.nseindia.com/api/holidays?type=trading"
NSE_EVENTS_URL = "https://www.nseindia.com/api/event-calendar"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# NSE date strings arrive in several formats — try each in order
_NSE_DATE_FMTS = ["%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"]


def _parse_nse_date(s: str) -> date | None:
    if not s:
        return None
    s = s.strip().split(" ")[0]   # drop time component if present
    for fmt in _NSE_DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _nse_client() -> httpx.Client:
    """Return an httpx Client with an NSE session cookie already set."""
    client = httpx.Client(headers=_HEADERS, timeout=10.0, follow_redirects=True)
    try:
        client.get(NSE_BASE)   # establishes the session cookie NSE requires
    except Exception:
        pass
    return client


def _fetch_nse_holidays(client: httpx.Client) -> list[dict]:
    """Fetch upcoming NSE trading holidays."""
    try:
        r = client.get(NSE_HOLIDAYS_URL)
        r.raise_for_status()
        data = r.json()

        # NSE returns {"FO": [...], "CM": [...]} or a flat list depending on endpoint
        rows = []
        if isinstance(data, dict):
            rows = data.get("FO") or data.get("CM") or []
        elif isinstance(data, list):
            rows = data

        today = date.today()
        results = []
        for row in rows:
            raw_date = row.get("tradingDate") or row.get("date") or row.get("holidayDate") or ""
            ev_date = _parse_nse_date(raw_date)
            if ev_date is None or ev_date < today:
                continue
            results.append({
                "date": ev_date,
                "name": row.get("description") or row.get("desc") or row.get("weekDay") or "Market Holiday",
                "impact": "MEDIUM",
                "notes": "NSE market holiday — markets closed.",
                "source": "nse_holiday",
            })
        return results
    except Exception:
        return []


def _fetch_nse_events(client: httpx.Client) -> list[dict]:
    """Fetch upcoming macro events from NSE event calendar."""
    try:
        r = client.get(NSE_EVENTS_URL)
        r.raise_for_status()
        data = r.json()

        rows = data if isinstance(data, list) else (data.get("data") or data.get("events") or [])

        today = date.today()
        results = []
        for row in rows:
            raw_date = (
                row.get("date") or row.get("broadcastDt") or
                row.get("eventDate") or row.get("announceDt") or ""
            )
            ev_date = _parse_nse_date(raw_date)
            if ev_date is None or ev_date < today:
                continue

            name = (
                row.get("head") or row.get("desc") or row.get("eventDesc") or
                row.get("name") or row.get("catDes") or "Market Event"
            )

            raw_impact = (row.get("importance") or row.get("impact") or "").upper()
            impact = "HIGH" if raw_impact in ("HIGH", "H") else "MEDIUM"

            # Classify known high-impact events regardless of NSE's own tagging
            name_up = name.upper()
            if any(k in name_up for k in ("RBI", "MONETARY POLICY", "MPC", "FOMC", "FEDERAL RESERVE", "BUDGET")):
                impact = "HIGH"

            results.append({
                "date": ev_date,
                "name": name.strip(),
                "impact": impact,
                "notes": row.get("notes") or row.get("body") or "",
                "source": "nse_events",
            })
        return results
    except Exception:
        return []


def _fno_expiry_events(expiry_list: list[dict]) -> list[dict]:
    """Convert the Kite-derived expiry list into event dicts."""
    today = date.today()
    results = []
    for exp in expiry_list:
        try:
            ev_date = datetime.strptime(exp["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if ev_date < today:
            continue
        is_monthly = exp.get("type") == "M"
        results.append({
            "date": ev_date,
            "name": f"{'Monthly' if is_monthly else 'Weekly'} F&O Expiry",
            "impact": "HIGH" if is_monthly else "MEDIUM",
            "notes": (
                "Monthly expiry — gamma risk extreme near end of day. "
                "Reduce size; no new positions after 2:30 PM IST."
            ) if is_monthly else (
                "Weekly expiry — elevated gamma for near-expiry contracts."
            ),
            "source": "kite_expiry",
        })
    return results


def get_upcoming_events(expiry_list: list[dict] | None = None, days_ahead: int = 30) -> list[dict]:
    """Return all upcoming events within `days_ahead` days, sorted by date.

    Each item:
      date_str  — human-readable date
      name      — event name
      impact    — HIGH / MEDIUM
      days_away — integer days from today
      notes     — brief context string
      source    — "kite_expiry" | "nse_holiday" | "nse_events"
    """
    today = date.today()
    horizon = today + timedelta(days=days_ahead)

    # Kite expiry events — always reliable
    raw: list[dict] = _fno_expiry_events(expiry_list or [])

    # NSE events — best-effort, single session to avoid double cookie fetch
    try:
        with _nse_client() as client:
            raw += _fetch_nse_holidays(client)
            raw += _fetch_nse_events(client)
    except Exception:
        pass

    # Filter to window, deduplicate by (date, name), sort
    seen: set[tuple] = set()
    results = []
    for ev in raw:
        ev_date = ev["date"]
        if not (today <= ev_date <= horizon):
            continue
        key = (ev_date, ev["name"][:30])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "date_str": ev_date.strftime("%d %b %Y"),
            "date_iso": ev_date.isoformat(),
            "name": ev["name"],
            "impact": ev["impact"],
            "days_away": (ev_date - today).days,
            "notes": ev["notes"],
            "source": ev["source"],
        })

    results.sort(key=lambda e: e["days_away"])
    return results


def event_risk_level(events: list[dict]) -> str:
    if any(e["impact"] == "HIGH" for e in events[:5]):   # only first 5 days matter for risk
        return "HIGH"
    if any(e["impact"] == "MEDIUM" for e in events):
        return "MEDIUM"
    return "NONE"

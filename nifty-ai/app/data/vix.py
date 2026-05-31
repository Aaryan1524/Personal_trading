# India VIX data
import httpx

NSE_HOMEPAGE = "https://www.nseindia.com"
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def get_india_vix() -> float | None:
    try:
        with httpx.Client(headers=_HEADERS, timeout=10.0, follow_redirects=True) as client:
            client.get(NSE_HOMEPAGE)
            r = client.get(NSE_ALL_INDICES)
            r.raise_for_status()
            data = r.json()
            for row in data.get("data", []):
                name = (row.get("index") or row.get("indexSymbol") or "").upper()
                if "INDIA VIX" in name:
                    value = row.get("last") or row.get("lastPrice")
                    return float(value) if value is not None else None
    except Exception:
        return None
    return None

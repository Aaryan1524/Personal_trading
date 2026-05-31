# Open positions tracking
import re

from ..data.kite import get_kite_client

_INDEX_SYMBOL_PATTERN = re.compile(r"^(NIFTY|BANKNIFTY)\d")


def get_positions() -> list[dict]:
    try:
        kite = get_kite_client()
        net = kite.positions().get("net", [])
        return [p for p in net if _INDEX_SYMBOL_PATTERN.match(p.get("tradingsymbol", ""))]
    except Exception:
        return []

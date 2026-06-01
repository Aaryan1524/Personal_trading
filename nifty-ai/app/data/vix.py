# India VIX via Kite Connect — instrument token 264969 (NSE:INDIA VIX)
from .kite import get_kite_client

_INDIA_VIX_TOKEN = 264969


def get_india_vix() -> float | None:
    try:
        kite = get_kite_client()
        quote = kite.quote([_INDIA_VIX_TOKEN])
        return float(quote[str(_INDIA_VIX_TOKEN)]["last_price"])
    except Exception:
        return None

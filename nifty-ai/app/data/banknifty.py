# Bank Nifty data fetchers
from datetime import date

from .kite import get_kite_client
from .nifty50 import _build_option_chain

BANKNIFTY_INSTRUMENT_TOKEN = 260105
BANKNIFTY_NAME = "BANKNIFTY"
BANKNIFTY_LOT_SIZE = 15


def get_banknifty_data() -> dict:
    kite = get_kite_client()
    q = kite.quote([BANKNIFTY_INSTRUMENT_TOKEN])
    spot = float(q[str(BANKNIFTY_INSTRUMENT_TOKEN)]["last_price"])
    chain, expiry = _build_option_chain(kite, BANKNIFTY_NAME, spot)
    atm = min((leg["strike"] for leg in chain), key=lambda k: abs(k - spot)) if chain else None
    return {
        "spot": spot,
        "strikes": chain,
        "atm_strike": atm,
        "days_to_expiry": (expiry - date.today()).days,
        "lot_size": BANKNIFTY_LOT_SIZE,
    }

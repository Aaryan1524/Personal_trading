# Bank Nifty data fetchers
from datetime import date

from .kite import get_kite_client
from .nifty50 import _build_option_chain, _get_expiries

BANKNIFTY_INSTRUMENT_TOKEN = 260105
BANKNIFTY_NAME = "BANKNIFTY"
BANKNIFTY_LOT_SIZE = 30


def get_banknifty_expiries() -> list[dict]:
    return _get_expiries(BANKNIFTY_NAME)


def get_banknifty_data(target_expiry: date | None = None) -> dict:
    kite = get_kite_client()
    q = kite.quote([BANKNIFTY_INSTRUMENT_TOKEN])
    spot = float(q[str(BANKNIFTY_INSTRUMENT_TOKEN)]["last_price"])
    chain, expiry, expiry_list = _build_option_chain(kite, BANKNIFTY_NAME, spot, target_expiry)
    atm = min((leg["strike"] for leg in chain), key=lambda k: abs(k - spot)) if chain else None
    return {
        "spot": spot,
        "strikes": chain,
        "atm_strike": atm,
        "expiry_date": expiry.strftime("%d-%b-%Y"),
        "days_to_expiry": (expiry - date.today()).days,
        "lot_size": BANKNIFTY_LOT_SIZE,
        "expiries": expiry_list,
    }

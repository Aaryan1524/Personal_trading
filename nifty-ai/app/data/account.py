# Live account equity via Kite margins — drives position sizing so risk
# scales with the account (the compounding lever for account growth).
from .kite import get_kite_client


def get_account_equity() -> float | None:
    """Net deployable equity (cash + usable collateral) on the Kite account.

    Returns None if the margins call fails (e.g. expired token), so callers
    can fall back to a default and flag that sizing is using a stale number.
    """
    try:
        kite = get_kite_client()
        margins = kite.margins("equity")
        net = margins.get("net")
        return float(net) if net is not None else None
    except Exception:
        return None

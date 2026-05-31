# Kite Connect client wrapper
import json
from pathlib import Path


# pyrefly: ignore [missing-import]
from kiteconnect import KiteConnect

TOKEN_PATH = Path(__file__).resolve().parents[2] / "token.json"


def get_kite_client() -> KiteConnect:
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"token.json not found at {TOKEN_PATH}. Run `python auth.py` first to authenticate with Kite."
        )

    data = json.loads(TOKEN_PATH.read_text())
    kite = KiteConnect(api_key=data["api_key"])
    kite.set_access_token(data["access_token"])
    return kite

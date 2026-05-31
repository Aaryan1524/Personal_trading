# Trade log persistence
import json
from datetime import datetime, timezone
from pathlib import Path

TRADES_PATH = Path(__file__).resolve().parents[2] / "data_store" / "trades.json"


def _load() -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    try:
        return json.loads(TRADES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def append_trade(entry: dict) -> dict:
    trades = _load()
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    trades.append(record)
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRADES_PATH.write_text(json.dumps(trades, indent=2))
    return record


def list_trades() -> list[dict]:
    return _load()

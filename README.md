# Personal trading

> **The actual app lives in [`nifty-ai/`](./nifty-ai). Everything below is just the launcher.**

## First-time setup (already done if you're reading this on a working machine)

```sh
cd nifty-ai
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit nifty-ai/.env and fill in:
#   KITE_API_KEY=...
#   KITE_API_SECRET=...
#   ANTHROPIC_API_KEY=...
```

## Daily workflow

From this `Personal_trading/` directory:

```sh
./auth.sh           # 1. Kite OAuth — opens browser, paste redirect URL back
./start.sh          # 2. starts the FastAPI server at http://localhost:8000
```

Both scripts handle the `cd nifty-ai` and `source .venv/bin/activate` for you.

## If you'd rather do it manually

```sh
cd nifty-ai
source .venv/bin/activate
python auth.py                                # once each market morning
uvicorn app.main:app --reload --port 8000    # then start the server
```

Open http://localhost:8000.

See [`nifty-ai/README.md`](./nifty-ai/README.md) for architecture, file map, and the known-issues TODO list.

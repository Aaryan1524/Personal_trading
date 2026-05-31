# nifty-ai

A personal Indian-market trading assistant that pulls live Nifty 50 / Bank Nifty spot, option chain, technicals, and India VIX from Kite Connect, computes implied vol and Greeks per strike via Black-Scholes, assembles a market-context system prompt, and hands it to Claude for conversational analysis. A FastAPI backend serves a single-page dashboard with a chain viewer, dynamic strategy builder, position tracker, and chat panel. A local JSON file keeps a trade log you can review later.

## Prerequisites

- **Python 3.11+**
- **Kite Connect subscription** (with API key + secret from [developers.kite.trade](https://developers.kite.trade))
- **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))

## Setup

```sh
git clone <this-repo>
cd nifty-ai

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in:
#   KITE_API_KEY=...
#   KITE_API_SECRET=...
#   ANTHROPIC_API_KEY=...
```

## Daily workflow

Kite access tokens expire each morning (~06:00 IST), so the auth flow runs once per trading day.

```sh
# 1. Authenticate with Kite (opens browser, paste redirect URL back)
python auth.py

# 2. Start the API + dashboard
uvicorn app.main:app --reload --port 8000

# 3. Open the dashboard
open http://localhost:8000
```

If `token.json` is missing when you start the server, the lifespan check fails fast with a clear "run `python auth.py`" error.

## Instrument switching

The top bar has a **NIFTY / BANKNIFTY** segmented toggle. Click either button and the dashboard:

1. Re-fetches `/api/market?instrument=...` with the new instrument
2. Re-renders the top bar (spot, ATM, DTE, VIX), signals, technicals, chain, and strategy builder
3. Tags subsequent chat messages with the active instrument so Claude sees the right market context

The chat session ID does **not** reset when you switch — your conversation history carries across instruments. Use the **Clear** button in the chat header if you want a fresh session.

## File map

| File | Purpose |
|---|---|
| `auth.py` | One-time daily Kite OAuth flow; writes access token to `token.json`. |
| `app/main.py` | FastAPI app, routes, CORS, startup token check, static frontend mount. |
| `app/chat.py` | Anthropic SDK wrapper; `send_message()` with prompt-cached system prompt. |
| `app/context.py` | `build_market_context()` (PCR, max pain, OI walls, trend) + `build_system_prompt()`. |
| `app/session.py` | `SessionManager` — in-memory conversation history per `session_id`. |
| `app/data/kite.py` | Loads `token.json`, returns authenticated `KiteConnect` client. |
| `app/data/nifty50.py` | Nifty 50 spot + chain with Black-Scholes IV/Greeks; shared chain helper. |
| `app/data/banknifty.py` | Bank Nifty spot + chain (reuses the nifty50 chain helper). |
| `app/data/technicals.py` | 60d OHLCV, EMA20/EMA50, 20d support/resistance, 52w IV percentile. |
| `app/data/vix.py` | Scrapes India VIX from NSE's `allIndices` endpoint; returns `None` on failure. |
| `app/trades/log.py` | Append/list trades in `data_store/trades.json` with UTC timestamps. |
| `app/trades/positions.py` | Live positions from Kite filtered to NIFTY/BANKNIFTY symbols. |
| `frontend/index.html` | Dashboard layout — top bar, three panels, three tabs, log-trade modal. |
| `frontend/style.css` | Color tokens + layout (dark left sidebar, light main, green accent). |
| `frontend/app.js` | Render orchestration, chat, dynamic strategy builder, instrument toggle. |
| `requirements.txt` | FastAPI, uvicorn, kiteconnect, anthropic, httpx, python-dotenv, pandas, numpy. |
| `.env.example` | Template for `KITE_API_KEY`, `KITE_API_SECRET`, `ANTHROPIC_API_KEY`. |
| `data_store/.gitkeep` | Keeps the trade/IV-history directory in git. |
| `.gitignore` | Excludes `.env`, `token.json`, `__pycache__`, `data_store/iv_history.json`, `*.pyc`. |

## Wiring check — TODO

The following gaps and minor mismatches turned up during a cross-file audit. None are blockers, but worth fixing as the system matures.

- [ ] **Position entry-price field mismatch.** `app/context.py:146` reads `p.get("entry_price", p.get("avg_price", "?"))` when rendering positions in the system prompt, but Kite's position objects use `average_price`. Live positions will render `entry=?` to Claude. Add `"average_price"` to the fallback chain (the frontend at `app.js:163` already handles both).
- [ ] **Position Greeks aren't computed.** Both `context.py` and `app.js` look for `p.greeks` on each position, but Kite doesn't supply Greeks and nothing computes them. They render as `—`. Would need to parse the option's tradingsymbol → strike/type/expiry, then call `_greeks()` from `app/data/nifty50.py` against the current spot.
- [ ] **`/api/trades` is defined but has no UI consumer.** `app/main.py:94` exposes the trade log, and `frontend/app.js:11` lists it in the `API` object, but nothing calls it — there's no view of past trades. Either add a "History" tab or a side panel.
- [ ] **Sonnet 4.5 is a legacy alias.** `app/chat.py:11` pins `claude-sonnet-4-5`. Still active, but `claude-sonnet-4-6` is the current Sonnet — drop-in upgrade when you're ready.
- [ ] **Body `min-width` is 1280px, spec asked for 1200px.** `frontend/style.css:39` — lower if you want the dashboard to fit on smaller laptops.
- [ ] **Per-refresh Kite load is heavy.** Every `/api/market` call triggers `kite.instruments("NFO")` (used inside `_build_option_chain`), two `kite.historical_data()` calls (60d + 400d), `kite.positions()` (via `context.build_market_context` → `get_positions`), plus chunked `kite.quote()` for the chain. Consider caching the instruments list and 400d history for the trading day.
- [ ] **`Iv_percentile` aliased to `iv_rank`.** Server returns `iv_percentile` from `technicals.py`, but `context.py:97` and the UI label it "IV Rank". They're different things (rank = (current − low) / (high − low); percentile = % of days below current). Pick one and label consistently.
- [ ] **`get_positions()` is called twice per refresh.** Once inside `build_market_context()` (for the system prompt) and once again via `/api/positions` from the frontend. Cheap, but redundant — consider returning positions in the `/api/market` payload too, or having the frontend skip the second call.
- [ ] **Sideways-trend strategies can be empty.** `app.js buildStrategies()` only adds Iron Butterfly when `cards.length < 3`, and the other sideways branches require IV ≥70 or ≤30. A sideways market with mid IV will show zero cards.
- [ ] **NSE VIX scraping is fragile.** `nseindia.com/api/allIndices` blocks aggressively without warm cookies. `vix.py` does the homepage GET first to seed cookies, but expect intermittent `None` returns. Top bar will show `—` for VIX when this happens.

## Verified ✓

- All Python imports resolve (`from .x import y` matches the exporting module in every case).
- Every function `main.py` imports (`_sessions`, `send_message`, `build_market_context`, `build_system_prompt`, `TOKEN_PATH`, `append_trade`, `list_trades`, `get_positions`) exists in its source module with a matching signature.
- `.env` keys are consistent: `auth.py` reads `KITE_API_KEY` + `KITE_API_SECRET`; the Anthropic SDK reads `ANTHROPIC_API_KEY` from env after `chat.py` loads `nifty-ai/.env`. All three keys appear in `.env.example`.
- Frontend API calls match backend routes one-to-one: `GET /api/market`, `POST /api/chat`, `POST /api/session/clear`, `GET /api/positions`, `POST /api/trades/log` are all defined in `main.py`. `GET /api/trades` is defined but unconsumed (see TODO above).
- `TOKEN_PATH` resolves to the same `nifty-ai/token.json` whether imported from `auth.py` (`parent`) or `app/data/kite.py` (`parents[2]`).

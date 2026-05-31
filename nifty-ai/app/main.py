# FastAPI entrypoint
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .chat import _sessions, send_message
from .context import _SCENARIO_STRATEGY, build_market_context, build_system_prompt, detect_scenario
from .data.kite import TOKEN_PATH
from .trades.log import append_trade, list_trades
from .trades.positions import get_positions

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"token.json not found at {TOKEN_PATH}. Run `python auth.py` to authenticate with Kite before starting the API."
        )
    yield


app = FastAPI(title="nifty-ai", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/market")
def get_market(instrument: str = Query(...)):
    try:
        return build_market_context(instrument)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[ERROR] /api/market: {type(e).__name__}: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": True, "message": "Market data unavailable — check Kite connection or re-run auth.py", "detail": str(e)},
        )


@app.get("/api/scenario")
def get_scenario(instrument: str = Query(...)):
    try:
        ctx = build_market_context(instrument)
        scenario = detect_scenario(ctx)
        info = _SCENARIO_STRATEGY.get(scenario, {})
        return {
            "scenario": scenario,
            "primary_strategy": info.get("primary", ""),
            "reasoning": info.get("reasoning", ""),
            "alternatives": info.get("alternatives", []),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[ERROR] /api/scenario: {type(e).__name__}: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": True, "message": "Market data unavailable — check Kite connection or re-run auth.py", "detail": str(e)},
        )


class ChatRequest(BaseModel):
    session_id: str
    message: str
    instrument: str


@app.post("/api/chat")
def post_chat(req: ChatRequest):
    try:
        context = build_market_context(req.instrument)
        system_prompt = build_system_prompt(context)
        response = send_message(req.session_id, req.message, system_prompt)
        return {"response": response, "session_id": req.session_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[ERROR] /api/chat: {type(e).__name__}: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": True, "message": "Market data unavailable — check Kite connection or re-run auth.py", "detail": str(e)},
        )


class ClearRequest(BaseModel):
    session_id: str


@app.post("/api/session/clear")
def post_session_clear(req: ClearRequest):
    _sessions.clear_session(req.session_id)
    return {"ok": True}


@app.get("/api/positions")
def get_positions_endpoint():
    return get_positions()


class TradeLogRequest(BaseModel):
    instrument: str
    strategy: str
    legs: list[Any]
    notes: str | None = None


@app.post("/api/trades/log")
def post_trades_log(req: TradeLogRequest):
    append_trade(req.model_dump(exclude_none=True))
    return {"ok": True}


@app.get("/api/trades")
def get_trades():
    return list_trades()


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

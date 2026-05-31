#!/usr/bin/env bash
# Convenience launcher — cd's into nifty-ai/, activates venv, starts the server.
set -e
cd "$(dirname "$0")/nifty-ai"
source .venv/bin/activate
exec uvicorn app.main:app --reload --port 8000

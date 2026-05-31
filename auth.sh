#!/usr/bin/env bash
# Convenience: run the daily Kite OAuth flow.
set -e
cd "$(dirname "$0")/nifty-ai"
source .venv/bin/activate
exec python auth.py

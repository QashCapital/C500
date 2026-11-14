# QUINT CAPITAL CRASH 500 INTELLIGENCE V1

A standalone Deriv Crash 500 market-data collector and shadow-research foundation.
It does **not** place trades, buy contracts, sell contracts, or access account balances.

## What V1 does
- Connects to Deriv's public market-data WebSocket (no account token required).
- Resolves the exact Crash 500 symbol dynamically through `active_symbols`.
- Requests a configurable historical tick seed.
- Subscribes to live ticks.
- Stores history and live ticks in SQLite on the Railway persistent volume.
- Builds M1, M5, M15 and H1 OHLC candles from ticks.
- Flags unusually large one-tick downside moves as **spike candidates** using a rolling baseline.
- Exposes JSON endpoints and a small live dashboard.

Spike candidates are descriptive statistical flags, not confirmed labels, trade signals, or predictions.
The detector requires a minimum warm-up sample and its parameters must be calibrated against actual stored data.

## Railway deployment
1. Create a **new** Railway project/service from this folder or its GitHub repository.
2. Attach a persistent volume to the service at `/app/data`.
3. Deploy using the included Dockerfile (or Procfile).
4. Set these optional variables if desired:
   - `DATA_DIR=/app/data/quint_crash500_lab`
   - `DERIV_SYMBOL_NAME=Crash 500 Index`
   - `HISTORY_TICK_COUNT=5000`
   - `RECONNECT_SECONDS=5`
   - `SPIKE_ROLLING_WINDOW=500`
   - `SPIKE_MULTIPLIER=8.0`
   - `MIN_SPIKE_PIPS=10`
5. Open the generated Railway domain.

Do not attach this service to the XAUUSD deployment or reuse its database directory.
Do not set any trading token; public market data is sufficient.

## Endpoints
- `/health` — health check
- `/api/status` — connection, symbol, storage and collector state
- `/api/ticks?limit=100`
- `/api/spikes?limit=50`
- `/api/candles/60` — M1
- `/api/candles/300` — M5
- `/api/candles/900` — M15
- `/api/candles/3600` — H1

## Data layout
`$DATA_DIR/crash500_research.sqlite3`

Tables: `ticks`, `candles`, `spike_events`, `service_state`.
SQLite WAL mode and a busy timeout are enabled. Data is append-oriented; no startup reset or automatic deletion is performed.

## Important research controls
- Do not treat 500 ticks as a countdown to the next spike.
- Do not infer profitability from spike frequency or a small sample.
- Keep all candidate strategies in paper/shadow mode until walk-forward testing, cost modelling, and drawdown analysis are complete.
- Confirm symbol resolution, tick continuity, and storage persistence in Railway logs before interpreting research results.

## Local run
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8000
```

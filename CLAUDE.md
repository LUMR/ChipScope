# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChipScope is a Chinese A-share stock price and chip distribution analysis system (A股股价与筹码分布分析系统). It collects K-line data, calculates chip distribution snapshots using a triangle-distribution + decay algorithm, and provides a web UI with candlestick charts, chip flame charts, pattern recognition, and historical replay.

## Commands

### Backend (Python 3.12, FastAPI)

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run tests (requires PostgreSQL running on localhost:5433)
pytest                          # all tests
pytest tests/test_chip_engine.py -v   # single file
pytest -k "test_triangle" -v   # single test by name

# Start API server (port 8001 expected by frontend proxy)
uvicorn app.main:app --reload --port 8001

# Start scheduler (realtime quotes every 3s, daily holders/flow at 16:00 CST)
python -m app.scheduler

# Database migrations
alembic upgrade head            # apply all migrations
alembic revision --autogenerate -m "description"  # create new migration

# Smoke tests / demo data
python scripts/smoke_ingest.py  # end-to-end EastMoney ingest
python scripts/smoke_chip.py    # chip engine with synthetic data
python scripts/seed_demo.py     # seed 600519 (Moutai) demo data
```

### Frontend (React 19 + TypeScript + Vite)

```bash
cd frontend

npm install
npm run dev       # dev server on port 5173, proxies /api and /ws to localhost:8001
npm run build     # tsc -b && vite build
npm run lint      # eslint
npx vitest        # run tests
```

### Infrastructure

```bash
docker compose up -d   # starts PostgreSQL (port 5433) + Redis (port 6380)
```

The backend expects PostgreSQL on port 5432 (use `CHIPSCOPE_DATABASE_URL` env var to override). The docker-compose maps host 5433→container 5432, so either set the env var or adjust the port mapping.

## Architecture

```
Frontend (React SPA, Vite dev proxy)
    │
    ├── /api/*  → FastAPI backend (port 8001)
    │     ├── /api/stocks          — stock list, search, K-line, holders, flow
    │     ├── /api/stocks/{code}/chips — chip distribution (latest + history)
    │     └── /api/stocks/{code}/pattern — pattern recognition
    │
    └── /ws/*   → WebSocket (realtime quotes, per-stock fan-out)
          │
          └── ConnectionManager → Redis cache (10s TTL)
```

### Data Flow

1. **Collection**: `collector/eastmoney.py` (HTTP, shareholders + money flow) and `collector/tdx_client.py` (TCP binary via mootdx, K-lines + realtime quotes) fetch raw data.
2. **Ingest**: `services/ingest.py` upserts into PostgreSQL with `ON CONFLICT DO UPDATE` (idempotent).
3. **Chip Engine** (pure NumPy, no I/O):
   - `chip_engine.py`: 400 price bins → triangle distribution (peak at VWAP) → decay step (`min(turnover × decay_coeff/100, 0.95)`)
   - `chip_metrics.py`: profit ratio, average cost, 90% concentration, peak price
   - `chip_pattern.py`: single-peak dense, divergence, high/low single-peak, upward/downward shift
4. **Scheduling**: `scheduler.py` — APScheduler with realtime loop (3s) and daily collection (16:00 CST).
5. **Frontend**: Single page `StockDetail` with ECharts candlestick, chip flame chart (horizontal bars), date slider for historical replay, and metric panel.

### Key Design Decisions

- **All timestamps are UTC** (`TIMESTAMPTZ`). Trading dates normalized to 15:30 Beijing time via `utils/time.py:trading_day_ts()`.
- **mootdx is synchronous TCP** — wrapped with `ThreadPoolExecutor` in `TdxClient` to avoid blocking the async event loop.
- **EastMoneyClient has built-in throttling** (`eastmoney_min_interval`, default 0.5s) to avoid IP bans.
- **Tests use real PostgreSQL** (not SQLite). The `conftest.py` fixture `TRUNCATE`s all tables before/after each test. Tests mock HTTP (respx) and TCP (fake DataFrames) but not the database.
- **Chip distribution stored as JSONB** (`{"15.00": 0.08, ...}`) with GIN index. 400 bins per snapshot.

### Module Map

| Path | Responsibility |
|---|---|
| `backend/app/config.py` | pydantic-settings; env prefix `CHIPSCOPE_`; reads `backend/.env` |
| `backend/app/database.py` | async SQLAlchemy engine + session factory |
| `backend/app/models/` | ORM models (stock, kline, chip, holder, flow) |
| `backend/app/schemas/` | Pydantic response models |
| `backend/app/api/` | FastAPI routers (stocks, chips, websocket) |
| `backend/app/services/collector/` | Data source clients (eastmoney HTTP, tdx TCP) |
| `backend/app/services/chip_*.py` | Chip engine (pure functions) |
| `backend/app/services/ingest.py` | DB upsert logic |
| `backend/app/services/realtime.py` | Redis cache + WebSocket fan-out |
| `backend/app/utils/time.py` | Trading day timestamp normalization |
| `frontend/src/api/` | Typed fetch wrapper + endpoint calls |
| `frontend/src/components/` | KLineChart, ChipFlame, MetricPanel, DateSlider, Header, Watchlist |
| `frontend/src/hooks/useStockData.ts` | Aggregated data fetching (kline + pattern) |
| `frontend/src/types/domain.ts` | Shared TypeScript types |

## Environment Variables

All prefixed with `CHIPSCOPE_`:

| Variable | Default | Description |
|---|---|---|
| `CHIPSCOPE_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/chipscope` | Async PostgreSQL connection string |
| `CHIPSCOPE_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `CHIPSCOPE_EASTMONEY_MIN_INTERVAL` | `0.5` | Throttle between EastMoney HTTP calls (seconds) |
| `CHIPSCOPE_WATCHLIST` | `600519` | Comma-separated stock codes for realtime monitoring |

## Conventions

- Python: all async. Use `async def` / `await` everywhere. Sync libraries (mootdx) must be wrapped with `run_in_executor`.
- Upserts: always use PostgreSQL `ON CONFLICT DO UPDATE` pattern (see `ingest.py`).
- Chip engine functions are pure NumPy — no side effects, no I/O, no database access. Keep them that way.
- Frontend API calls go through `api/client.ts:apiGet<T>()` which prepends `/api` and handles errors.
- The `secucode` format is `{code}.{market}` (e.g., `600519.SH`, `000001.SZ`). The `secid` format is `{market_int}.{code}` (e.g., `1.600519`).

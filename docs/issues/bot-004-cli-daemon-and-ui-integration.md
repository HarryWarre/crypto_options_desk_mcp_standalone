# BOT-004 — CLI Daemon Runner & Web Dashboard Integration

**Status:** backlog  
**Branch:** `feat/options-neutral-spread-paper-bot`  
**Target:** `main`

## 1. Problem & Context
The automated options bot needs to run as a reliable, long-running daemon in paper or live mode, with full event logging, signal handling, and status visibility via the existing Desk FastAPI app and web terminal.

## 2. Target Features
- **CLI Runner:**
  ```bash
  python -m options_lib.strategy.iron_condor_bot --asset BTC --mode paper --capital 10000 --target-delta 0.15
  ```
- **Signal Handling:** Graceful shutdown on SIGINT/SIGTERM, saving paper state to disk without losing in-flight trades.
- **REST Endpoints:**
  - `GET /api/v1/bot/status`: Returns current bot state, active positions, equity, margin usage.
  - `GET /api/v1/bot/trades`: Returns historical paper trade log.
  - `POST /api/v1/bot/control`: Start, pause, or emergency close positions.

## 3. Sub-tasks
- [ ] **BOT-004A**: CLI entry point with argument parsing, environment variable overrides, and structured logging.
- [ ] **BOT-004B**: REST API integration in `src/options_app/api.py`.
- [ ] **BOT-004C**: Real-time terminal / UI stream integration for monitoring paper trades.


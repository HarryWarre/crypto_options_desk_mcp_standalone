# DESK-001 — Backend Bot Manager Service & WebSocket Stream

**Status:** in-progress  
**Branch:** `feat/desk-bot-manager-and-stream`  
**Target:** `main`

## 1. Problem & Context
The automated options bot (`IronCondorBot`) currently runs as a standalone script from terminal or CLI daemon. To integrate it directly into the web-based Live Desk workspace, we need:
1. An in-process service (`BotManager`) managing bot lifecycle (Start, Stop, Run single cycle, Emergency Close All, Reset Account).
2. A REST control endpoint (`POST /api/v1/bot/control`) to trigger operations from the frontend.
3. A real-time WebSocket endpoint (`WS /api/v1/bot/stream`) to broadcast live portfolio state, mark-to-market PnL, margin utilization, and execution events to connected browser sessions without polling.

## 2. Architecture

```text
Browser / Live Desk UI (WebSocket client)
         ▲
         │ JSON stream (state, fills, margin, PnL)
         ▼
[WS /api/v1/bot/stream] ◄──┐
                           │ (Broadcasts events)
[POST /api/v1/bot/control] ┼──► BotManager (Asyncio background worker)
                           │         │
                           │         ▼
                           │    IronCondorBot
                           │         │
                           │         ▼
                           └─── PaperBroker (PaperAccount & SQLite)
```

## 3. Acceptance Criteria
- [ ] `BotManager` class implemented in `src/options_app/bot_manager.py` with singleton accessor `get_bot_manager()`.
- [ ] `POST /api/v1/bot/control` handles `start`, `stop`, `cycle`, `close_all`, and `reset` actions with structured responses.
- [ ] `WS /api/v1/bot/stream` accepts WebSocket connections, sends an initial snapshot immediately upon connect, and streams subsequent state changes.
- [ ] Unit tests in `tests/test_bot_manager.py` verify control actions, background task execution, and WebSocket broadcast.

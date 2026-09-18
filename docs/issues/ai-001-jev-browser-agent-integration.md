# AI-001 — Jev Browser Agent Integration & Project Automation

Status: done  
Branch: `main`  
Target: `main`  

## Problem

When developing and maintaining the options desk web UI, live scanner dashboard, and strategy builder, AI agents and automated workflows require fast browser access to:
1. Inspect live rendered DOM, HTML, and accessibility trees (e.g., verifying option chain tables, strike ladders, WebSocket streaming indicators).
2. Execute end-to-end user journeys without manual browser clicks or writing heavy test scaffolding for exploratory tasks.
3. Rapidly audit visual layouts, take screenshots, and detect console/network errors during UI changes.

Previously, there was no dedicated fast browser agent CLI or MCP tool configured in the project environment.

## Outcome

Configured Jev Browser (`@jkudish/jev-browser`) across the system and project:
- Installed `@jkudish/jev-browser` globally via npm with `jev` and `jev-browser` binary aliases.
- Verified Playwright Chromium headless engine and browser dependencies.
- Added `jev-browser` to MCP server configurations (`~/.gemini/config/mcp_config.json`), providing the `jev_navigate` MCP tool to AI assistants.
- Added npm automation scripts (`browser:agent` and `jev`) to `crypto_options_desk_mcp/package.json`.
- Added `.env.example` documenting required environment variables (`TYPESAFE_API_KEY`, `OPENROUTER_API_KEY`, `JEV_BROWSER_HEADED`, etc.).
- Created agent instructions in `.agents/rules/jev-browser.md` and updated `AGENTS.md` for seamless tool discovery by AI assistants.

## Acceptance criteria

- [x] Global CLI commands `jev` and `jev-browser` are installed and operational.
- [x] Playwright Chromium engine launches successfully in headless mode.
- [x] MCP server integration configured in `~/.gemini/config/mcp_config.json` with stdio protocol support (`jev_navigate`).
- [x] Project `package.json` contains `browser:agent` and `jev` runner scripts.
- [x] `.env.example` template documents all configuration options and keys.
- [x] Agent rules in `.agents/rules/jev-browser.md` and `AGENTS.md` describe usage patterns and flags.

## Usage

### CLI
```bash
jev run "Verify Options Chain loads BTC strikes" http://localhost:8000 --screenshot .screenshot.jpg --format markdown
```

### NPM Script
```bash
npm --prefix crypto_options_desk_mcp run browser:agent -- "Open Scanner and check stream status" http://localhost:8000
```

### MCP Tool
Call `jev_navigate` with parameters:
- `task`: Natural language goal
- `start_url`: `http://localhost:8000` (or target web URL)
- `format`: `markdown` | `text` | `html` | `aria`
- `screenshot`: `final` | `none`

# AI-002 — Graphify Knowledge Graph & Architecture Indexing

Status: in-progress  
Branch: `feat/graphify-knowledge-graph`  
Target: `main`  

## Problem

As the options trading desk, scanner engine, market feeds, and strategy modules have expanded (over 140 code files, 3,500+ symbols, and 9,200+ dependencies across `options_lib`, `bybit_api`, `indicators_lib`, `options_app`, `strategy_head`, etc.):
1. AI agents and developers frequently spend thousands of prompt tokens grepping and traversing files repeatedly to understand call chains and downstream impact.
2. Answering architecture or dependency questions from raw file reads is slow and risks missing distant dependencies (e.g., how changes in `BybitPublicClient` affect `opportunity_scanner.py` and `live_desk.py`).
3. No persistent visual graph or structured knowledge representation existed to quickly explore modules, god nodes, and call flows.

## Outcome

Integrated **Graphify** (`@Graphify-Labs/graphify`) and indexed the entire project knowledge graph:
- Installed `graphifyy` CLI and `graphify-mcp` server using `uv tool` with Python 3.13.
- Extracted and clustered the full codebase:
  - **3,527 nodes** (classes, functions, files, modules)
  - **9,280 edges** (calls, imports, inheritances)
  - **108 communities** (detected clusters/subsystems)
- Exported interactive visualizations and reports in `graphify-out/`:
  - `graph.html`: Interactive 2D/3D force-directed network graph.
  - `GRAPH_TREE.html`: D3 collapsible tree view of the module hierarchy.
  - `Flowsurface-callflow.html`: Mermaid call-flow diagrams and interaction tables.
  - `wiki/`: 118 Wikipedia-style markdown articles for fast agent navigation.
  - `GRAPH_REPORT.md`: Comprehensive report identifying god nodes and community hubs.
- Configured Antigravity rules and MCP integration:
  - Added `graphify-mcp` to `~/.gemini/config/mcp_config.json`.
  - Configured project rules in `.agents/rules/graphify.md` and `AGENTS.md`.
  - Created isolated git worktree at `.worktrees/graphify-knowledge-graph`.

## Acceptance Criteria

- [x] CLI commands `graphify` and `graphify-mcp` installed and accessible in PATH.
- [x] Full codebase AST extraction and community clustering completed into `graphify-out/graph.json`.
- [x] Interactive web visualizations generated (`graph.html`, `GRAPH_TREE.html`, `Flowsurface-callflow.html`).
- [x] Wiki documentation generated in `graphify-out/wiki/`.
- [x] MCP server registered in `~/.gemini/config/mcp_config.json`.
- [x] Agent rules configured in `.agents/rules/graphify.md` and `AGENTS.md`.
- [x] Dedicated worktree `.worktrees/graphify-knowledge-graph` initialized on branch `feat/graphify-knowledge-graph`.

## Usage

### Querying the Knowledge Graph
```bash
# BFS traversal for broad context
graphify query "How does opportunity_scanner calculate payoff and EV?"

# Find relationship / shortest path between two components
graphify path "opportunity_scanner.py" "BybitPublicClient"

# Explain a specific component
graphify explain "VolatilityAnalyzer"

# Keep graph updated after modifying code
graphify update .
```

### Viewing Visualizations in Browser
- Interactive Force Graph: `open graphify-out/graph.html`
- Architecture Call-Flow: `open graphify-out/Flowsurface-callflow.html`
- Collapsible Tree: `open graphify-out/GRAPH_TREE.html`

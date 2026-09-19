# BOT-005: Scalable Deribit Options Data Pipeline & Iron Condor Backtest Optimization

**Status:** merged  
**Branch:** `feat/bot-005-deribit-parquet-backtest`  
**Target:** `main`

## 1. Problem & Context
The automated options bot (`IronCondorBot`) needs rigorous historical backtesting to confirm positive expectancy and optimal configuration before live execution.
Raw crypto options orderbook / tick data is prohibitive in size (tens of gigabytes per ticker per year), causing high RAM and disk consumption on standard workstations.

## 2. Architecture & Solution
1. **15m/1h Snapshot Downsampling**: Swing trading (Iron Condor DTE 7-14) only requires discrete snapshots of mark prices, IV, and underlying index, bypassing tick-level clutter.
2. **Columnar Parquet Compression**: Store data using Apache Parquet via `pyarrow` (already in `.venv`), achieving 85-90% compression compared to raw JSON/JSONL.
3. **Google Drive Integration**: Provide an `rclone` sync script to treat Google Drive (5TB) as cold storage.
4. **Vectorized/Chunked Replay Engine**: Backtest Iron Condors through historical snapshots with TP (50%), SL (1.5x-2x), and roll logic.
5. **Parameter Optimization**: Grid search across delta levels and IV-RV thresholds to output the highest Sharpe & win-rate profile.

## 3. Acceptance Criteria
- [ ] `src/options_lib/data/deribit_downloader.py`: Fetch & convert Deribit historical data into compressed Parquet files.
- [ ] `scripts/sync_gdrive.sh`: Utility script for syncing datasets to/from Google Drive via rclone.
- [ ] `src/options_lib/strategy/iron_condor_backtest.py`: Fast, low-memory backtesting engine implementing complete Iron Condor lifecycle.
- [ ] `tests/test_iron_condor_backtest.py`: Comprehensive unit tests for PnL calculation, TP/SL triggers, and metrics.
- [ ] `scripts/optimize_iron_condor.py`: Grid-search script evaluating parameters and generating summary statistics.
- [ ] All test suites (pytest, playwright) remain passing.


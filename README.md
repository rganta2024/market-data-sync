# Supabase Stock & Options Market Data System

This system houses the database schema, batch sync pipelines, and automated daily incremental update jobs for **223 major stocks & ETFs** and **10 key option underlyings** in Supabase.

---

## 1. Database Coverage in Supabase

### A. Stocks & ETFs (`stock_ohlc_daily` & `symbol_metadata`)
* **Total Tracked Symbols:** **223 symbols**
* **Total Stock OHLC Rows:** **32,611 rows** (150 trading days history)
* **Technical Indicators Included:**
  * Trend: `SMA(20, 50, 200)`, `EMA(9, 20, 50, 200)`
  * Momentum & Oscillators: `RSI(14)`, `MACD(12,26,9)`, `Stochastic(14,3)`, `ADX(14)`
  * Volatility: `Bollinger Bands(20,2)`, `ATR(14)`
  * Volume: `Volume SMA(20)`, `Volume Ratio`, `OBV`
  * Range: `52-week High/Low`, `% Distance from 52w High/Low`

### B. Options OHLC & Greeks (`option_ohlc_daily` & `option_contracts_metadata`)
* **Total Tracked Contracts:** **2,298 active option contracts**
* **Total Option Daily OHLC Rows:** **17,281 rows**
* **Core Underlyings:** `QQQ`, `SPY`, `SPXL`, `TQQQ`, `IWM`, `DIA`, `SOXL`, `NVDA`, `TSLA`, `AAPL`
* **Metrics Stored:** `open`, `high`, `low`, `close`, `volume`, `trade_count`, `vwap`, `bid`, `ask`, `mid_price`, `implied_volatility`, `delta`, `gamma`, `theta`, `vega`, `rho`, `underlying_close`, `moneyness_pct`, `days_to_exp`

---

## 2. Serverless Cloud Automation (Option 2: n8n Cloud $\rightarrow$ GitHub Actions)

```
┌─────────────────────────────────────────────────────────────┐
│                          n8n Cloud                          │
│                                                             │
│  ► Schedule Trigger (Mon-Fri 4:30 PM EST)                   │
│  ► Webhook Trigger (On-Demand / Antigravity MCP)            │
│  ► HTTP Request Node ──► POST GitHub /dispatches API        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (Cloud VM)                │
│                                                             │
│  ► Repository: .github/workflows/daily_market_sync.yml      │
│  ► Runs: sync_master_daily.py (Python 3.11)                 │
│  ► Execution time: ~25 seconds                              │
│  ► Upserts directly into Supabase Cloud PostgreSQL          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Supabase Cloud DB                      │
│                                                             │
│  ► stock_ohlc_daily                                         │
│  ► option_ohlc_daily                                        │
│  ► v_stock_latest_snapshot                                  │
│  ► v_option_latest_chain                                    │
└─────────────────────────────────────────────────────────────┘
```

### Quick Setup Steps for GitHub Actions & n8n Cloud:

#### Step 1: Push Repository to GitHub
Create a private GitHub repository (e.g. `market-data-sync`) with the files from this directory:
```bash
git init
git add .
git commit -m "Add stock & options sync pipelines"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

#### Step 2: Add GitHub Repository Secrets
In your GitHub repo, go to **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions** $\rightarrow$ **New repository secret**:
* `ALPACA_API_KEY`: Your Alpaca API Key ID
* `ALPACA_SECRET_KEY`: Your Alpaca Secret Key
* `HEDGE_DATABASE_URL`: Your Supabase connection string (`postgresql://postgres.xxx:pass@aws-0-us-west-2.pooler.supabase.com:5432/postgres`)

#### Step 3: Import Workflow into n8n Cloud
1. Open n8n Cloud $\rightarrow$ **Workflows** $\rightarrow$ **Add Workflow** $\rightarrow$ Click `...` $\rightarrow$ **Import from File**.
2. Select [n8n_github_actions_trigger_workflow.json](file:///C:/Users/ganta/OneDrive/ClaudeCode/Fidelity/OHLC_Data_Supabase/n8n_github_actions_trigger_workflow.json).
3. In the node **"Configure GitHub Credentials"**, fill in:
   * `GITHUB_OWNER`: Your GitHub username
   * `GITHUB_REPO`: Your repository name
   * `GITHUB_PAT`: A GitHub Personal Access Token (classic with `repo` scope or fine-grained with Actions write permission).
4. Activate the workflow.

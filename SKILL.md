---
name: fundamental-alpha
description: >-
  Generate alpha factor expressions from fundamental data (financial statements,
  valuation ratios, cash-flow derivatives, earnings forecasts,
  and ownership signals) using only PandaData (panda_data). Takes a research
  document, URL, or natural language query as input — or lets the model invent
  from a trading paradigm — and produces validated point-in-time alpha
  expressions backed by a formula contract. Use when an agent needs to generate
  alpha ideas from academic papers, market commentary, research notes, or its
  own invention in value, quality, growth, cash-flow, forecast, or ownership
  factor styles.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-fundamental-alpha
  repository_url: https://github.com/quantskills/skill-fundamental-alpha
  project_type: skill
  collection: factor-generation
  creator: davideliu
  creator_url: https://github.com/davideliu
  maintainer: davideliu
  maintainer_url: https://github.com/davideliu
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-fundamental-alpha
  repository_url: https://github.com/quantskills/skill-fundamental-alpha
  project_type: skill
  collection: factor-generation
  category: factor
  tags:
    - fundamental-data
    - financial-statements
    - alpha-generation
    - factor-discovery
    - point-in-time
    - value-investing
    - quality
    - pandadata
    - a-shares
    - ownership-signals
  platforms:
    - claude-code
    - codex
    - cursor
    - openclaw
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires:
    - panda_data>=0.1.0
  summary_zh: 基于基本面数据（PandaData）生成Alpha因子表达式，支持从研报/自然语言输入中提取估值、质量、成长、现金流、预期与股东信号，并通过公式合约与PIT面板验证。
  summary_en: Generate alpha factor expressions from fundamental data (PandaData). Accepts a document, URL, natural language query, or model invention and returns validated point-in-time factors.
---
---

# Fundamental Alpha

Use this skill to generate **alpha factor expressions from fundamental data**.
Unlike OHLCV-only factor generation, this skill exploits financial statements,
valuation ratios, cash-flow derivatives, earnings forecasts,
and ownership signals — with rigorous **point-in-time (PIT)** discipline so no
signal peeks into the future.

## Input Modes

The skill accepts **four types of input**. You can mix them freely:

| Mode | Example | How it works |
|:---|:---|:---|
| **📄 Document** | `--doc paper.pdf` | Extracts text from a research paper, then maps its concepts (e.g. "accruals anomaly", "quality minus junk") to the fundamental field catalog. |
| **🔗 URL / Link** | `--doc https://arxiv.org/...` | Fetches the page content, then generates alphas from the text. Works with any accessible URL containing research text. |
| **💬 Natural Language** | `--query "cheap stocks with improving cash flow"` | Maps free-text concepts to the field catalog. Keywords like "value", "quality", "accruals", "buyback" are auto-mapped. |
| **💡 Model Invention** | `--query "invent 5 quality alphas using profitability and safety"` | No external document needed. The model generates novel alphas from a trading paradigm description. |

**All four modes** produce the same output: validated alpha expressions (with
expanded formulas), field-level derivations, and backtest-ready factor CSVs.

This skill requires **PandaData** (`panda_data`) as its only data source. Set
credentials in `.env`.

It provides:

- **Fundamental data fetcher** — pulls quarterly statements
  (`get_financial_ex`, `is_latest=False` for restatement history),
  precomputed factors (`get_factor`: `ratio_*`, `cfd_*`, `fin_*`, `*_mrq_n`),
  daily prices (`get_market_data`), earnings forecasts, and ownership signals
  (holder count, buybacks).
- **Point-in-time panel builder** — produces `fundamentals.csv`, a wide
  `date × symbol` panel in which every value reflects only information known
  at that date (statements lagged by filing date, announcements lagged by
  announcement date, precomputed factors PIT by construction).
- **80-field fundamental catalog** across 7 families: valuation, cash flow,
  capital structure, statements (TTM/YoY/margins/accruals), MRQ latest-report
  values, forecast, ownership. Agents may also define **custom
  features** (`new_features`) over existing fields and operators.
- **Formula contract** — `references/fundamental_ops.md` defines every allowed
  field and function. Operators are loaded from `references/operators.json`
  at runtime; new operators (`new_operator`) can be proposed by the agent.
- **Validator** — evaluates each expression against the real PIT panel to
  catch errors, NaN ratios, look-ahead violations, and instability.
- **Auto-correction loop** — failed alphas get categorized diagnostics and
  correction hints; the agent retries up to 5 times.
- **Backtest export** — validation automatically materializes
  `backtest_factors/<alpha>.csv` (`date,ticker,value`) files compatible with
  `skill-factor-backtest`.
- **Run README** — each run directory gets a `README.md` auto-generated after
  validation, documenting all alphas, fields used, expanded formulas, and
  backtest integration instructions.

## Creator, Maintainer, And Scope

- Creator: `davideliu` (`https://github.com/davideliu`).
- Maintainer: `davideliu` for the QuantSkills community.
- Repository: `https://github.com/quantskills/skill-fundamental-alpha`.
- License: GNU General Public License v3.0 only (`GPL-3.0-only`).
- Scope: alpha factor ideation from fundamental data. The skill is not
  official investment advice, a certified data product, or a guarantee of
  trading performance.

## Core Workflow

```
┌─────────────────────────────────┐
│  Input: Document or NL query     │
│  e.g. "Accruals anomaly" or     │
│  "cheap stocks with high OCF"   │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Step 1: Fetch fundamental data │
│  statements + factors + prices  │
│  + forecast/ownership          │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Step 2: Build PIT panel        │
│  lag filings & announcements,   │
│  compute TTM/YoY/ratios         │
│  → fundamentals.csv             │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Step 3: Generate N alphas      │
│  from document/query using LLM  │
│  following fundamental_ops.md   │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Step 4: Validate expressions   │
│  against real PIT panel         │
│  → NaN, look-ahead, stability   │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Step 5: Auto-correct failures  │
│  Up to 5 retries with diagnostics│
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  Output: validated alpha JSON   │
│  + factor CSVs for backtesting  │
└─────────────────────────────────┘
```

## Quick Start

### 1. Set up credentials

Create a `.env` file with your PandaData credentials:

```bash
# .env
```

```
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
```

### 2. Run the pipeline (pick your input mode)

```bash
# Shared: fetch data + build PIT panel (uses config.json defaults)
python scripts/fetch_fundamental_data.py --run-name myrun
python scripts/build_pit_fundamentals.py --run-name myrun

# 📄 Mode A: From a research document (PDF, txt)
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc path/to/paper.pdf --n 5

# 🔗 Mode B: From a URL
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc "https://arxiv.org/abs/..." --n 5

# 💬 Mode C: From a natural language query
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "cheap stocks with improving cash flow" --n 5

# 💡 Mode D: Let the model invent from a paradigm
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "invent 5 quality alphas using profitability and safety" --n 5

# Fill in the alphas in output/<run>/alphas.json (LLM agent step)

# Validate (auto-generates backtest_factors/ + README.md)
python scripts/validate_fundamental_alphas.py --run-name myrun

# Optional: print correction context for failed alphas
python scripts/validate_fundamental_alphas.py --run-name myrun --correction-context
```

### 3. Run output structure

After successful validation, each run directory contains:

```
output/<run>/
├── README.md                    # Auto-generated run documentation
├── statements.csv               # Raw quarterly statements (PIT history)
├── factors.csv                  # Precomputed ratio/cfd/fin/mrq factors
├── market_data.csv              # Daily prices
├── forecast.csv                 # Earnings forecasts
├── holder_count.csv / repurchase.csv              # Ownership signals
├── fundamentals.csv             # Point-in-time panel (date,symbol,field)
├── fundamental_definitions.json # Field catalog with formulas + PIT rules
├── data_report.json             # Panel coverage statistics
├── alphas.json                  # Alpha expressions (prompt + filled)
├── validated_alphas.json        # Validated alphas with expanded formulas
└── backtest_factors/            # Daily factor CSVs for backtesting
    ├── <alpha1>.csv             # date,ticker,value
    ├── <alpha2>.csv
    └── ...

# Backtest any factor:
python ../skill-factor-backtest/scripts/run_factor_backtest.py \
  --input-file output/<run>/backtest_factors/<alpha>.csv \
  --factor-column <alpha_name> \
  --data-root <market_data_dir> --timespan YYYYMMDD YYYYMMDD
```

## Fundamental Field Families

The PIT panel exposes 80 fields across 7 families:

| Family | # Fields | Examples |
|:---|:---:|:---|
| **Valuation** | 17 | `ep_ttm`, `bm_lf`, `sp_ttm`, `cfp_ttm`, `ev_ebitda_ttm`, `peg_ttm`, `div_yield_ttm`, `mktcap` |
| **Cash Flow** | 13 | `fcff_ttm`, `fcfe_ttm`, `ocf_to_debt_ttm`, `surplus_cash_multi_ttm`, `ebitda_to_int_ttm` |
| **Capital** | 7 | `int_debt_lf`, `non_int_cur_liab_lf`, `undistr_profit_per_share_lf` |
| **Statement (derived)** | 23 | `revenue_ttm`, `ni_ttm`, `gross_margin`, `roe_ttm`, `accruals_ttm`, `rev_yoy`, `ni_yoy` |
| **MRQ latest-report** | 10 | `ni_mrq1`, `rev_mrq4`, `ocf_mrq1`, `eq_mrq1`, `assets_mrq1`, `eps_mrq1` |
| **Forecast** | 6 | `fc_np_mid`, `fc_growth_mid`, `fc_width`, `fc_type_score`, `fc_revision` |
| **Ownership** | 4 | `holder_count`, `holder_change_yoy`, `buyback_value_ttm`, `buyback_percent` |

## Point-In-Time Discipline

This is the core design constraint of the skill:

- **Statements** (`get_financial_ex`): a quarter's value is only visible after
  its **filing date** + `pit_lag_days`. Restatement rows (`if_adjusted`)
  become visible only when actually published.
- **Precomputed factors** (`get_factor`): PIT by construction.
- **Forecasts / ownership**: joined by **announcement date** +
  `pit_lag_days`.
- **A-share cumulative convention**: quarterly income statement items are
  year-to-date cumulative within the fiscal year, so
  `TTM(x) = x(FY t−1) + x(YTD t) − x(YTD t−1)` (for Q4, `TTM = x(Q4)`).
- Expressions using `delay(x, n)`, `delta(x, n)`, `returns(x, n)` must use
  `n ≥ 1` — the validator rejects anything else.

## Document → Alpha Mapping

When processing a document or NL query, the LLM:

1. **Reads the contract** in `references/fundamental_ops.md` — all allowed
   fields and functions.
2. **Maps document concepts** to the fundamental catalog:
   - "accruals anomaly" → `accruals_ttm`, `ocf_to_ni`
   - "quality minus junk" → `roe_ttm`, `gross_margin`, `debt_to_assets`
   - "value premium" → `ep_ttm`, `bm_lf`, `cfp_ttm`
   - "cash flow predictability" → `surplus_cash_multi_ttm`, `ocf_to_assets`
   - "smart money / chip concentration" → `holder_change_yoy`
   - "buyback signaling" → `buyback_value_ttm`, `buyback_percent`
3. **Generates expressions** using only the allowed fields/functions.
4. **Attributes sources** — each alpha cites the academic paper or document
   passage that inspired it.

## Parameters (config.json)

Scripts read `config.json` for defaults; CLI arguments override. Change values
in config.json to set your preferred defaults.

| Parameter | Default | CLI Flag | Description |
|:---|:---|:---|:---|
| `universe` | `"000300"` | `--universe` | CSI 300, CSI 500, CSI 1000, SSE 50. |
| `start_date` | `"20240101"` | `--start-date` | Daily data start (YYYYMMDD). |
| `end_date` | `"20250801"` | `--end-date` | Daily data end (YYYYMMDD). |
| `start_quarter` | `"2021q1"` | `--start-quarter` | Statement history start (TTM/YoY need ≥ 9 quarters). |
| `end_quarter` | `"2025q2"` | `--end-quarter` | Statement history end. |
| `pit_lag_days` | `1` | — | Days after a filing/announcement before it counts as known. |
| `max_alphas` | `5` | `--n` | Default number of alphas per run. |
| `nan_threshold` | `0.1` | `--nan-threshold` | Max NaN ratio before flagging. |
| `extreme_threshold` | `5.0` | `--extreme-threshold` | Max z-score before flagging instability. |

## Agent Platform Instructions

When an agent uses this skill, follow the workflow in
`agents/portable-loader.md` or the per-platform configs in `agents/`.

General pattern:
```
Read SKILL.md → Read references/fundamental_ops.md → Fetch fundamental data →
Build PIT panel → Read input document → Generate alpha JSON →
Validate → (correct) → Output
```

## Reference Files

- `references/fundamental_ops.md` — the field & function contract.
- `references/fundamental_definitions.json` — field catalog with formulas and PIT rules.
- `references/operators.json` — operator catalog (add new operators here).
- `references/agent-integration.md` — install + smoke tests per agent platform.

# Fundamental Alpha

Generate **alpha factor expressions from fundamental data** (PandaData). Builds
a **point-in-time correct** fundamental panel (80 fields across 7 signal
families) from financial statements, valuation ratios, cash-flow derivatives,
earnings forecasts, and ownership signals, and outputs
validated alpha expressions ready for daily backtesting. Agents can extend the
catalog via custom features (`new_features`) and custom operators
(`new_operator`). Input can be a document, a URL, a natural language query, or
a model-invented paradigm.

## Quick Start

```bash
# 1. Configure credentials in .env

# 2. Fetch fundamental data + build the PIT panel (config.json defaults)
python scripts/fetch_fundamental_data.py --run-name myrun
python scripts/build_pit_fundamentals.py --run-name myrun

# 3. Generate alphas — pick an input mode:
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc paper.pdf --n 5                    # document
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc "https://arxiv.org/abs/..." --n 5  # URL
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "cheap stocks with improving cash flow" --n 5   # natural language
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "invent 5 quality alphas" --n 5  # model invention

# 4. Fill in output/<run>/alphas.json (LLM agent step)

# 5. Validate (auto-generates backtest_factors/ + README.md)
python scripts/validate_fundamental_alphas.py --run-name myrun
```

## Run Output

Each validated run produces:

```
output/<run>/
├── README.md                    # Auto-generated documentation
├── statements.csv               # Raw quarterly statements (restatement history)
├── factors.csv                  # Precomputed ratio/cfd/fin/mrq factors
├── market_data.csv              # Daily prices
├── forecast.csv                 # Earnings forecasts
├── holder_count.csv / repurchase.csv     # Ownership signals
├── fundamentals.csv             # PIT panel (date,symbol,field)
├── fundamental_definitions.json # Field catalog with formulas + PIT rules
├── data_report.json             # Panel coverage statistics
├── alphas.json                  # Alpha expressions
├── validated_alphas.json        # Validated alphas + expanded formulas
└── backtest_factors/            # Daily factor CSVs (backtest-ready)
    ├── <alpha1>.csv             # date,ticker,value
    └── <alpha2>.csv
```

## Backtest Integration

Backtest factors are generated **automatically** during validation:

```bash
python ../skill-factor-backtest/scripts/run_factor_backtest.py \
  --input-file output/<run>/backtest_factors/<alpha>.csv \
  --factor-column <alpha_name> \
  --data-root <market_data_dir> --timespan YYYYMMDD YYYYMMDD
```

## Requirements

- Python 3.10+
- `panda_data>=0.1.0`
- Valid PandaData credentials in `.env`

## Parameters (config.json)

| Parameter | Default | Description |
|---|---|---|
| `universe` | `000300` | CSI 300, CSI 500, CSI 1000, SSE 50 |
| `start_date` / `end_date` | `20240101` / `20250801` | Daily data range |
| `start_quarter` / `end_quarter` | `2021q1` / `2025q2` | Statement history (TTM/YoY need ≥ 9 quarters) |
| `pit_lag_days` | `1` | Days after a filing/announcement before data counts as known |
| `max_alphas` | `5` | Default number of alphas per run |

## Disclaimer

This repository is a research-methodology reference only and does not
constitute investment advice.

## License

GPL-3.0-only

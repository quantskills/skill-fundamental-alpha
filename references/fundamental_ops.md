# Fundamental Alpha Expression — Field & Function Contract

This document defines the exact contract for fundamental alpha expressions.
All generated expressions **must** use only the fields and functions listed
below.

> **Complete field formulas and derivations are in [`fundamental_definitions.json`](fundamental_definitions.json).**
> Every run copies this file to the output directory as `fundamental_definitions.json`.
>
> **Custom features**: agents may define new features (beyond the catalog) as
> expressions over existing fields + operators, declared via `new_features` in
> the alpha JSON. See "Defining Custom Features" below.
>
> **Custom operators**: agents may propose new functions via `new_operator`,
> following [`operators.json`](operators.json).

## Data Source & Point-In-Time (PIT) Discipline

All data comes from **PandaData only** (`panda_data`). The panel
`fundamentals.csv` produced by `build_pit_fundamentals.py` is already
point-in-time correct:

- **Statements** (`get_financial_ex`): a quarter's value is only visible after
  its **filing date** + `pit_lag_days` (config). Values as known at time t come
  from the latest filing for that quarter with filing date ≤ t (restatements
  included only once published). `if_adjusted` rows are handled by this rule.
- **Precomputed factors** (`get_factor` `ratio_*`, `cfd_*`, `fin_*`, `*_mrq_n`):
  PIT by construction — each value is as of the query date.
- **Forecasts / ownership**: joined by their **announcement date** +
  `pit_lag_days`.

**Do NOT** write expressions that mix a field with `delay(x, 0)` or any
future-looking window — validation rejects `delay/delta/returns` with n < 1.

### A-Share Cumulative Convention

A-share quarterly income statement items are **year-to-date cumulative within
the fiscal year** (Q4 = full year). The panel follows this convention:

- `TTM(x) = x(FY t−1) + x(YTD t) − x(YTD t−1)`; for Q4, `TTM = x(Q4)`.
- `rev_yoy / ni_yoy / ocf_yoy` are YTD-vs-YTD comparisons.
- `*_mrq4` fields are the report 4 periods before the latest (≈ same quarter
  last year), so `x_mrq1 / x_mrq4 − 1` is a usable PIT YoY-style growth.

## Available Field Variables

Each field is a `date × symbol` column of `fundamentals.csv`. Grouped by signal
family. (See `fundamental_definitions.json` for exact formulas.)

### Valuation (17)

| Field | Description |
|:---|:---|
| `mktcap` | Total market cap (CNY) |
| `pe_ttm`, `pe_lyr` | Price-to-earnings (TTM / last fiscal year) |
| `pb_lf` | Price-to-book (latest filing) |
| `ep_ttm`, `ep_lyr` | Earnings yield |
| `bm_lf`, `bm_ttm` | Book-to-market |
| `sp_ttm`, `ps_ttm` | Sales yield / price-to-sales |
| `pcf_ocf_ttm`, `cfp_ttm` | Price-to-OCF / OCF yield |
| `div_yield_ttm` | Dividend yield (%) |
| `peg_ttm` | PEG ratio |
| `ev_ebitda_ttm`, `ev_ebitda_lyr`, `ev_no_cash_ebit_ttm` | EV multiples |

### Cashflow (13)

| Field | Description |
|:---|:---|
| `flow_per_share_ttm`, `ocf_per_share_ttm` | Cash flow per share |
| `fcff_ttm`, `fcfe_ttm`, `fcff_per_share_ttm`, `fcfe_per_share_ttm` | Free cash flow (absolute / per share) |
| `ocf_to_debt_ttm`, `ocf_to_net_debt_ttm`, `ocf_to_int_debt_ttm`, `ocf_to_cur_liab_ttm` | OCF coverage ratios |
| `surplus_cash_multi_ttm` | OCF / net profit (earnings quality) |
| `ebitda_to_int_ttm` | Interest coverage |
| `depr_amort_ttm` | Depreciation + amortization (CNY) |

### Capital (7)

| Field | Description |
|:---|:---|
| `int_debt_lf`, `int_debt_ttm` | Interest-bearing debt |
| `non_int_cur_liab_lf`, `non_int_ncl_lf` | Non-interest-bearing liabilities |
| `cap_reserve_per_share_lf`, `earned_reserve_per_share_lf`, `undistr_profit_per_share_lf` | Per-share reserves |

### Statement (23, derived PIT from `get_financial_ex`)

| Field | Description |
|:---|:---|
| `revenue_ttm`, `ni_ttm`, `ocf_ttm`, `eps_ttm` | Trailing-12-month fundamentals |
| `equity`, `total_assets`, `total_liab` | Latest balance sheet items |
| `gross_margin`, `op_margin`, `np_margin` | Margins, latest quarter |
| `roe_ttm`, `roa_ttm` | Returns (TTM) |
| `accruals_ttm` | Accruals / assets (Sloan 1996) |
| `ocf_to_assets`, `ocf_to_ni` | Cash realization of earnings |
| `debt_to_assets`, `current_ratio`, `cash_to_assets` | Leverage / liquidity |
| `rd_to_revenue`, `goodwill_to_assets` | R&D intensity, goodwill overhang |
| `rev_yoy`, `ni_yoy`, `ocf_yoy` | YoY growth (YTD convention) |

### MRQ — Latest-Report Values (10, PIT by construction)

| Field | Description |
|:---|:---|
| `ni_mrq1`, `rev_mrq1`, `ocf_mrq1`, `eq_mrq1`, `assets_mrq1`, `eps_mrq1` | Latest report value known at date t |
| `ni_mrq4`, `rev_mrq4`, `ocf_mrq4`, `eq_mrq4` | Value from the report 4 periods back |

### Forecast (6)

| Field | Description |
|:---|:---|
| `fc_np_mid`, `fc_eps_mid` | Forecast range midpoints (net profit / EPS) |
| `fc_growth_mid` | Forecast growth midpoint (%) |
| `fc_width` | Relative width of forecast range (narrow = confident) |
| `fc_type_score` | Forecast-type score (预增=3 … 预减=-3) |
| `fc_revision` | Consensus forecast YoY growth (%) |

### Ownership (4)

| Field | Description |
|:---|:---|
| `holder_count` | Number of shareholders |
| `holder_change_yoy` | YoY change in shareholder count |
| `buyback_value_ttm` | Buyback amount, trailing year (CNY) |
| `buyback_percent` | Latest buyback program size (% of capital) |

## Defining Custom Features

When a document or query requires a signal not in the catalog, the agent may
declare **new features** via a `new_features` list (top-level or per-alpha):

```json
{
  "name": "fcf_yield_mrq",
  "expression": "(ocf_mrq1 * 4) / max(mktcap, 1e-8)",
  "description": "Annualized latest-quarter OCF over market cap.",
  "formula": "4 × OCF_mrq1 / mktcap",
  "family": "custom"
}
```

Rules:

- Custom features are evaluated **in declaration order**; later features may
  reference earlier ones.
- They must use only catalog fields, operators, and previously-declared custom
  features.
- Do **not** reuse an existing catalog field name.
- The validator computes them at validation time and injects them into the
  field space, so alphas may use them as leaf variables.

## Available Functions

> **Operators are defined in [`operators.json`](operators.json).**
> To add a new operator, append an entry to that file with `name`, `signature`,
> `description`, `category`, and `numpy_impl`. The validator and generator
> auto-load from this file — no code changes needed.

### Cross-Sectional (per date)

| Function | Signature | Description |
|:---|:---|:---|
| `rank(x)` | `rank(x)` | Cross-sectional percentile rank [0,1] |
| `zscore(x)` | `zscore(x)` | Cross-sectional z-score |
| `scale(x, a=1)` | `scale(x, a=1)` | Rescale so \|Σx\| = a |
| `demean(x)` | `demean(x)` | x − mean(x) per date |
| `winsorize(x, n=3)` | `winsorize(x, n=3)` | Clip to mean ± n×std per date |
| `fillna_median(x)` | `fillna_median(x)` | NaN → cross-sectional median |

### Time-Series Rolling

| Function | Signature | Description |
|:---|:---|:---|
| `ts_rank(x, n)` | `ts_rank(x, n)` | Time-series percentile rank over n periods |
| `ts_zscore(x, n)` | `ts_zscore(x, n)` | Rolling z-score over n periods |
| `ts_mean(x, n)` | `ts_mean(x, n)` | Rolling mean over n periods |
| `ts_std(x, n)` | `ts_std(x, n)` | Rolling std over n periods |
| `ts_max(x, n)` | `ts_max(x, n)` | Rolling max over n periods |
| `ts_min(x, n)` | `ts_min(x, n)` | Rolling min over n periods |
| `ts_sum(x, n)` | `ts_sum(x, n)` | Rolling sum over n periods |
| `ts_argmax(x, n)` | `ts_argmax(x, n)` | Periods since rolling max |
| `ts_argmin(x, n)` | `ts_argmin(x, n)` | Periods since rolling min |
| `correlation(x, y, n)` | `correlation(x, y, n)` | Rolling Pearson correlation |
| `decay_linear(x, n)` | `decay_linear(x, n)` | Linear-decay weighted moving average |

### Lag / Difference

| Function | Signature | Description |
|:---|:---|:---|
| `delay(x, n)` | `delay(x, n)` | Lag by n periods (n ≥ 1) |
| `delta(x, n)` | `delta(x, n)` | x − delay(x, n) (n ≥ 1) |
| `returns(x, n=1)` | `returns(x, n=1)` | pct_change over n periods (n ≥ 1) |

### Element-Wise Math

| Function | Signature | Description |
|:---|:---|:---|
| `sign(x)` | `sign(x)` | Sign of x |
| `abs(x)` | `abs(x)` | Absolute value |
| `log(x)` | `log(x)` | Natural log (clamped to ≥ 1e-8) |
| `power(x, n)` | `power(x, n)` | x^n |
| `signed_power(x, n)` | `signed_power(x, n)` | sign(x) × \|x\|^n |
| `min(x, y)` | `min(x, y)` | Element-wise min |
| `max(x, y)` | `max(x, y)` | Element-wise max |
| `clip(x, lower, upper)` | `clip(x, lower, upper)` | Clip to [lower, upper] |

### Arithmetic

Standard `+`, `-`, `*`, `/` work between arrays and scalars.

## Example Expressions

```python
# Value: cheap on earnings and book
rank(ep_ttm) + rank(bm_lf)

# Earnings quality: high cash realization, low accruals (Sloan 1996)
-1 * rank(accruals_ttm)

# Quality-minus-junk composite
rank(roe_ttm) + rank(gross_margin) - rank(debt_to_assets)

# Growth at reasonable price (GARP)
rank(ni_yoy) + rank(rev_yoy) - rank(pe_ttm)

# Cash-flow yield with safety
rank(cfp_ttm) + rank(ocf_to_debt_ttm)

# Forecast revision (event-driven)
rank(fc_revision) + rank(fc_type_score)

# PIT YoY growth from MRQ series
(rev_mrq1 / max(rev_mrq4, 1e-8)) - 1

# Chip concentration: falling shareholder count
-1 * rank(holder_change_yoy)

# Buyback signal, smoothed
ts_mean(rank(buyback_percent), 60)

# Fundamental momentum: 60d change in profitability rank
delta(rank(roe_ttm), 60)

# Composite: value + quality + safety
rank(ep_ttm) + rank(surplus_cash_multi_ttm) - rank(debt_to_assets)
```

## Validation Rules

1. Every field name must match exactly one of the fields defined above, or a
   custom feature declared via `new_features`.
2. Every function name must match exactly (case-sensitive).
3. Argument counts and types must match the signatures above.
4. Only catalog fields and declared custom features may appear as leaf
   variables.
5. `delay(x, n)`, `delta(x, n)`, and `returns(x, n)` MUST use n ≥ 1
   (look-ahead prevention).
6. Never divide by something that could be zero — use `max(denom, 1e-8)`.
7. Never take `log(x)` without ensuring `x > 0` — use `log(max(x, 1e-8))`.
8. Prefer `rank()` and `zscore()` based expressions — they are naturally
   stable.
9. Fundamental panels are sparse — use `fillna_median(x)` where a field has
   low coverage, and beware denominators that are only defined for positive
   values (`peg_ttm`, `pe_ttm` are undefined for loss-makers).
10. Each alpha must include a `source` field citing the academic paper or
    document passage that inspired it (APA/MLA format).
11. Provide a `source_link` with DOI or arXiv URL where possible, or null.
12. Each alpha must include a `signal_family` from: `valuation`,
    `profitability`, `growth`, `cashflow`, `leverage`, `liquidity`,
    `forecast`, `ownership`, `custom`.

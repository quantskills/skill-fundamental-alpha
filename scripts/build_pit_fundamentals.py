#!/usr/bin/env python3
"""Build the point-in-time fundamental panel (fundamentals.csv).

Merges everything fetched by fetch_fundamental_data.py into a wide
`date,symbol,<field>` panel in which every value is only what was KNOWN at
that date:

  - precomputed factors (ratio_*/cfd_*/fin_*/_mrq_n): PIT by construction
  - quarterly statements: asof filing date + pit_lag_days
  - forecasts / ownership: asof announcement date + pit_lag_days

A-share convention: quarterly income statement items are year-to-date
cumulative within the fiscal year. TTM(x) = x(FY t-1) + x(YTD t) - x(YTD t-1);
for Q4, TTM(x) = x(Q4).

Usage:
    python build_pit_fundamentals.py --input-dir output/run_<ts>_<name>/ \
        --output output/run_<ts>_<name>/fundamentals.csv
    python build_pit_fundamentals.py --run-name myrun
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SKILL_ROOT = Path(__file__).resolve().parent.parent

# ═══════════════════════════════════════════════════════════════════════════════
# Renames: get_factor column → panel field
# ═══════════════════════════════════════════════════════════════════════════════

FACTOR_RENAME = {
    "ratio_pe_ttm": "pe_ttm", "ratio_pe_lyr": "pe_lyr", "ratio_pb_lf": "pb_lf",
    "ratio_ep_ttm": "ep_ttm", "ratio_ep_lyr": "ep_lyr", "ratio_bm_lf": "bm_lf",
    "ratio_bm_ttm": "bm_ttm", "ratio_sp_ttm": "sp_ttm", "ratio_ps_ttm": "ps_ttm",
    "ratio_pcf_ocf_ttm": "pcf_ocf_ttm", "ratio_cfp_ttm": "cfp_ttm",
    "ratio_div_yield_ttm": "div_yield_ttm", "ratio_peg_ttm": "peg_ttm",
    "ratio_ev_ebitda_ttm": "ev_ebitda_ttm", "ratio_ev_ebitda_lyr": "ev_ebitda_lyr",
    "ratio_ev_no_cash_ebit_ttm": "ev_no_cash_ebit_ttm",
    "ratio_market_cap_total": "mktcap",
    "cfd_flow_per_share_ttm": "flow_per_share_ttm",
    "cfd_ocf_per_share_ttm": "ocf_per_share_ttm",
    "cfd_fcff_ttm": "fcff_ttm", "cfd_fcfe_ttm": "fcfe_ttm",
    "cfd_fcff_per_share_ttm": "fcff_per_share_ttm",
    "cfd_fcfe_per_share_ttm": "fcfe_per_share_ttm",
    "cfd_ocf_to_debt_ttm": "ocf_to_debt_ttm",
    "cfd_ocf_to_net_debt_ttm": "ocf_to_net_debt_ttm",
    "cfd_ocf_to_int_debt_ttm": "ocf_to_int_debt_ttm",
    "cfd_ocf_to_cur_liab_ttm": "ocf_to_cur_liab_ttm",
    "cfd_surplus_cash_multi_ttm": "surplus_cash_multi_ttm",
    "cfd_ebitda_to_int_ttm": "ebitda_to_int_ttm",
    "cfd_depr_amort_ttm": "depr_amort_ttm",
    "fin_int_debt_lf": "int_debt_lf", "fin_int_debt_ttm": "int_debt_ttm",
    "fin_non_int_cur_liab_lf": "non_int_cur_liab_lf",
    "fin_non_int_ncl_lf": "non_int_ncl_lf",
    "fin_cap_reserve_per_share_lf": "cap_reserve_per_share_lf",
    "fin_earned_reserve_per_share_lf": "earned_reserve_per_share_lf",
    "fin_undistr_profit_per_share_lf": "undistr_profit_per_share_lf",
    "is_n_income_attr_p_mrq_1": "ni_mrq1", "is_n_income_attr_p_mrq_4": "ni_mrq4",
    "is_total_revenue_mrq_1": "rev_mrq1", "is_total_revenue_mrq_4": "rev_mrq4",
    "cfs_net_cash_operating_mrq_1": "ocf_mrq1",
    "cfs_net_cash_operating_mrq_4": "ocf_mrq4",
    "bs_total_hldr_eqy_exc_min_int_mrq_1": "eq_mrq1",
    "bs_total_hldr_eqy_exc_min_int_mrq_4": "eq_mrq4",
    "bs_total_assets_mrq_1": "assets_mrq1",
    "is_basic_eps_mrq_1": "eps_mrq1",
}

# Statement field → role in derived computations
S_TTM_FIELDS = ["is_total_revenue", "is_n_income_attr_p",
                "cfs_net_cash_operating", "is_basic_eps"]
S_LATEST_FIELDS = [
    "is_total_revenue", "is_oper_cost", "is_operate_profit",
    "is_n_income_attr_p", "bs_total_assets", "bs_total_liab",
    "bs_total_hldr_eqy_exc_min_int", "bs_money_cap", "bs_inventory",
    "is_rd_exp", "bs_goodwill", "bs_total_cur_assets", "bs_total_cur_liab",
]

_QUARTER_RE = re.compile(r"(\d{4})q([1-4])")

FC_TYPE_SCORE = {
    "预增": 3.0, "略增": 2.0, "续盈": 1.0, "扭亏": 2.5,
    "略减": -2.0, "预减": -3.0, "首亏": -3.0, "续亏": -3.0,
    "增亏": -3.0, "减亏": 1.5, "不确定": 0.0, "其他": 0.0,
}

def parse_qidx(quarter: str) -> int:
    """'2024q1' → 2024*4 + 0 (year-indexed quarter ordinal)."""
    m = _QUARTER_RE.search(str(quarter))
    if not m:
        raise ValueError(f"unexpected quarter label: {quarter!r}")
    year, qnum = int(m.group(1)), int(m.group(2))
    return year * 4 + (qnum - 1)


def _to_d64(dates: pd.Series) -> np.ndarray:
    return pd.to_datetime(dates, format="%Y%m%d", errors="coerce").values.astype("datetime64[D]")


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Numeric column with NaN fallback when the column is absent."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype=float)


def _asof_values(
    grid: pd.DataFrame,
    events: pd.DataFrame,
    event_date_col: str,
    value_col: str,
    lag_days: int,
) -> np.ndarray:
    """PIT asof join: per (date,symbol) in grid, latest event value with
    event_date <= date + lag_days. Returns array aligned to grid rows."""
    out = np.full(len(grid), np.nan)
    if events is None or events.empty:
        return out
    ev = events[[event_date_col, value_col, "symbol"]].copy()
    ev["d64"] = _to_d64(ev[event_date_col])
    ev = ev.dropna(subset=["d64"]).sort_values("d64")
    ev[value_col] = pd.to_numeric(ev[value_col], errors="coerce")

    grid_d64 = grid["date64"].values
    for sym, grp in ev.groupby("symbol"):
        mask = (grid["symbol"].values == sym)
        if not mask.any():
            continue
        t = grid_d64[mask]
        d = grp["d64"].values + np.timedelta64(lag_days, "D")
        v = grp[value_col].values
        idx = np.searchsorted(d, t, side="right") - 1
        valid = idx >= 0
        out[mask] = np.where(valid, v[np.clip(idx, 0, None)], np.nan)
    return out


def _rolling_sum_values(
    grid: pd.DataFrame,
    events: pd.DataFrame,
    event_date_col: str,
    value_col: str,
    window_days: int,
    lag_days: int,
) -> np.ndarray:
    """PIT trailing-window sum: sum of event values with
    date - window < event_date <= date + lag_days."""
    out = np.zeros(len(grid))
    if events is None or events.empty:
        return out
    ev = events[[event_date_col, value_col, "symbol"]].copy()
    ev["d64"] = _to_d64(ev[event_date_col])
    ev = ev.dropna(subset=["d64"]).sort_values("d64")
    ev[value_col] = pd.to_numeric(ev[value_col], errors="coerce").fillna(0.0)

    grid_d64 = grid["date64"].values
    for sym, grp in ev.groupby("symbol"):
        mask = (grid["symbol"].values == sym)
        if not mask.any():
            continue
        t = grid_d64[mask]
        d = grp["d64"].values + np.timedelta64(lag_days, "D")
        v = grp[value_col].values
        hi = np.searchsorted(d, t, side="right")
        lo = np.searchsorted(d, t - np.timedelta64(window_days, "D"), side="left")
        # prefix sums
        cum = np.concatenate([[0.0], np.cumsum(v)])
        out[mask] = np.where(hi > lo, cum[np.clip(hi, 0, None)] - cum[np.clip(lo, 0, None)], 0.0)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Statement PIT engine
# ═══════════════════════════════════════════════════════════════════════════════

def _build_statement_block(
    grid: pd.DataFrame, stmt: pd.DataFrame, lag_days: int
) -> pd.DataFrame:
    """Compute statement-derived PIT fields for every grid row."""
    cols = [
        "revenue_ttm", "ni_ttm", "ocf_ttm", "eps_ttm",
        "equity", "total_assets", "total_liab",
        "gross_margin", "op_margin", "np_margin",
        "roe_ttm", "roa_ttm", "accruals_ttm", "ocf_to_assets",
        "ocf_to_ni", "debt_to_assets", "current_ratio", "cash_to_assets",
        "rd_to_revenue", "goodwill_to_assets",
        "rev_yoy", "ni_yoy", "ocf_yoy",
    ]
    result = pd.DataFrame(
        np.nan, index=grid.index, columns=cols, dtype=float
    )

    if stmt is None or stmt.empty:
        return result

    st = stmt.copy()
    st = st.dropna(subset=["date"])
    st = st.drop_duplicates(subset=["symbol", "quarter", "date"], keep="last")
    try:
        st["qidx"] = st["quarter"].astype(str).map(parse_qidx)
    except ValueError as e:
        print(f"[WARN] {e}; statement PIT skipped.", file=sys.stderr)
        return result
    st["d64"] = _to_d64(st["date"].astype(str))
    st = st.dropna(subset=["d64"]).sort_values("d64")

    num_fields = set(S_TTM_FIELDS) | set(S_LATEST_FIELDS)
    for f in num_fields:
        if f in st.columns:
            st[f] = pd.to_numeric(st[f], errors="coerce")

    grid_d64 = grid["date64"].values

    for sym, grp in st.groupby("symbol"):
        sym = str(sym)
        mask = grid["symbol"].values == sym
        if not mask.any():
            continue
        t = grid_d64[mask]
        d = grp["d64"].values + np.timedelta64(lag_days, "D")

        # per-quarter arrays (sorted by date); positions within each quarter
        all_fields = sorted(set(S_TTM_FIELDS) | set(S_LATEST_FIELDS))
        q_arrays: dict[int, dict] = {}
        for qidx, qgrp in grp.groupby("qidx"):
            q_arrays[qidx] = {
                "d": qgrp["d64"].values,
                "vals": {f: qgrp[f].values for f in all_fields if f in qgrp.columns},
            }
        qidxs = sorted(q_arrays.keys())

        n = len(t)
        # known position per quarter asof t
        known: dict[int, np.ndarray] = {}
        for qidx in qidxs:
            qd = q_arrays[qidx]["d"]
            idx = np.searchsorted(qd, t, side="right") - 1
            known[qidx] = idx  # -1 means "not known yet"

        # latest quarter with a known filing (a quarter counts only if it has
        # at least one known row asof t)
        has_q = np.stack([known[q] >= 0 for q in qidxs], axis=1)  # (n, nq)
        latest_ok = np.full(n, -1, dtype=np.int64)
        for j, qidx in enumerate(reversed(qidxs)):
            k = len(qidxs) - 1 - j
            latest_ok = np.where(latest_ok == -1, np.where(has_q[:, k], qidx, -1), latest_ok)

        def val_at(field: str, qidx: int) -> np.ndarray:
            qa = q_arrays.get(qidx)
            if qa is None:
                return np.full(n, np.nan)
            arr = qa["vals"].get(field)
            if arr is None:
                return np.full(n, np.nan)
            rows = known[qidx]
            return np.where(rows >= 0, arr[np.clip(rows, 0, None)], np.nan)

        def ttm_of(field: str) -> np.ndarray:
            out = np.full(n, np.nan)
            for qidx in qidxs:
                qnum = (qidx % 4) + 1
                if qnum == 4:
                    v = val_at(field, qidx)
                else:
                    prev_q4 = qidx - qnum
                    same_q_prev = qidx - 4
                    cur = val_at(field, qidx)
                    p4 = val_at(field, prev_q4)
                    sp = val_at(field, same_q_prev)
                    v = cur + p4 - sp
                out = np.where(latest_ok == qidx, v, out)
            return out

        def yoy_of(field: str) -> np.ndarray:
            out = np.full(n, np.nan)
            for qidx in qidxs:
                if qidx - 4 not in q_arrays:
                    continue
                cur = val_at(field, qidx)
                prev = val_at(field, qidx - 4)
                v = cur / np.where(prev == 0, np.nan, prev) - 1.0
                out = np.where(latest_ok == qidx, v, out)
            return out

        # values at the latest quarter
        def latest_val(field: str) -> np.ndarray:
            out = np.full(n, np.nan)
            for qidx in qidxs:
                v = val_at(field, qidx)
                out = np.where(latest_ok == qidx, v, out)
            return out

        rev_t = ttm_of("is_total_revenue")
        ni_t = ttm_of("is_n_income_attr_p")
        ocf_t = ttm_of("cfs_net_cash_operating")
        eps_t = ttm_of("is_basic_eps")

        rev_q = latest_val("is_total_revenue")
        cost_q = latest_val("is_oper_cost")
        opr_q = latest_val("is_operate_profit")
        ni_q = latest_val("is_n_income_attr_p")
        assets_q = latest_val("bs_total_assets")
        liab_q = latest_val("bs_total_liab")
        eq_q = latest_val("bs_total_hldr_eqy_exc_min_int")
        cash_q = latest_val("bs_money_cap")
        inv_q = latest_val("bs_inventory")
        rd_q = latest_val("is_rd_exp")
        gw_q = latest_val("bs_goodwill")
        ca_q = latest_val("bs_total_cur_assets")
        cl_q = latest_val("bs_total_cur_liab")

        r = result.loc[mask]
        r["revenue_ttm"] = rev_t
        r["ni_ttm"] = ni_t
        r["ocf_ttm"] = ocf_t
        r["eps_ttm"] = eps_t
        r["equity"] = eq_q
        r["total_assets"] = assets_q
        r["total_liab"] = liab_q
        r["gross_margin"] = (rev_q - cost_q) / np.where(rev_q == 0, np.nan, rev_q)
        r["op_margin"] = opr_q / np.where(rev_q == 0, np.nan, rev_q)
        r["np_margin"] = ni_q / np.where(rev_q == 0, np.nan, rev_q)
        r["roe_ttm"] = ni_t / np.where(eq_q == 0, np.nan, eq_q)
        r["roa_ttm"] = ni_t / np.where(assets_q == 0, np.nan, assets_q)
        r["accruals_ttm"] = (ni_t - ocf_t) / np.where(assets_q == 0, np.nan, assets_q)
        r["ocf_to_assets"] = ocf_t / np.where(assets_q == 0, np.nan, assets_q)
        r["ocf_to_ni"] = ocf_t / np.where(ni_t == 0, np.nan, ni_t)
        r["debt_to_assets"] = liab_q / np.where(assets_q == 0, np.nan, assets_q)
        r["current_ratio"] = ca_q / np.where(cl_q == 0, np.nan, cl_q)
        r["cash_to_assets"] = cash_q / np.where(assets_q == 0, np.nan, assets_q)
        r["rd_to_revenue"] = rd_q / np.where(rev_q == 0, np.nan, rev_q)
        r["goodwill_to_assets"] = gw_q / np.where(assets_q == 0, np.nan, assets_q)
        r["rev_yoy"] = yoy_of("is_total_revenue")
        r["ni_yoy"] = yoy_of("is_n_income_attr_p")
        r["ocf_yoy"] = yoy_of("cfs_net_cash_operating")

        result.loc[mask] = r

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Forecast / ownership blocks
# ═══════════════════════════════════════════════════════════════════════════════

def _build_forecast_block(
    grid: pd.DataFrame, fc: pd.DataFrame, lag_days: int
) -> pd.DataFrame:
    cols = ["fc_np_mid", "fc_eps_mid", "fc_growth_mid", "fc_width",
            "fc_type_score", "fc_revision"]
    result = pd.DataFrame(np.nan, index=grid.index, columns=cols, dtype=float)
    if fc is None or fc.empty:
        return result

    f = fc.copy()
    date_col = "info_date" if "info_date" in f.columns else "date"
    if date_col not in f.columns:
        return result
    f[date_col] = f[date_col].astype(str)

    def mid(a_col: str, b_col: str) -> np.ndarray:
        return ((_col(f, a_col) + _col(f, b_col)) / 2.0).values

    f["__np_mid"] = mid("forecast_np_floor", "forecast_np_ceiling")
    f["__eps_mid"] = mid("forecast_eps_floor", "forecast_eps_ceiling")
    f["__g_mid"] = mid("forecast_growth_rate_floor", "forecast_growth_rate_ceiling")
    f["__np_width"] = (
        np.abs(_col(f, "forecast_np_ceiling") - _col(f, "forecast_np_floor")).values
        / np.maximum(np.abs(f["__np_mid"]), 1e-6)
    )
    if "forecast_type" in f.columns:
        f["__type_score"] = (
            f["forecast_type"].map(FC_TYPE_SCORE).fillna(0.0).astype(float).values
        )
    else:
        f["__type_score"] = np.zeros(len(f))
    f["__revision"] = _col(f, "net_profit_yoy_const_forecast").values

    result["fc_np_mid"] = _asof_values(grid, f, date_col, "__np_mid", lag_days)
    result["fc_eps_mid"] = _asof_values(grid, f, date_col, "__eps_mid", lag_days)
    result["fc_growth_mid"] = _asof_values(grid, f, date_col, "__g_mid", lag_days)
    result["fc_width"] = _asof_values(grid, f, date_col, "__np_width", lag_days)
    result["fc_type_score"] = _asof_values(grid, f, date_col, "__type_score", lag_days)
    result["fc_revision"] = _asof_values(grid, f, date_col, "__revision", lag_days)
    return result


def _build_ownership_block(
    grid: pd.DataFrame,
    holder: pd.DataFrame | None,
    repurchase: pd.DataFrame | None,
    lag_days: int,
) -> pd.DataFrame:
    cols = ["holder_count", "holder_change_yoy",
            "buyback_value_ttm", "buyback_percent"]
    result = pd.DataFrame(np.nan, index=grid.index, columns=cols, dtype=float)

    # holder count + YoY change
    if holder is not None and not holder.empty:
        h = holder.copy()
        h_date = "date" if "date" in h.columns else "end_date"
        h[h_date] = h[h_date].astype(str)
        holders_col = "holders" if "holders" in h.columns else "a_holders"
        h["__holders"] = _col(h, holders_col).values
        result["holder_count"] = _asof_values(
            grid, h, h_date, "__holders", lag_days
        )
        # YoY change: compare with value known ~365 days earlier
        prev = _asof_values(
            grid.assign(date64=grid["date64"] - np.timedelta64(365, "D")),
            h, h_date, "__holders", lag_days,
        )
        cur = result["holder_count"].values
        result["holder_change_yoy"] = np.where(
            (prev == 0) | np.isnan(prev) | np.isnan(cur), np.nan, cur / prev - 1.0
        )

    # buyback: trailing-year value + latest program percent
    if repurchase is not None and not repurchase.empty:
        b = repurchase.copy()
        b_date = "date" if "date" in b.columns else "announcement_dt"
        if b_date in b.columns:
            b[b_date] = b[b_date].astype(str).str[:8]  # keep YYYYMMDD prefix
            result["buyback_value_ttm"] = _rolling_sum_values(
                grid, b, b_date, "buy_back_value", 365, lag_days
            )
            result["buyback_percent"] = _asof_values(
                grid, b, b_date, "buy_back_percent", lag_days
            )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════════

def build_panel(input_dir: Path, lag_days: int) -> pd.DataFrame:
    def _load(name: str) -> pd.DataFrame | None:
        path = input_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            return None
        try:
            df = pd.read_csv(path, dtype={"symbol": str, "date": str})
            return df
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] Could not read {path}: {e}", file=sys.stderr)
            return None

    market = _load("market_data.csv")
    factors = _load("factors.csv")
    stmt = _load("statements.csv")
    fc = _load("forecast.csv")
    holder = _load("holder_count.csv")
    repurchase = _load("repurchase.csv")

    universe_path = input_dir / "universe.json"
    universe_symbols: list[str] | None = None
    if universe_path.is_file():
        with open(universe_path, "r", encoding="utf-8") as f:
            universe_symbols = json.load(f).get("symbols", []) or None

    # ── Grid: (date, symbol) pairs ──────────────────────────────────────────
    grid_sources = []
    if factors is not None and not factors.empty and {"date", "symbol"} <= set(factors.columns):
        grid_sources.append(factors[["date", "symbol"]])
    if market is not None and not market.empty and {"date", "symbol"} <= set(market.columns):
        grid_sources.append(market[["date", "symbol"]])
    if not grid_sources:
        print("[FATAL] Neither factors.csv nor market_data.csv available — "
              "cannot build a trade-date grid.", file=sys.stderr)
        sys.exit(1)

    grid = pd.concat(grid_sources, ignore_index=True).drop_duplicates()
    grid["date"] = grid["date"].astype(str)
    grid["symbol"] = grid["symbol"].astype(str)
    if universe_symbols:
        grid = grid[grid["symbol"].isin(universe_symbols)]
    grid = grid.sort_values(["date", "symbol"]).reset_index(drop=True)
    grid["date64"] = _to_d64(grid["date"])
    grid = grid.dropna(subset=["date64"])

    print(f"[INFO] Grid: {len(grid):,} rows × "
          f"{grid['symbol'].nunique()} symbols × {grid['date'].nunique()} dates.",
          file=sys.stderr)

    panel = grid[["date", "symbol"]].copy()

    # ── 1. Precomputed factors (PIT by construction) ────────────────────────
    if factors is not None and not factors.empty:
        fac = factors.copy()
        fac["date"] = fac["date"].astype(str)
        fac["symbol"] = fac["symbol"].astype(str)
        rename = {k: v for k, v in FACTOR_RENAME.items() if k in fac.columns}
        fac = fac.rename(columns=rename)
        keep = ["date", "symbol"] + [v for v in rename.values()]
        fac = fac[[c for c in keep if c in fac.columns]]
        panel = panel.merge(fac, on=["date", "symbol"], how="left")
        print(f"[INFO] Merged {len(rename)} precomputed factor fields.",
              file=sys.stderr)

    # ── 2. Statement-derived PIT fields ─────────────────────────────────────
    stmt_block = _build_statement_block(grid, stmt, lag_days)
    panel = pd.concat([panel, stmt_block.reset_index(drop=True)], axis=1)

    # ── 3. Forecast / ownership PIT joins ──────────────────────────────────
    for block in (
        _build_forecast_block(grid, fc, lag_days),
        _build_ownership_block(grid, holder, repurchase, lag_days),
    ):
        panel = pd.concat([panel, block.reset_index(drop=True)], axis=1)

    return panel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the point-in-time fundamental panel."
    )
    parser.add_argument("--input-dir", default=None,
                        help="Directory with fetch output CSVs.")
    parser.add_argument("--output", default=None,
                        help="Output path for fundamentals.csv.")
    parser.add_argument("--run-name", default=None,
                        help="Run name. Resolves input dir and output path.")
    args = parser.parse_args()

    config = {}
    config_path = _SKILL_ROOT / "config.json"
    if config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as cf:
            config = json.load(cf)

    if args.run_name:
        out_root = _SKILL_ROOT / config.get("output_dir", "output")
        candidates = sorted(out_root.glob(f"run_*_{args.run_name}"), reverse=True)
        if not candidates:
            print(f"[FATAL] No run dir matching '*_{args.run_name}'",
                  file=sys.stderr)
            sys.exit(1)
        run_dir = candidates[0]
        args.input_dir = str(run_dir)
        args.output = str(run_dir / "fundamentals.csv")
        print(f"[INFO] Matched: {run_dir.name}", file=sys.stderr)

    if not args.input_dir:
        print("[FATAL] Requires --input-dir or --run-name.", file=sys.stderr)
        sys.exit(1)

    input_dir = Path(args.input_dir)
    lag_days = int(config.get("pit_lag_days", 1))

    panel = build_panel(input_dir, lag_days)

    output_path = Path(args.output) if args.output else input_dir / "fundamentals.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False)
    print(f"[INFO] Saved panel: {panel.shape[0]:,} rows × "
          f"{panel.shape[1]} cols → {output_path}", file=sys.stderr)

    # coverage report
    cov = {}
    for col in panel.columns:
        if col in ("date", "symbol"):
            continue
        ratio = panel[col].isna().mean()
        cov[col] = round(float(1.0 - ratio), 4)
    report = {
        "rows": int(len(panel)),
        "symbols": int(panel["symbol"].nunique()),
        "dates": int(panel["date"].nunique()),
        "pit_lag_days": lag_days,
        "coverage": cov,
    }
    with open(output_path.parent / "data_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # copy definitions catalog into the run dir
    src_defs = _SKILL_ROOT / "references" / "fundamental_definitions.json"
    if src_defs.is_file():
        shutil.copy(src_defs, output_path.parent / "fundamental_definitions.json")
        print(f"[INFO] Definitions → {output_path.parent / 'fundamental_definitions.json'}",
              file=sys.stderr)

    print(
        f"\n[INFO] Next: python scripts/generate_fundamental_alphas.py "
        f"--fundamentals {output_path} --query '<your idea>' --n 5 "
        f"--output {output_path.parent}/alphas.json",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

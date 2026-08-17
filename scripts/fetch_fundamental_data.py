#!/usr/bin/env python3
"""Fetch fundamental data from PandaData for a given stock universe.

Pulls everything needed to build a point-in-time fundamental panel:
  - quarterly statements  (get_financial_ex, is_latest=False → PIT history)
  - precomputed factors   (get_factor: ratio_*/cfd_*/fin_*/_mrq_n → PIT by design)
  - daily market data     (get_market_data → prices / panel skeleton)
  - earnings forecasts    (get_financial_forecast)
  - ownership signals     (get_holder_count, get_buy_back)

Every dataset is optional; failures degrade with warnings instead of aborting
(only a total absence of usable data is fatal).

Usage:
    python fetch_fundamental_data.py --run-name myrun
    python fetch_fundamental_data.py \
        --start-date 20240101 --end-date 20240301 \
        --start-quarter 2021q1 --end-quarter 2023q4 \
        --universe 000300 --output /tmp/fundamental_fetch/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# Load .env from skill root
# ═══════════════════════════════════════════════════════════════════════════════

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _SKILL_ROOT / ".env"

if _ENV_PATH.is_file():
    with open(_ENV_PATH, "r", encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key not in os.environ:
                    os.environ[_key] = _val

# ═══════════════════════════════════════════════════════════════════════════════
# Field catalogs (see references/fundamental_definitions.json for semantics)
# ═══════════════════════════════════════════════════════════════════════════════

STATEMENT_FIELDS = [
    "symbol", "quarter", "date", "if_adjusted",
    # Income statement (A-share cumulative-YTD convention)
    "is_total_revenue", "is_oper_cost", "is_operate_profit", "is_total_profit",
    "is_n_income_attr_p", "is_net_after_nr", "is_rd_exp", "is_sell_exp",
    "is_admin_exp", "is_fin_exp", "is_invest_income", "is_non_recurring_pnl",
    "is_basic_eps",
    # Balance sheet
    "bs_total_assets", "bs_total_liab", "bs_total_hldr_eqy_exc_min_int",
    "bs_money_cap", "bs_inventory", "bs_net_accts_receive", "bs_goodwill",
    "bs_total_cur_assets", "bs_total_cur_liab", "bs_st_borr", "bs_lt_borr",
    "bs_total_nca",
    # Cash flow
    "cfs_net_cash_operating", "cfs_net_cash_investing", "cfs_net_cash_financing",
    "cfs_cash_paid_div_interest", "cfs_fix_asset_depr", "cfs_net_inc_cash_equiv",
]

PRECOMPUTED_FIELDS = [
    # Valuation (ratio_*)
    "ratio_pe_ttm", "ratio_pe_lyr", "ratio_pb_lf", "ratio_ep_ttm",
    "ratio_ep_lyr", "ratio_bm_lf", "ratio_bm_ttm", "ratio_sp_ttm",
    "ratio_ps_ttm", "ratio_pcf_ocf_ttm", "ratio_cfp_ttm",
    "ratio_div_yield_ttm", "ratio_peg_ttm", "ratio_ev_ebitda_ttm",
    "ratio_ev_ebitda_lyr", "ratio_ev_no_cash_ebit_ttm", "ratio_market_cap_total",
    # Cash-flow derivatives (cfd_*)
    "cfd_flow_per_share_ttm", "cfd_ocf_per_share_ttm", "cfd_fcff_ttm",
    "cfd_fcfe_ttm", "cfd_fcff_per_share_ttm", "cfd_fcfe_per_share_ttm",
    "cfd_ocf_to_debt_ttm", "cfd_ocf_to_net_debt_ttm", "cfd_ocf_to_int_debt_ttm",
    "cfd_ocf_to_cur_liab_ttm", "cfd_surplus_cash_multi_ttm",
    "cfd_ebitda_to_int_ttm", "cfd_depr_amort_ttm",
    # Financial derivatives (fin_*)
    "fin_int_debt_lf", "fin_int_debt_ttm", "fin_non_int_cur_liab_lf",
    "fin_non_int_ncl_lf", "fin_cap_reserve_per_share_lf",
    "fin_earned_reserve_per_share_lf", "fin_undistr_profit_per_share_lf",
    # MRQ statement values (PIT by construction)
    "is_n_income_attr_p_mrq_1", "is_n_income_attr_p_mrq_4",
    "is_total_revenue_mrq_1", "is_total_revenue_mrq_4",
    "cfs_net_cash_operating_mrq_1", "cfs_net_cash_operating_mrq_4",
    "bs_total_hldr_eqy_exc_min_int_mrq_1", "bs_total_hldr_eqy_exc_min_int_mrq_4",
    "bs_total_assets_mrq_1", "is_basic_eps_mrq_1",
]

CHUNK_SIZE = 100

# ═══════════════════════════════════════════════════════════════════════════════
# PandaData Client
# ═══════════════════════════════════════════════════════════════════════════════

_panda_data = None
_panda_init_attempted = False


def _init_pandadata() -> None:
    global _panda_data, _panda_init_attempted
    if _panda_init_attempted:
        return
    _panda_init_attempted = True

    try:
        import panda_data
    except ImportError:
        print(
            "[FATAL] panda_data is not installed. Install it with:\n"
            "    pip install panda_data>=0.1.0\n"
            "See requirements.txt for full dependency list.",
            file=sys.stderr,
        )
        sys.exit(1)

    username = os.environ.get("PANDA_AI_USERNAME", "")
    password = os.environ.get("PANDA_AI_PASSWORD", "")
    base_url = os.environ.get(
        "PANDA_AI_BASE_URL", "http://pandadata.pandaaiquant.com",
    )

    if not username or not password:
        print(
            "[FATAL] PandaData credentials not found in .env.\n"
            "Set PANDA_AI_USERNAME and PANDA_AI_PASSWORD in the .env file\n"
            f"at {_ENV_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        panda_data.init_token(
            username=username,
            password=password,
            base_url=base_url,
        )
        _panda_data = panda_data
        print("[INFO] PandaData initialized successfully.", file=sys.stderr)
    except Exception as e:
        print(f"[FATAL] PandaData init failed: {e}", file=sys.stderr)
        sys.exit(1)


def _call_first(method_candidates: list[str], **kwargs) -> pd.DataFrame:
    """Call the first existing method among candidates (docs name → actual name
    mapping safety). Returns DataFrame; raises the last error if all fail."""
    last_err: Exception | None = None
    for name in method_candidates:
        method = getattr(_panda_data, name, None)
        if method is None:
            continue
        try:
            result = method(**kwargs)
            if result is None:
                return pd.DataFrame()
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise (last_err if last_err is not None else AttributeError(
        f"none of {method_candidates} available"))


# ═══════════════════════════════════════════════════════════════════════════════
# Universe resolution
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_universe(universe: str, start_date: str, end_date: str) -> list[str]:
    """Resolve a universe index code to a list of stock symbols.

    Tries, in order:
      1. get_factor with index_component=<universe>
      2. get_market_data with indicator=<universe>
      3. get_index_weights (with and without .SH suffix)
      4. all listed stocks (fallback)
    """
    if _panda_data is None:
        _init_pandadata()

    attempts = []

    # 1) get_market_data with indicator=<universe> (verified working)
    try:
        df = _call_first(
            ["get_market_data"],
            start_date=start_date, end_date=end_date, indicator=universe,
            type="stock", fields=["symbol", "date"],
        )
        if df is not None and not df.empty and "symbol" in df.columns:
            syms = sorted(df["symbol"].dropna().astype(str).unique().tolist())
            attempts.append(("get_market_data indicator", len(syms)))
            if syms:
                return syms
    except Exception as e:  # noqa: BLE001
        attempts.append(("get_market_data indicator", f"failed: {e}"))

    # 2) get_index_weights with/without suffix
    for code in (f"{universe}.SH", f"{universe}.SZ", universe):
        try:
            df = _call_first(
                ["get_index_weights"],
                index_symbol=code, stock_symbol="",
                start_date=start_date, end_date=end_date,
            )
            if df is not None and not df.empty and "stock_symbol" in df.columns:
                syms = sorted(df["stock_symbol"].dropna().astype(str).unique().tolist())
                attempts.append((f"get_index_weights {code}", len(syms)))
                if syms:
                    return syms
        except Exception as e:  # noqa: BLE001
            attempts.append((f"get_index_weights {code}", f"failed: {e}"))

    # 3) Fallback: all listed stocks (head 300, code-sorted proxy)
    try:
        df = _call_first(
            ["get_stock_detail"],
            fields=["symbol"], market="cn", status=1,
        )
        if df is not None and not df.empty and "symbol" in df.columns:
            syms = sorted(df["symbol"].dropna().astype(str).unique().tolist())[:300]
            attempts.append(("get_stock_detail fallback", len(syms)))
            return syms
    except Exception as e:  # noqa: BLE001
        attempts.append(("get_stock_detail fallback", f"failed: {e}"))

    print("[FATAL] Could not resolve universe. Attempts:", file=sys.stderr)
    for name, res in attempts:
        print(f"  - {name}: {res}", file=sys.stderr)
    sys.exit(1)


def _chunks(items: list[str], size: int = CHUNK_SIZE) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# ═══════════════════════════════════════════════════════════════════════════════
# Dataset fetchers
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_market_data(symbols: list[str], start_date: str, end_date: str,
                      universe: str) -> pd.DataFrame:
    """Daily OHLCV for the universe. get_market_data(indicator=...) returns
    the whole stock pool in one call (passing a symbol list returns only one
    symbol in this package build, so indicator is the reliable path)."""
    try:
        df = _call_first(
            ["get_market_data"],
            start_date=start_date, end_date=end_date,
            type="stock", indicator=universe,
            fields=["symbol", "date", "close", "volume", "trade_status"],
        )
        if df is not None and not df.empty:
            return df
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] market data (indicator) failed: {e}; "
              f"falling back to per-symbol batches.", file=sys.stderr)

    parts = []
    for chunk in _chunks(symbols):
        try:
            df = _call_first(
                ["get_market_data"],
                start_date=start_date, end_date=end_date,
                symbol=chunk, type="stock",
                fields=["symbol", "date", "close", "volume", "trade_status"],
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] market data chunk failed: {e}", file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fetch_precomputed_factors(symbols: list[str], start_date: str,
                              end_date: str, universe: str) -> pd.DataFrame:
    # Per-symbol batches: get_factor(index_component=...) does not accept index
    # codes in this package build, but a symbol list works.
    parts = []
    for chunk in _chunks(symbols):
        try:
            df = _call_first(
                ["get_factor"],
                start_date=start_date, end_date=end_date,
                symbol=chunk, factors=PRECOMPUTED_FIELDS, type="stock",
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] get_factor chunk failed: {e}", file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _quarter_covering(date_str: str) -> str:
    """Quarter label (YYYYqN) containing the given YYYYMMDD date."""
    year = int(date_str[:4])
    month = int(date_str[4:6])
    return f"{year}q{(month - 1) // 3 + 1}"


def fetch_statements(symbols: list[str], start_quarter: str,
                     end_quarter: str, end_date: str) -> pd.DataFrame:
    """Quarterly statements as a point-in-time snapshot.

    get_financial_ex requires (start_quarter, end_quarter, date) to be passed
    together, and `date` must fall inside that quarter window. `date` returns
    every filing with filing date <= date, with as-filed values
    (if_adjusted=0) plus restatements (if_adjusted=1). This is the correct PIT
    input: build_pit_fundamentals.py then asof-joins by filing date to
    reconstruct what was known at each trade date.
    """
    # Widen end_quarter so it contains end_date (server rejects date outside
    # the [start_quarter, end_quarter] window).
    covering = _quarter_covering(end_date)
    if covering > end_quarter:
        end_quarter = covering

    parts = []
    for chunk in _chunks(symbols):
        try:
            df = _call_first(
                ["get_financial_ex", "get_fina_reports"],
                symbol=chunk,
                start_quarter=start_quarter,
                end_quarter=end_quarter,
                date=end_date,
                is_latest=False,
                fields=STATEMENT_FIELDS,
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] statements chunk failed: {e}", file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fetch_forecast(start_date: str, end_date: str) -> pd.DataFrame:
    """Earnings forecasts published within [start_date, end_date].

    get_financial_forecast only filters by info_date (an exact publication date,
    universe-wide). `symbol` and `end_quarter` are NOT honored by this package
    build, so we iterate over trading days and concatenate the results.

    Forecasts are event-driven (业绩预告 / 业绩快报): most days return nothing,
    which is expected — only companies that pre-announce have records.
    """
    # Resolve trading days (fall back to business days if the calendar API fails)
    days: list[str] = []
    try:
        cal = _call_first(
            ["get_trading_calendar"],
            start_date=start_date, end_date=end_date,
        )
        if cal is not None and not cal.empty and "date" in cal.columns:
            days = sorted(cal["date"].astype(str).unique().tolist())
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] trading calendar unavailable ({e}); "
              f"falling back to business days.", file=sys.stderr)
    if not days:
        days = [d.strftime("%Y%m%d") for d in pd.bdate_range(start_date, end_date)]

    parts = []
    for i, d in enumerate(days):
        try:
            df = _call_first(
                ["get_financial_forecast", "get_fina_forecast"], info_date=d
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] forecast fetch failed for {d}: {e}", file=sys.stderr)
        if (i + 1) % 60 == 0:
            print(f"[INFO]   forecast: {i+1}/{len(days)} days scanned...",
                  file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fetch_holder_count(symbols: list[str], start_date: str,
                       end_date: str) -> pd.DataFrame:
    parts = []
    for chunk in _chunks(symbols):
        try:
            df = _call_first(
                ["get_holder_count", "get_holder_number"],
                symbol=chunk, start_date=start_date, end_date=end_date,
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] holder count chunk failed: {e}", file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fetch_repurchase(symbols: list[str], start_date: str,
                     end_date: str) -> pd.DataFrame:
    parts = []
    for chunk in _chunks(symbols):
        try:
            df = _call_first(
                ["get_buy_back", "get_repurchase"],
                symbol=chunk, start_date=start_date, end_date=end_date,
            )
            if df is not None and not df.empty:
                parts.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] repurchase chunk failed: {e}", file=sys.stderr)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_all(
    universe: str,
    start_date: str,
    end_date: str,
    start_quarter: str,
    end_quarter: str,
) -> dict[str, pd.DataFrame]:
    if _panda_data is None:
        _init_pandadata()

    symbols = resolve_universe(universe, start_date, end_date)
    print(f"[INFO] Universe {universe}: {len(symbols)} symbols.", file=sys.stderr)

    datasets: dict[str, pd.DataFrame] = {}
    datasets["universe"] = pd.DataFrame({"symbol": symbols})

    print("[INFO] Fetching market data...", file=sys.stderr)
    datasets["market"] = fetch_market_data(symbols, start_date, end_date, universe)

    print("[INFO] Fetching precomputed factors...", file=sys.stderr)
    datasets["factors"] = fetch_precomputed_factors(
        symbols, start_date, end_date, universe
    )

    print("[INFO] Fetching quarterly statements...", file=sys.stderr)
    datasets["statements"] = fetch_statements(
        symbols, start_quarter, end_quarter, end_date
    )

    print("[INFO] Fetching earnings forecasts...", file=sys.stderr)
    datasets["forecast"] = fetch_forecast(start_date, end_date)

    print("[INFO] Fetching holder counts...", file=sys.stderr)
    datasets["holder_count"] = fetch_holder_count(symbols, start_date, end_date)

    print("[INFO] Fetching repurchases...", file=sys.stderr)
    datasets["repurchase"] = fetch_repurchase(symbols, start_date, end_date)

    usable = sum(1 for k, v in datasets.items() if v is not None and not v.empty)
    if usable <= 1:  # only universe itself
        print("[FATAL] No usable data fetched. Check credentials, universe "
              "code, and date/quarter ranges.", file=sys.stderr)
        sys.exit(1)

    return datasets


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch fundamental data from PandaData for a stock universe."
    )
    parser.add_argument("--start-date", default=None, help="Start date YYYYMMDD.")
    parser.add_argument("--end-date", default=None, help="End date YYYYMMDD.")
    parser.add_argument("--start-quarter", default=None, help="Start quarter YYYYqN.")
    parser.add_argument("--end-quarter", default=None, help="End quarter YYYYqN.")
    parser.add_argument("--universe", default=None,
                        help="Stock universe code (default: 000300=CSI 300).")
    parser.add_argument("--output", default=None,
                        help="Output directory for raw CSVs.")
    parser.add_argument("--run-name", default=None,
                        help="Run name. Creates output/run_<ts>_<name>/.")
    args = parser.parse_args()

    config_path = _SKILL_ROOT / "config.json"
    config = {}
    if config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as cf:
            config = json.load(cf)

    if args.run_name:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = _SKILL_ROOT / config.get("output_dir", "output") / f"run_{ts}_{args.run_name}"
        out_dir.mkdir(parents=True, exist_ok=True)
    elif args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        print("[FATAL] Either --output or --run-name is required.", file=sys.stderr)
        sys.exit(1)

    universe = args.universe or config.get("universe", "000300")
    start_date = args.start_date or config.get("start_date", "20240101")
    end_date = args.end_date or config.get("end_date", "20250801")
    start_quarter = args.start_quarter or config.get("start_quarter", "2021q1")
    end_quarter = args.end_quarter or config.get("end_quarter", "2025q2")

    datasets = fetch_all(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        start_quarter=start_quarter,
        end_quarter=end_quarter,
    )

    # Save datasets
    report = {
        "universe": universe,
        "start_date": start_date,
        "end_date": end_date,
        "start_quarter": start_quarter,
        "end_quarter": end_quarter,
        "datasets": {},
    }
    file_names = {
        "universe": "universe.json",
        "market": "market_data.csv",
        "factors": "factors.csv",
        "statements": "statements.csv",
        "forecast": "forecast.csv",
        "holder_count": "holder_count.csv",
        "repurchase": "repurchase.csv",
    }
    for key, df in datasets.items():
        path = out_dir / file_names[key]
        if key == "universe":
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "universe": universe,
                    "symbols": df["symbol"].tolist(),
                }, f, indent=2, ensure_ascii=False)
        else:
            df.to_csv(path, index=False)
        report["datasets"][key] = {
            "rows": int(len(df)),
            "cols": df.shape[1],
            "file": file_names[key],
        }
        print(f"[INFO] Saved {key}: {len(df):,} rows → {path}", file=sys.stderr)

    with open(out_dir / "fetch_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(
        f"\n[INFO] Fetch complete → {out_dir}\n"
        f"[INFO] Next: python scripts/build_pit_fundamentals.py "
        f"--input-dir {out_dir} --output {out_dir}/fundamentals.csv",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

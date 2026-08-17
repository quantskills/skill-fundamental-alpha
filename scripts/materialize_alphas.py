#!/usr/bin/env python3
"""Export validated fundamental alphas as daily-frequency factor CSVs
compatible with skill-factor-backtest.

Evaluates each alpha expression against fundamentals.csv and produces a
date,ticker,<alpha_name> CSV per alpha.

Usage:
    python materialize_alphas.py --run-name myrun
    python materialize_alphas.py \
        --alphas output/run_001/validated_alphas.json \
        --fundamentals output/run_001/fundamentals.csv \
        --output-dir output/run_001/backtest_factors/

Output format (per alpha):
    date,ticker,<alpha_name>
    20240102,1,0.0234
    20240102,2,-0.0156
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from expression_engine import (
    build_eval_namespace,
    collect_new_features,
    compute_new_features,
)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent


def symbol_to_ticker(symbols: pd.Series) -> pd.Series:
    """Convert '000001.SZ' → 1, '600000.SH' → 600000."""
    return symbols.str.replace(r"\.(SZ|SH)$", "", regex=True).astype(int)


def evaluate_expression(expression: str, fundamentals_df: pd.DataFrame) -> pd.Series:
    """Evaluate alpha expression → pandas Series aligned to fundamentals_df."""
    ns = build_eval_namespace(fundamentals_df)
    values = eval(expression, {"__builtins__": {}}, ns)
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) > 0:
        values = np.clip(values, -5 * np.nanstd(finite), 5 * np.nanstd(finite))
    return pd.Series(values, index=fundamentals_df.index)


def materialize_run(alphas_path: str, fundamentals_path: str,
                    output_dir: str) -> list[str]:
    with open(alphas_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    alphas = data.get("alphas", data) if isinstance(data, dict) else data
    if isinstance(alphas, dict):
        alphas = alphas.get("alphas", [])

    if not alphas:
        print("[WARN] No alphas found.", file=sys.stderr)
        return []

    fundamentals_df = pd.read_csv(fundamentals_path)
    print(f"[INFO] {fundamentals_df.shape[0]} rows, {len(alphas)} alphas",
          file=sys.stderr)

    # Compute agent-defined custom features
    new_feature_defs = collect_new_features(data) if isinstance(data, dict) else []
    if new_feature_defs:
        fundamentals_df, computed, ferrs = compute_new_features(
            fundamentals_df, new_feature_defs
        )
        if ferrs:
            for err in ferrs:
                print(f"[WARN] {err}", file=sys.stderr)
        print(f"[INFO] {len(computed)} custom features computed.", file=sys.stderr)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []

    for alpha in alphas:
        name = alpha.get("name", "unnamed")
        expr = alpha.get("expression", "")
        if not expr:
            continue

        print(f"[EVAL] {name}: {expr[:70]}...", file=sys.stderr)
        try:
            series = evaluate_expression(expr, fundamentals_df)
        except Exception as e:
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
            continue

        out_df = pd.DataFrame({
            "date": fundamentals_df["date"].values,
            "ticker": symbol_to_ticker(fundamentals_df["symbol"]).values,
            name: series.values,
        }).dropna(subset=[name]).sort_values(["date", "ticker"]).reset_index(drop=True)

        path = out_dir / f"{name}.csv"
        out_df.to_csv(path, index=False)
        files.append(str(path))
        print(f"  ✓ {out_df.shape[0]:,} rows, {out_df['date'].nunique()} dates "
              f"→ {path.name}", file=sys.stderr)

    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export fundamental alphas as daily backtest-ready CSVs."
    )
    parser.add_argument("--alphas", default=None, help="Path to validated_alphas.json.")
    parser.add_argument("--fundamentals", default=None, help="Path to fundamentals.csv.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--run-name", default=None,
                        help="Run name. Auto-resolves inputs and output dir.")
    args = parser.parse_args()

    if args.run_name:
        candidates = sorted(
            (_SKILL_ROOT / "output").glob(f"run_*_{args.run_name}"), reverse=True
        )
        if not candidates:
            print(f"[FATAL] No run dir matching '*_{args.run_name}'", file=sys.stderr)
            sys.exit(1)
        rd = candidates[0]
        args.alphas = str(rd / "validated_alphas.json")
        if not Path(args.alphas).is_file():
            args.alphas = str(rd / "alphas.json")
        args.fundamentals = str(rd / "fundamentals.csv")
        args.output_dir = str(rd / "backtest_factors")
        print(f"[INFO] Run: {rd.name}", file=sys.stderr)

    if not args.alphas or not args.fundamentals:
        print("[FATAL] Requires --alphas + --fundamentals, or --run-name.",
              file=sys.stderr)
        sys.exit(1)
    if not args.output_dir:
        args.output_dir = str(Path(args.alphas).parent / "backtest_factors")

    files = materialize_run(args.alphas, args.fundamentals, args.output_dir)
    print(f"\n[INFO] {len(files)} factor CSVs → {args.output_dir}", file=sys.stderr)

    if files:
        print(
            f"\nBacktest with skill-factor-backtest:\n"
            f"  python ../skill-factor-backtest/scripts/run_factor_backtest.py \\\n"
            f"    --input-file {files[0]} \\\n"
            f"    --factor-column {Path(files[0]).stem} \\\n"
            f"    --data-root <market_data_dir> \\\n"
            f"    --timespan YYYYMMDD YYYYMMDD",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

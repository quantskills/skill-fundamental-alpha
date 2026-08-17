#!/usr/bin/env python3
"""Validate fundamental alpha expressions against the PIT panel.

Checks for:
  - Parse errors (invalid syntax)
  - Undefined fields (not in the contract / not in the panel)
  - Unknown operators (not in operators.json)
  - Look-ahead bias (delay/delta/returns with n < 1)
  - NaN/Inf ratios exceeding threshold
  - Numerical instability (extreme z-scores)
  - Zero-division and log-of-negative violations
  - PIT audit: every field used must carry a pit_rule in the definitions

Usage:
    python validate_fundamental_alphas.py \
        --alphas output/run_001/alphas.json \
        --fundamentals output/run_001/fundamentals.csv \
        --output output/run_001/validated_alphas.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from expression_engine import collect_new_features, compute_new_features

# ═══════════════════════════════════════════════════════════════════════════════
# Contract: field catalog loaded from references/fundamental_definitions.json
# ═══════════════════════════════════════════════════════════════════════════════

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_DEFINITIONS_PATH = _SKILL_ROOT / "references" / "fundamental_definitions.json"


def _load_definitions() -> dict:
    if not _DEFINITIONS_PATH.is_file():
        print(f"[FATAL] fundamental_definitions.json not found at "
              f"{_DEFINITIONS_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(_DEFINITIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_DEFINITIONS = _load_definitions()
ALLOWED_FIELDS: set[str] = set(_DEFINITIONS.get("features", {}).keys())
FIELD_DEFS: dict[str, dict] = _DEFINITIONS.get("features", {})

_OPERATORS_PATH = _SKILL_ROOT / "references" / "operators.json"


def _load_operators() -> list[dict]:
    if not _OPERATORS_PATH.is_file():
        print(f"[WARN] operators.json not found at {_OPERATORS_PATH}", file=sys.stderr)
        return []
    with open(_OPERATORS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("operators", [])


_OPERATORS = _load_operators()
ALLOWED_FUNCTIONS: set[str] = {op["name"] for op in _OPERATORS}
LOOKAHEAD_FUNCTIONS: set[str] = {
    op["name"] for op in _OPERATORS if op.get("lookahead_risk", False)
}

# ═══════════════════════════════════════════════════════════════════════════════
# Static checks
# ═══════════════════════════════════════════════════════════════════════════════

def extract_field_refs(expression: str) -> set[str]:
    tokens = set(re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', expression))
    return tokens & ALLOWED_FIELDS


def extract_function_calls(expression: str) -> set[str]:
    return set(re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', expression))


def extract_unknown_functions(expression: str) -> set[str]:
    all_funcs = extract_function_calls(expression)
    known = ALLOWED_FUNCTIONS | ALLOWED_FIELDS | {
        "int", "float", "str", "bool", "list", "dict", "tuple",
        "len", "range", "print", "True", "False", "None",
    }
    return all_funcs - known


def check_lookahead(expression: str) -> list[str]:
    issues = []
    for func in LOOKAHEAD_FUNCTIONS:
        pattern = rf'{func}\s*\([^,)]*,\s*(-?\d+)'
        for match in re.finditer(pattern, expression):
            n = int(match.group(1))
            if n < 1:
                issues.append(f"{func}(..., {n}): n must be ≥ 1 (look-ahead bias)")
    return issues


def check_zero_division(expression: str) -> list[str]:
    issues = []
    divisions = re.findall(r'/\s*([a-zA-Z_][a-zA-Z0-9_]*)', expression)
    for field in divisions:
        if field in ALLOWED_FIELDS:
            issues.append(
                f"Division by '{field}' without zero-guard. "
                f"Use max({field}, 1e-8) as denominator."
            )
    return issues


def check_log_safety(expression: str) -> list[str]:
    issues = []
    log_calls = re.findall(r'log\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)', expression)
    for field in log_calls:
        if field in ALLOWED_FIELDS:
            issues.append(f"log({field}) without clamping. "
                          f"Use log(max({field}, 1e-8)).")
    return issues


def _build_eval_namespace(fundamentals_df: pd.DataFrame) -> dict:
    """Field columns + compiled operators."""
    namespace = {"np": np, "pd": pd}
    for col in fundamentals_df.columns:
        namespace[col] = fundamentals_df[col].values
    for op in _OPERATORS:
        name = op["name"]
        impl = op.get("numpy_impl", "")
        if not impl:
            continue
        try:
            local_ns = {}
            exec_globals = {"np": np, "pd": pd}
            if impl.strip().startswith("def "):
                exec(impl, exec_globals, local_ns)
                namespace[name] = local_ns[name]
            elif impl.strip().startswith("lambda"):
                namespace[name] = eval(impl, exec_globals)
            else:
                namespace[name] = eval(impl, exec_globals)
        except Exception as e:
            print(f"[WARN] Failed to compile operator '{name}': {e}", file=sys.stderr)
    return namespace


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_expression(
    expression: str,
    fundamentals_df: pd.DataFrame,
    nan_threshold: float = 0.1,
    extreme_threshold: float = 5.0,
    extra_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate an alpha expression against the fundamental panel."""
    result = {"expression": expression, "valid": True, "issues": [], "stats": {}}
    allowed_fields = ALLOWED_FIELDS | set(extra_fields or [])

    # 1. Fields
    used_fields = extract_field_refs(expression)
    unknown_fields = {f for f in used_fields if f not in allowed_fields}
    if unknown_fields:
        result["issues"].append(f"Unknown fields: {unknown_fields}")
        result["valid"] = False

    missing_fields = used_fields - set(fundamentals_df.columns)
    if missing_fields:
        result["issues"].append(f"Fields not in panel: {missing_fields}")
        result["valid"] = False

    # 2. Functions
    unknown_funcs = extract_unknown_functions(expression)
    if unknown_funcs:
        result["issues"].append(
            f"Unknown operators (not in operators.json): {unknown_funcs}")
        result["valid"] = False

    # 3. Look-ahead
    la_issues = check_lookahead(expression)
    if la_issues:
        result["issues"].extend(la_issues)
        result["valid"] = False

    # 4. Zero division
    zd_issues = check_zero_division(expression)
    if zd_issues:
        result["issues"].extend(zd_issues)
        result["valid"] = False

    # 5. Log safety
    log_issues = check_log_safety(expression)
    if log_issues:
        result["issues"].extend(log_issues)
        result["valid"] = False

    # 6. Evaluate
    if result["valid"]:
        try:
            namespace = _build_eval_namespace(fundamentals_df)
            values = eval(expression, {"__builtins__": {}}, namespace)
            values = np.asarray(values, dtype=float)

            nan_ratio = np.isnan(values).mean()
            inf_ratio = np.isinf(values).mean()
            result["stats"]["nan_ratio"] = float(nan_ratio)
            result["stats"]["inf_ratio"] = float(inf_ratio)

            if nan_ratio > nan_threshold:
                result["issues"].append(
                    f"NaN ratio {nan_ratio:.2%} > {nan_threshold:.0%}")
                result["valid"] = False
            if inf_ratio > 0.0:
                result["issues"].append(f"Inf ratio {inf_ratio:.2%} > 0%")
                result["valid"] = False

            finite = values[np.isfinite(values)]
            if len(finite) > 0:
                max_z = np.max(np.abs((finite - np.mean(finite)) / np.std(finite)))
                result["stats"]["max_zscore"] = float(max_z)
                if max_z > extreme_threshold:
                    result["issues"].append(
                        f"Max |z-score| = {max_z:.1f} > {extreme_threshold} "
                        f"(numerically unstable)")
                    result["valid"] = False

            result["stats"]["mean"] = float(np.nanmean(finite)) if len(finite) > 0 else 0.0
            result["stats"]["std"] = float(np.nanstd(finite)) if len(finite) > 0 else 0.0

        except Exception as e:
            result["issues"].append(f"Evaluation error: {e}")
            result["valid"] = False

    # 7. PIT audit (informational; panel is PIT, fields must be documented)
    result["pit_audit"] = []
    for fname in sorted(used_fields):
        info = FIELD_DEFS.get(fname) or {}
        result["pit_audit"].append({
            "field": fname,
            "family": info.get("family", "custom"),
            "pit_rule": info.get("pit_rule", "custom (agent-defined)"),
        })

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Correction context
# ═══════════════════════════════════════════════════════════════════════════════

def build_correction_context(failures: list[dict]) -> str:
    lines = [
        "The following alpha expressions FAILED validation. Fix them:",
        "",
    ]
    for i, alpha in enumerate(failures):
        v = alpha.get("validation", {})
        lines.append(f"{i+1}. `{alpha.get('name', 'unnamed')}`: "
                     f"`{alpha.get('expression', '')}`")
        for issue in v.get("issues", []):
            lines.append(f"   - {issue}")
        lines.append("")
    lines.extend([
        "Rules to satisfy:",
        "- Use only catalog fields (see references/fundamental_ops.md) or declared new_features.",
        "- Use only operators from references/operators.json.",
        "- delay/delta/returns need n ≥ 1.",
        "- Guard divisions with max(denom, 1e-8) and logs with max(x, 1e-8).",
        "- Keep NaN ratio low: use fillna_median(x) for sparse fields.",
        "Return the corrected JSON array (same keys).",
    ])
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate fundamental alpha expressions."
    )
    parser.add_argument("--alphas", default=None, help="Input JSON with alphas.")
    parser.add_argument("--fundamentals", default=None, help="fundamentals.csv.")
    parser.add_argument("--output", default=None, help="Output JSON path.")
    parser.add_argument("--run-name", default=None,
                        help="Run name. Resolves alphas.json + fundamentals.csv.")
    parser.add_argument("--nan-threshold", type=float, default=0.1,
                        help="Max allowed NaN ratio (default: 0.1).")
    parser.add_argument("--extreme-threshold", type=float, default=5.0,
                        help="Max allowed z-score (default: 5.0).")
    parser.add_argument("--correction-context", action="store_true",
                        help="Print a ready-to-use LLM correction prompt for failures.")
    args = parser.parse_args()

    if args.run_name:
        out_root = _SKILL_ROOT / "output"
        candidates = sorted(out_root.glob(f"run_*_{args.run_name}"), reverse=True)
        if not candidates:
            print(f"[FATAL] No run dir matching '*_{args.run_name}'", file=sys.stderr)
            sys.exit(1)
        run_dir = candidates[0]
        args.alphas = str(run_dir / "alphas.json")
        args.fundamentals = str(run_dir / "fundamentals.csv")
        args.output = str(run_dir / "validated_alphas.json")
        print(f"[INFO] Matched: {run_dir.name}", file=sys.stderr)
    elif not args.alphas or not args.fundamentals or not args.output:
        print("[FATAL] Requires --alphas, --fundamentals, --output, or --run-name.",
              file=sys.stderr)
        sys.exit(1)

    # Load alphas
    with open(args.alphas, "r", encoding="utf-8") as f:
        alphas_data = json.load(f)

    if isinstance(alphas_data, list):
        alphas = alphas_data
    elif isinstance(alphas_data, dict) and "alphas" in alphas_data:
        alphas = alphas_data["alphas"]
    else:
        print("[FATAL] Unexpected alphas JSON format.", file=sys.stderr)
        sys.exit(1)

    if not alphas:
        print("[WARN] No alphas to validate. Has the agent filled in the "
              "'alphas' array yet?", file=sys.stderr)

    fundamentals_df = pd.read_csv(args.fundamentals)
    print(f"[INFO] Loaded panel {fundamentals_df.shape[0]:,} rows × "
          f"{fundamentals_df.shape[1]} cols.", file=sys.stderr)

    # Custom features
    new_feature_defs = (
        collect_new_features(alphas_data) if isinstance(alphas_data, dict) else []
    )
    if new_feature_defs:
        fundamentals_df, computed_features, feature_errors = compute_new_features(
            fundamentals_df, new_feature_defs
        )
        extra_fields = set(computed_features)
        if feature_errors:
            print("[WARN] Custom feature errors:", file=sys.stderr)
            for err in feature_errors:
                print(f"  - {err}", file=sys.stderr)
    else:
        computed_features = []
        feature_errors = []
        extra_fields = set()

    # Validate
    results = []
    passed = 0
    failed = 0

    for i, alpha in enumerate(alphas):
        expr = alpha.get("expression", "")
        name = alpha.get("name", f"alpha_{i}")
        print(f"\n[VALIDATE] {name}: {expr[:80]}...", file=sys.stderr)

        if not expr:
            results.append({
                **alpha,
                "validation": {"valid": False, "issues": ["Empty expression"]},
            })
            failed += 1
            continue

        validation = evaluate_expression(
            expr, fundamentals_df,
            nan_threshold=args.nan_threshold,
            extreme_threshold=args.extreme_threshold,
            extra_fields=extra_fields,
        )

        if validation["valid"]:
            print("  ✓ PASSED", file=sys.stderr)
            passed += 1
        else:
            print(f"  ✗ FAILED: {'; '.join(validation['issues'])}", file=sys.stderr)
            failed += 1

        results.append({**alpha, "validation": validation})

    output = {
        "alphas": results,
        "summary": {
            "total": len(alphas),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(alphas) if alphas else 0.0,
        },
        "new_features": new_feature_defs,
        "custom_features": {
            "defined": len(new_feature_defs),
            "computed": computed_features,
            "errors": feature_errors,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Expanded formulas from definitions
    features = dict(FIELD_DEFS)
    for fdef in new_feature_defs:
        fname = (fdef.get("name") or "").strip()
        if fname and fname in computed_features:
            features[fname] = {
                "formula": fdef.get("formula") or fdef.get("expression", ""),
                "family": fdef.get("family", "custom"),
            }
    for alpha in output["alphas"]:
        expr = alpha.get("expression", "")
        expanded = expr
        for name in sorted(features, key=len, reverse=True):
            if name in expanded:
                formula = features[name].get("formula", "")
                expanded = expanded.replace(name, f"{name}[{formula}]")
        alpha["expanded_formula"] = expanded
        alpha["fields_used"] = [
            {"field": n, "formula": features[n].get("formula", ""),
             "family": features[n].get("family", "")}
            for n in sorted(features, key=len, reverse=True)
            if re.search(rf'\b{re.escape(n)}\b', expr)
        ]
    print("[INFO] Added expanded formulas to output.", file=sys.stderr)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[INFO] Validation complete: {passed}/{len(alphas)} passed → "
          f"{output_path}", file=sys.stderr)

    # Correction context
    failures = [a for a in results if not a.get("validation", {}).get("valid")]
    if failures and args.correction_context:
        print("\n" + "=" * 60 + "\nCORRECTION CONTEXT (feed to LLM):\n" + "=" * 60,
              file=sys.stderr)
        print(build_correction_context(failures), file=sys.stderr)

    # Post-validation: materialize backtest factors
    run_dir = output_path.parent
    try:
        from materialize_alphas import materialize_run
        bt_dir = run_dir / "backtest_factors"
        bt_files = materialize_run(
            str(output_path), str(run_dir / "fundamentals.csv"), str(bt_dir)
        )
        if bt_files:
            print(f"[INFO] Backtest factors: {len(bt_files)} CSVs → {bt_dir}",
                  file=sys.stderr)
    except Exception as e:
        print(f"[WARN] Could not materialize backtest factors: {e}", file=sys.stderr)

    # Post-validation: run README
    try:
        _generate_run_readme(run_dir, output)
    except Exception as e:
        print(f"[WARN] Could not generate README: {e}", file=sys.stderr)


def _generate_run_readme(run_dir: Path, validated: dict) -> None:
    """Generate a README.md describing the run output."""
    summary = validated.get("summary", {})
    alphas_list = validated.get("alphas", [])
    passed_alphas = [a for a in alphas_list if a.get("validation", {}).get("valid")]

    lines = [
        f"# Run: {run_dir.name}",
        "",
        "## Summary",
        "",
        f"- **Total alphas**: {summary.get('total', 0)}",
        f"- **Passed**: {summary.get('passed', 0)}",
        f"- **Failed**: {summary.get('failed', 0)}",
        f"- **Pass rate**: {summary.get('pass_rate', 0):.0%}",
        "",
        "## Output Files",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| `statements.csv` | Quarterly statements (raw, from get_financial_ex) |",
        "| `factors.csv` | Precomputed factors (ratio/cfd/fin/mrq, from get_factor) |",
        "| `market_data.csv` | Daily prices (from get_market_data) |",
        "| `forecast.csv` | Earnings forecasts |",
        "| `holder_count.csv` / `repurchase.csv` | Ownership signals |",
        "| `fundamentals.csv` | Point-in-time fundamental panel (date,symbol,field) |",
        "| `fundamental_definitions.json` | Field catalog with formulas + PIT rules |",
        "| `data_report.json` | Panel coverage statistics |",
        "| `alphas.json` | Generated alpha expressions (prompt + filled) |",
        "| `validated_alphas.json` | Validated alphas with expanded formulas |",
        "| `backtest_factors/` | Daily factor CSVs ready for skill-factor-backtest |",
        "",
        "## Validated Alphas",
        "",
    ]

    for a in passed_alphas:
        name = a.get("name", "unnamed")
        expr = a.get("expression", "")
        desc = a.get("description", "")
        expanded = a.get("expanded_formula", "")
        fields_used = a.get("fields_used", [])
        families = sorted(set(f.get("family", "") for f in fields_used if f.get("family")))

        lines.append(f"### {name}")
        lines.append(f"```\n{expr}\n```")
        if desc:
            lines.append(f"\n{desc}\n")
        lines.append(f"- **Fields used**: {', '.join(f['field'] for f in fields_used)}")
        lines.append(f"- **Families**: {', '.join(families)}")
        expanded_line = (f"- **Expanded**: `{expanded[:120]}...`" if len(expanded) > 120
                         else f"- **Expanded**: `{expanded}`")
        lines.append(expanded_line)
        lines.append(f"- **Backtest CSV**: `backtest_factors/{name}.csv`")
        lines.append("")

    lines.append("## Backtest Integration")
    lines.append("")
    lines.append("```bash")
    lines.append("# Run backtest on any factor:")
    if passed_alphas:
        first = passed_alphas[0]["name"]
        lines.append(f"python ../skill-factor-backtest/scripts/run_factor_backtest.py \\")
        lines.append(f"  --input-file backtest_factors/{first}.csv \\")
        lines.append(f"  --factor-column {first} \\")
        lines.append(f"  --data-root <market_data_dir> \\")
        lines.append(f"  --timespan YYYYMMDD YYYYMMDD")
    lines.append("```")
    lines.append("")

    readme_path = run_dir / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] Run README → {readme_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Shared expression engine for Fundamental Alpha.

Loads operators from references/operators.json, builds evaluation namespaces
over the fundamental panel, and computes agent-defined custom features
(new_features). Shared by validate_fundamental_alphas.py and
materialize_alphas.py so both stages see the identical augmented field space.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_OPERATORS_PATH = (
    Path(__file__).resolve().parent.parent / "references" / "operators.json"
)


def load_operators() -> list[dict]:
    """Load operator definitions from operators.json."""
    if not _OPERATORS_PATH.is_file():
        print(f"[WARN] operators.json not found at {_OPERATORS_PATH}", file=sys.stderr)
        return []
    with open(_OPERATORS_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("operators", [])


def build_eval_namespace(
    panel_df: pd.DataFrame, operators: list[dict] | None = None
) -> dict:
    """Build the evaluation namespace: field columns + compiled operators."""
    if operators is None:
        operators = load_operators()

    namespace = {"np": np, "pd": pd}
    for col in panel_df.columns:
        namespace[col] = panel_df[col].values

    for op in operators:
        name = op["name"]
        impl = op.get("numpy_impl", "")
        if not impl:
            continue
        try:
            local_ns: dict = {}
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


def compute_new_features(
    panel_df: pd.DataFrame,
    new_feature_defs: list[dict],
    operators: list[dict] | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Compute agent-defined features and return the augmented DataFrame.

    Returns: (augmented_df, computed_names, errors)
    """
    df = panel_df.copy()
    computed: list[str] = []
    errors: list[str] = []

    for fdef in new_feature_defs:
        if not isinstance(fdef, dict):
            errors.append("Custom feature definition must be an object; skipped.")
            continue
        name = (fdef.get("name") or "").strip()
        expr = (fdef.get("expression") or "").strip()
        if not name or not expr:
            errors.append("Custom feature missing 'name' or 'expression'; skipped.")
            continue
        if name in df.columns:
            errors.append(
                f"Custom feature '{name}' collides with an existing column; skipped."
            )
            continue

        ns = build_eval_namespace(df, operators)
        try:
            values = np.asarray(eval(expr, {"__builtins__": {}}, ns), dtype=float)
        except Exception as e:
            errors.append(f"Custom feature '{name}' evaluation failed: {e}")
            continue

        df[name] = values
        computed.append(name)

    return df, computed, errors


def collect_new_features(alphas_data) -> list[dict]:
    """Gather custom feature definitions from top-level and per-alpha fields.

    Accepts a dict ({"alphas": [...], "new_features": [...]}) or a plain list.
    Returns a de-duplicated list (first declaration wins).
    """
    defs: list[dict] = []
    seen: set[str] = set()

    def _add(feature_list) -> None:
        if not isinstance(feature_list, list):
            return
        for fdef in feature_list:
            if not isinstance(fdef, dict):
                continue
            name = (fdef.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            defs.append(fdef)

    if isinstance(alphas_data, dict):
        _add(alphas_data.get("new_features"))
        for alpha in alphas_data.get("alphas", []):
            if isinstance(alpha, dict):
                _add(alpha.get("new_features"))

    return defs

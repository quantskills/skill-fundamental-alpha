#!/usr/bin/env python3
"""Generate fundamental alpha expressions from a document or natural language
query (or pure model invention).

Maps document/query concepts to the fundamental field catalog and produces
alpha expressions following the formula contract in
references/fundamental_ops.md.

Four input modes, all producing the same output:
    --doc paper.pdf            # research document (PDF/TXT/MD)
    --doc https://arxiv.org/... # any accessible URL with research text
    --query "cheap stocks ..."  # natural language query
    --query "invent 5 quality alphas"  # model invention from a paradigm

Usage:
    python generate_fundamental_alphas.py \
        --doc path/to/paper.txt \
        --fundamentals output/run_001/fundamentals.csv \
        --n 5 --output output/run_001/alphas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# Load operators catalog
# ═══════════════════════════════════════════════════════════════════════════════

_OPERATORS_PATH = Path(__file__).resolve().parent.parent / "references" / "operators.json"


def _load_operators() -> list[dict]:
    if _OPERATORS_PATH.is_file():
        with open(_OPERATORS_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("operators", [])
    return []


def _read_document(doc_path: Path) -> str:
    """Read text from a PDF, TXT, MD, or other document file."""
    suffix = doc_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(doc_path))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n\n".join(pages)
        except ImportError:
            print("[WARN] PyPDF2 not installed, trying raw read.", file=sys.stderr)
            return doc_path.read_text(encoding="utf-8", errors="replace")
    return doc_path.read_text(encoding="utf-8", errors="replace")


def _fetch_url(url: str) -> str:
    """Fetch text content from a URL (research pages, arXiv abstracts)."""
    import re
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(1500000).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] URL fetch failed: {e}", file=sys.stderr)
        return ""
    # Very small HTML → text extraction; enough to seed alpha generation.
    raw = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw,
                 flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _format_operator_catalog(operators: list[dict]) -> str:
    by_cat: dict[str, list[dict]] = {}
    for op in operators:
        cat = op.get("category", "other")
        by_cat.setdefault(cat, []).append(op)

    cat_names = {
        "cross_sectional": "Cross-Sectional (per date)",
        "time_series": "Time-Series Rolling",
        "lag": "Lag / Difference",
        "elementwise": "Element-Wise Math",
    }

    lines = []
    for cat_key in ["cross_sectional", "time_series", "lag", "elementwise"]:
        ops = by_cat.get(cat_key, [])
        if not ops:
            continue
        lines.append(f"\n### {cat_names.get(cat_key, cat_key)}")
        for op in ops:
            lookahead = " ⚠️ LOOKAHEAD-RISK (n≥1 required)" if op.get("lookahead_risk") else ""
            lines.append(f"  {op['signature']:40s} — {op['description']}{lookahead}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Concept → Field Mapping
# ═══════════════════════════════════════════════════════════════════════════════

CONCEPT_MAP = {
    # Value
    "value": ["ep_ttm", "bm_lf", "sp_ttm", "cfp_ttm", "div_yield_ttm",
              "ev_ebitda_ttm", "pe_ttm"],
    "cheap": ["ep_ttm", "bm_lf", "sp_ttm", "cfp_ttm", "pe_ttm"],
    "undervalued": ["ep_ttm", "bm_lf", "ev_ebitda_ttm"],
    "value investing": ["ep_ttm", "bm_lf", "cfp_ttm", "div_yield_ttm"],
    "distressed": ["debt_to_assets", "ocf_to_debt_ttm", "int_debt_lf",
                   "current_ratio"],

    # Profitability / quality
    "quality": ["roe_ttm", "gross_margin", "op_margin", "accruals_ttm",
                "ocf_to_ni", "surplus_cash_multi_ttm"],
    "profitability": ["roe_ttm", "roa_ttm", "gross_margin", "op_margin",
                      "np_margin"],
    "roe": ["roe_ttm", "eq_mrq1", "ni_mrq1"],
    "margin": ["gross_margin", "op_margin", "np_margin"],
    "junk": ["accruals_ttm", "debt_to_assets", "goodwill_to_assets"],
    "accrual": ["accruals_ttm", "ocf_to_ni", "surplus_cash_multi_ttm"],
    "sloan": ["accruals_ttm"],

    # Growth
    "growth": ["rev_yoy", "ni_yoy", "ocf_yoy", "fc_growth_mid", "eps_ttm"],
    "momentum": ["rev_yoy", "ni_yoy", "fc_revision", "rev_mrq1", "ni_mrq1"],
    "garp": ["peg_ttm", "ni_yoy", "pe_ttm"],
    "peg": ["peg_ttm", "pe_ttm"],

    # Cash flow
    "cash flow": ["ocf_to_assets", "ocf_to_ni", "fcff_ttm", "fcfe_ttm",
                  "ocf_to_debt_ttm", "surplus_cash_multi_ttm", "cfp_ttm"],
    "cashflow": ["ocf_to_assets", "ocf_to_ni", "fcff_ttm", "fcfe_ttm",
                 "ocf_to_debt_ttm", "surplus_cash_multi_ttm", "cfp_ttm"],
    "free cash flow": ["fcff_ttm", "fcfe_ttm", "fcff_per_share_ttm",
                       "fcfe_per_share_ttm", "mktcap"],
    "earnings quality": ["accruals_ttm", "ocf_to_ni", "surplus_cash_multi_ttm"],

    # Leverage / liquidity
    "leverage": ["debt_to_assets", "int_debt_lf", "ocf_to_debt_ttm",
                 "total_liab"],
    "debt": ["debt_to_assets", "int_debt_lf", "ocf_to_debt_ttm"],
    "liquidity": ["current_ratio", "cash_to_assets", "non_int_cur_liab_lf"],
    "solvency": ["debt_to_assets", "current_ratio", "ocf_to_debt_ttm",
                 "ebitda_to_int_ttm"],

    # Forecast / revision
    "forecast": ["fc_np_mid", "fc_eps_mid", "fc_growth_mid", "fc_width",
                 "fc_type_score", "fc_revision"],
    "revision": ["fc_revision", "fc_type_score", "fc_width"],
    "expectation": ["fc_revision", "fc_growth_mid", "fc_type_score"],
    "guidance": ["fc_growth_mid", "fc_width", "fc_type_score"],
    "earnings surprise": ["fc_type_score", "fc_revision", "ni_yoy"],

    # Ownership / events
    "ownership": ["holder_count", "holder_change_yoy"],
    "shareholder": ["holder_count", "holder_change_yoy"],
    "chip concentration": ["holder_change_yoy", "holder_count"],
    "buyback": ["buyback_value_ttm", "buyback_percent", "mktcap"],
    "repurchase": ["buyback_value_ttm", "buyback_percent", "mktcap"],

    # Misc
    "dividend": ["div_yield_ttm"],
    "size": ["mktcap"],
    "small cap": ["mktcap"],
    "rd": ["rd_to_revenue"],
    "innovation": ["rd_to_revenue", "goodwill_to_assets"],
    "reversal": ["rev_yoy", "ni_yoy", "fc_revision"],
}


def map_query_to_fields(query: str) -> list[str]:
    """Map a natural language query to relevant fundamental panel columns."""
    query_lower = query.lower()
    matched = set()

    for concept, fields in CONCEPT_MAP.items():
        if concept in query_lower:
            matched.update(fields)

    if not matched:
        matched = {
            "ep_ttm", "roe_ttm", "ni_yoy", "ocf_to_assets",
            "accruals_ttm", "debt_to_assets", "holder_change_yoy",
            "fc_revision",
        }

    return sorted(matched)


def build_agent_prompt(
    text: str,
    field_columns: list[str],
    n_alphas: int,
    fundamentals_df: Optional[pd.DataFrame] = None,
    operators: Optional[list[dict]] = None,
) -> str:
    """Build the prompt for the LLM agent to generate fundamental alphas."""
    if operators is None:
        operators = _load_operators()

    operator_catalog = _format_operator_catalog(operators)

    field_stats = ""
    if fundamentals_df is not None:
        stats_lines = []
        for col in field_columns:
            if col in fundamentals_df.columns:
                s = fundamentals_df[col]
                stats_lines.append(
                    f"  {col}: mean={s.mean():.4f}, std={s.std():.4f}, "
                    f"min={s.min():.4f}, max={s.max():.4f}"
                )
        if stats_lines:
            field_stats = (
                "\nFIELD STATISTICS (for context):\n"
                + "\n".join(stats_lines[:25])
                + "\n"
            )

    prompt = f"""You are a quantitative researcher specializing in A-share
fundamental investing. Based on the following document or query, generate
exactly {n_alphas} novel alpha factor expressions for stock selection using
the point-in-time fundamental panel described below.

DOCUMENT / QUERY:
{text}

AVAILABLE FUNDAMENTAL FIELDS (date × symbol panel, point-in-time correct):
{chr(10).join(f'  - {f}' for f in field_columns)}

{field_stats}
AVAILABLE OPERATORS (from operators.json):
{operator_catalog}

CRITICAL — POINT-IN-TIME (PIT) DISCIPLINE:
- The panel is already PIT: every value reflects only information known at
  that date (statement values lagged by filing date, ownership/forecast
  values lagged by announcement date).
- delay(x, n), delta(x, n), and returns(x, n) MUST use n ≥ 1.
- Do not assume future filings are known: never combine a field with a
  zero-lag forward-looking window.

CRITICAL — NUMERICAL STABILITY:
- Never divide by something that could be zero. Use max(denom, 1e-8).
- Never take log(x) without ensuring x > 0: use log(max(x, 1e-8)).
- Fundamental panels are sparse: use fillna_median(x) where coverage is low.
- Prefer rank() and zscore() based expressions — they are naturally stable.
- pe_ttm / peg_ttm / ev_ebitda_ttm are undefined for loss-makers; guard them.

OPERATOR EXTENSION RULE:
You MAY propose NEW operators not listed above if the document/query requires
a custom computation. For each new operator, provide:
  - "new_operator": {{"name": "...", "signature": "...", "description": "...", "category": "..", "numpy_impl": "lambda ..."}}
  - The operator will be added to operators.json and validated.
Standard arithmetic (+, -, *, /) and parentheses are always available.

FEATURE EXTENSION RULE:
You MAY define NEW fundamental features if the document/query requires a
signal not present in the catalog. Each new feature must be computable as an
expression over EXISTING fields and operators, provided in a "new_features"
list (top-level or on each alpha):
  "new_features": [{{"name": "my_feature", "expression": "ts_mean(ocf_to_assets, 60) / max(debt_to_assets, 1e-8)", "description": "...", "formula": "...", "family": "custom"}}]
- New features are computed in declaration order; later features may reference earlier ones.
- Do NOT reuse an existing catalog field name.

REQUIRED — ACADEMIC ATTRIBUTION:
- For each alpha, cite the specific academic paper, research article, or
  document passage that inspired it in a "source" field (full APA citation).
- Provide a "source_link" with a DOI or arXiv URL. Use null if unavailable.

OUTPUT FORMAT:
Return a JSON array of objects with keys:
  name, expression, description, rationale, signal_family, source, source_link,
  new_operator (optional, only if proposing a new operator),
  new_features (optional, list of custom feature definitions)

Where signal_family is one of:
  valuation, profitability, growth, cashflow, leverage, liquidity,
  forecast, ownership, custom
"""
    return prompt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate fundamental alpha expressions from document/query."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--doc", help="Path to document file or URL.")
    input_group.add_argument("--query", help="Natural language query or invention paradigm.")
    parser.add_argument("--fundamentals", default=None, help="fundamentals.csv path.")
    parser.add_argument("--n", type=int, default=5, help="Number of alphas to generate.")
    parser.add_argument("--output", default=None, help="Output JSON path.")
    parser.add_argument("--run-name", default=None,
                        help="Run name. Resolves fundamentals.csv in run dir.")
    args = parser.parse_args()

    if args.run_name:
        out_root = Path(__file__).resolve().parent.parent / "output"
        candidates = sorted(out_root.glob(f"run_*_{args.run_name}"), reverse=True)
        if not candidates:
            print(f"[FATAL] No run dir matching '*_{args.run_name}'", file=sys.stderr)
            sys.exit(1)
        run_dir = candidates[0]
        args.fundamentals = str(run_dir / "fundamentals.csv")
        args.output = str(run_dir / "alphas.json")
        print(f"[INFO] Matched: {run_dir.name}", file=sys.stderr)
    elif not args.fundamentals or not args.output:
        print("[FATAL] Requires --fundamentals and --output, or --run-name.",
              file=sys.stderr)
        sys.exit(1)

    fundamentals_df = pd.read_csv(args.fundamentals)
    field_columns = sorted(
        [c for c in fundamentals_df.columns if c not in ("date", "symbol")]
    )
    print(
        f"[INFO] Loaded {len(field_columns)} fields from {args.fundamentals}.",
        file=sys.stderr,
    )

    # Read input text (document file, URL, or query)
    input_type = "query"
    if args.doc:
        doc_ref = args.doc
        if doc_ref.startswith(("http://", "https://")):
            text = _fetch_url(doc_ref)
            input_type = "url"
            if not text:
                print("[FATAL] URL fetch returned no usable text.", file=sys.stderr)
                sys.exit(1)
        else:
            doc_path = Path(doc_ref)
            if not doc_path.is_file():
                print(f"[FATAL] Document not found: {args.doc}", file=sys.stderr)
                sys.exit(1)
            text = _read_document(doc_path)
            input_type = "document"
        print(f"[INFO] Input ({input_type}): {len(text)} chars.", file=sys.stderr)
    else:
        text = args.query
        print(f"[INFO] Query: {args.query[:80]}...", file=sys.stderr)

    # Map query → relevant fields
    if input_type == "query":
        relevant = [f for f in map_query_to_fields(args.query)
                    if f in field_columns]
        print(f"[INFO] Query mapped to {len(relevant)} relevant fields: "
              f"{relevant[:10]}...", file=sys.stderr)
    else:
        relevant = field_columns

    operators = _load_operators()
    prompt = build_agent_prompt(
        text=text,
        field_columns=relevant,
        n_alphas=args.n,
        fundamentals_df=fundamentals_df,
        operators=operators,
    )

    output = {
        "prompt": prompt,
        "n_alphas": args.n,
        "relevant_fields": relevant,
        "all_fields": field_columns,
        "input_type": input_type,
        "operators_catalog": str(_OPERATORS_PATH),
        "operator_count": len(operators),
        "instructions": (
            "Pass the 'prompt' field to an LLM agent (Claude, GPT-4, etc.). "
            "The agent should return a JSON array of alpha objects with keys: "
            "name, expression, description, rationale, signal_family, source, source_link. "
            "Optionally include 'new_operator' to propose a new function, or "
            "'new_features' to define custom fundamental features. "
            "Then run validate_fundamental_alphas.py to check correctness."
        ),
        "alphas": [],  # To be filled by the agent
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(
        f"[INFO] Prompt saved → {output_path}\n"
        f"[INFO] Feed this prompt to an LLM agent. The agent should return "
        f"{args.n} alpha objects as a JSON array.",
        file=sys.stderr,
    )
    print(f"\n{'='*60}\nPROMPT PREVIEW:\n{'='*60}\n{prompt[:1500]}...", file=sys.stderr)


if __name__ == "__main__":
    main()

# Portable Loader Prompt — Fundamental Alpha

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does
not natively discover `SKILL.md` folders.

```text
You have access to a local skill named fundamental-alpha at:
<<SKILL_ROOT>>

When the user asks to generate alpha factors from fundamental data,
financial statements, valuation or quality signals, earnings forecasts,
ownership/buyback signals, or any document discussing
fundamental-based stock selection:

1. Read <<SKILL_ROOT>>/SKILL.md.
2. Read <<SKILL_ROOT>>/references/fundamental_ops.md for the formula
   contract — all allowed fields and functions.
3. Read <<SKILL_ROOT>>/config.json for current hyperparameters.
4. Ensure PandaData credentials are set in <<SKILL_ROOT>>/.env.
5. Fetch fundamental data:
   python <<SKILL_ROOT>>/scripts/fetch_fundamental_data.py \
     --start-date YYYYMMDD --end-date YYYYMMDD \
     --start-quarter YYYYqN --end-quarter YYYYqN \
     --universe 000300 --output output/run_<ts>/
6. Build the point-in-time panel:
   python <<SKILL_ROOT>>/scripts/build_pit_fundamentals.py \
     --input-dir output/run_<ts>/ \
     --output output/run_<ts>/fundamentals.csv
7. Generate alphas from the user's document or query:
   python <<SKILL_ROOT>>/scripts/generate_fundamental_alphas.py \
     --query "<user's query or paste doc text>" \
     --fundamentals output/run_<ts>/fundamentals.csv \
     --n 5 --output output/run_<ts>/alphas.json
   OR for a file / URL:
   python <<SKILL_ROOT>>/scripts/generate_fundamental_alphas.py \
     --doc "<path/to/document or https://...>" \
     --fundamentals output/run_<ts>/fundamentals.csv \
     --n 5 --output output/run_<ts>/alphas.json
8. Validate:
   python <<SKILL_ROOT>>/scripts/validate_fundamental_alphas.py \
     --alphas output/run_<ts>/alphas.json \
     --fundamentals output/run_<ts>/fundamentals.csv \
     --output output/run_<ts>/validated_alphas.json
   If alphas fail, re-run with --correction-context and feed the fix prompt
   back to the LLM (retry up to 5 times).
9. Read validated_alphas.json. Present to the user:
   - Each alpha expression with its name, description, rationale
   - The signal family used (valuation, quality, growth, ...)
   - Validation status (passed / corrected / failed)
   - PIT audit info (pit_rule per field used)
   - Academic source attribution
```

Runtime placement notes:
- Codex: keep under a Codex skill path, invoke `$fundamental-alpha`.
- Claude Code: keep under a Claude skill path, invoke `$fundamental-alpha`.
- Cursor: copy to `.cursor/skills/fundamental-alpha`, enable `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount as local skill root or paste loader prompt with real path.

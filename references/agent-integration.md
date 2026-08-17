# Agent Integration Guide — Fundamental Alpha

## Supported Platforms

| Platform | Config | Instructions |
|:---|:---|:---|
| Claude Code | `agents/openai.yaml` | Register as skill, invoke `$fundamental-alpha` |
| Codex | `agents/openai.yaml` | Register as skill, invoke `$fundamental-alpha` |
| Cursor | `agents/cursor-rule.mdc` | Copy to `.cursor/skills/fundamental-alpha/`, enable rule |
| OpenClaw / Hermes | `agents/portable-loader.md` | Paste loader prompt with real `<<SKILL_ROOT>>` |

## Prerequisites

1. **Python 3.10+** with `panda_data>=0.1.0`, `pandas`, `numpy`.
2. **PandaData credentials** in `.env` (see `.env.example`).
3. **Network access** to `http://pandadata.pandaaiquant.com`.

## Cross-Agent Smoke Test

After installing the skill:

```bash
# 1. Verify fundamental data fetch works (statements + precomputed factors + ownership)
python scripts/fetch_fundamental_data.py \
  --start-date 20240101 --end-date 20240301 \
  --start-quarter 2021q1 --end-quarter 2023q4 \
  --universe 000300 \
  --output /tmp/test_fetch/

# 2. Verify PIT panel construction
python scripts/build_pit_fundamentals.py \
  --input-dir /tmp/test_fetch/ \
  --output /tmp/test_fundamentals.csv

# 3. Verify alpha generation (NL query mode)
python scripts/generate_fundamental_alphas.py \
  --query "cheap stocks with improving cash flow" \
  --fundamentals /tmp/test_fundamentals.csv \
  --n 2 \
  --output /tmp/test_alphas.json

# 4. Verify validation
python scripts/validate_fundamental_alphas.py \
  --alphas /tmp/test_alphas.json \
  --fundamentals /tmp/test_fundamentals.csv \
  --output /tmp/test_validated.json
```

All four commands should exit 0 and produce non-empty output files.

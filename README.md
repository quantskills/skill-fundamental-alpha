# Fundamental Alpha

基于**基本面数据**（PandaData）生成 Alpha 因子表达式。从财务报表、估值指标、
现金流衍生、业绩预告与股东信号中构建**点对点（PIT）正确的**基本面
面板（80 个字段，7 大信号族），并输出经过验证、可直接用于日频回测的 Alpha
表达式。智能体可通过自定义特征（`new_features`）和自定义算子（`new_operator`）
扩展目录。输入可以是研报、链接、自然语言查询，或直接由模型构思范式。

## 快速开始

```bash
# 1. 在 .env 中配置凭证

# 2. 拉取基本面数据 + 构建 PIT 面板（使用 config.json 默认参数）
python scripts/fetch_fundamental_data.py --run-name myrun
python scripts/build_pit_fundamentals.py --run-name myrun

# 3. 生成 Alpha —— 选择输入模式：
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc paper.pdf --n 5                    # 文档
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --doc "https://arxiv.org/abs/..." --n 5  # 链接
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "cheap stocks with improving cash flow" --n 5   # 自然语言
python scripts/generate_fundamental_alphas.py --run-name myrun \
  --query "invent 5 quality alphas" --n 5  # 模型构思

# 4. 在 output/<run>/alphas.json 中填写 Alpha（由 LLM 智能体完成）

# 5. 验证（自动生成 backtest_factors/ + README.md）
python scripts/validate_fundamental_alphas.py --run-name myrun
```

## 运行输出

每次验证后的运行都会生成：

```
output/<run>/
├── README.md                    # 自动生成的文档
├── statements.csv               # 季度财报原始数据（含重述历史）
├── factors.csv                  # ratio/cfd/fin/mrq 预计算因子
├── market_data.csv              # 日线行情
├── forecast.csv                 # 业绩预告
├── holder_count.csv / repurchase.csv     # 股东信号
├── fundamentals.csv             # PIT 基本面面板（date,symbol,field）
├── fundamental_definitions.json # 字段目录及公式 + PIT 规则
├── data_report.json             # 面板覆盖率统计
├── alphas.json                  # Alpha 表达式
├── validated_alphas.json        # 已验证 Alpha + 展开公式
└── backtest_factors/            # 日频因子 CSV（可直接回测）
    ├── <alpha1>.csv             # date,ticker,value
    └── <alpha2>.csv
```

## 回测集成

回测因子在验证阶段**自动生成**，可直接回测：

```bash
python ../skill-factor-backtest/scripts/run_factor_backtest.py \
  --input-file output/<run>/backtest_factors/<alpha>.csv \
  --factor-column <alpha_name> \
  --data-root <market_data_dir> --timespan YYYYMMDD YYYYMMDD
```

## 环境要求

- Python 3.10+
- `panda_data>=0.1.0`
- 在 `.env` 中配置有效的 PandaData 凭证

## 参数（config.json）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `universe` | `000300` | 沪深300、中证500、中证1000、上证50 |
| `start_date` / `end_date` | `20240101` / `20250801` | 日频数据区间 |
| `start_quarter` / `end_quarter` | `2021q1` / `2025q2` | 财报历史区间（TTM/YoY 需 ≥ 9 个季度） |
| `pit_lag_days` | `1` | 公告日后数据生效的滞后天数 |
| `max_alphas` | `5` | 每次运行的默认 Alpha 数量 |

## 免责声明

本仓库仅作研究方法层面的整理，不构成任何投资建议。

## 许可证

GPL-3.0-only

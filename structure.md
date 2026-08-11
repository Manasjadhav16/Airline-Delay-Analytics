# Project Structure

airline-delay-analytics/
├── CLAUDE.md              # Instructions for Claude Code agent
├── STRUCTURE.md           # This file
├── README.md              # Project overview (for GitHub)
├── requirements.txt       # Python dependencies
├── .gitignore
├── data/
│   ├── raw/                # Original Kaggle CSV (never modified)
│   └── processed/          # Cleaned/aggregated data (parquet, csv)
├── notebooks/
│   └── analysis.ipynb      # Final Colab-ready notebook
├── src/
│   ├── ingest.py           # Load raw data into Spark
│   ├── clean.py            # Data cleaning logic
│   ├── aggregate.py        # Delay-by-carrier/airport/month queries
│   ├── eda.py               # Chart generation
│   └── model.py             # Random Forest delay prediction
├── outputs/
│   ├── charts/              # PNGs for report/PPT
│   └── metrics/             # JSON model performance results
├── docs/
│   └── architecture.png     # Pipeline diagram
└── tests/
    └── test_pipeline.py
# Contributing to Data Engineering

Thank you for your interest in contributing to the Data Engineering project!

## Getting Started

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your environment variables

## Project Structure

```
data-engineering/
├── src/                    # Source code
│   ├── aggregator/         # Org aggregator Lambda
│   ├── categorizer/        # Auto-categorizer Lambda
│   ├── scrapers/           # Web scrapers
│   ├── models/             # Data models
│   ├── translation/        # Translation utilities
│   └── utils/              # Shared utilities
├── datasets/               # Data files (gitignored)
├── notebooks/              # Jupyter notebooks
├── tests/                  # Test files
├── infrastructure/         # Docker, K8s configs
└── scripts/                # Deployment scripts
```

## Code Style

- Follow PEP 8 guidelines
- Use snake_case for file names and functions
- Add docstrings to functions and classes

## Pull Request Process

1. Create a feature branch from `dev`
2. Make your changes
3. Update documentation if needed
4. Submit a PR for review

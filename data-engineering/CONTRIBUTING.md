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

## Where to Create New Files

To maintain a clean project structure, please follow these guidelines when adding new code.

### Adding a New Lambda Function

All Lambda functions live under `src/`. Create a new folder for your Lambda:

```
src/
└── your_lambda_name/
    ├── __init__.py          # Required - makes it a Python package
    ├── handler.py           # Entry point for the Lambda
    ├── requirements.txt     # Lambda-specific dependencies
    └── other_modules.py     # Supporting code (optional)
```

**Steps:**
1. Create folder: `mkdir src/your_lambda_name`
2. Add `__init__.py`: `touch src/your_lambda_name/__init__.py`
3. Create `handler.py` with your Lambda entry point
4. Add a `requirements.txt` with dependencies specific to this Lambda
5. Add a deploy script: `scripts/deploy/deploy_your_lambda.sh`

**Example:** See `src/aggregator/` or `src/categorizer/` for reference.

### Adding a New Scraper

Scrapers go under `src/scrapers/`. Choose the appropriate subfolder:

| Scraper Type | Location |
|--------------|----------|
| Emergency contacts | `src/scrapers/emergency_contacts/` |
| NGO data | `src/scrapers/ngo/` |
| New category | Create `src/scrapers/your_category/` |

**Naming convention:** Use lowercase with underscores (e.g., `united_states.py`, not `UnitedStates.py`)

**Steps for a new scraper:**
1. Add your scraper file: `src/scrapers/ngo/country_name.py`
2. If creating a new category:
   ```
   mkdir src/scrapers/your_category
   touch src/scrapers/your_category/__init__.py
   ```
3. Output raw data to `datasets/raw/`
4. Output cleaned data to `datasets/cleaned/`

### Working with Data Files

**Never commit large data files to git.** The `datasets/` folder is gitignored.

| Data State | Location |
|------------|----------|
| Raw/unprocessed | `datasets/raw/` |
| Cleaned/processed | `datasets/cleaned/` |

Use relative paths in your code:
```python
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw_path = os.path.join(PROJECT_ROOT, 'datasets', 'raw', 'your_file.csv')
```

### Adding Database Models

Database models go in `src/models/`:

```
src/models/
├── __init__.py
├── fraud_requests.py    # Existing model
└── your_model.py        # Add new models here
```

**Naming:** Use snake_case for filenames, PascalCase for class names.

### Working with the Database Layer (Future: Vector Store Migration)

> **Heads up:** We're planning to migrate from PostgreSQL to a vector database (Redis, Pinecone, etc.) for certain use cases.

**Current database code:**
- Connection helpers: `src/utils/` (add `db_client.py` here)
- ORM models: `src/models/`

**When adding database code:**
1. **Don't** scatter database connections across files
2. **Do** use `src/utils/db_client.py` for all DB connections
3. **Do** abstract your queries so they can be swapped out later

**Example pattern:**
```python
# src/utils/db_client.py
class DatabaseClient:
    """Abstraction layer for database operations.
    
    When we migrate to Redis/vector store, we only need to
    change this file, not every file that uses the DB.
    """
    def __init__(self):
        # Currently PostgreSQL
        self.conn = get_postgres_connection()
    
    def search_similar(self, query_vector):
        # TODO: Replace with vector store search
        pass
```

### Shared Utilities

Reusable helpers (AWS clients, logging, config) go in `src/utils/`:

```
src/utils/
├── __init__.py
├── db_client.py       # Database connections
├── aws_client.py      # AWS SDK helpers
├── genai_client.py    # OpenAI/Gemini wrappers
└── logger.py          # Logging setup
```

### Quick Reference

| Task | Create files in |
|------|-----------------|
| New Lambda function | `src/your_lambda/` |
| New scraper (existing category) | `src/scrapers/category/` |
| New scraper category | `src/scrapers/new_category/` |
| Database model | `src/models/` |
| Shared utility | `src/utils/` |
| Jupyter notebook | `notebooks/` |
| Test file | `tests/` |
| Deploy script | `scripts/deploy/` |
| Docker/K8s config | `infrastructure/` |

## Pull Request Process

1. Create a feature branch from `dev`
2. Make your changes
3. Update documentation if needed
4. Submit a PR for review

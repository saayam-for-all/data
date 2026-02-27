# Contributing to Data Engineering

> **This is your day-to-day reference for working in this codebase.** Repo structure, setup, code standards, where to put files, and how to submit work — it's all here.

---

## Local Setup

```bash
git clone -b dev https://github.com/saayam-for-all/data.git
cd data
python -m venv venv
source venv/bin/activate    # macOS/Linux — or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env        # Fill in your environment variables
```

### Local Development First

**You will not get AWS Lambda/S3 access.** You develop and test locally with mock data. When your code works, let the team leads know — they handle AWS deployment. Structure your code so AWS calls can be easily mocked.

---

## Tech Stack

| Tech | Purpose |
|------|---------|
| **Python** | Primary language |
| **AWS Lambda** | Serverless functions (team leads deploy — you don't get access) |
| **AWS S3** | Data lake storage |
| **PostgreSQL (Aurora)** | Primary database |
| **boto3** | AWS SDK for Python |
| **SQLAlchemy** | ORM for database interactions |
| **pandas** | Data cleaning and manipulation |
| **Docker** | Containerization |

---

## Repository Structure

```
data-engineering/
├── .env.example
├── .gitignore
├── CONTRIBUTING.md
├── KNOWLEDGE_TRANSFER.md
├── README.md
├── TASK_TRACKER.md
├── requirements.txt
│
├── datasets/
│   ├── cleaned/
│   └── raw/
│
├── infrastructure/
│   ├── deployment.yaml
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── service.yaml
│
├── notebooks/
│   └── analytics_sql_and_visualizations.ipynb
│
├── scripts/
│   └── deploy/
│       ├── deploy_aggregator.sh
│       └── deploy_categorizer.sh
│
├── src/
│   ├── __init__.py
│   ├── app.py
│   ├── config.py
│   ├── extensions.py
│   ├── main.py
│   │
│   ├── aggregator/
│   │   ├── __init__.py
│   │   ├── db_client.py
│   │   ├── genai_client.py
│   │   ├── handler.py
│   │   ├── merger.py
│   │   └── requirements.txt
│   │
│   ├── categorizer/
│   │   ├── __init__.py
│   │   ├── categories.py
│   │   ├── classifier.py
│   │   ├── handler.py
│   │   └── requirements.txt
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── fraud_requests.py
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── emergency_contacts/
│   │   │   ├── __init__.py
│   │   │   ├── cleaner.py
│   │   │   ├── loader.py
│   │   │   └── scraper.py
│   │   └── ngo/
│   │       ├── __init__.py
│   │       ├── afghanistan.py
│   │       ├── india.py
│   │       └── malaysia.py
│   │
│   ├── translation/
│   │   ├── __init__.py
│   │   └── lang_detection.py
│   │
│   └── utils/
│       └── __init__.py
│
└── tests/

data-analytics/
├── README.md
└── notebooks/
```

---

## How to Contribute

### Task Assignment

**Do not self-assign tasks.** Do not edit issue descriptions or user stories. Task assignment and issue management are the responsibility of **team leads and project managers**. If you want to work on something, let us know in the team meeting or WhatsApp group and we will assign it to you.

### Branch Naming

```
<your_github_username>_<issue_number>_<brief_description>
```
Example: `saquibb8_100_auto_categorize_requests`

### Workflow

1. Get assigned a task by a team lead or PM.
2. Branch off `dev`: `git checkout -b <your_branch_name>`
3. Develop and test locally with mock data.
4. Commit with issue references: `git commit -m "#100: Add classification logic"`
5. Push and create a PR targeting `dev` (never `main`). Assign reviewers.
6. Address code review feedback. PRs need **at least 2 reviews**.
7. Team lead merges after approval.

### What NOT to Do

- ❌ Don't push directly to `main` or `dev`.
- ❌ Don't self-assign tasks or edit issue descriptions.
- ❌ Don't commit secrets, API keys, or AWS credentials.
- ❌ Don't disappear after being assigned a task.

---

## Code Standards

- Python 3.10+, PEP 8, type hints where practical.
- `snake_case` for file names and functions, `PascalCase` for class names.
- Docstrings for all functions and classes.
- No credentials in code — use `.env` files.
- Never commit `__pycache__/`, `venv/`, `.env`, or IDE files.
- Update `requirements.txt` if you add dependencies.

---

## Where to Create New Files

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

---

*Last updated: February 2026*

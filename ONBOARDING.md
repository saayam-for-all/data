# Saayam For All — Data Engineering Team

> **⚠️ Read this entire document before you start working on any task.**
> It will save you (and us) a lot of time. Seriously.

---

## Table of Contents

1. [What is Saayam For All?](#what-is-saayam-for-all)
2. [How the Organization Works](#how-the-organization-works)
3. [The Data Engineering Team](#the-data-engineering-team)
4. [Tech Stack](#tech-stack)
5. [Repository Structure](#repository-structure)
6. [How the Data Repo Connects to Other Repos](#how-the-data-repo-connects-to-other-repos)
7. [Getting Started — Setup & Access](#getting-started--setup--access)
8. [How to Contribute](#how-to-contribute)
9. [Beginner Task](#beginner-task)
10. [Expectations & Formalities](#expectations--formalities)
11. [Key Contacts](#key-contacts)
12. [FAQs](#faqs)

---

## What is Saayam For All?

Saayam For All is a **501(c)(3) nonprofit** building an "Uber for Help" platform — a web and mobile application that connects people in need (beneficiaries) with volunteers and organizations that can help them with basic necessities like food, shelter, healthcare, education, and general advice.

- **Website (latest features, test env):** [test-saayam.netlify.app](https://test-saayam.netlify.app/)
- **Website (production):** [saayam.netlify.app](https://saayam.netlify.app/)
- **GitHub Organization:** [github.com/saayam-for-all](https://github.com/saayam-for-all/)
- **EIN:** 93-2798273 | **Location:** San Jose, CA
- **Email:** info@SaayamForAll.org

### How It Works

A user submits a help request (e.g., "I need emergency food assistance in Austin, TX"). The platform matches them with nearby volunteers and relevant organizations based on category, location, and language preferences. Think of it as **Lyft meets Tinder meets 911** — request help, get matched, get helped.

The platform has four user roles: **Beneficiaries** (help seekers), **Volunteers** (helpers), **Organizations** (registered charities), and **Admins**.

> 💡 **Your first action:** Go to [test-saayam.netlify.app](https://test-saayam.netlify.app/) and explore. Create an account, submit a test help request, look at the categories and subcategories. Understand the product you are building for — this context is essential for every task you work on.

---

## How the Organization Works

### Communication

- **Daily Scrum Call:** Every weekday at **10:00 AM PST** on Zoom, led by **Rao Bhethanabotla**. The Zoom link is posted in the WhatsApp Organization group each morning. This is the single best way to get oriented and unblocked. **If you have received an offer letter, attending this call is mandatory.** If you cannot attend, send your status update to your team's WhatsApp group.
-**Weekly Team Meet⚠️:** Every week at **03:00 PM CST** 
- **WhatsApp Groups:** This is the primary communication channel. You will be added to the main group and Data Engineering/Analytics group. Always post questions in Data Engineering/Analytics group first. If no response within 24 hours, escalate to the main group. First escalate to Team Leads and final escalation goes to Rao.
- **Important:** Our volunteers are from different countries and time zones. Never call someone directly without checking their availability via WhatsApp first. Even a direct text message might cost money in some countries.

### Meetings & Recordings

- All Zoom meetings are recorded and preserved.
- All WhatsApp communications are preserved.

### Offer Letters

Saayam offers official **volunteering/interning offer letters**. Contact Sri Tejaswi Vadapalli or Sharanya Domakonda for these. If you have received an offer letter, daily scrum attendance and weekly status updates are mandatory. Volunteers who do not attend scrum or send status updates for one week without prior notice will have their offer letter voided.

### Org-Wide Onboarding Wiki

For more detailed information about the organization beyond what is covered here, read the full onboarding guide:
**[New Volunteer Onboarding Wiki](https://github.com/saayam-for-all/docs/wiki/New-Volunteer-Onboarding)**

---

## The Data Engineering Team

### What We Do

The Data Engineering team is responsible for building the **data pipeline** that powers Saayam's intelligent features. Our work sits at the center of the platform — we take raw data from various sources, clean and transform it, and make it available for the AI team and the frontend to consume.

### Our Current Work

Here is what the team is actively working on:

| Issue | Title | Status | Description |
|-------|-------|--------|-------------|
| [#98](https://github.com/saayam-for-all/data/issues/98) | Aggregate Organization Listings from Multiple Sources | ✅ Completed | Built the `saayam-org-aggregator` Lambda that pulls org data from the Saayam DB and the GenAI Lambda, merges them, and returns a unified list |
| [#99](https://github.com/saayam-for-all/data/issues/99) | Integrate Org Aggregator to Display Context-Aware Suggestions | 🔄 Open | Wire up the org-aggregator Lambda endpoint to the webapp frontend (cross-team task: data + webapp) |
| [#100](https://github.com/saayam-for-all/data/issues/100) | Auto-Categorize Help Requests Using Lambda Function | 🔄 Open | Build a Lambda that uses an LLM to classify help requests into the correct category/subcategory |

### The Big Picture — Strategic Direction

The long-term vision for the data team is to build a full data pipeline:

```
PostgreSQL (RDBMS) → S3 Data Lake → Vectorize Data → Vector DB → AI Agent
```

This means periodically moving data from our relational database into an S3 data lake, vectorizing that data, storing it in a vector database, and ultimately powering an AI agent that understands Saayam's data. Future tasks will align with this pipeline.

---

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| **Python** | Primary language for all data engineering work |
| **AWS Lambda** | Serverless functions for data processing (deployed by team leads only) |
| **AWS S3** | Data lake storage for datasets |
| **PostgreSQL (Aurora)** | Primary relational database |
| **boto3** | AWS SDK for Python — used to interact with Lambda, S3, etc. |
| **SQLAlchemy** | ORM for database interactions |
| **pandas** | Data cleaning and manipulation |
| **Flask** | Lightweight API framework (used in some services) |
| **Docker** | Containerization for deployment |

### Important: Local Development First

**You will not get AWS Lambda access as a new volunteer.** This is by design — we cannot give Lambda/S3 access to everyone due to cost and security. Here is how development works:

1. You develop and test everything **locally** on your machine using mock/sample data.
2. Once your code is working and reviewed, you notify the team lead.
3. The team lead deploys your code to AWS Lambda.

This means your code should be structured so that AWS-specific calls (boto3, Lambda invocations, S3 reads) can be easily swapped with local mocks.

---

## Repository Structure

```
data/
├── README.md                          # This file — start here
├── KNOWLEDGE_TRANSFER.md              # Team knowledge transfer document
├── CONTRIBUTING.md                    # Contribution guidelines
├── requirements.txt                   # Python dependencies
├── .gitignore                         # Git ignore rules
│
├── src/                               # All source code
│   ├── aggregator/                    # Organization aggregator Lambda (#98)
│   ├── categorizer/                   # Help request auto-categorizer (#100)
│   ├── scrapers/                      # Web scraping scripts
│   │   ├── emergency_contacts/        # Emergency contact data extraction
│   │   └── ngo/                       # NGO data scrapers (Afghanistan, India, Malaysia, etc.)
│   ├── models/                        # SQLAlchemy models (FraudRequests, etc.)
│   ├── translation/                   # Language detection and translation
│   └── utils/                         # Shared utility functions
│
├── data/                              # Data files (CSVs, cleaned datasets)
│   ├── raw/                           # Unprocessed source data
│   └── cleaned/                       # Cleaned/processed data ready for use
│
├── notebooks/                         # Jupyter notebooks for analysis/EDA
│
├── tests/                             # Unit and integration tests
│
├── infrastructure/                    # Deployment configs
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── deployment.yaml
│   └── service.yaml
│
└── docs/                              # Additional documentation, architecture diagrams
```

> **Note:** The repo is currently being restructured to match this layout. See [PROPOSED_REPO_STRUCTURE.md](./PROPOSED_REPO_STRUCTURE.md) for the migration plan.

---

## How the Data Repo Connects to Other Repos

Saayam has 40+ repos but only **7 are actively developed**. Here is how our data repo fits into the bigger picture:

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER FACING                              │
│  webapp (React) ←──── api (AWS API Gateway) ←──── mobileapp    │
└────────┬────────────────────────┬───────────────────────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│   volunteer      │    │     request          │
│ (Java/Spring)    │    │  (Help request svc)  │
│ User profiles    │    │                      │
└────────┬─────────┘    └──────────┬───────────┘
         │                         │
         ▼                         ▼
┌──────────────────────────────────────────────┐
│              database (PostgreSQL)            │
│         Schema, stored procedures            │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│         data (Python) ← YOU ARE HERE         │
│  Scraping, cleaning, aggregation, pipelines  │
│  Lambdas: org-aggregator, auto-categorizer   │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│              ai (Python/Flask)               │
│  GenAI microservice: Gemini, ChatGPT, Grok  │
│  Zero-shot classification, AI agent          │
└──────────────────────────────────────────────┘

        devsecops — CI/CD, infrastructure, deployment (all teams)
```

### Active Repos You Should Know

| Repo | Team | What It Does | Why It Matters to Us |
|------|------|-------------|---------------------|
| **[data](https://github.com/saayam-for-all/data)** | Data Engineering | Data pipelines, scraping, Lambdas | **Our repo** |
| **[webapp](https://github.com/saayam-for-all/webapp)** | Frontend | React web application | Consumes our Lambda endpoints (e.g., org-aggregator) |
| **[ai](https://github.com/saayam-for-all/ai)** | GenAI | Multi-model AI assistant (Flask) | Downstream consumer — our vectorized data feeds their AI agent |
| **[api](https://github.com/saayam-for-all/api)** | Backend | AWS API Gateway routing | Routes frontend requests to our Lambdas |
| **[database](https://github.com/saayam-for-all/database)** | Database | PostgreSQL schema, stored procedures | Source of truth — we extract data from here |
| **[volunteer](https://github.com/saayam-for-all/volunteer)** | Backend | User/volunteer profile APIs (Java/Spring) | Provides volunteer data we may need to aggregate |
| **[devsecops](https://github.com/saayam-for-all/devsecops)** | Infrastructure | CI/CD, Docker, Kubernetes, AWS | Manages our deployment pipeline |

---

## Getting Started — Setup & Access

### Step 1: Get Access

1. **Fill out the Access Hub form:** [https://forms.gle/Mg8J3fSvA7AAHVxq5](https://forms.gle/Mg8J3fSvA7AAHVxq5)
   - This gets you added to the GitHub organization and relevant WhatsApp groups.
   - Make sure your GitHub profile has your **real name and a profile picture** — this is required for task assignments.

2. **Join WhatsApp groups:** You will be added to the main Software group and the Data Engineering team group. Introduce yourself with: your full name, qualifications, school, location, and hobbies/interests.

3. **Attend the daily scrum:** 10:00 AM PST on Zoom. Even if you have nothing to report yet, attending helps you understand the org and meet the team.

4. **Attend the weekly team meets:** 3:00 PM CST.

### Step 2: Set Up Your Local Environment

```bash
# 1. Clone the data repo
git clone -b dev https://github.com/saayam-for-all/data.git
cd data

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# OR
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify your setup
python --version                # Should be 3.10+
pip list                        # Confirm packages installed
```

### Step 3: Understand the Product

- Visit [test-saayam.netlify.app](https://test-saayam.netlify.app/) and explore.
- Create an account, submit a help request, see how categories work.
- Read through the issues in the [data repo](https://github.com/saayam-for-all/data/issues) to understand what work has been done and what is in progress.

### Step 4: Complete the Beginner Task

See the [Beginner Task](#beginner-task) section below. Complete it, submit a PR, and get it reviewed. This is your onboarding checkpoint.

---

## How to Contribute

### Branch Naming Convention

```
<your_github_username>_<issue_number>_<brief_description>
```

**Example:** `saquibb8_100_auto_categorize_requests`

### Workflow

1. **Pick an issue:** Check the [Issues tab](https://github.com/saayam-for-all/data/issues). Only work on issues that are **explicitly open and active**. If unsure, ask in the team WhatsApp group.
2. **Assign yourself:** Comment on the issue that you are picking it up. Wait for confirmation from a team lead before starting.
3. **Create a branch from `dev`:**
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b <your_branch_name>
   ```
4. **Develop locally:** Write your code, test with mock/sample data. Do not rely on AWS access.
5. **Commit with clear messages:**
   ```bash
   git add .
   git commit -m "#100: Add zero-shot classification for help request categorization"
   ```
   Always reference the issue number in your commit message.
6. **Push and create a Pull Request:**
   ```bash
   git push origin <your_branch_name>
   ```
   Create a PR targeting the `dev` branch (never `main`). Assign reviewers.
7. **Code review:** Address feedback. PRs require **at least 2 code reviews** before merging.
8. **Merge:** A team lead or designated member will merge your PR into `dev` after approval.

### Code Standards

- **Python 3.10+** — use type hints where practical.
- **Follow PEP 8** — consistent formatting, meaningful variable names.
- **Write docstrings** for all functions and classes.
- **No credentials in code** — use environment variables or `.env` files (and add `.env` to `.gitignore`).
- **No `__pycache__/` or `venv/` in commits** — these must be in `.gitignore`.
- **Include a `requirements.txt`** update if you add new dependencies.
- **Test your code** — at minimum, manual testing with sample data. Unit tests are strongly encouraged.

### What NOT to Do

- ❌ Do not push directly to `main` or `dev`.
- ❌ Do not commit `__pycache__/`, `venv/`, `.env`, or any IDE-specific files.
- ❌ Do not commit AWS credentials, API keys, or secrets of any kind.
- ❌ Do not pick up a task without commenting on the issue first.
- ❌ Do not disappear after picking up a task. If you cannot continue, let the team know.

---

## Beginner Task

### Nonprofit Data Cleaning Exercise

**Objective:** Demonstrate that you can set up the development environment, work with Python and pandas, and follow the contribution workflow.

#### What You Need to Do

1. **Create a sample CSV file** called `sample_nonprofits.csv` with the following columns:
   ```
   name, city, state, category, website, phone
   ```
   Include at least **15 rows** of sample nonprofit data. Intentionally include these data quality issues:
   - 3-4 duplicate rows (exact or near-duplicates with slight name variations like "Red Cross" vs "red cross" vs "The Red Cross")
   - 2-3 rows with missing fields (empty city, missing phone, etc.)
   - Inconsistent formatting (e.g., "CA" vs "California" vs "ca", phone numbers in different formats)
   - Leading/trailing whitespace in some fields

2. **Write a Python script** called `clean_nonprofits.py` that:
   - Reads the sample CSV using pandas
   - Normalizes text fields (consistent casing, strip whitespace)
   - Standardizes state names (e.g., all to 2-letter abbreviations)
   - Standardizes phone number formatting (e.g., all to `(XXX) XXX-XXXX`)
   - Removes duplicate organizations (case-insensitive matching on name + city)
   - Handles missing data appropriately (fill, flag, or drop with justification)
   - Outputs a cleaned CSV called `cleaned_nonprofits.csv`
   - Prints a summary: total rows before, total rows after, duplicates removed, missing values handled

3. **Submit a PR** following the contribution guidelines above. Your branch should be named:
   ```
   <your_username>_beginner_task_data_cleaning
   ```

#### Why This Task?

This exercise mirrors the real work our team does. For example, the `Emergency Contact/EDA.py` script in this repo does exactly this kind of work — cleaning raw scraped data, handling duplicates, normalizing formats, and preparing data for database insertion. If you can do this, you can contribute to real tasks.

#### Acceptance Criteria

- [ ] Script runs without errors on Python 3.10+
- [ ] Sample CSV contains realistic data with intentional quality issues
- [ ] All data quality issues are handled with clear logic
- [ ] Output CSV is clean and consistent
- [ ] Code follows PEP 8 and includes docstrings
- [ ] PR follows the branch naming and commit message conventions
- [ ] A brief summary is included in the PR description explaining your approach

---

## Expectations & Formalities

### Time Commitment

This is a volunteer/intern position. We understand you have other commitments. However, **consistency matters more than hours**. We would rather you commit to 5 hours/week reliably than promise 20 and disappear.

### Timesheets

All hours must be logged in the **Google Sheet** shared in the WhatsApp Organization group every Monday. Your entry must include:

- Your name
- Hours worked that week
- Team name (Data Engineering)
- A clickable GitHub issue URL for what you worked on
- A brief description of tasks completed

**Deadline:** All entries must be submitted by **Tuesday end of day**. The submission window closes **Wednesday at 12:00 AM EST**. Late submissions are not accepted.

### Daily Scrum

- **When:** 10:00 AM PST, every weekday
- **Where:** Zoom (link posted in WhatsApp Organization group)
- **What to share:** What you did since the last scrum, what you plan to do today, any blockers
- **Mandatory** if you have an offer letter. If you cannot attend, send your status to the team WhatsApp group.
- The meeting starts 2 minutes early for icebreaking and has a 2-minute grace period. If there is no quorum, it wraps up after 10 minutes.
- **Show your face** — cameras on is encouraged.

### Pair Programming

Saayam follows a **pair programming model**. Most tasks are assigned to 2 or more people. This means:

- You are never working alone on a task — coordinate with your pair.
- If you need to step away, inform your pair programmer and your team lead.
- Never abandon a task without informing the team. This is taken seriously.

### What Gets You Removed

To be direct: **97% of volunteers who join do not work consistently.** People sign up, attend one meeting, pick up a task, and vanish. Here is what will get your offer letter voided:

- Not attending scrum and not sending status updates for 1 week without prior notice.
- Picking up a task and disappearing without informing anyone.
- Not logging timesheets.

We are not trying to be harsh — we just need reliability. If life gets in the way, just let us know. Communication is everything.

---

## Key Contacts

| Role | Who | How to Reach |
|------|-----|-------------|
| **Org Lead / Daily Scrum** | Rao Bhethanabotla | WhatsApp: (408) 390-1725 — escalation only, try team group first |
| **Data Engineering Team Lead** | _Ask in team WhatsApp group_ | Team WhatsApp group |
| **Offer Letters** | Sri Tejaswi Vadapalli / Sharanya Domakonda | WhatsApp |
| **GitHub/Access Issues** | Fill out [Access Hub Form](https://forms.gle/Mg8J3fSvA7AAHVxq5) | Google Form |

### Escalation Chain

1. Post in your **Data Engineering team WhatsApp group**
2. If no response in 24 hours → post in the **Software WhatsApp group**
3. If still unresolved → escalate to **Rao Bhethanabotla**

---

## FAQs

**Q: I do not have AWS access. How do I test my Lambda code?**
A: You develop and test locally using mock/sample data. Structure your code so that AWS-specific calls (boto3, Lambda invocations, S3 reads) can be easily swapped with local mocks. When your code works locally, the team lead will deploy it to AWS.

**Q: I want to work on a task but it already has people assigned. Can I still join?**
A: Yes — Saayam encourages pair programming, and tasks can have up to 10 assignees. Comment on the issue and ask in the team group.

**Q: I need to take a break from volunteering. What should I do?**
A: Just let your team lead and pair programmer know. Communicate proactively — nobody will be upset if you need time off. What causes problems is disappearing without a word.

**Q: What branch should I work off of?**
A: Always branch off `dev`. Never work directly on `main` (production) or push to it.

**Q: How do I get my code deployed to AWS?**
A: Once your PR is merged into `dev` and tested, notify the team lead. They will handle wrapping your code into a Lambda function and deploying it.

**Q: What if I am stuck and nobody is responding?**
A: Attend the daily 10 AM PST scrum call — it is the fastest way to get help. Rao personally helps unblock people during these calls.

**Q: I am interested in another team (frontend, AI, etc.). Can I switch?**
A: Absolutely. Talk to your current team lead and the lead of the team you want to join. You can even be on multiple teams if you want.

---

## Useful Links

| Resource | Link |
|----------|------|
| Test App (latest features) | [test-saayam.netlify.app](https://test-saayam.netlify.app/) |
| Production App | [saayam.netlify.app](https://saayam.netlify.app/) |
| GitHub Organization | [github.com/saayam-for-all](https://github.com/saayam-for-all/) |
| Data Repo Issues | [github.com/saayam-for-all/data/issues](https://github.com/saayam-for-all/data/issues) |
| Onboarding Wiki | [New Volunteer Onboarding](https://github.com/saayam-for-all/docs/wiki/New-Volunteer-Onboarding) |
| Access Hub Form | [Google Form](https://forms.gle/Mg8J3fSvA7AAHVxq5) |
| Architecture Wiki | [Architecture](https://github.com/saayam-for-all/docs/wiki/Architecture) |
| Saayam YouTube | [youtube.com/@SaayamForAll1](https://www.youtube.com/@SaayamForAll1) |
| Saayam Proposal Slides | [Google Slides](https://docs.google.com/presentation/d/19Uju43jUDaeaPip7yW1x3tXl_Tkw1jVFP6LL-55psZU/edit#slide=id.p1) |

---

*Last updated: February 2026*

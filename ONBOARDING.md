# Saayam For All — Data Engineering Team

> **⚠️ Read this before you do anything else.** No exceptions.

---

## What is Saayam For All?

Saayam For All is a **501(c)(3) nonprofit** building an "Uber for Help" platform — a web and mobile app that connects people in need with volunteers and organizations who can help with food, shelter, healthcare, education, and more.

- **Test App (latest features):** [test-saayam.netlify.app](https://test-saayam.netlify.app/)
- **Production App:** [saayam.netlify.app](https://saayam.netlify.app/)
- **GitHub:** [github.com/saayam-for-all](https://github.com/saayam-for-all/)

> 💡 **First thing you should do:** Go to [test-saayam.netlify.app](https://test-saayam.netlify.app/), create an account, submit a test help request, and explore the categories. Understand the product before you touch any code.

---

## Team Structure

The **Data** group at Saayam consists of two sub-teams that share one WhatsApp group and one GitHub repo ([data](https://github.com/saayam-for-all/data)):

| Sub-Team | Focus | Leads |
|----------|-------|-------|
| **Data Engineering** | Data pipelines, scraping, Lambda functions, data processing | **Saquib** · **Sana** |
| **Data Analytics** | Dashboards, analytics, insights, reporting | **Prachi** · **Vighnesh** |
| **Project Management** | Task planning, coordination, timelines | **Janhavi** · **Ritvik** *(confirm name with Janhavi)* |

**This README is oriented toward the Data Engineering team.** If you are joining Data Analytics, connect with Prachi or Vighnesh for guidance on analytics-specific work.

---

## Meetings & Communication

### Weekly Team Meeting (REQUIRED — #1 Priority)

| | |
|---|---|
| **When** | Every **Tuesday** — **1:00 PM PST** · **3:00 PM CST** · **4:00 PM EST** |
| **Who** | Both Data Engineering and Data Analytics |
| **Where** | Zoom (link shared in WhatsApp group) |

This is the most important meeting. This is where you give updates, ask questions, get unblocked, and sync with the team. **Save your questions for this meeting** — mid-week, people get busy and responses take time.

**If you miss 4 team meetings in a row, you will be removed from the group.**

### Daily Scrum (Org-Wide)

| | |
|---|---|
| **When** | Every weekday at **10:00 AM PST** |
| **Who** | All Saayam tech volunteers |
| **Led by** | **Rao Bhethanabotla** |

This is an org-wide standup. Useful for getting context on what other teams are doing and for getting help from Rao directly. **Mandatory if you have an offer letter.** If you cannot attend, send your status to the WhatsApp group.

### WhatsApp

One shared WhatsApp group for both Data Engineering and Data Analytics. This is the primary communication channel. Introduce yourself when you join: name, qualifications, school, location, interests.

**Communication etiquette:** Our volunteers are across time zones and countries. Never call someone directly without checking availability via WhatsApp first.

**Escalation chain:** Team WhatsApp group → Software WhatsApp group (if no response in 24 hrs) → Rao Bhethanabotla (408-390-1725).

---

## What the Data Engineering Team Does

We build the **data pipeline** that powers Saayam's intelligent features — scraping, cleaning, aggregating, and serving data so the AI team and frontend can use it.

### Active Work

| Issue | Title | Status |
|-------|-------|--------|
| [#98](https://github.com/saayam-for-all/data/issues/98) | Aggregate Organization Listings from Multiple Sources | ✅ Completed |
| [#99](https://github.com/saayam-for-all/data/issues/99) | Integrate Org Aggregator into Frontend | 🔄 Open (cross-team: data + webapp) |
| [#100](https://github.com/saayam-for-all/data/issues/100) | Auto-Categorize Help Requests Using Lambda | 🔄 Open |

### Strategic Direction

The long-term pipeline Rao has set:

```
PostgreSQL (RDBMS) → S3 Data Lake → Vectorize → Vector DB → AI Agent
```

Future tasks will align with building out this pipeline.

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

### Local Development First

**You will not get AWS Lambda/S3 access.** You develop and test locally with mock data. When your code works, let the team leads know — we handle AWS deployment. Structure your code so AWS calls can be easily mocked.

---

## Repository Structure

The [data repo](https://github.com/saayam-for-all/data) contains issues for both Data Engineering and Data Analytics, but the codebase is primarily Data Engineering work. Analytics work has generally been implemented directly into the application via Java or Python in other repos.

```
data/
├── README.md                    # This file
├── KNOWLEDGE_TRANSFER.md        # Team knowledge transfer doc
├── requirements.txt
├── .gitignore
├── src/                         # All source code
│   ├── aggregator/              # Org aggregator Lambda (#98)
│   ├── categorizer/             # Auto-categorizer Lambda (#100)
│   ├── scrapers/                # Web scraping scripts
│   │   ├── emergency_contacts/  # Emergency number data pipeline
│   │   └── ngo/                 # NGO scrapers (Afghanistan, India, Malaysia)
│   ├── models/                  # SQLAlchemy models
│   ├── translation/             # Language detection & translation
│   └── utils/                   # Shared utilities
├── data/                        # Data files (raw/ and cleaned/)
├── notebooks/                   # Jupyter notebooks
├── tests/                       # Unit tests
└── infrastructure/              # Dockerfile, K8s configs
```

> **Note:** The repo is being restructured to this layout. See `PROPOSED_REPO_STRUCTURE.md` for the migration plan.

---

## How the Data Repo Connects to Other Repos

Only **7 of 40+ repos** are actively developed:

```
webapp (React) ←── api (API Gateway) ←── mobileapp
        │                  │
        ▼                  ▼
   volunteer          request
  (Java/Spring)    (Help requests)
        │                  │
        ▼                  ▼
      database (PostgreSQL)
              │
              ▼
    data (Python) ← YOU ARE HERE
              │
              ▼
       ai (Python/Flask — GenAI)

   devsecops — CI/CD, infra (all teams)
```

| Repo | Why It Matters to Us |
|------|---------------------|
| **[webapp](https://github.com/saayam-for-all/webapp)** | Consumes our Lambda endpoints |
| **[ai](https://github.com/saayam-for-all/ai)** | We invoke their GenAI Lambda; future: we feed vectorized data to their agent |
| **[api](https://github.com/saayam-for-all/api)** | Routes frontend requests to our Lambdas |
| **[database](https://github.com/saayam-for-all/database)** | Source of truth — we extract data from here |
| **[volunteer](https://github.com/saayam-for-all/volunteer)** | Volunteer data we may aggregate |
| **[devsecops](https://github.com/saayam-for-all/devsecops)** | Manages our deployment infra |

---

## Getting Started

### 1. Get Access

- Fill out the **[Access Hub Form](https://forms.gle/Mg8J3fSvA7AAHVxq5)** to get added to GitHub and WhatsApp.
- Make sure your GitHub profile has your **real name and profile picture** — required for task assignments.

### 2. Set Up Locally

```bash
git clone -b dev https://github.com/saayam-for-all/data.git
cd data
python -m venv venv
source venv/bin/activate    # macOS/Linux — or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Explore the Product

Go to [test-saayam.netlify.app](https://test-saayam.netlify.app/). Submit a help request. Understand the categories.

### 4. Complete the Beginner Task

There is a **beginner task** you must complete before being assigned real work. Check the issues tab for the issue labeled `good first issue` or ask in the team WhatsApp group for the current beginner task.

### 5. Attend the Tuesday Team Meeting

Show up, introduce yourself, and you'll be guided from there.

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

### Code Standards

- Python 3.10+, PEP 8, type hints where practical.
- Docstrings for all functions and classes.
- No credentials in code — use `.env` files.
- Never commit `__pycache__/`, `venv/`, `.env`, or IDE files.
- Update `requirements.txt` if you add dependencies.

### What NOT to Do

- ❌ Don't push directly to `main` or `dev`.
- ❌ Don't self-assign tasks or edit issue descriptions.
- ❌ Don't commit secrets, API keys, or AWS credentials.
- ❌ Don't disappear after being assigned a task.

---

## Expectations

### Accountability

We'll be real with you: **97% of volunteers who join don't work consistently.** We're not trying to be harsh — we just need reliability. Here are the rules:

- **If you are assigned a task and have no updates, no heads up, and no valid reason — you will be removed from the task.**
- **If you miss 4 weekly team meetings in a row — you will be removed from the group.**
- If life gets in the way, just tell us. Communication is everything. Nobody will be upset if you need time off — what causes problems is silence.

### Timesheets

Log your hours weekly in the **Google Sheet** shared in the WhatsApp Organization group every Monday:
- Your name, hours worked, team name, GitHub issue URL, brief task description.
- **Deadline:** Tuesday EOD. Window closes **Wednesday 12:00 AM EST**. No late submissions.

### Pair Programming

Most tasks are assigned to 2+ people. Coordinate with your pair. If you need to step away, tell your pair and your team lead.

---

## Key Contacts

| Role | Who | Reach Via |
|------|-----|-----------|
| **Data Engineering Leads** | **Saquib** · **Sana** | Team WhatsApp group |
| **Data Analytics Leads** | **Prachi** · **Vighnesh** | Team WhatsApp group |
| **Project Managers** | **Janhavi** · **Ritvik** | Team WhatsApp group |
| **Org Lead / Scrum** | **Rao Bhethanabotla** | (408) 390-1725 — escalation only |
| **Offer Letters** | Sri Tejaswi Vadapalli / Sharanya Domakonda | WhatsApp |
| **Access Issues** | [Access Hub Form](https://forms.gle/Mg8J3fSvA7AAHVxq5) | Google Form |

---

## Useful Links

| Resource | Link |
|----------|------|
| Test App | [test-saayam.netlify.app](https://test-saayam.netlify.app/) |
| Production App | [saayam.netlify.app](https://saayam.netlify.app/) |
| Data Repo Issues | [github.com/saayam-for-all/data/issues](https://github.com/saayam-for-all/data/issues) |
| Onboarding Wiki | [New Volunteer Onboarding](https://github.com/saayam-for-all/docs/wiki/New-Volunteer-Onboarding) |
| Access Hub Form | [Google Form](https://forms.gle/Mg8J3fSvA7AAHVxq5) |
| Architecture Wiki | [Architecture](https://github.com/saayam-for-all/docs/wiki/Architecture) |
| Saayam YouTube | [youtube.com/@SaayamForAll1](https://www.youtube.com/@SaayamForAll1) |

---

*Last updated: February 2026*

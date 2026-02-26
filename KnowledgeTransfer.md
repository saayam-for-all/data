# Knowledge Transfer Document — Data Engineering Team

> **Purpose:** If the current team leads leave tomorrow, this document should allow the next person to pick up where they left off with zero handholding.

---

## Team Structure

The Data group consists of two sub-teams sharing one WhatsApp group and one GitHub repo:

| Sub-Team | Leads | Focus |
|----------|-------|-------|
| **Data Engineering** | **Saquib**, **Sana** | Pipelines, scraping, Lambda functions, data processing |
| **Data Analytics** | **Prachi**, **Vighnesh** | Dashboards, analytics, insights, reporting |
| **Project Management** | **Janhavi**, **Ruthwik** | Task planning, coordination |

**Org Leadership:** Rao Bhethanabotla — sets strategic direction, runs daily scrum, final escalation point.

**This document is focused on Data Engineering.** Analytics work has generally been implemented into the application via Java or Python in other repos, not in the data repo.

---

## Architecture & Data Flow

### Current Pipeline

```
External Data (Wikipedia, NGO sites)
        │ Web scraping (Python)
        ▼
┌──────────────┐    ┌──────────────────┐
│  Saayam DB   │    │  GenAI Lambda    │
│ (PostgreSQL) │    │ (More_Org_GenAI  │
│              │    │  _Py_v3126)      │
└──────┬───────┘    └────────┬─────────┘
       └────────┬────────────┘
                ▼
     saayam-org-aggregator Lambda
     (merges sources, deduplicates)
                │
                ▼
     API Gateway → webapp frontend
```

### Future Pipeline (Rao's Directive)

```
PostgreSQL → S3 Data Lake → Vectorize → Vector DB → AI Agent
```

Not yet built. The team needs to produce a functional spec / design spec for this.

---

## Completed Work

### Organization Aggregator Lambda (#98) ✅

Lambda that accepts a help request (subject, description, location, category) and fetches matching orgs from:
1. **Saayam DB** — registered orgs (tagged "verified")
2. **GenAI Lambda** — AI-suggested orgs (tagged "genai")

Merges, deduplicates (DB takes priority), returns unified list with graceful degradation.

**Lambda:** `saayam-org-aggregator` (us-east-1)

**Input:**
```json
{
  "category": "Shelter",
  "subject": "Shelter",
  "description": "i need a place to stay",
  "location": "tampa"
}
```

**Output:**
```json
{
  "statusCode": 200,
  "body": [
    {
      "name": "The Salvation Army Tampa",
      "location": "Tampa, FL",
      "contact": "(813) 223-1320",
      "email": "...",
      "web_url": "...",
      "mission": "...",
      "source": "..."
    }
  ]
}
```

### Emergency Contact Data Pipeline

Scrapes emergency contact numbers from Wikipedia → cleans with pandas → inserts into PostgreSQL via SQLAlchemy.

**Files:** `Emergency Contact/` — `script_to_extract_emergency_contact.py` (scraper), `EDA.py` (cleaner), `insert_data_to_db.py` (DB loader).

### NGO Web Scrapers

Country-specific scrapers for nonprofit listings: `web_scraping/afghanistan_data.py`, `india_data.py`, `malaysia_data.py`. Run independently, produce CSVs. Not yet in an automated pipeline.

### Language Detection & Translation

`translation/lang_detection.py` — detects language with `langdetect`, translates to English with `GoogleTranslator`.

### Fraud Detection Model (Schema Only)

`Models/FraudRequests.py` — SQLAlchemy model for fraud requests. Schema defined, no active detection logic built.

### Earlier Pipeline Work (#55-#67)

ETL architecture design (#57), Aurora schema for nonprofits (#56), AWS architecture doc (#55), IRS S3 Lambda (#60), Charity Navigator scraper (#62), IRS nonprofit categorization (#67). These informed the current pipeline but IRS data was later dropped (see Decision Log).

---

## Active Work

| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| [#99](https://github.com/saayam-for-all/data/issues/99) | Integrate Org Aggregator into Frontend | Open | Cross-team (data + webapp). Lambda is done. Remaining work is React frontend integration. |
| [#100](https://github.com/saayam-for-all/data/issues/100) | Auto-Categorize Help Requests Using Lambda | Open | LLM-based classification. Assigned to ramumarrp77, anupbpote02. |

**Note:** Many issues in the #80-90 range are stale — created by volunteers who are no longer active. These need triage (reassign or close).

---

## Future Roadmap

1. **RDBMS → S3 Data Lake** — Periodic data export from Aurora to S3. Needs functional spec.
2. **Data Vectorization** — Generate embeddings. Tech selection needed.
3. **Vector DB Setup** — Evaluate Pinecone, Weaviate, pgvector, etc.
4. **Saayam AI Agent** — Agent that queries vector DB with Saayam's own data.
5. **Content Safety** — Sentiment analysis for threatening language (#87), translation for content filtering (#86). Stale.
6. **Analytics Dashboard** — Super Admin analytics (#81-89). Stale. Data Analytics team scope.

---

## AWS Infrastructure

| Service | Purpose | Access |
|---------|---------|--------|
| **Lambda** | Serverless functions | Team leads only |
| **S3** | Data lake, datasets | Team leads only |
| **Aurora PostgreSQL** | Primary database | Team leads only |
| **API Gateway** | Routes to Lambdas | API/DevSecOps team |

New volunteers **do not** get AWS access. Local dev with mocks only. Team leads deploy.

**Invoking other Lambdas:**
```python
client = boto3.client('lambda', region_name='us-east-1')
response = client.invoke(FunctionName='More_Org_GenAI_Py_v3126', ...)
```

---

## Cross-Team Dependencies

| Team | Repo | How We Interact |
|------|------|----------------|
| **GenAI / AI** | [ai](https://github.com/saayam-for-all/ai) | We invoke their Lambda. Future: we feed vectorized data to their agent. |
| **Frontend** | [webapp](https://github.com/saayam-for-all/webapp) | They consume our Lambda endpoints. #99 is a cross-team task. |
| **Backend / API** | [api](https://github.com/saayam-for-all/api) | They set up API Gateway routes to our Lambdas. |
| **Database** | [database](https://github.com/saayam-for-all/database) | We read from their DB. Coordinate for schema changes. |
| **DevSecOps** | [devsecops](https://github.com/saayam-for-all/devsecops) | They manage AWS infra our Lambdas run on. |
| **Product** | [prod](https://github.com/saayam-for-all/prod) | Defines what we build. [MVP Pages wiki](https://github.com/saayam-for-all/prod/wiki/1.0-MVP-Pages). |

---

## Operational Rhythms

### Weekly (Most Important)

- **Tuesday — 1:00 PM PST / 3:00 PM CST / 4:00 PM EST** — Team meeting. Both Data Engineering and Analytics. Updates, questions, task coordination.

### Daily

- **10:00 AM PST** — Org-wide scrum (Zoom, led by Rao).

### Weekly Admin

- **Monday** — Timesheet Google Sheet shared. Enter your hours.
- **Tuesday EOD** — Finalize timesheet entries.
- **Wednesday 12:00 AM EST** — Submission window closes.

### Task Management Rules

- **Team leads and PMs assign tasks.** Volunteers do not self-assign or edit issue descriptions/user stories.
- **No updates + no heads up + no valid reason → removed from the task.**
- **4 missed weekly team meetings in a row → removed from the group.**

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Feb 2026 | Dropped IRS data from org-aggregator | Too noisy, not useful for matching. Aggregator uses Saayam DB + GenAI only. |
| Feb 2026 | #99 is cross-team (data + webapp) | Lambda done. Frontend work remains — needs React-comfortable volunteer. |
| 2025 | Local-first development | AWS access cannot be given to all volunteers. Cost and security. |
| 2025 | Pair programming mandate | 97% churn means no single person should own a task alone. |
| Apr 2025 | Aurora PostgreSQL as primary DB | PostgreSQL compatible, managed AWS, scalable. |

---

## Known Issues & Technical Debt

1. **`__pycache__/` and `venv/` committed to repo.** Need `git rm -r --cached` and `.gitignore` update.
2. **Flat repo structure.** All files at root. Proposed restructure in `PROPOSED_REPO_STRUCTURE.md`.
3. **No tests.** No `tests/` directory, no unit tests.
4. **No CI/CD.** No GitHub Actions for automated testing/linting.
5. **Stale issues (#80-90).** Need triage — reassign or close.
6. **No `.env.example`.** No template for environment variables.
7. **Folder name with spaces.** `Emergency Contact/` causes tool issues.

---

## Handoff Checklist

If you are leaving the team lead role:

- [ ] Update this document and the README with any changes.
- [ ] Brief the incoming lead on active issues (#99, #100, and any new ones).
- [ ] Introduce the new lead in the WhatsApp group.
- [ ] Transfer AWS access (coordinate with Rao and DevSecOps).
- [ ] Share any credentials not in the shared environment.
- [ ] Walk through deployed Lambdas on AWS — what, where, how configured.
- [ ] Review and hand off open PRs.
- [ ] Inform Rao about the transition.
- [ ] Update Key Contacts in the README.
- [ ] Close or reassign stale issues.

---

*Last updated: February 2026 · Maintained by: Data Engineering Team Leads*

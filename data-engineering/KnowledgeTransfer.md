# Knowledge Transfer Document — Data Engineering Team

> **Purpose:** If the current team leads leave tomorrow, this document should allow the next person to pick up where they left off with zero handholding.
>
> **Audience:** Team leads and senior contributors. For onboarding, see [README.md](README.md). For dev workflow, see [CONTRIBUTING.md](CONTRIBUTING.md). For task status, see [TASK_TRACKER.md](TASK_TRACKER.md).

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

### Cross-Team Dependencies

| Team | Repo | How We Interact |
|------|------|----------------|
| **GenAI / AI** | [ai](https://github.com/saayam-for-all/ai) | We invoke their Lambda. Future: we feed vectorized data to their agent. |
| **Frontend** | [webapp](https://github.com/saayam-for-all/webapp) | They consume our Lambda endpoints. #99 is a cross-team task. |
| **Backend / API** | [api](https://github.com/saayam-for-all/api) | They set up API Gateway routes to our Lambdas. |
| **Database** | [database](https://github.com/saayam-for-all/database) | We read from their DB. Coordinate for schema changes. |
| **DevSecOps** | [devsecops](https://github.com/saayam-for-all/devsecops) | They manage AWS infra our Lambdas run on. |
| **Product** | [prod](https://github.com/saayam-for-all/prod) | Defines what we build. [MVP Pages wiki](https://github.com/saayam-for-all/prod/wiki/1.0-MVP-Pages). |

---

## Technical Details of Completed Work

### Organization Aggregator Lambda (#98)

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

**Files:** `src/scrapers/emergency_contacts/` — `scraper.py`, `cleaner.py`, `loader.py`.

### NGO Web Scrapers

Country-specific scrapers for nonprofit listings: `src/scrapers/ngo/afghanistan.py`, `india.py`, `malaysia.py`. Run independently, produce CSVs. Not yet in an automated pipeline.

### Language Detection & Translation

`src/translation/lang_detection.py` — detects language with `langdetect`, translates to English with `GoogleTranslator`.

### Fraud Detection Model (Schema Only)

`src/models/fraud_requests.py` — SQLAlchemy model for fraud requests. Schema defined, no active detection logic built.

### Earlier Pipeline Work (#55-#67)

ETL architecture design (#57), Aurora schema for nonprofits (#56), AWS architecture doc (#55), IRS S3 Lambda (#60), Charity Navigator scraper (#62), IRS nonprofit categorization (#67). These informed the current pipeline but IRS data was later dropped (see Decision Log).

---

## AWS Infrastructure

| Service | Purpose | Access |
|---------|---------|--------|
| **Lambda** | Serverless functions | Team leads only |
| **S3** | Data lake, datasets | Team leads only |
| **Aurora PostgreSQL** | Primary database | Team leads only |
| **API Gateway** | Routes to Lambdas | API/DevSecOps team |

**Invoking other Lambdas:**
```python
client = boto3.client('lambda', region_name='us-east-1')
response = client.invoke(FunctionName='More_Org_GenAI_Py_v3126', ...)
```

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

1. **No tests.** No unit tests written yet.
2. **No CI/CD.** No GitHub Actions for automated testing/linting.
3. **Stale issues (#80-90).** Need triage — reassign or close.

---

## Handoff Checklist

If you are leaving the team lead role:

- [ ] Update this document and the README with any changes.
- [ ] Brief the incoming lead on active issues (see [TASK_TRACKER.md](TASK_TRACKER.md)).
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
